"""Lint pipeline — wiki health check: contradictions, gaps, stale info."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from rawtowise.config import Config
from rawtowise.llm import call_llm
from rawtowise.sources import abs_path, append_log, load_manifest, rel_path, sha256_file

console = Console()

SYSTEM_LINT = """\
You are a knowledge base quality auditor. Your job is to review a wiki for issues \
and suggest improvements.

Write in {language}. Be specific — cite exact article names and claims.
"""

PROMPT_LINT = """\
Here is the complete wiki content:

<wiki>
{wiki_content}
</wiki>

Perform a thorough health check. Find and report:

{checks}

For each issue found, provide:
- Category (contradiction / gap / stale / suggestion)
- Severity (high / medium / low)
- Description with specific article references
- Suggested fix

Also provide an overall health score (0-100) and a summary.

Output as JSON:
{{
  "score": 85,
  "summary": "Overall assessment...",
  "issues": [
    {{
      "category": "contradiction",
      "severity": "high",
      "description": "...",
      "articles": ["article1.md", "article2.md"],
      "suggestion": "..."
    }}
  ],
  "suggested_questions": ["question1", "question2"]
}}

Return ONLY valid JSON, no markdown fences, no commentary.
"""

CHECK_TYPES = {
    "contradictions": "1. CONTRADICTIONS: Claims in one article that conflict with claims in another.",
    "gaps": "2. COVERAGE GAPS: Important topics mentioned but lacking their own article, or topics that should be covered given the scope.",
    "stale": "3. STALE INFORMATION: Claims that may be outdated or that lack source citations.",
    "suggest": "4. EXPLORATION SUGGESTIONS: Interesting questions to investigate next, connections worth exploring.",
}


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    brace_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass
    return None


def lint_wiki(
    project_dir: Path,
    config: Config,
    contradictions: bool = True,
    gaps: bool = True,
    stale: bool = True,
    suggest: bool = True,
) -> dict | None:
    """Run wiki health check and return report."""
    wiki_dir = project_dir / "wiki"
    if not wiki_dir.exists():
        console.print("[yellow]No wiki found. Run `rtw compile` first.[/yellow]")
        return None

    structural_issues = _structural_issues(project_dir)

    # Read all wiki content
    wiki_parts = []
    for f in sorted(wiki_dir.rglob("*.md")):
        rel = f.relative_to(wiki_dir)
        content = f.read_text(encoding="utf-8")
        wiki_parts.append(f"\n--- {rel} ---\n{content}")

    wiki_content = "\n".join(wiki_parts)
    if not wiki_content.strip():
        console.print("[yellow]Wiki is empty.[/yellow]")
        return None

    # Build checks list
    checks = []
    if contradictions:
        checks.append(CHECK_TYPES["contradictions"])
    if gaps:
        checks.append(CHECK_TYPES["gaps"])
    if stale:
        checks.append(CHECK_TYPES["stale"])
    if suggest:
        checks.append(CHECK_TYPES["suggest"])

    lang = config.compile.language

    console.print("[bold]Running wiki health check...[/bold]")

    result_raw = call_llm(
        config,
        model=config.llm.lint,
        system=SYSTEM_LINT.format(language=lang),
        user=PROMPT_LINT.format(
            wiki_content=wiki_content[:150_000],
            checks="\n".join(checks),
        ),
        max_tokens=4096,
    )

    # Parse JSON
    report = _extract_json(result_raw)
    if not report:
        console.print("[red]Failed to parse lint result[/red]")
        console.print(result_raw)
        return None

    if structural_issues:
        report.setdefault("issues", [])
        report["issues"] = structural_issues + report["issues"]
        try:
            base_score = int(report.get("score", 0))
        except (TypeError, ValueError):
            base_score = 0
        report["score"] = max(0, base_score - min(20, len(structural_issues) * 2))

    # Display report
    try:
        score = int(report.get("score", 0))
    except (TypeError, ValueError):
        score = 0
        report["score"] = score
    color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(Panel(
        f"[bold {color}]Health Score: {score}/100[/bold {color}]\n\n{report.get('summary', '')}",
        title="Wiki Health Report",
    ))

    issues = report.get("issues", [])
    if issues:
        console.print(f"\n[bold]Issues found: {len(issues)}[/bold]")
        for issue in issues:
            sev = issue.get("severity", "?")
            sev_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(sev, "white")
            cat = issue.get("category", "?")
            desc = issue.get("description", "")
            console.print(f"  [{sev_color}][{sev}][/{sev_color}] [{cat}] {desc}")
            if issue.get("suggestion"):
                console.print(f"    [dim]→ {issue['suggestion']}[/dim]")

    suggestions = report.get("suggested_questions", [])
    if suggestions:
        console.print("\n[bold]Suggested explorations:[/bold]")
        for q in suggestions:
            console.print(f"  ? {q}")

    # Save report
    rtw_dir = project_dir / ".rtw"
    rtw_dir.mkdir(parents=True, exist_ok=True)
    report["timestamp"] = datetime.now(timezone.utc).isoformat()
    (rtw_dir / "lint-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    append_log(
        project_dir,
        "lint",
        "wiki health check",
        {
            "score": report.get("score"),
            "issues": len(report.get("issues", [])),
            "report": rel_path(project_dir, rtw_dir / "lint-report.json"),
        },
    )

    return report


def _structural_issues(project_dir: Path) -> list[dict]:
    """Find deterministic structural wiki problems before the LLM audit."""
    wiki_dir = project_dir / "wiki"
    issues: list[dict] = []
    if not wiki_dir.exists():
        return issues

    wiki_files = sorted(wiki_dir.rglob("*.md"))
    page_stems = {p.stem for p in wiki_files}
    inbound: dict[str, int] = {p.stem: 0 for p in wiki_files}

    for path in wiki_files:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = path.relative_to(wiki_dir).as_posix()

        if rel.startswith("concepts/") and "[source:" not in content:
            issues.append({
                "category": "gap",
                "severity": "medium",
                "description": f"{rel} has no source citations.",
                "articles": [rel],
                "suggestion": "Add source citations to factual claims.",
            })

        for target in re.findall(r"\[\[([^\]]+)\]\]", content):
            slug = target.split("|", 1)[0].strip()
            slug = Path(slug).stem
            if slug in inbound:
                inbound[slug] += 1
            elif slug not in page_stems:
                issues.append({
                    "category": "gap",
                    "severity": "low",
                    "description": f"{rel} links to missing page [[{slug}]].",
                    "articles": [rel],
                    "suggestion": f"Create {slug}.md or update the wikilink.",
                })

    for path in wiki_files:
        rel = path.relative_to(wiki_dir).as_posix()
        if rel.startswith("concepts/") and inbound.get(path.stem, 0) == 0:
            issues.append({
                "category": "gap",
                "severity": "low",
                "description": f"{rel} has no inbound wikilinks.",
                "articles": [rel],
                "suggestion": "Add cross-references from related pages or the index.",
            })

    manifest = load_manifest(project_dir)
    for source_id, record in sorted(manifest.get("sources", {}).items()):
        raw_path = abs_path(project_dir, record.get("raw_path"))
        processed_path = abs_path(project_dir, record.get("processed_path"))
        check_path = processed_path or raw_path
        if raw_path and not raw_path.exists():
            issues.append({
                "category": "stale",
                "severity": "high",
                "description": f"Raw source file for {source_id} is missing.",
                "articles": ["_sources.md"],
                "suggestion": "Re-ingest the source or remove the stale manifest record.",
            })
        if not check_path or not check_path.exists():
            issues.append({
                "category": "stale",
                "severity": "high",
                "description": f"Source {source_id} points to a missing file.",
                "articles": ["_sources.md"],
                "suggestion": "Re-ingest the source or remove the stale manifest record.",
            })
            continue

        raw_expected = record.get("sha256")
        if raw_path and raw_path.exists() and raw_expected and sha256_file(raw_path) != raw_expected:
            issues.append({
                "category": "stale",
                "severity": "medium",
                "description": f"Raw source {source_id} has changed since ingest.",
                "articles": ["_sources.md"],
                "suggestion": "Re-ingest the source so processed markdown and hashes stay aligned.",
            })

        processed_expected = record.get("processed_sha256")
        if (
            processed_path
            and processed_path.exists()
            and processed_expected
            and sha256_file(processed_path) != processed_expected
        ):
            issues.append({
                "category": "stale",
                "severity": "medium",
                "description": f"Processed source {source_id} has changed since ingest.",
                "articles": ["_sources.md"],
                "suggestion": "Run rtw compile to refresh affected wiki pages.",
            })

    return issues
