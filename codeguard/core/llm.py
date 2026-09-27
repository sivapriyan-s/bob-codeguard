"""
codeguard/core/llm.py
Thin async wrapper around the OpenAI chat completions API.
Provides a single call_llm() coroutine used by all agents.
"""
from __future__ import annotations
import json
import logging
from typing import Any

from openai import AsyncOpenAI, NotFoundError

from .config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL_FALLBACKS = [
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
]

_client: AsyncOpenAI | None = None


def get_model_candidates(model_name: str | None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in [model_name, *DEFAULT_MODEL_FALLBACKS]:
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


def _is_model_not_found_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    message = str(exc).lower()
    return "model_not_found" in message or "does not exist" in message or "not found" in message and "model" in message


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

    last_error: Exception | None = None
    for model_name in get_model_candidates(cfg.openai_model):
        kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except (NotFoundError, Exception) as exc:  # pragma: no cover - exercised through API behavior
            if not _is_model_not_found_error(exc):
                raise
            last_error = exc
            logger.warning(
                "Model %s is unavailable for this provider; trying fallback model: %s",
                model_name,
                exc,
            )

    if last_error is not None:
        raise RuntimeError(
            f"All configured LLM models failed for this provider. Last error: {last_error}"
        ) from last_error
    raise RuntimeError("No LLM model was available for the current configuration.")


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
