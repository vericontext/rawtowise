"""Compile pipeline — raw/ → wiki/ structured knowledge base."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from rawtowise.config import Config
from rawtowise.llm import call_llm

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

Extract up to {max_concepts} concepts. Focus on the most important and cross-referenced ones.
Return ONLY valid JSON, no markdown fences.
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


def _truncate_sources(sources: dict[str, str], max_chars: int = 150_000) -> str:
    """Combine sources into a single text block, truncating if needed."""
    parts = []
    total = 0
    for name, content in sources.items():
        header = f"\n--- SOURCE: {name} ---\n"
        if total + len(header) + len(content) > max_chars:
            remaining = max_chars - total - len(header) - 100
            if remaining > 500:
                parts.append(header + content[:remaining] + "\n[...truncated...]")
            break
        parts.append(header + content)
        total += len(header) + len(content)
    return "\n".join(parts)


def compile_wiki(project_dir: Path, config: Config, full: bool = False) -> None:
    """Compile raw sources into a structured wiki."""
    sources = _read_raw_sources(project_dir)
    if not sources:
        console.print("[yellow]raw/ 디렉토리에 소스가 없습니다. `rtw ingest`로 소스를 추가하세요.[/yellow]")
        return

    # Check for incremental
    prev_state = _load_compile_state(project_dir)
    if not full and set(sources.keys()) == set(prev_state.get("compiled_files", [])):
        console.print("[yellow]변경된 소스가 없습니다. --full 옵션으로 전체 재컴파일할 수 있습니다.[/yellow]")
        return

    wiki_dir = project_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "concepts").mkdir(exist_ok=True)

    lang = config.compile.language
    sources_text = _truncate_sources(sources)

    # Step 1: Extract concepts
    console.print("\n[bold]1/4[/bold] 개념 추출 중...")
    concepts_raw = call_llm(
        config,
        system=SYSTEM_COMPILE.format(language=lang),
        user=PROMPT_EXTRACT_CONCEPTS.format(
            project_name=config.name,
            sources_text=sources_text,
            max_concepts=config.compile.max_concepts,
        ),
        max_tokens=4096,
    )

    try:
        # Try to parse JSON, handling potential markdown fences
        cleaned = concepts_raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        concepts_data = json.loads(cleaned)
        concepts = concepts_data.get("concepts", [])
    except json.JSONDecodeError:
        console.print("[red]개념 추출 JSON 파싱 실패. 재시도합니다...[/red]")
        # Retry with stricter prompt
        concepts = []

    if not concepts:
        console.print("[red]개념을 추출하지 못했습니다.[/red]")
        return

    console.print(f"  [green]✓[/green] {len(concepts)}개 개념 추출됨")

    # Step 2: Write concept articles
    console.print(f"\n[bold]2/4[/bold] 아티클 생성 중 ({len(concepts)}개)...")
    articles_summary = []

    for i, concept in enumerate(concepts):
        cid = concept.get("id", f"concept-{i}")
        title = concept.get("title", cid)
        desc = concept.get("description", "")
        concept_sources = concept.get("sources", [])

        console.print(f"  [{i+1}/{len(concepts)}] {title}...")

        # Gather relevant source texts
        relevant = {}
        for sname in concept_sources:
            if sname in sources:
                relevant[sname] = sources[sname]
        # If no specific sources matched, use all (truncated)
        if not relevant:
            relevant = sources

        wiki_index_text = "\n".join(
            f"- [[{c.get('id', '')}]] — {c.get('description', '')}"
            for c in concepts
        )

        article_content = call_llm(
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

        article_path = wiki_dir / "concepts" / f"{cid}.md"
        article_path.write_text(article_content, encoding="utf-8")
        articles_summary.append(f"- [[{cid}]] ({title}): {desc}")

    console.print(f"  [green]✓[/green] {len(concepts)}개 아티클 생성 완료")

    # Step 3: Write _index.md
    console.print("\n[bold]3/4[/bold] 인덱스 생성 중...")
    index_content = call_llm(
        config,
        system=SYSTEM_COMPILE.format(language=lang),
        user=PROMPT_WRITE_INDEX.format(
            project_name=config.name,
            articles_summary="\n".join(articles_summary),
            language=lang,
        ),
        max_tokens=4096,
    )
    (wiki_dir / "_index.md").write_text(index_content, encoding="utf-8")
    console.print("  [green]✓[/green] _index.md 생성")

    # Step 4: Write _sources.md
    console.print("\n[bold]4/4[/bold] 소스 카탈로그 생성 중...")
    sources_list_text = "\n".join(
        f"- {name} ({len(content)} chars)" for name, content in sources.items()
    )
    sources_content = call_llm(
        config,
        system=SYSTEM_COMPILE.format(language=lang),
        user=PROMPT_WRITE_SOURCES.format(
            sources_list=sources_list_text,
            language=lang,
        ),
        max_tokens=4096,
    )
    (wiki_dir / "_sources.md").write_text(sources_content, encoding="utf-8")
    console.print("  [green]✓[/green] _sources.md 생성")

    # Save state
    _save_compile_state(project_dir, sources)
    console.print(f"\n[bold green]컴파일 완료![/bold green] wiki/ 에 {len(concepts) + 2}개 파일 생성됨")
