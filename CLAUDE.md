# Claude Code Guide

Claude Code should follow the shared repository rules in `AGENTS.md`. Read that file before making code changes and treat it as the source of truth for project structure, LLM backend behavior, tests, and commit safety.

## Claude-Specific Notes

- `.claude/settings.json` installs hooks for Claude Code only.
- `.claude/hooks/version-sync.sh` keeps `pyproject.toml` and `src/rawtowise/__init__.py` versions aligned after edits.
- `.claude/hooks/version-auto-bump.sh` bumps the patch version when Claude Code runs `git commit`.
- `.codex/config.toml` contains Codex project-scoped defaults and enables Codex hooks.
- `.codex/hooks.json` registers Codex hook commands; `.codex/hooks/*.py` contains their implementation.
- Codex does not run Claude hooks, so do not assume version sync happened if changes came from Codex.

## Authentication

RawToWise should work through a logged-in Claude Code CLI without requiring `ANTHROPIC_API_KEY`.

Claude Code itself prioritizes `ANTHROPIC_API_KEY` over subscription login when the variable is present. RawToWise's `claude-code` backend removes that variable from subprocess calls by default so local runs stay on the logged-in Claude Code path. Set `RAWTOWISE_AGENT_USE_ENV_KEYS=1` only when intentionally testing API-key-backed agent CLI behavior.

## Default Checks

Before handing off substantial code changes, run:

```bash
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m unittest discover -s tests
```

Also run `PYTHONPATH=src python -m compileall src tests` when touching imports, config loading, or CLI/backend plumbing.
