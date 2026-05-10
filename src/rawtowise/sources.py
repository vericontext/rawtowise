"""Source manifest, wiki schema, and operation log helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1
MANIFEST_PATH = ".rtw/sources.json"


def utc_date() -> str:
    """Return the current UTC date."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_timestamp() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str, max_len: int = 80) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def sha256_file(path: Path) -> str:
    """Hash a file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """Hash a text blob in UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel_path(project_dir: Path, path: Path | None) -> str | None:
    """Store paths in manifests relative to the project root."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return path.expanduser().resolve().as_posix()


def abs_path(project_dir: Path, value: str | None) -> Path | None:
    """Resolve a manifest path back to an absolute path."""
    if not value:
        return None
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    return project_dir / p


def load_manifest(project_dir: Path) -> dict[str, Any]:
    """Load source manifest, returning an empty manifest if missing."""
    path = project_dir / MANIFEST_PATH
    if not path.exists():
        return {"version": MANIFEST_VERSION, "sources": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": MANIFEST_VERSION, "sources": {}}
    raw.setdefault("version", MANIFEST_VERSION)
    raw.setdefault("sources", {})
    return raw


def save_manifest(project_dir: Path, manifest: dict[str, Any]) -> None:
    """Persist source manifest."""
    path = project_dir / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["version"] = MANIFEST_VERSION
    manifest.setdefault("sources", {})
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_source_id(title: str, identity: str, existing: set[str] | None = None) -> str:
    """Create a stable, collision-resistant source id."""
    existing = existing or set()
    base = slugify(title or identity, max_len=56)
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    source_id = f"{base}-{suffix}"
    if source_id not in existing:
        return source_id

    i = 2
    while f"{source_id}-{i}" in existing:
        i += 1
    return f"{source_id}-{i}"


def processed_source_path(project_dir: Path, source_id: str) -> Path:
    """Return the processed markdown path for a source."""
    return project_dir / ".rtw" / "processed" / "sources" / f"{source_id}.md"


def upsert_source(project_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a source record in the manifest."""
    manifest = load_manifest(project_dir)
    sources = manifest.setdefault("sources", {})
    record = dict(record)
    record.setdefault("ingested_at", utc_timestamp())
    record.setdefault("status", "ready")
    record["updated_at"] = utc_timestamp()
    sources[record["id"]] = record
    save_manifest(project_dir, manifest)
    return record


def source_display_name(record: dict[str, Any]) -> str:
    """Readable label for logs and catalogs."""
    return str(record.get("title") or record.get("source") or record.get("id") or "source")


def ensure_wiki_scaffold(project_dir: Path, project_name: str = "My Research") -> None:
    """Create schema and log files if missing."""
    wiki_dir = project_dir / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "concepts").mkdir(exist_ok=True)

    agents_path = wiki_dir / "AGENTS.md"
    if not agents_path.exists():
        agents_path.write_text(
            f"""# {project_name} Wiki Agent Guide

This wiki is maintained by RawToWise. The raw sources are the source of truth; generated wiki pages are synthesis artifacts.

## Structure

- `_index.md`: catalog of generated pages and major themes.
- `_sources.md`: catalog of source records and their provenance.
- `concepts/`: synthesized concept pages with wikilinks.
- `log.md`: append-only timeline of ingests, compiles, queries, and lint runs.

## Rules

- Do not modify raw source files during wiki maintenance.
- Prefer updating existing concept pages over creating duplicates.
- Use `[[concept-slug]]` links for related pages.
- Cite factual claims with `[source: source_id:location]` where location is a page, line, or chunk id when available.
- If sources conflict, state the contradiction and cite both sides.
- Keep pages concise enough for repeated agent use.
""",
            encoding="utf-8",
        )

    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        log_path.write_text(f"# {project_name} Wiki Log\n\n", encoding="utf-8")


def append_log(
    project_dir: Path,
    event: str,
    title: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append a parseable entry to wiki/log.md."""
    ensure_wiki_scaffold(project_dir)
    log_path = project_dir / "wiki" / "log.md"
    details = details or {}
    date = utc_date()
    lines = [f"## [{date}] {event} | {title}"]
    for key, value in details.items():
        if value is None:
            continue
        lines.append(f"- {key}: {value}")
    lines.append("")
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
