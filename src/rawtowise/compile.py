"""Compile pipeline — raw/ → wiki/ structured knowledge base."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from rawtowise.config import Config
from rawtowise.llm import call_llm, call_llm_async

console = Console()

SYSTEM_COMPILE = """\
You are a knowledge compiler. Your job is to read raw source documents and produce \
a structured wiki in markdown format.

RULES:
- Write in {language}.
- Every claim MUST cite its source as [source: filename].
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

TASK: Analyze all sources and extract the key concepts, entities, and themes.

Return a JSON object with this structure:
{{
  "concepts": [
    {{
      "id": "concept-slug",
      "title": "Concept Title",
      "description": "One-line description",
      "sources": ["source-file-1.md", "source-file-2.md"],
      "related": ["other-concept-slug"]
    }}
  ]
}}

Extract EXACTLY {max_concepts} concepts — no more, no less.
Only include the highest-level, most important concepts. Merge related sub-topics into broader concepts.
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
- YAML frontmatter with: title, tags (list), sources (list of filenames), created (date)
- Use ## and ### headings to structure the content
- Cite sources as [source: filename] for every factual claim
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
- Filename
- Source URL or path (from frontmatter if available)
- Ingested date
- Brief description (1-2 sentences)
- Which wiki concepts it contributes to

Write in {language}. Output ONLY the markdown content.
"""


def _read_raw_sources(project_dir: Path) -> dict[str, str]:
    """Read all raw source files and return {filename: content}."""
    raw_dir = project_dir / "raw"
    if not raw_dir.exists():
        return {}

    sources = {}
    for f in sorted(raw_dir.rglob("*")):
        if f.is_file() and f.suffix in (".md", ".txt"):
            rel = f.relative_to(raw_dir)
            try:
                sources[str(rel)] = f.read_text(encoding="utf-8")
            except Exception:
                continue
    return sources


def _load_compile_state(project_dir: Path) -> dict:
    """Load previous compile state."""
    state_path = project_dir / ".rtw" / "compile-state.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {"compiled_files": [], "last_compile": None}


def _save_compile_state(project_dir: Path, sources: dict[str, str]):
    """Save compile state."""
    rtw_dir = project_dir / ".rtw"
    rtw_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "compiled_files": list(sources.keys()),
        "last_compile": datetime.now(timezone.utc).isoformat(),
    }
    (rtw_dir / "compile-state.json").write_text(json.dumps(state, indent=2))


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
        # Cap each source individually
        capped = content[:max_per_source]
        if len(content) > max_per_source:
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


def compile_wiki(project_dir: Path, config: Config, full: bool = False) -> None:
    """Compile raw sources into a structured wiki."""
    sources = _read_raw_sources(project_dir)
    if not sources:
        console.print("[yellow]No sources in raw/. Run `rtw ingest` to add sources.[/yellow]")
        return

    # Check for incremental
    prev_state = _load_compile_state(project_dir)
    if not full and set(sources.keys()) == set(prev_state.get("compiled_files", [])):
        console.print("[yellow]No new sources. Use --full to force a full recompile.[/yellow]")
        return

    wiki_dir = project_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "concepts").mkdir(exist_ok=True)

    lang = config.compile.language
    sources_text = _truncate_sources(sources)

    # Scale concepts to source count: ~5 per source, capped by config
    max_concepts = min(config.compile.max_concepts, max(5, len(sources) * 5))

    # Step 1: Extract concepts
    console.print("\n[bold]1/4[/bold] Extracting concepts...")
    concepts_raw = call_llm(
        config,
        system=SYSTEM_COMPILE.format(language=lang),
        user=PROMPT_EXTRACT_CONCEPTS.format(
            project_name=config.name,
            sources_text=sources_text,
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
        console.print(f"[red]Failed to extract concepts.[/red]")
        console.print(f"[dim]LLM response ({len(concepts_raw)} chars): {preview}...[/dim]")
        console.print(f"[dim]Debug saved to .rtw/debug/[/dim]")
        return

    console.print(f"  [green]✓[/green] {len(concepts)} concepts extracted")

    # Step 2: Write concept articles (parallel)
    console.print(f"\n[bold]2/4[/bold] Generating articles ({len(concepts)}) in parallel...")

    wiki_index_text = "\n".join(
        f"- [[{c.get('id', '')}]] — {c.get('description', '')}"
        for c in concepts
    )

    async def _generate_article(i: int, concept: dict) -> tuple[str, str, str]:
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
        console.print(f"  [green]✓[/green] {title}")
        return cid, title, desc, content

    results = asyncio.run(asyncio.gather(
        *[_generate_article(i, c) for i, c in enumerate(concepts)]
    ))

    articles_summary = []
    for cid, title, desc, content in results:
        (wiki_dir / "concepts" / f"{cid}.md").write_text(content, encoding="utf-8")
        articles_summary.append(f"- [[{cid}]] ({title}): {desc}")

    console.print(f"  {len(concepts)} articles generated")

    # Step 3+4: Generate index and source catalog in parallel
    console.print("\n[bold]3/4[/bold] Generating index + source catalog...")
    sources_list_text = "\n".join(
        f"- {name} ({len(content)} chars)" for name, content in sources.items()
    )

    async def _generate_meta():
        idx, src = await asyncio.gather(
            call_llm_async(
                config,
                system=SYSTEM_COMPILE.format(language=lang),
                user=PROMPT_WRITE_INDEX.format(
                    project_name=config.name,
                    articles_summary="\n".join(articles_summary),
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
    _save_compile_state(project_dir, sources)
    console.print(f"\n[bold green]Compile complete![/bold green] {len(concepts) + 2} files in wiki/")
