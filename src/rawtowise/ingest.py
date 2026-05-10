"""Ingest pipeline — URL/file/directory → raw/ storage."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from rich.console import Console

from rawtowise.sources import (
    append_log,
    make_source_id,
    processed_source_path,
    rel_path,
    sha256_file,
    slugify,
    source_display_name,
    upsert_source,
    utc_date,
)

console = Console()

NATIVE_TEXT_SUFFIXES = {".md", ".txt"}
CONVERTIBLE_SUFFIXES = {
    ".pdf",
    ".html",
    ".htm",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".json",
    ".xml",
    ".epub",
}
SUPPORTED_SUFFIXES = NATIVE_TEXT_SUFFIXES | CONVERTIBLE_SUFFIXES


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    return slugify(text)


def _extract_title_from_md(content: str) -> str:
    """Extract title from first heading or first line."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("# ").strip()
        if line:
            return line[:80]
    return "untitled"


def _clean_web_markdown(content: str) -> str:
    """Strip web boilerplate from Jina Reader markdown output.

    Removes navigation menus, image refs, checkbox UI artifacts,
    and Wikipedia footer sections to keep only article content.
    """
    lines = content.splitlines()

    # 1. Find actual content start
    # Strategy: find "Markdown Content:" marker, then keep the # Title line
    # but skip everything until the first real ## section heading
    title_line = ""
    mc_index = -1
    for i, line in enumerate(lines):
        if line.strip() == "Markdown Content:":
            mc_index = i
            break

    if mc_index >= 0:
        # Find the title line (first # heading after marker)
        for i in range(mc_index + 1, min(mc_index + 5, len(lines))):
            if lines[i].startswith("# "):
                title_line = lines[i]
                break
        # Find first real ## section (skip "## Contents" and nav)
        start = mc_index + 1
        skip_headings = {"contents", "search", "personal tools", "navigation",
                         "contribute", "appearance", "general", "languages"}
        for i in range(mc_index + 1, len(lines)):
            if lines[i].startswith("## "):
                heading_text = lines[i].lstrip("# ").strip().lower()
                if heading_text not in skip_headings:
                    start = i
                    break
        lines = lines[start:]
        if title_line:
            lines.insert(0, title_line)
            lines.insert(1, "")
    else:
        # Fallback: skip to first ## heading
        for i, line in enumerate(lines):
            if re.match(r"^##\s+\S", line):
                lines = lines[i:]
                break

    # 2. Truncate at terminal sections (References, External links)
    end = len(lines)
    for i, line in enumerate(lines):
        if re.match(r"^##\s+(References|External [Ll]inks|Notes|Citations)\s*$", line):
            end = i
            break
    lines = lines[:end]

    cleaned = []
    for line in lines:
        # 3. Remove image references
        if re.match(r"^\s*!\[", line):
            continue
        # 4. Remove standalone link-only lines (nav artifacts)
        if re.match(r"^\s*\[.*?\]\(.*?\)\s*$", line) and not line.strip().startswith("*"):
            continue
        # 5. Clean checkbox markup (Wikipedia UI artifacts)
        line = re.sub(r"^(\s*)-\s*\[[ x]\]\s*", r"\1- ", line)
        # 6. Remove [edit] link lines and inline [edit] refs
        if re.match(r"^\s*\[+\s*edit\s*\]", line):
            continue
        line = re.sub(r"\s*\[+\s*edit\s*\]+\s*(\([^)]*\))?\s*\]?", "", line)
        # 7. Remove footnote references like [1], [23], [175]
        line = re.sub(r"\[(\d+)\]", "", line)
        cleaned.append(line)

    result = "\n".join(cleaned)
    # 6. Collapse 3+ consecutive blank lines to 2
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _encode_url(url: str) -> str:
    """Encode URL path segments to handle special characters like parentheses."""
    parsed = urlparse(url)
    encoded_path = quote(parsed.path, safe="/")
    return parsed._replace(path=encoded_path).geturl()


