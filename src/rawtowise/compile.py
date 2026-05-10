"""Compile pipeline — raw/ → wiki/ structured knowledge base."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from rawtowise.config import Config
from rawtowise.llm import call_llm, call_llm_async
from rawtowise.sources import (
    abs_path,
    append_log,
    ensure_wiki_scaffold,
    load_manifest,
    rel_path,
    sha256_file,
    sha256_text,
)

console = Console()


@dataclass
class SourceDoc:
    """A source that can be sent to the compiler."""

    id: str
    content: str
    path: str
    digest: str
    title: str
    parser: str


SYSTEM_COMPILE = """\
You are a knowledge compiler. Your job is to read raw source documents and produce \
a structured wiki in markdown format.

RULES:
- Write in {language}.
- Every claim MUST cite its source as [source: source_id:Lx-Ly] when line numbers are available.
- Create concept articles that synthesize information across multiple sources.
- Use wiki-style backlinks: [[concept-name]] to link between articles.
- Each article should have YAML frontmatter with: title, tags, sources, created date.
- Be comprehensive but concise. Prioritize accuracy over completeness.
- If sources conflict, note the contradiction explicitly.
"""

PROMPT_EXTRACT_CONCEPTS = """\
Below are the raw source documents for a knowledge base called "{project_name}".

<sources>
{sources_text}
</sources>

<existing_wiki_index>
{wiki_index}
</existing_wiki_index>

TASK: Analyze all sources and extract the key concepts, entities, and themes.

Return a JSON object with this structure:
{{
  "concepts": [
    {{
      "id": "concept-slug",
      "title": "Concept Title",
      "description": "One-line description",
      "sources": ["source-id-1", "source-id-2"],
      "related": ["other-concept-slug"]
    }}
  ]
}}

Extract up to {max_concepts} concepts.
Only include the highest-level, most important concepts. Merge related sub-topics into broader concepts.
Prefer existing concept ids when the source updates a topic already listed in the wiki index.
Keep descriptions SHORT (under 15 words each).
Return ONLY valid JSON, no markdown fences, no commentary.
"""

PROMPT_WRITE_ARTICLE = """\
You are writing a wiki article for the concept: "{concept_title}"
Description: {concept_desc}

<sources>
{relevant_sources}
</sources>

<existing_wiki_index>
{wiki_index}
</existing_wiki_index>

Write a comprehensive wiki article in markdown. Requirements:
- YAML frontmatter with: title, tags (list), sources (list of source ids), created (date)
- Use ## and ### headings to structure the content
- Cite sources as [source: source_id:Lx-Ly] for every factual claim when line numbers are available
- Use [[concept-name]] backlinks to link to related concepts in the wiki
- Write in {language}
- Be thorough but concise

Output ONLY the markdown article content (including frontmatter).
"""

PROMPT_WRITE_INDEX = """\
You are generating the master index for a knowledge wiki called "{project_name}".

<articles>
{articles_summary}
</articles>

Generate _index.md — the master index of this wiki. Requirements:
- Start with a brief overview of the knowledge base topic and scope
- List ALL articles organized by category (concepts, entities, etc.)
- Each entry: [[article-slug]] — one-line summary
- Include a "Quick Stats" section: number of articles, sources, main themes
- Write in {language}

Output ONLY the markdown content.
"""

PROMPT_WRITE_SOURCES = """\
Here are all the source documents in this knowledge base:

<sources>
{sources_list}
</sources>

Generate _sources.md — a catalog of all source documents. For each source:
- Source id and filename/path
- Source URL or path (from frontmatter if available)
- Ingested date
- Brief description (1-2 sentences)
- Which wiki concepts it contributes to

