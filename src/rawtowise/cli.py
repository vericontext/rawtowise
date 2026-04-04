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
    help="RawToWise — compiles raw documents into a structured wiki via LLM.",
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
    project: str = typer.Option(None, "--project", "-p", help="Project directory"),
    name: str = typer.Option("My Research", "--name", "-n", help="Project name"),
):
    """Initialize a new RawToWise project."""
    import os

    project_dir = _resolve_project(project)

    # Create directories
    for d in ["raw/articles", "raw/papers", "wiki/concepts", "output/queries", ".rtw"]:
        (project_dir / d).mkdir(parents=True, exist_ok=True)

    # Write rtw.yaml
    config_path = project_dir / "rtw.yaml"
    if not config_path.exists():
        content = default_yaml().replace('name: "My Research"', f'name: "{name}"')
        config_path.write_text(content)
        console.print("[green]✓[/green] rtw.yaml created")
    else:
        console.print("[dim]rtw.yaml already exists[/dim]")

    # API key setup
    env_path = project_dir / ".env"
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_env_file = env_path.exists() and "ANTHROPIC_API_KEY" in env_path.read_text()

    if not has_key and not has_env_file:
        console.print("\n[bold]API Key Setup[/bold]")
        console.print("RawToWise requires an Anthropic API key.")
        console.print("Get one at: [link]https://console.anthropic.com/settings/keys[/link]\n")
        api_key = typer.prompt(
            "ANTHROPIC_API_KEY (enter to skip)",
            default="",
            show_default=False,
            hide_input=True,
        )
        if api_key.strip():
            env_path.write_text(f"ANTHROPIC_API_KEY={api_key.strip()}\n")
            console.print("[green]✓[/green] Saved to .env")
            console.print("[dim]Tip: .env is in .gitignore — your key stays local[/dim]")
        else:
            console.print("[dim]Skipped. Set it later: echo 'ANTHROPIC_API_KEY=sk-...' > .env[/dim]")
    else:
        console.print("[green]✓[/green] API key configured")

    console.print(f"\n[bold green]Project initialized![/bold green] ({project_dir})")
    console.print("\nNext steps:")
    console.print("  1. [bold]rtw ingest <URL or file>[/bold] — collect sources")
    console.print("  2. [bold]rtw compile[/bold] — compile wiki")
    console.print("  3. [bold]rtw query \"question\"[/bold] — ask the wiki")


@app.command()
def ingest(
    sources: list[str] = typer.Argument(..., help="URL, file path, or directory"),
    project: str = typer.Option(None, "--project", "-p", help="Project directory"),
):
    """Ingest sources into raw/."""
    from rawtowise.ingest import ingest_source

    project_dir, _config = _load(project)
    console.print(f"[bold]Ingesting...[/bold] ({len(sources)} source(s))")

    total_saved = []
    for source in sources:
        saved = ingest_source(source, project_dir)
        total_saved.extend(saved)

    console.print(f"\n[bold green]Done![/bold green] {len(total_saved)} file(s) saved")
    if total_saved:
        console.print("\nNext: [bold]rtw compile[/bold] to build the wiki.")


@app.command(name="compile")
def compile_cmd(
    project: str = typer.Option(None, "--project", "-p", help="Project directory"),
    full: bool = typer.Option(False, "--full", help="Full recompile"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Cost estimate only"),
):
    """Compile raw/ sources into a structured wiki/."""
    from rawtowise.compile import compile_wiki, _read_raw_sources

    project_dir, config = _load(project)

    if dry_run:
        sources = _read_raw_sources(project_dir)
        total_chars = sum(len(v) for v in sources.values())
        est_tokens = total_chars // 3
        est_cost = (est_tokens / 1_000_000) * 3.0 + (est_tokens / 1_000_000) * 0.5 * 15.0
        console.print(f"Sources: {len(sources)} files, ~{total_chars:,} chars")
        console.print(f"Est. tokens: ~{est_tokens:,} input")
        console.print(f"Est. cost: ~${est_cost:.2f}")
        return

    console.print(f"[bold]Compiling wiki[/bold] ({'full rebuild' if full else 'incremental'})")
    compile_wiki(project_dir, config, full=full)


@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask the wiki"),
    project: str = typer.Option(None, "--project", "-p", help="Project directory"),
    fmt: str = typer.Option("text", "--format", "-f", help="Output format: text, table, marp"),
    deep: bool = typer.Option(False, "--deep", help="Deep research mode"),
    no_save: bool = typer.Option(False, "--no-save", help="Don't save answer to file"),
):
    """Query the wiki and get answers."""
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
    project: str = typer.Option(None, "--project", "-p", help="Project directory"),
    contradictions: bool = typer.Option(True, help="Check contradictions"),
    gaps: bool = typer.Option(True, help="Check coverage gaps"),
    stale: bool = typer.Option(True, help="Detect stale info"),
    suggest: bool = typer.Option(True, help="Suggest questions to explore"),
):
    """Run wiki health check."""
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
    project: str = typer.Option(None, "--project", "-p", help="Project directory"),
):
    """Show wiki statistics."""
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

    table = Table(title=f"{project_dir.name} Knowledge Base")
    table.add_column("Item", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Sources (raw/)", str(len(raw_files)))
    table.add_row("Wiki articles (wiki/)", str(len(wiki_files)))
    table.add_row("Wiki total words", f"{wiki_words:,}")
    table.add_row("Query outputs (output/)", str(len(query_files)))

    # Compile state
    state_path = project_dir / ".rtw" / "compile-state.json"
    if state_path.exists():
        import json
        state = json.loads(state_path.read_text())
        table.add_row("Last compiled", state.get("last_compile", "N/A")[:19])
    else:
        table.add_row("Last compiled", "never")

    console.print(table)


@app.command()
def version():
    """Show version info."""
    console.print(f"RawToWise v{__version__}")


def main():
    app()


if __name__ == "__main__":
    main()
