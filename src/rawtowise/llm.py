"""LLM client wrapper for RawToWise."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

from anthropic import Anthropic, AsyncAnthropic

from rawtowise.config import Config

Provider = str


class LLMBackendError(RuntimeError):
    """Raised when the configured LLM backend cannot be used."""


def _normalize_provider(provider: str) -> Provider:
    normalized = provider.strip().lower().replace("_", "-")
    aliases = {
        "anthropic-api": "anthropic",
        "claude": "claude-code",
        "claudecode": "claude-code",
        "claude-code-cli": "claude-code",
        "codex-cli": "codex",
        "openai-codex": "codex",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"auto", "anthropic", "codex", "claude-code"}:
        raise LLMBackendError(
            f"Unsupported LLM provider: {provider!r}. "
            "Use one of: auto, anthropic, codex, claude-code."
        )
    return normalized


def resolve_provider(config: Config) -> Provider:
    """Resolve the active LLM provider from config, environment, and local CLIs."""
    requested = os.environ.get("RAWTOWISE_LLM_PROVIDER") or config.llm.provider
    provider = _normalize_provider(requested)
    if provider != "auto":
        return provider

    if os.environ.get("CODEX_THREAD_ID") and shutil.which("codex"):
        return "codex"
    if os.environ.get("CLAUDE_CODE_SSE_PORT") and shutil.which("claude"):
        return "claude-code"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude-code"
    if shutil.which("codex"):
        return "codex"

    raise LLMBackendError(
        "No LLM backend found. Install and log in to Codex or Claude Code, "
        "or set ANTHROPIC_API_KEY for direct Anthropic API usage."
    )


def _project_dir(config: Config) -> Path:
    return (config.project_dir or Path.cwd()).resolve()


def _agent_prompt(*, system: str, user: str, max_tokens: int) -> str:
    return f"""\
You are RawToWise's non-interactive LLM backend.
Return only the content requested by the user prompt. Do not edit files, run shell commands, or add progress notes.
The caller expects at most about {max_tokens} output tokens.

<system>
{system}
</system>