Write in {language}. Output ONLY the markdown content.
"""


def _read_compilable_sources(project_dir: Path) -> dict[str, SourceDoc]:
    """Read text sources and processed markdown sources for compilation."""
    raw_dir = project_dir / "raw"
    docs: dict[str, SourceDoc] = {}

    manifest = load_manifest(project_dir)
    manifest_sources = manifest.get("sources", {})
    represented_paths: set[str] = set()

    for source_id, record in sorted(manifest_sources.items()):
        if record.get("status") != "ready":
            continue

        manifest_path = record.get("processed_path") or record.get("raw_path")
        path = abs_path(project_dir, manifest_path)
        if not path or not path.exists() or path.suffix.lower() not in (".md", ".txt"):
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        path_key = rel_path(project_dir, path) or str(path)
        represented_paths.add(path_key)
        docs[source_id] = SourceDoc(
            id=source_id,
            content=content,
            path=path_key,
            digest=sha256_file(path),
            title=str(record.get("title") or source_id),
            parser=str(record.get("parser") or "unknown"),
        )

    # Backward compatibility: projects created before sources.json still compile.
    if raw_dir.exists():
        for f in sorted(raw_dir.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (".md", ".txt"):
                continue
            path_key = rel_path(project_dir, f) or str(f)
            if path_key in represented_paths:
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                continue
            source_id = f.relative_to(raw_dir).as_posix()
            docs[source_id] = SourceDoc(
                id=source_id,
                content=content,
                path=path_key,
                digest=sha256_text(content),
                title=f.stem,
                parser="legacy-raw",
            )

    return docs


def _read_raw_sources(project_dir: Path) -> dict[str, str]:
    """Read all compilable source files and return {source_id: content}."""
    return {
        source_id: doc.content
        for source_id, doc in _read_compilable_sources(project_dir).items()
    }


def _load_compile_state(project_dir: Path) -> dict:
    """Load previous compile state."""
    state_path = project_dir / ".rtw" / "compile-state.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {"compiled_files": [], "last_compile": None}


def _save_compile_state(project_dir: Path, sources: dict[str, SourceDoc]):
    """Save compile state."""
    rtw_dir = project_dir / ".rtw"
    rtw_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "compiled_files": list(sources.keys()),
        "source_hashes": {source_id: doc.digest for source_id, doc in sources.items()},
        "last_compile": datetime.now(timezone.utc).isoformat(),
    }
    (rtw_dir / "compile-state.json").write_text(json.dumps(state, indent=2))


def _source_changes(prev_state: dict, sources: dict[str, SourceDoc]) -> tuple[set[str], set[str], set[str]]:
    """Return new, changed, and deleted source ids."""
    prev_hashes = prev_state.get("source_hashes") or {
        name: None for name in prev_state.get("compiled_files", [])
    }
    curr_hashes = {source_id: doc.digest for source_id, doc in sources.items()}

    prev_ids = set(prev_hashes)
    curr_ids = set(curr_hashes)
    new_ids = curr_ids - prev_ids
    deleted_ids = prev_ids - curr_ids
    changed_ids = {
        source_id
        for source_id in curr_ids & prev_ids
        if prev_hashes.get(source_id) != curr_hashes.get(source_id)
    }
    return new_ids, changed_ids, deleted_ids


def _truncate_sources(
    sources: dict[str, str],
    max_chars: int = 150_000,
    max_per_source: int = 50_000,
) -> str:
    """Combine sources into a single text block with fair per-source caps."""
    parts = []
    total = 0
    for name, content in sources.items():
        header = f"\n--- SOURCE: {name} ---\n"
        numbered = _with_line_numbers(content)
        # Cap each source individually
        capped = numbered[:max_per_source]
        if len(numbered) > max_per_source:
            capped += "\n[...truncated...]"
        # Check total budget
        if total + len(header) + len(capped) > max_chars:
            remaining = max_chars - total - len(header) - 100
            if remaining > 500:
                parts.append(header + capped[:remaining] + "\n[...truncated...]")
            break
        parts.append(header + capped)
        total += len(header) + len(capped)
    return "\n".join(parts)


def _with_line_numbers(content: str) -> str:
    """Prefix source lines so the LLM can produce location-aware citations."""
    return "\n".join(
        f"L{i:04d}: {line}"
        for i, line in enumerate(content.splitlines(), start=1)
    )


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences, preamble, and truncation."""
    # Strip markdown fences
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    # Try to repair truncated JSON (e.g., output cut off by max_tokens)
    # Find the last complete object in an array and close the structure
    brace_start = cleaned.find("{")
    if brace_start >= 0:
        fragment = cleaned[brace_start:]
        # Find last complete object: look for },\n which precedes the next (incomplete) entry
        last_complete = fragment.rfind("},")
        if last_complete > 0:
            repaired = fragment[:last_complete + 1] + "]}"
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    return None


