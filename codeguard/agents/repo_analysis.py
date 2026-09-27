"""
codeguard/agents/repo_analysis.py
Repository Analysis Agent — understands the structure, tech stack, and key files
of a GitHub repository before deeper analysis begins.
"""
from __future__ import annotations
from typing import Any

from codeguard.core.llm import call_llm_json
from .base import BaseAgent


SYSTEM_PROMPT = """\
You are a senior software engineer performing repository analysis for Bob CodeGuard.
Given a repository file tree and README, produce a structured analysis in JSON.

Return JSON with exactly these keys:
{
  "language": "primary language",
  "framework": "primary framework or empty string",
  "tech_stack": ["list", "of", "technologies"],
  "entry_points": ["main entry files"],
  "key_source_dirs": ["important source directories"],
  "test_dirs": ["test directories"],
  "doc_files": ["documentation files"],
  "config_files": ["config files"],
  "api_files": ["files likely containing API routes"],
  "db_files": ["files likely containing DB models/queries"],
  "summary": "2-3 sentence description of what this repository does"
}
"""


class RepoAnalysisAgent(BaseAgent):
    name = "RepoAnalysisAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        owner: str = context["owner"]
        repo: str = context["repo"]

        self.log.info("Analyzing repository %s/%s", owner, repo)

        # Get repo tree and README in parallel
        import asyncio
        tree_task = asyncio.create_task(self.gh.get_repo_tree(owner, repo))
        readme_task = asyncio.create_task(self.gh.get_readme(owner, repo))
        tree, readme = await asyncio.gather(tree_task, readme_task)

        # Build compact tree listing (blobs only, max 300 paths)
        paths = [item["path"] for item in tree if item["type"] == "blob"]
        tree_text = "\n".join(paths[:300])
        if len(paths) > 300:
            tree_text += f"\n... and {len(paths) - 300} more files"

        user_prompt = f"""
Repository: {owner}/{repo}

File tree:
{tree_text}

README (first 3000 chars):
{readme[:3000]}
"""

        result = await call_llm_json(SYSTEM_PROMPT, user_prompt)
        result["all_paths"] = paths  # store full path list for other agents
        self.log.info("Repo analysis complete: %s / %s", result.get("language"), result.get("framework"))
        return result
