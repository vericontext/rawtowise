"""Lint pipeline — wiki health check: contradictions, gaps, stale info."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from rawtowise.config import Config
from rawtowise.llm import call_llm

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

Return ONLY valid JSON.
"""

CHECK_TYPES = {
    "contradictions": "1. CONTRADICTIONS: Claims in one article that conflict with claims in another.",
    "gaps": "2. COVERAGE GAPS: Important topics mentioned but lacking their own article, or topics that should be covered given the scope.",
    "stale": "3. STALE INFORMATION: Claims that may be outdated or that lack source citations.",
    "suggest": "4. EXPLORATION SUGGESTIONS: Interesting questions to investigate next, connections worth exploring.",
}


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
        console.print("[yellow]wiki가 없습니다. 먼저 `rtw compile`을 실행하세요.[/yellow]")
        return None

    # Read all wiki content
    wiki_parts = []
    for f in sorted(wiki_dir.rglob("*.md")):
        rel = f.relative_to(wiki_dir)
        content = f.read_text(encoding="utf-8")
        wiki_parts.append(f"\n--- {rel} ---\n{content}")

    wiki_content = "\n".join(wiki_parts)
    if not wiki_content.strip():
        console.print("[yellow]wiki가 비어있습니다.[/yellow]")
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

    console.print("[bold]위키 헬스체크 실행 중...[/bold]")

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
    try:
        cleaned = result_raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        report = json.loads(cleaned)
    except json.JSONDecodeError:
        console.print("[red]린트 결과 파싱 실패[/red]")
        console.print(result_raw)
        return None

    # Display report
    score = report.get("score", 0)
    color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    console.print(Panel(
        f"[bold {color}]Health Score: {score}/100[/bold {color}]\n\n{report.get('summary', '')}",
        title="Wiki Health Report",
    ))

    issues = report.get("issues", [])
    if issues:
        console.print(f"\n[bold]발견된 이슈: {len(issues)}개[/bold]")
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
        console.print("\n[bold]탐색 제안:[/bold]")
        for q in suggestions:
            console.print(f"  ? {q}")

    # Save report
    rtw_dir = project_dir / ".rtw"
    rtw_dir.mkdir(parents=True, exist_ok=True)
    report["timestamp"] = datetime.now(timezone.utc).isoformat()
    (rtw_dir / "lint-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    return report