<user>
{user}
</user>
"""


def _subprocess_env(provider: Provider) -> dict[str, str]:
    env = os.environ.copy()
    if os.environ.get("RAWTOWISE_AGENT_USE_ENV_KEYS", "").lower() in {"1", "true", "yes"}:
        return env

    # Keep keyless agent backends on their logged-in subscription/session path by default.
    if provider == "claude-code":
        env.pop("ANTHROPIC_API_KEY", None)
    elif provider == "codex":
        env.pop("OPENAI_API_KEY", None)
    return env


def _backend_model(config: Config, provider: Provider, model: str | None) -> str | None:
    if provider == "codex":
        return os.environ.get("RAWTOWISE_CODEX_MODEL") or config.llm.codex_model or None
    if provider == "claude-code":
        return (
            os.environ.get("RAWTOWISE_CLAUDE_CODE_MODEL")
            or config.llm.claude_code_model
            or model
            or config.llm.compile
        )
    return model or config.llm.compile


def _run_blocking(args: list[str], prompt: str, config: Config, provider: Provider) -> str:
    import subprocess

    try:
        proc = subprocess.run(
            args,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=config.llm.timeout_seconds,
            cwd=_project_dir(config),
            env=_subprocess_env(provider),
            check=False,
        )
    except FileNotFoundError as exc:
        raise LLMBackendError(
            f"{provider} CLI not found. Install and log in to the CLI, "
            "or set llm.provider: anthropic with ANTHROPIC_API_KEY."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMBackendError(
            f"{provider} CLI timed out after {config.llm.timeout_seconds} seconds."
        ) from exc

    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout).strip()
        raise LLMBackendError(f"{provider} CLI failed with exit code {proc.returncode}: {details}")
    return proc.stdout.strip()


async def _run_async(args: list[str], prompt: str, config: Config, provider: Provider) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_project_dir(config),
            env=_subprocess_env(provider),
        )
    except FileNotFoundError as exc:
        raise LLMBackendError(
            f"{provider} CLI not found. Install and log in to the CLI, "
            "or set llm.provider: anthropic with ANTHROPIC_API_KEY."
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")),
            timeout=config.llm.timeout_seconds,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise LLMBackendError(
            f"{provider} CLI timed out after {config.llm.timeout_seconds} seconds."
        ) from exc

    if proc.returncode != 0:
        details = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise LLMBackendError(f"{provider} CLI failed with exit code {proc.returncode}: {details}")
    return stdout.decode("utf-8", errors="replace").strip()


def _claude_args(config: Config, *, model: str | None, system: str) -> list[str]:
    args = [
        "claude",
        "-p",
        "--output-format",
        "text",
        "--input-format",
        "text",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--system-prompt",
        system,
    ]
    backend_model = _backend_model(config, "claude-code", model)
    if backend_model:
        args.extend(["--model", backend_model])
    return args


def _call_claude_code(
    config: Config,
    *,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    _ = max_tokens
    return _run_blocking(_claude_args(config, model=model, system=system), user, config, "claude-code")


async def _call_claude_code_async(
    config: Config,
    *,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    _ = max_tokens
    return await _run_async(_claude_args(config, model=model, system=system), user, config, "claude-code")


def _codex_args(config: Config, *, model: str | None, output_path: Path) -> list[str]:
    args = [
        "codex",
        "exec",
        "--cd",
        str(_project_dir(config)),
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
    ]
    backend_model = _backend_model(config, "codex", model)
    if backend_model:
        args.extend(["--model", backend_model])
    args.append("-")
    return args


def _call_codex(
    config: Config,
    *,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    prompt = _agent_prompt(system=system, user=user, max_tokens=max_tokens)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tmp:
        output_path = Path(tmp.name)
    try:
        _run_blocking(_codex_args(config, model=model, output_path=output_path), prompt, config, "codex")
        return output_path.read_text(encoding="utf-8").strip()
    finally:
        output_path.unlink(missing_ok=True)


async def _call_codex_async(
    config: Config,
    *,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int,
) -> str:
    prompt = _agent_prompt(system=system, user=user, max_tokens=max_tokens)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tmp:
        output_path = Path(tmp.name)
    try:
        await _run_async(_codex_args(config, model=model, output_path=output_path), prompt, config, "codex")
        return output_path.read_text(encoding="utf-8").strip()
    finally:
        output_path.unlink(missing_ok=True)


def call_llm(
    config: Config,
    *,
    model: str | None = None,
    system: str,
    user: str,
    max_tokens: int = 8192,
) -> str:
    """Call the configured LLM backend and return the text response."""
    provider = resolve_provider(config)
    if provider == "codex":
        return _call_codex(
            config, model=model, system=system, user=user, max_tokens=max_tokens
        )
    if provider == "claude-code":
        return _call_claude_code(
            config, model=model, system=system, user=user, max_tokens=max_tokens
        )

    client = Anthropic(api_key=config.api_key)
    resp = client.messages.create(
        model=model or config.llm.compile,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


async def call_llm_async(
    config: Config,
    *,
    model: str | None = None,
    system: str,
    user: str,
    max_tokens: int = 8192,
) -> str:
    """Call the configured LLM backend asynchronously."""
    provider = resolve_provider(config)
    if provider == "codex":
        return await _call_codex_async(
            config, model=model, system=system, user=user, max_tokens=max_tokens
        )
    if provider == "claude-code":
        return await _call_claude_code_async(
            config, model=model, system=system, user=user, max_tokens=max_tokens
        )

    client = AsyncAnthropic(api_key=config.api_key)
    resp = await client.messages.create(
        model=model or config.llm.compile,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


def stream_llm(
    config: Config,
    *,
    model: str | None = None,
    system: str,
    user: str,
    max_tokens: int = 8192,
) -> Generator[str, None, None]:
    """Stream the configured LLM response, yielding text chunks."""
    provider = resolve_provider(config)
    if provider == "codex":
        yield _call_codex(
            config, model=model, system=system, user=user, max_tokens=max_tokens
        )
        return
    if provider == "claude-code":
        yield _call_claude_code(
            config, model=model, system=system, user=user, max_tokens=max_tokens
        )
        return

    client = Anthropic(api_key=config.api_key)
    with client.messages.stream(
        model=model or config.llm.compile,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text
