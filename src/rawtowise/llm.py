"""LLM client wrapper for RawToWise."""

from __future__ import annotations

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
