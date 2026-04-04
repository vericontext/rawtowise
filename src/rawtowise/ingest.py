"""Ingest pipeline — URL/file/directory → raw/ storage."""

from __future__ import annotations

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from rich.console import Console

console = Console()


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:80] or "untitled"


def _extract_title_from_md(content: str) -> str:
    """Extract title from first heading or first line."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("# ").strip()
        if line:
            return line[:80]
    return "untitled"


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
        saved.extend(_ingest_url(source, raw_dir))
    else:
        source_path = Path(source).expanduser().resolve()
        if source_path.is_dir():
            for f in sorted(source_path.rglob("*")):
                if f.is_file() and f.suffix in (".md", ".txt", ".pdf", ".html"):
                    saved.extend(_ingest_file(f, raw_dir))
        elif source_path.is_file():
            saved.extend(_ingest_file(source_path, raw_dir))
        else:
            console.print(f"[red]Source not found: {source}[/red]")

    return saved


def _ingest_url(url: str, raw_dir: Path) -> list[Path]:
    """Fetch URL and save as markdown."""
    console.print(f"  [dim]Fetching:[/dim] {url}")
    try:
        content, title = _fetch_url_as_markdown(url)
    except Exception as e:
        console.print(f"  [red]URL fetch failed: {e}[/red]")
        return []

    # Add source metadata header
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"---\nsource: {url}\ningested: {now}\n---\n\n"

    slug = _slugify(title)
    dest = raw_dir / "articles" / f"{slug}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting — append hash if exists
    if dest.exists():
        h = hashlib.md5(url.encode()).hexdigest()[:6]
        dest = dest.with_stem(f"{slug}-{h}")

    dest.write_text(header + content, encoding="utf-8")
    console.print(f"  [green]✓[/green] {dest.relative_to(raw_dir.parent)}")
    return [dest]


def _ingest_file(file_path: Path, raw_dir: Path) -> list[Path]:
    """Copy a local file into raw/."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        sub = "papers"
    elif suffix in (".md", ".txt"):
        sub = "articles"
    elif suffix == ".html":
        sub = "articles"
    else:
        sub = "misc"

    dest_dir = raw_dir / sub
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / file_path.name
    if dest.exists():
        h = hashlib.md5(str(file_path).encode()).hexdigest()[:6]
        dest = dest.with_stem(f"{file_path.stem}-{h}")

    if suffix in (".md", ".txt"):
        content = file_path.read_text(encoding="utf-8")
        # Add frontmatter if missing
        if not content.startswith("---"):
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            header = f"---\nsource: {file_path}\ningested: {now}\n---\n\n"
            content = header + content
        dest.write_text(content, encoding="utf-8")
    else:
        shutil.copy2(file_path, dest)

    console.print(f"  [green]✓[/green] {dest.relative_to(raw_dir.parent)}")
    return [dest]
