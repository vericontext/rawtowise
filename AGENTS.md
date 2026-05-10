# RawToWise Agent Guide

This file is the shared operating guide for Codex, Claude Code, and other coding agents working in this repository. Keep `CLAUDE.md` aligned with this file.

## Project

RawToWise is a Python CLI that turns raw sources into a structured Markdown wiki inspired by Andrej Karpathy's LLM knowledge base workflow.

- Package source: `src/rawtowise/`
- CLI entry point: `rawtowise.cli:app`
- Tests: `tests/`
- Codex project config/hooks: `.codex/`
- Claude Code project config/hooks: `.claude/`
- User/generated project data: `raw/`, `wiki/`, `output/`, `.rtw/` and `.env` are ignored and should not be committed.

## Current Architecture

- `ingest.py` copies/fetches sources into `raw/`, converts supported documents with MarkItDown, and records provenance in `.rtw/sources.json`.
- `compile.py` reads manifest-backed sources, builds/updates `wiki/concepts/`, `_index.md`, `_sources.md`, and records compile state.
- `query.py` reads the wiki and writes answers to `output/queries/` unless disabled.
- `lint.py` combines deterministic structure checks with an LLM audit.
- `llm.py` supports `llm.provider: auto`, `anthropic`, `codex`, and `claude-code`.

## LLM Backend Rules

The default `llm.provider: auto` should work without a project API key when the user is already inside Codex or Claude Code.

Resolution order:

1. Active Codex session and installed `codex` CLI
2. Active Claude Code session and installed `claude` CLI
3. `ANTHROPIC_API_KEY` for direct Anthropic API calls
4. Installed Claude Code CLI
5. Installed Codex CLI

Do not make `ANTHROPIC_API_KEY` mandatory for local development. Direct Anthropic API support must remain available, but keyless Codex/Claude Code backends are first-class.

For agent CLI backends, avoid forwarding provider API keys by default. `RAWTOWISE_AGENT_USE_ENV_KEYS=1` is the explicit opt-in for forwarding those environment variables.

## Development Commands

Use local source imports while developing:

```bash
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m compileall src tests
```

Useful CLI smoke tests:

```bash
PYTHONPATH=src python -m rawtowise.cli --help
PYTHONPATH=src rtw compile --dry-run
```

If the installed `rtw` command points at a different version, prefer `PYTHONPATH=src python -m rawtowise.cli ...` or install editable mode.

## Change Rules

- Preserve backward compatibility for existing `rtw.yaml` files.
- Keep edits narrowly scoped to the requested behavior.
- Prefer existing Typer/Rich/stdlib patterns over new dependencies.
- Keep source IDs, source manifests, and citation formats stable unless explicitly migrating them.
- Do not edit generated `wiki/` outputs as if they were source code.
- Do not commit raw source files, generated wiki files, query outputs, `.rtw/`, `.env`, videos, or local Claude settings.

## Versioning

The release version appears in both `pyproject.toml` and `src/rawtowise/__init__.py`; keep them identical.

Claude Code has hooks in `.claude/hooks/` that sync these files and auto-bump patch versions on `git commit`.

Codex has matching experimental hooks in `.codex/hooks/` enabled by `.codex/config.toml` and registered in `.codex/hooks.json`.

- `pre_tool_use.py`: blocks a small set of destructive Bash commands and auto-bumps patch versions before `git commit`.
- `post_tool_use.py`: keeps `pyproject.toml` and `src/rawtowise/__init__.py` version strings in sync after file edits.

Use `RAWTOWISE_ALLOW_DESTRUCTIVE=1` only when intentionally bypassing the Codex destructive-command guard.

## Documentation

When changing user-facing behavior, update `README.md` and, if it affects manual verification, `TESTING.md`.

Document keyless agent behavior as Codex/Claude Code CLI backend behavior, not as direct API usage.

Keep `.codex/config.toml` minimal and project-scoped. Do not add personal model, auth, approval, telemetry, MCP, or sandbox preferences there.

Use `.codex/hooks.json` for hook registration and `.codex/hooks/*.py` for hook implementation. Do not define inline `[hooks]` in `.codex/config.toml` unless removing `hooks.json`; Codex loads both and warns when both forms exist in one layer.

## Safety

- Never run destructive git commands unless explicitly requested.
- Check `git status --short` before and after substantial edits.
- Treat unrelated dirty files as user work.
- Prefer deterministic tests over live LLM calls. Live `compile`, `query`, and `lint` calls may invoke paid or subscription-backed model usage.
