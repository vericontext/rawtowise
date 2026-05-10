"""Query pipeline — search wiki, synthesize answers, optionally file back."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from rawtowise.config import Config
from rawtowise.llm import call_llm, stream_llm
from rawtowise.sources import append_log, rel_path

console = Console()

SYSTEM_QUERY = """\
You are a research assistant that answers questions using a curated knowledge wiki.

RULES:
- Base your answers ONLY on the wiki content provided. If the wiki doesn't cover something, say so.
- Cite sources using [source: source_id:location] notation when available.
- Use [[concept-name]] to reference wiki articles.
- Be thorough, analytical, and precise.
- Write in {language}.
"""

PROMPT_FIND_RELEVANT = """\
Here is the wiki index:

<index>
{index_content}
</index>

The user's question is: "{question}"

List the wiki article filenames (just the filenames, one per line) that are most relevant \
to answering this question. List up to 10 articles, most relevant first.
Return ONLY filenames, one per line, no bullets or numbers.
"""

PROMPT_ANSWER = """\
The user asked: "{question}"

Here is the relevant wiki content:

<wiki_content>
{wiki_content}
</wiki_content>

Provide a comprehensive answer based on the wiki content.
- Cite sources with [source: source_id:location] when available
- Reference wiki articles with [[concept-name]]
- If the wiki doesn't have enough information, state what's missing
- Write in {language}
{format_instruction}
"""

FORMAT_INSTRUCTIONS = {
    "text": "",
    "table": "\nFormat the answer as a markdown table where appropriate.",
    "marp": (
        "\nFormat the answer as a Marp slide deck. "
        "Start with `---\\nmarp: true\\n---` and separate slides with `---`."
    ),
}


def _read_wiki_index(project_dir: Path) -> str:
    """Read the wiki index file."""
    index_path = project_dir / "wiki" / "_index.md"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return ""


def _read_wiki_articles(project_dir: Path) -> dict[str, str]:
    """Read all wiki articles."""
    wiki_dir = project_dir / "wiki"
    if not wiki_dir.exists():
        return {}

    articles = {}
    for f in sorted(wiki_dir.rglob("*.md")):
        rel = f.relative_to(wiki_dir)
        articles[str(rel)] = f.read_text(encoding="utf-8")
    return articles


def _file_back_answer(
    project_dir: Path, question: str, answer: str, fmt: str
) -> Path | None:
    """Save the answer back into output/queries/."""
    output_dir = project_dir / "output" / "queries"
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Create a slug from the question
    slug = re.sub(r"[^\w\s]", "", question.lower())
    slug = re.sub(r"\s+", "-", slug.strip())[:50]

    ext = ".marp.md" if fmt == "marp" else ".md"
    filename = f"{date_str}-{slug}{ext}"
    filepath = output_dir / filename

    frontmatter = f"---\nquestion: \"{question}\"\ndate: {date_str}\nformat: {fmt}\n---\n\n"
    filepath.write_text(frontmatter + answer, encoding="utf-8")
    return filepath


def query_wiki(
    question: str,
    project_dir: Path,
    config: Config,
    fmt: str = "text",
    file_back: bool | None = None,
    deep: bool = False,
) -> str:
    """Query the wiki and return an answer."""
    index_content = _read_wiki_index(project_dir)
    if not index_content:
        console.print("[yellow]No wiki found. Run `rtw compile` first.[/yellow]")
        return ""

    all_articles = _read_wiki_articles(project_dir)
    if not all_articles:
        console.print("[yellow]No wiki articles found.[/yellow]")
        return ""

    lang = config.compile.language
    model = config.llm.query

    # Step 1: Find relevant articles
    console.print("[dim]Searching relevant articles...[/dim]")
    relevant_names_raw = call_llm(
        config,
        model=model,
        system="You help find relevant wiki articles. Return only filenames.",
        user=PROMPT_FIND_RELEVANT.format(
            index_content=index_content,
            question=question,
        ),
        max_tokens=1024,
    )

    # Parse filenames
    candidate_names = []
    for line in relevant_names_raw.strip().splitlines():
        name = line.strip().lstrip("- ").lstrip("0123456789. ")
        if name:
            candidate_names.append(name)

    # Match to actual articles
    relevant_content_parts = []
    for cname in candidate_names:
        for aname, acontent in all_articles.items():
            # Fuzzy match: check if candidate name appears in article path
            if cname in aname or aname in cname or Path(cname).stem in aname:
                relevant_content_parts.append(f"\n--- ARTICLE: {aname} ---\n{acontent}")
                break

    # If no match found, use all articles (for small wikis)
    if not relevant_content_parts:
        for aname, acontent in all_articles.items():
            relevant_content_parts.append(f"\n--- ARTICLE: {aname} ---\n{acontent}")

    wiki_content = "\n".join(relevant_content_parts)

    # Truncate if too long
    if len(wiki_content) > 150_000:
        wiki_content = wiki_content[:150_000] + "\n[...truncated...]"

    # Step 2: Generate answer (streamed)
    console.print("[dim]Generating answer...[/dim]\n")
    format_instruction = FORMAT_INSTRUCTIONS.get(fmt, "")

    chunks: list[str] = []
    for chunk in stream_llm(
        config,
        model=model,
        system=SYSTEM_QUERY.format(language=lang),
        user=PROMPT_ANSWER.format(
            question=question,
            wiki_content=wiki_content,
            language=lang,
            format_instruction=format_instruction,
        ),
        max_tokens=8192 if deep else 4096,
    ):
        print(chunk, end="", flush=True)
        chunks.append(chunk)

    answer = "".join(chunks)
    print()  # newline after stream

    # File back
    should_file_back = file_back if file_back is not None else config.file_back
    saved: Path | None = None
    if should_file_back:
        saved = _file_back_answer(project_dir, question, answer, fmt)
        if saved:
            console.print(f"\n[dim]Answer saved: {saved.relative_to(project_dir)}[/dim]")

    append_log(
        project_dir,
        "query",
        question[:80],
        {
            "format": fmt,
            "deep": deep,
            "saved": rel_path(project_dir, saved) if should_file_back and saved else None,
        },
    )

    return answer
