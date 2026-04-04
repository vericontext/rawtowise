"""RawToWise CLI — LLM Knowledge Compiler."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from rawtowise import __version__
from rawtowise.config import Config, default_yaml, load_config

app = typer.Typer(
    name="rtw",
    help="RawToWise — raw 문서를 LLM이 구조화된 위키로 컴파일합니다.",
    no_args_is_help=True,
)
console = Console()


def _resolve_project(project: str | None) -> Path:
    """Resolve project directory."""
    if project:
        p = Path(project).resolve()
    else:
        p = Path.cwd()
    return p


def _load(project: str | None) -> tuple[Path, Config]:
    """Resolve project dir and load config."""
    project_dir = _resolve_project(project)
    config = load_config(project_dir)
    return project_dir, config


@app.command()
def init(
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 디렉토리"),
    name: str = typer.Option("My Research", "--name", "-n", help="프로젝트 이름"),
):
    """새 RawToWise 프로젝트를 초기화합니다."""
    project_dir = _resolve_project(project)

    # Create directories
    for d in ["raw/articles", "raw/papers", "wiki/concepts", "output/queries", ".rtw"]:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Write rtw.yaml
    config_path = project_dir / "rtw.yaml"
    if not config_path.exists():
        content = default_yaml().replace('name: "My Research"', f'name: "{name}"')
        config_path.write_text(content)
        console.print(f"[green]✓[/green] rtw.yaml 생성됨")
    else:
        console.print("[dim]rtw.yaml 이미 존재합니다[/dim]")

    console.print(f"\n[bold green]프로젝트 초기화 완료![/bold green] ({project_dir})")
    console.print("\n다음 단계:")
    console.print("  1. [bold]rtw ingest <URL 또는 파일>[/bold] — 소스 수집")
    console.print("  2. [bold]rtw compile[/bold] — 위키 컴파일")
    console.print("  3. [bold]rtw query \"질문\"[/bold] — 위키에 질문")


@app.command()
def ingest(
    sources: list[str] = typer.Argument(..., help="URL, 파일 경로, 또는 디렉토리"),
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 디렉토리"),
):
    """소스를 수집하여 raw/에 저장합니다."""
    from rawtowise.ingest import ingest_source

    project_dir, _config = _load(project)
    console.print(f"[bold]소스 수집 중...[/bold] ({len(sources)}개)")

    total_saved = []
    for source in sources:
        saved = ingest_source(source, project_dir)
        total_saved.extend(saved)

    console.print(f"\n[bold green]수집 완료![/bold green] {len(total_saved)}개 파일 저장됨")
    if total_saved:
        console.print("\n다음: [bold]rtw compile[/bold] 로 위키를 컴파일하세요.")


@app.command(name="compile")
def compile_cmd(
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 디렉토리"),
    full: bool = typer.Option(False, "--full", help="전체 재컴파일"),
    dry_run: bool = typer.Option(False, "--dry-run", help="비용 추정만"),
):
    """raw/ 소스를 구조화된 wiki/로 컴파일합니다."""
    from rawtowise.compile import compile_wiki, _read_raw_sources

    project_dir, config = _load(project)

    if dry_run:
        sources = _read_raw_sources(project_dir)
        total_chars = sum(len(v) for v in sources.values())
        est_tokens = total_chars // 3
        est_cost = (est_tokens / 1_000_000) * 3.0 + (est_tokens / 1_000_000) * 0.5 * 15.0
        console.print(f"소스: {len(sources)}개 파일, ~{total_chars:,} 문자")
        console.print(f"예상 토큰: ~{est_tokens:,} input")
        console.print(f"예상 비용: ~${est_cost:.2f}")
        return

    console.print(f"[bold]위키 컴파일 시작[/bold] ({'전체 재빌드' if full else '증분'})")
    compile_wiki(project_dir, config, full=full)


@app.command()
def query(
    question: str = typer.Argument(..., help="위키에 대한 질문"),
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 디렉토리"),
    fmt: str = typer.Option("text", "--format", "-f", help="출력 형식: text, table, marp"),
    deep: bool = typer.Option(False, "--deep", help="심층 리서치 모드"),
    no_save: bool = typer.Option(False, "--no-save", help="답변을 파일로 저장하지 않음"),
):
    """위키를 탐색하여 질문에 답합니다."""
    from rawtowise.query import query_wiki

    project_dir, config = _load(project)
    query_wiki(
        question=question,
        project_dir=project_dir,
        config=config,
        fmt=fmt,
        file_back=not no_save,
        deep=deep,
    )


@app.command()
def lint(
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 디렉토리"),
    contradictions: bool = typer.Option(True, help="모순 검사"),
    gaps: bool = typer.Option(True, help="커버리지 갭 검사"),
    stale: bool = typer.Option(True, help="구식 정보 감지"),
    suggest: bool = typer.Option(True, help="탐색 질문 제안"),
):
    """위키 헬스체크를 실행합니다."""
    from rawtowise.lint import lint_wiki

    project_dir, config = _load(project)
    lint_wiki(
        project_dir, config,
        contradictions=contradictions,
        gaps=gaps,
        stale=stale,
        suggest=suggest,
    )


@app.command()
def stats(
    project: str = typer.Option(None, "--project", "-p", help="프로젝트 디렉토리"),
):
    """위키 통계를 표시합니다."""
    project_dir = _resolve_project(project)

    raw_dir = project_dir / "raw"
    wiki_dir = project_dir / "wiki"
    output_dir = project_dir / "output"

    raw_files = list(raw_dir.rglob("*")) if raw_dir.exists() else []
    raw_files = [f for f in raw_files if f.is_file()]

    wiki_files = list(wiki_dir.rglob("*.md")) if wiki_dir.exists() else []
    wiki_words = 0
    for f in wiki_files:
        try:
            wiki_words += len(f.read_text().split())
        except Exception:
            pass

    query_files = list((output_dir / "queries").rglob("*.md")) if (output_dir / "queries").exists() else []

    table = Table(title=f"📊 {project_dir.name} Knowledge Base")
    table.add_column("항목", style="bold")
    table.add_column("수치", justify="right")

    table.add_row("소스 (raw/)", str(len(raw_files)))
    table.add_row("위키 아티클 (wiki/)", str(len(wiki_files)))
    table.add_row("위키 총 단어 수", f"{wiki_words:,}")
    table.add_row("질의 결과 (output/)", str(len(query_files)))

    # Compile state
    state_path = project_dir / ".rtw" / "compile-state.json"
    if state_path.exists():
        import json
        state = json.loads(state_path.read_text())
        table.add_row("마지막 컴파일", state.get("last_compile", "N/A")[:19])
    else:
        table.add_row("마지막 컴파일", "미실행")

    console.print(table)


@app.command()
def version():
    """버전 정보를 표시합니다."""
    console.print(f"RawToWise v{__version__}")


def main():
    app()


if __name__ == "__main__":
    main()