def _read_existing_index(project_dir: Path) -> str:
    index_path = project_dir / "wiki" / "_index.md"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return ""


def _article_summaries(wiki_dir: Path, generated: list[tuple[str, str, str, str]]) -> list[str]:
    """Summarize generated and existing concept pages for index generation."""
    summaries_by_slug: dict[str, str] = {}
    for cid, title, desc, _content in generated:
        summaries_by_slug[cid] = f"- [[{cid}]] ({title}): {desc}"

    concepts_dir = wiki_dir / "concepts"
    if concepts_dir.exists():
        for path in sorted(concepts_dir.glob("*.md")):
            slug = path.stem
            if slug in summaries_by_slug:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
            title = _extract_article_title(content) or slug
            summaries_by_slug[slug] = f"- [[{slug}]] ({title}): existing concept page"

    return [summaries_by_slug[k] for k in sorted(summaries_by_slug)]


def _extract_article_title(content: str) -> str | None:
    """Best-effort title extraction from frontmatter or headings."""
    match = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    for line in content.splitlines():
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return None


def _sources_catalog_text(sources: dict[str, SourceDoc]) -> str:
    """Build source catalog input for _sources.md generation."""
    lines = []
    for source_id, doc in sorted(sources.items()):
        lines.append(
            f"- {source_id}: title={doc.title}; path={doc.path}; "
            f"parser={doc.parser}; chars={len(doc.content)}; sha256={doc.digest[:12]}"
        )
    return "\n".join(lines)