def _fetch_url_as_markdown(url: str) -> tuple[str, str]:
    """Fetch a URL and convert to markdown using Jina Reader."""
    encoded = _encode_url(url)
    reader_url = f"https://r.jina.ai/{encoded}"
    resp = httpx.get(reader_url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    content = resp.text
    title = _extract_title_from_md(content)
    return content, title


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def ingest_source(source: str, project_dir: Path) -> list[Path]:
    """Ingest a source (URL, file, or directory) into raw/.

    Returns list of saved file paths.
    """
    raw_dir = project_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []

    if _is_url(source):
        saved.extend(_ingest_url(source, project_dir))
    else:
        source_path = Path(source).expanduser().resolve()
        if source_path.is_dir():
            for f in sorted(source_path.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES:
                    saved.extend(_ingest_file(f, project_dir))
        elif source_path.is_file():
            saved.extend(_ingest_file(source_path, project_dir))
        else:
            console.print(f"[red]Source not found: {source}[/red]")

    return saved


def _ingest_url(url: str, project_dir: Path) -> list[Path]:
    """Fetch URL and save as markdown."""
    raw_dir = project_dir / "raw"
    console.print(f"  [dim]Fetching:[/dim] {url}")
    try:
        content, title = _fetch_url_as_markdown(url)
    except Exception as e:
        console.print(f"  [red]URL fetch failed: {e}[/red]")
        return []

    # Clean web boilerplate (nav menus, image refs, etc.)
    content = _clean_web_markdown(content)

    # Add source metadata header
    now = utc_date()
    header = f"---\nsource: {url}\ningested: {now}\n---\n\n"

    slug = _slugify(title)
    dest = raw_dir / "articles" / f"{slug}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting — append hash if exists
    if dest.exists():
        h = hashlib.md5(url.encode()).hexdigest()[:6]
        dest = dest.with_stem(f"{slug}-{h}")

    dest.write_text(header + content, encoding="utf-8")

    file_hash = sha256_file(dest)
    source_id = make_source_id(title, url)
    record = upsert_source(project_dir, {
        "id": source_id,
        "title": title,
        "kind": "url",
        "source": url,
        "raw_path": rel_path(project_dir, dest),
        "processed_path": None,
        "sha256": file_hash,
        "processed_sha256": None,
        "parser": "jina-reader",
        "status": "ready",
        "content_type": "markdown",
    })
    append_log(
        project_dir,
        "ingest",
        source_display_name(record),
        {"source_id": source_id, "raw": rel_path(project_dir, dest), "parser": "jina-reader"},
    )
    console.print(f"  [green]✓[/green] {dest.relative_to(raw_dir.parent)}")
    return [dest]


def _ingest_file(file_path: Path, project_dir: Path) -> list[Path]:
    """Copy a local file into raw/."""
    raw_dir = project_dir / "raw"
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        sub = "papers"
    elif suffix in (".md", ".txt", ".html", ".htm"):
        sub = "articles"
    elif suffix in {".csv", ".json", ".xml", ".xls", ".xlsx"}:
        sub = "data"
    elif suffix in {".doc", ".docx", ".ppt", ".pptx", ".epub"}:
        sub = "documents"
    else:
        sub = "misc"

    dest_dir = raw_dir / sub
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / file_path.name
    if dest.exists():
        h = hashlib.md5(str(file_path).encode()).hexdigest()[:6]
        dest = dest.with_stem(f"{file_path.stem}-{h}")

    if suffix in NATIVE_TEXT_SUFFIXES:
        content = file_path.read_text(encoding="utf-8")
        # Add frontmatter if missing
        if not content.startswith("---"):
            now = utc_date()
            header = f"---\nsource: {file_path}\ningested: {now}\n---\n\n"
            content = header + content
        dest.write_text(content, encoding="utf-8")
    else:
        shutil.copy2(file_path, dest)

    raw_hash = sha256_file(dest)
    title = file_path.stem
    source_id = make_source_id(title, str(file_path))
    processed: Path | None = None
    processed_hash: str | None = None
    parser = "native"
    status = "ready"
    error = None

    if suffix in CONVERTIBLE_SUFFIXES:
        parser = "markitdown"
        processed = processed_source_path(project_dir, source_id)
        processed.parent.mkdir(parents=True, exist_ok=True)
        try:
            converted = _convert_file_to_markdown(dest)
            processed.write_text(
                _processed_header(file_path, source_id, parser) + converted,
                encoding="utf-8",
            )
            processed_hash = sha256_file(processed)
            title = _extract_title_from_md(converted) or title
        except Exception as e:
            processed = None
            parser = "markitdown"
            status = "failed"
            error = str(e)
            console.print(f"  [yellow]Conversion skipped:[/yellow] {file_path.name} ({e})")

    record = upsert_source(project_dir, {
        "id": source_id,
        "title": title,
        "kind": "file",
        "source": str(file_path),
        "raw_path": rel_path(project_dir, dest),
        "processed_path": rel_path(project_dir, processed),
        "sha256": raw_hash,
        "processed_sha256": processed_hash,
        "parser": parser,
        "status": status,
        "error": error,
        "content_type": suffix.lstrip(".") or "file",
    })
    append_log(
        project_dir,
        "ingest",
        source_display_name(record),
        {
            "source_id": source_id,
            "raw": rel_path(project_dir, dest),
            "processed": rel_path(project_dir, processed),
            "parser": parser,
            "status": status,
        },
    )

    console.print(f"  [green]✓[/green] {dest.relative_to(raw_dir.parent)}")
    return [dest]


def _convert_file_to_markdown(file_path: Path) -> str:
    """Convert a file to Markdown using MarkItDown."""
    from markitdown import MarkItDown

    result = MarkItDown().convert(file_path)
    markdown = result.text_content or result.markdown
    if not markdown.strip():
        raise ValueError("conversion produced empty markdown")
    return markdown.strip()


def _processed_header(source_path: Path, source_id: str, parser: str) -> str:
    now = utc_date()
    return (
        "---\n"
        f"source: {source_path}\n"
        f"source_id: {source_id}\n"
        f"processed: {now}\n"
        f"parser: {parser}\n"
        "---\n\n"
    )
