"""
codeguard/core/llm.py
Thin async wrapper around the OpenAI chat completions API.
Provides a single call_llm() coroutine used by all agents.
"""
from __future__ import annotations
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from .config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        cfg = get_settings()
        _client = AsyncOpenAI(
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
        )
    return _client


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_format: str = "text",  # "text" | "json"
) -> str:
    """Call the LLM and return the response text."""
    cfg = get_settings()
    client = _get_client()

    kwargs: dict[str, Any] = {
        "model": cfg.openai_model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> dict:
    """Call the LLM and parse JSON response. Returns empty dict on parse failure."""
    raw = await call_llm(system_prompt, user_prompt, temperature, max_tokens, response_format="json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON: %s", raw[:200])
        return {}