def compile_wiki(project_dir: Path, config: Config, full: bool = False) -> None:
    """Compile raw sources into a structured wiki."""
    ensure_wiki_scaffold(project_dir, config.name)

    source_docs = _read_compilable_sources(project_dir)
    if not source_docs:
        console.print("[yellow]No sources in raw/. Run `rtw ingest` to add sources.[/yellow]")
        return

    # Check for incremental
    prev_state = _load_compile_state(project_dir)
    prev_files = set(prev_state.get("compiled_files", []))
    new_files, changed_files, deleted_files = _source_changes(prev_state, source_docs)
    work_ids = set(source_docs) if full or not prev_files else new_files | changed_files

    if not full and not work_ids and not deleted_files:
        console.print("[yellow]No new sources. Use --full to force a full recompile.[/yellow]")
        return

    wiki_dir = project_dir / "wiki"

    if full or not prev_files:
        console.print(f"  [dim]Full compile: {len(source_docs)} sources[/dim]")
    else:
        console.print(
            f"  [dim]Changed sources: {len(work_ids)} "
            f"(new: {len(new_files)}, changed: {len(changed_files)}, total: {len(source_docs)})[/dim]"
        )

    lang = config.compile.language
    sources = {source_id: doc.content for source_id, doc in source_docs.items()}
    work_sources = {source_id: sources[source_id] for source_id in sorted(work_ids)}
    if not work_sources:
        work_sources = sources
    sources_text = _truncate_sources(work_sources)
    existing_index = _read_existing_index(project_dir)

    # Scale concepts to source count: ~5 per changed source, capped by config
    max_concepts = min(config.compile.max_concepts, max(5, len(work_sources) * 5))

    # Step 1: Extract concepts
    console.print("\n[bold]1/4[/bold] Extracting concepts...")
    concepts_raw = call_llm(
        config,
        system=SYSTEM_COMPILE.format(language=lang),
        user=PROMPT_EXTRACT_CONCEPTS.format(
            project_name=config.name,
            sources_text=sources_text,
            wiki_index=existing_index,
            max_concepts=max_concepts,
        ),
        max_tokens=16384,
    )

    concepts_data = _extract_json(concepts_raw)
    concepts = concepts_data.get("concepts", []) if concepts_data else []

    if not concepts:
        # Retry once with explicit instruction
        console.print("[yellow]  Retrying concept extraction...[/yellow]")
        concepts_raw = call_llm(
            config,
            system="You are a JSON generator. Return ONLY valid JSON, nothing else.",
            user=PROMPT_EXTRACT_CONCEPTS.format(
                project_name=config.name,
                sources_text=sources_text,
                wiki_index=existing_index,
                max_concepts=max_concepts,
            ),
            max_tokens=16384,
        )
        concepts_data = _extract_json(concepts_raw)
        concepts = concepts_data.get("concepts", []) if concepts_data else []

    if not concepts:
        # Save debug info
        debug_dir = project_dir / ".rtw" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "concepts-raw-response.txt").write_text(concepts_raw, encoding="utf-8")
        (debug_dir / "concepts-prompt-sources.txt").write_text(sources_text[:50_000], encoding="utf-8")
        preview = concepts_raw[:300].replace("\n", " ")
        console.print("[red]Failed to extract concepts.[/red]")
        console.print(f"[dim]LLM response ({len(concepts_raw)} chars): {preview}...[/dim]")
        console.print("[dim]Debug saved to .rtw/debug/[/dim]")
        return

    console.print(f"  [green]✓[/green] {len(concepts)} concepts extracted")

    # Step 2: Write concept articles (parallel with progress)
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

    wiki_index_text = "\n".join(
        f"- [[{c.get('id', '')}]] — {c.get('description', '')}"
        for c in concepts
    )
    if existing_index:
        wiki_index_text = existing_index + "\n\n" + wiki_index_text

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold]2/4[/bold] Generating articles"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.fields[current]}"),
        console=console,
    )
    task_id = progress.add_task("articles", total=len(concepts), current="")

    async def _generate_article(i: int, concept: dict) -> tuple[str, str, str, str]:
        cid = concept.get("id", f"concept-{i}")
        title = concept.get("title", cid)
        desc = concept.get("description", "")
        concept_sources = concept.get("sources", [])

        relevant = {}
        for sname in concept_sources:
            if sname in sources:
                relevant[sname] = sources[sname]
        if not relevant:
            relevant = sources

        content = await call_llm_async(
            config,
            system=SYSTEM_COMPILE.format(language=lang),
            user=PROMPT_WRITE_ARTICLE.format(
                concept_title=title,
                concept_desc=desc,
                relevant_sources=_truncate_sources(relevant, max_chars=80_000),
                wiki_index=wiki_index_text,
                language=lang,
            ),
            max_tokens=4096,
        )
        progress.update(task_id, advance=1, current=title)
        return cid, title, desc, content

    async def _generate_all_articles():
        return await asyncio.gather(
            *[_generate_article(i, c) for i, c in enumerate(concepts)]
        )

    with progress:
        results = asyncio.run(_generate_all_articles())

    articles_summary = []
    for cid, title, desc, content in results:
        (wiki_dir / "concepts" / f"{cid}.md").write_text(content, encoding="utf-8")
        articles_summary.append((cid, title, desc, content))

    console.print(f"  [green]✓[/green] {len(concepts)} articles generated")

    # Step 3+4: Generate index and source catalog in parallel
    console.print("\n[bold]3/4[/bold] Generating index + source catalog...")
    articles_summary_text = "\n".join(_article_summaries(wiki_dir, articles_summary))
    sources_list_text = _sources_catalog_text(source_docs)

    async def _generate_meta():
        idx, src = await asyncio.gather(
            call_llm_async(
                config,
                system=SYSTEM_COMPILE.format(language=lang),
                user=PROMPT_WRITE_INDEX.format(
                    project_name=config.name,
                    articles_summary=articles_summary_text,
                    language=lang,
                ),
                max_tokens=4096,
            ),
            call_llm_async(
                config,
                system=SYSTEM_COMPILE.format(language=lang),
                user=PROMPT_WRITE_SOURCES.format(
                    sources_list=sources_list_text,
                    language=lang,
                ),
                max_tokens=4096,
            ),
        )
        return idx, src

    index_content, sources_content = asyncio.run(_generate_meta())
    (wiki_dir / "_index.md").write_text(index_content, encoding="utf-8")
    (wiki_dir / "_sources.md").write_text(sources_content, encoding="utf-8")
    console.print("  [green]✓[/green] _index.md + _sources.md created")

    # Save state
    _save_compile_state(project_dir, source_docs)
    append_log(
        project_dir,
        "compile",
        "wiki",
        {
            "sources": len(source_docs),
            "new": len(new_files),
            "changed": len(changed_files),
            "deleted": len(deleted_files),
            "articles_generated": len(concepts),
            "mode": "full" if full else "incremental",
        },
    )
    console.print(f"\n[bold green]Compile complete![/bold green] {len(concepts) + 2} files in wiki/")
