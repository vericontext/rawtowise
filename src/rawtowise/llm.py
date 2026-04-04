"""LLM client wrapper for RawToWise."""

from __future__ import annotations

from collections.abc import Generator

from anthropic import Anthropic, AsyncAnthropic

from rawtowise.config import Config


def call_llm(
    config: Config,
    *,
    model: str | None = None,
    system: str,
    user: str,
    max_tokens: int = 8192,
) -> str:
    """Call Claude API and return the text response."""
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
    """Call Claude API asynchronously."""
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
    """Stream Claude API response, yielding text chunks."""
    client = Anthropic(api_key=config.api_key)
    with client.messages.stream(
        model=model or config.llm.compile,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text
