"""
codeguard/agents/base.py
Abstract base class for all CodeGuard agents.
"""
from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Any

from codeguard.core.evidence_store import EvidenceStore
from codeguard.core.github_client import GitHubClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """All specialized agents inherit from this."""

    name: str = "BaseAgent"

    def __init__(self, gh: GitHubClient, store: EvidenceStore) -> None:
        self.gh = gh
        self.store = store
        self.log = logging.getLogger(f"codeguard.agents.{self.name}")

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent and return a result dict."""
        ...

    # ── helpers ───────────────────────────────────────────────────────────────

    async def safe_get_file(self, owner: str, repo: str, path: str, ref: str = "HEAD") -> str:
        """Fetch a file, returning empty string on failure."""
        try:
            return await self.gh.get_file_content(owner, repo, path, ref)
        except Exception as exc:
            self.log.debug("Could not fetch %s: %s", path, exc)
            return ""

    def _truncate(self, text: str, max_chars: int = 12000) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
