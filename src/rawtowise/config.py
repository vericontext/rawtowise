"""Configuration management for RawToWise."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class LLMConfig:
    provider: str = "auto"
    compile: str = "claude-sonnet-4-6"
    query: str = "claude-sonnet-4-6"
    lint: str = "claude-haiku-4-5-20251001"
    codex_model: str = ""
    claude_code_model: str = ""
    timeout_seconds: int = 600


@dataclass
class CompileConfig:
    strategy: str = "incremental"
    max_concepts: int = 200
    language: str = "ko"
    backlinks: bool = True
    summaries: bool = True


@dataclass
class Config:
    version: int = 1
    name: str = "My Research"
    llm: LLMConfig = field(default_factory=LLMConfig)
    compile: CompileConfig = field(default_factory=CompileConfig)
    file_back: bool = True

    project_dir: Path | None = None

    @property
    def api_key(self) -> str:
        # .env is already loaded by load_config, just read the var
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not found.\n"
                "Either set llm.provider to codex/claude-code for a logged-in agent CLI, "
                "or set an Anthropic API key via:\n"
                "  1. .env file:  echo 'ANTHROPIC_API_KEY=sk-...' > .env\n"
                "  2. Environment: export ANTHROPIC_API_KEY=sk-..."
            )
        return key


def load_config(project_dir: Path) -> Config:
    """Load rtw.yaml from project directory, or return defaults."""
    # Load .env (project dir first, then cwd)
    load_dotenv(project_dir / ".env", override=False)
    load_dotenv(Path.home() / ".rawtowise" / ".env", override=False)

    config_path = project_dir / "rtw.yaml"
    if not config_path.exists():
        return Config(project_dir=project_dir)

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        provider=llm_raw.get("provider", LLMConfig.provider),
        compile=llm_raw.get("compile", LLMConfig.compile),
        query=llm_raw.get("query", LLMConfig.query),
        lint=llm_raw.get("lint", LLMConfig.lint),
        codex_model=llm_raw.get("codex_model", LLMConfig.codex_model),
        claude_code_model=llm_raw.get("claude_code_model", LLMConfig.claude_code_model),
        timeout_seconds=llm_raw.get("timeout_seconds", LLMConfig.timeout_seconds),
    )

    compile_raw = raw.get("compile", {})
    comp = CompileConfig(
        strategy=compile_raw.get("strategy", CompileConfig.strategy),
        max_concepts=compile_raw.get("max_concepts", CompileConfig.max_concepts),
        language=compile_raw.get("language", CompileConfig.language),
        backlinks=compile_raw.get("backlinks", CompileConfig.backlinks),
        summaries=compile_raw.get("summaries", CompileConfig.summaries),
    )

    output_raw = raw.get("output", {})

    return Config(
        version=raw.get("version", 1),
        name=raw.get("name", "My Research"),
        llm=llm,
        compile=comp,
        file_back=output_raw.get("file_back", True),
        project_dir=project_dir,
    )


def default_yaml() -> str:
    """Return default rtw.yaml content."""
    return """\
version: 1
name: "My Research"

llm:
  # auto = use the active agent CLI when available:
  #   Codex session -> codex exec
  #   Claude Code session -> claude -p
  #   otherwise Anthropic API if ANTHROPIC_API_KEY is set, then installed CLIs
  # Explicit options: anthropic, codex, claude-code
  provider: auto
  compile: claude-sonnet-4-6
  query: claude-sonnet-4-6
  lint: claude-haiku-4-5-20251001
  # Optional model overrides for keyless CLI backends.
  codex_model: ""
  claude_code_model: ""
  timeout_seconds: 600

compile:
  strategy: incremental
  max_concepts: 200
  language: en
  backlinks: true
  summaries: true

output:
  file_back: true
"""
