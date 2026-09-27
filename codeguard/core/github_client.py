"""
codeguard/core/github_client.py
Async GitHub REST API client — wraps the endpoints CodeGuard needs.
"""
from __future__ import annotations
import base64
import logging
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self) -> None:
        cfg = get_settings()
        self._headers = {
            "Authorization": f"Bearer {cfg.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ── internal ─────────────────────────────────────────────────────────────

    async def _get(self, url: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=self._headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _get_text(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=self._headers)
            r.raise_for_status()
            return r.text

    # ── repository ────────────────────────────────────────────────────────────

    async def get_repo(self, owner: str, repo: str) -> dict:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}")

    async def get_repo_tree(self, owner: str, repo: str, sha: str = "HEAD") -> list[dict]:
        data = await self._get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{sha}",
            params={"recursive": "1"},
        )
        return data.get("tree", [])

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str = "HEAD") -> str:
        """Return decoded text content of a file."""
        data = await self._get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        if isinstance(data, list):
            raise ValueError(f"{path} is a directory")
        content_b64 = data.get("content", "")
        # GitHub returns base64 with newlines
        return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")

    async def get_readme(self, owner: str, repo: str) -> str:
        try:
            data = await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/readme")
            return base64.b64decode(data["content"].replace("\n", "")).decode("utf-8", errors="replace")
        except Exception:
            return ""

    # ── issues ────────────────────────────────────────────────────────────────

    async def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}")

    async def get_issue_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}/comments")

    # ── pull requests ─────────────────────────────────────────────────────────

    async def get_pr(self, owner: str, repo: str, number: int) -> dict:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}")

    async def get_pr_files(self, owner: str, repo: str, number: int) -> list[dict]:
        """Returns list of changed files with patch diffs."""
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/files")

    async def get_pr_commits(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/commits")

    async def get_pr_reviews(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/reviews")

    # ── commits ───────────────────────────────────────────────────────────────

    async def get_commit(self, owner: str, repo: str, sha: str) -> dict:
        return await self._get(f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}")

    # ── search ────────────────────────────────────────────────────────────────

    async def search_code(self, owner: str, repo: str, query: str) -> list[dict]:
        """Search code within a repo. Returns list of items."""
        q = f"{query} repo:{owner}/{repo}"
        data = await self._get(f"{GITHUB_API}/search/code", params={"q": q, "per_page": 20})
        return data.get("items", [])

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def parse_repo(repo_str: str) -> tuple[str, str]:
        """Parse 'owner/repo' string into (owner, repo)."""
        parts = repo_str.strip().split("/")
        if len(parts) < 2:
            raise ValueError(f"Invalid repo format: {repo_str!r}. Expected 'owner/repo'.")
        return parts[-2], parts[-1]

    async def list_source_files(
        self,
        owner: str,
        repo: str,
        extensions: tuple[str, ...] = (".py", ".js", ".ts", ".go", ".java", ".rb", ".rs"),
    ) -> list[str]:
        """Return file paths filtered by extension."""
        tree = await self.get_repo_tree(owner, repo)
        return [
            item["path"]
            for item in tree
            if item["type"] == "blob" and any(item["path"].endswith(ext) for ext in extensions)
        ]

    async def list_doc_files(self, owner: str, repo: str) -> list[str]:
        tree = await self.get_repo_tree(owner, repo)
        doc_exts = (".md", ".rst", ".txt", ".adoc")
        doc_dirs = ("docs/", "doc/", "documentation/", "wiki/")
        results = []
        for item in tree:
            if item["type"] != "blob":
                continue
            p = item["path"].lower()
            if any(p.endswith(e) for e in doc_exts):
                results.append(item["path"])
            elif any(p.startswith(d) for d in doc_dirs):
                results.append(item["path"])
        return results
