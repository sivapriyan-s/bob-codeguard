"""
codeguard/agents/bug_investigation.py
Bug Investigation Agent — reads the issue, reads relevant source files,
identifies the root cause, and proposes a concrete fix.
"""
from __future__ import annotations
import json
from typing import Any

from codeguard.core.llm import call_llm_json
from codeguard.core.models import (
    Finding, Evidence, Confidence, Severity, FindingCategory
)
from .base import BaseAgent


SYSTEM_PROMPT = """\
You are a senior software engineer acting as a bug investigation agent for Bob CodeGuard.
Your job is to analyze a GitHub issue and the relevant source code, identify the root cause,
and produce a concrete fix.

Return JSON with exactly these keys:
{
  "root_cause": "precise explanation of the root cause",
  "affected_files": ["list of file paths that need changes"],
  "affected_functions": ["list of function/class names affected"],
  "fix_description": "description of what changes to make and why",
  "code_changes": [
    {
      "file": "path/to/file.py",
      "type": "modify|create|delete",
      "description": "what to change",
      "search": "exact existing code to replace (if modify)",
      "replacement": "new code to put in (if modify)"
    }
  ],
  "test_suggestions": [
    {
      "description": "what the test should verify",
      "test_code": "suggested test function code"
    }
  ],
  "potential_side_effects": ["list of potential side effects"],
  "findings": [
    {
      "category": "bug|security|code_quality",
      "severity": "critical|warning|suggestion|info",
      "title": "short title",
      "description": "detailed description",
      "file": "file path",
      "line": null,
      "symbol": "function or class name",
      "snippet": "relevant code snippet",
      "evidence_reason": "why this is a finding",
      "suggested_action": "what to do",
      "confidence": "confirmed|likely|potential"
    }
  ]
}

Ground every finding in actual code evidence. Do not hallucinate findings.
"""


class BugInvestigationAgent(BaseAgent):
    name = "BugInvestigationAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        owner: str = context["owner"]
        repo: str = context["repo"]
        issue: dict = context["issue"]
        repo_analysis: dict = context.get("repo_analysis", {})

        self.log.info("Investigating issue #%s", issue.get("number"))

        # Identify files to read based on issue text + repo analysis
        candidate_files = self._select_candidate_files(issue, repo_analysis)

        # Read relevant source files
        file_contents: dict[str, str] = {}
        import asyncio
        tasks = {
            path: asyncio.create_task(self.safe_get_file(owner, repo, path))
            for path in candidate_files[:12]  # limit to avoid huge prompts
        }
        results = await asyncio.gather(*tasks.values())
        for path, content in zip(tasks.keys(), results):
            if content:
                file_contents[path] = content

        # Read README too
        readme = await self.gh.get_readme(owner, repo)

        # Build context block
        files_block = ""
        for path, content in file_contents.items():
            files_block += f"\n\n### {path}\n```\n{self._truncate(content, 3000)}\n```"

        user_prompt = f"""
Repository: {owner}/{repo}
Language: {repo_analysis.get('language', 'unknown')}
Framework: {repo_analysis.get('framework', '')}

Issue #{issue['number']}: {issue['title']}

Issue body:
{issue.get('body') or '(no body)'}

Relevant source files:{files_block}

README (first 2000 chars):
{readme[:2000]}
"""
        result = await call_llm_json(SYSTEM_PROMPT, user_prompt)

        # Convert findings to Finding objects and add to evidence store
        raw_findings = result.get("findings", [])
        for rf in raw_findings:
            ev = Evidence(
                file=rf.get("file", "unknown"),
                line=rf.get("line"),
                symbol=rf.get("symbol"),
                snippet=rf.get("snippet"),
                reason=rf.get("evidence_reason", ""),
                confidence=Confidence(rf.get("confidence", "likely")),
            )
            finding = Finding(
                category=FindingCategory(rf.get("category", "bug")),
                severity=Severity(rf.get("severity", "warning")),
                title=rf.get("title", ""),
                description=rf.get("description", ""),
                evidence=[ev],
                suggested_action=rf.get("suggested_action", ""),
                confidence=Confidence(rf.get("confidence", "likely")),
            )
            self.store.add_finding(finding)

        return result

    def _select_candidate_files(self, issue: dict, repo_analysis: dict) -> list[str]:
        """Heuristically pick files most likely related to the issue."""
        all_paths: list[str] = repo_analysis.get("all_paths", [])
        issue_text = f"{issue.get('title', '')} {issue.get('body', '')}".lower()

        # Score files: higher score = more relevant
        scored: list[tuple[int, str]] = []
        for path in all_paths:
            score = 0
            name = path.lower()
            # Keyword match
            for word in issue_text.split():
                if len(word) > 4 and word in name:
                    score += 3
            # Prefer key source dirs
            for d in repo_analysis.get("key_source_dirs", []):
                if path.startswith(d):
                    score += 1
            # Penalize tests for initial investigation
            if "test" in name:
                score -= 1
            scored.append((score, path))

        scored.sort(reverse=True)
        result = [p for _, p in scored if _ > 0][:10]

        # Always include entry points
        entry_points = repo_analysis.get("entry_points", [])
        for ep in entry_points:
            if ep not in result:
                result.append(ep)

        return result
