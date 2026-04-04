"""Configuration management for KnowledgeForge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMConfig:
    compile: str = "claude-sonnet-4-20250514"
    query: str = "claude-sonnet-4-20250514"
    lint: str = "claude-haiku-4-5-20251001"


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

    @property
    def api_key(self) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 환경 변수를 설정하세요.")
        return key


def load_config(project_dir: Path) -> Config:
    """Load rtw.yaml from project directory, or return defaults."""
    config_path = project_dir / "rtw.yaml"
    if not config_path.exists():
        return Config()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        compile=llm_raw.get("compile", LLMConfig.compile),
        query=llm_raw.get("query", LLMConfig.query),
        lint=llm_raw.get("lint", LLMConfig.lint),
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
    )


def default_yaml() -> str:
    """Return default rtw.yaml content."""
    return """\
version: 1
name: "My Research"

llm:
  compile: claude-sonnet-4-20250514
  query: claude-sonnet-4-20250514
  lint: claude-haiku-4-5-20251001

compile:
  strategy: incremental
  max_concepts: 200
  language: ko
  backlinks: true
  summaries: true

output:
  file_back: true
"""
