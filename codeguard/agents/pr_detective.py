"""
codeguard/agents/pr_detective.py
PR Detective Agent — traces the ripple effect of every changed component
beyond the diff itself. Identifies hidden dependencies, callers, consumers,
affected APIs, DB, tests, and documentation.
"""
from __future__ import annotations
import asyncio
import re
from typing import Any

from codeguard.core.llm import call_llm_json
from codeguard.core.models import (
    Finding, Evidence, Confidence, Severity, FindingCategory, ImpactNode
)
from .base import BaseAgent


_DETECTIVE_SYS = """\
You are the PR Detective for Bob CodeGuard — the signature feature.
Your job is to find EVERYTHING in the repository that could be affected
by the changed components, going far beyond the changed lines.

You receive:
- The PR diff (what changed)
- The full repository file listing
- Contents of files that import/use the changed symbols

Return JSON with exactly these keys:
{
  "changed_symbols": ["list of key functions/classes/APIs that changed"],
  "direct_dependencies": [
    {"path": "file/path.py", "relation": "imports", "confidence": "confirmed|likely|potential", "reason": "..."}
  ],
  "indirect_dependencies": [
    {"path": "file/path.py", "relation": "transitive import", "confidence": "confirmed|likely|potential", "reason": "..."}
  ],
  "affected_apis": [
    {"endpoint": "POST /path", "file": "file.py", "confidence": "confirmed|likely|potential", "reason": "..."}
  ],
  "affected_db": [
    {"table": "table_name", "operation": "SELECT|INSERT|UPDATE|DELETE", "file": "file.py", "confidence": "confirmed|likely|potential"}
  ],
  "affected_tests": [
    {"path": "tests/test_x.py", "test_name": "test_something", "confidence": "confirmed|likely|potential", "reason": "..."}
  ],
  "missing_tests": ["description of test cases not covered by existing tests"],
  "affected_docs": [
    {"path": "README.md", "section": "section name", "reason": "..."}
  ],
  "impact_map": [
    {
      "path": "changed/file.py",
      "kind": "file",
      "relation": "direct",
      "confidence": "confirmed",
      "children": [
        {"path": "dependent/file.py", "kind": "file", "relation": "direct", "confidence": "confirmed", "children": []}
      ]
    }
  ],
  "findings": [
    {
      "category": "impact|regression|testing|documentation",
      "severity": "critical|warning|suggestion|info",
      "title": "...",
      "description": "...",
      "file": "...",
      "symbol": "...",
      "evidence_reason": "...",
      "suggested_action": "...",
      "confidence": "confirmed|likely|potential"
    }
  ],
  "summary": "2-3 sentence detective summary"
}

IMPORTANT: Distinguish clearly between Confirmed, Likely, and Potential.
Never present speculation as fact.
"""


class PRDetectiveAgent(BaseAgent):
    name = "PRDetectiveAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        owner: str = context["owner"]
        repo: str = context["repo"]
        pr: dict = context["pr"]
        pr_files: list[dict] = context["pr_files"]
        repo_analysis: dict = context.get("repo_analysis", {})

        self.log.info("PR Detective investigating PR #%s", pr["number"])

        # Build diff block for changed files
        diff_block = self._build_diff(pr_files)

        # Find files that might reference the changed files
        changed_paths = [f["filename"] for f in pr_files]
        related_files = self._find_potentially_related(changed_paths, repo_analysis.get("all_paths", []))

        # Read related file contents in parallel
        content_tasks = {
            path: asyncio.create_task(self.safe_get_file(owner, repo, path))
            for path in related_files[:15]
        }
        contents = await asyncio.gather(*content_tasks.values())
        related_contents = {
            path: content for path, content in zip(content_tasks.keys(), contents) if content
        }

        # Build related files block
        related_block = ""
        for path, content in related_contents.items():
            related_block += f"\n### {path}\n```\n{self._truncate(content, 1500)}\n```"

        user_prompt = f"""
Repository: {owner}/{repo}
PR #{pr['number']}: {pr['title']}

All repository paths ({len(repo_analysis.get('all_paths', []))} files):
{chr(10).join(repo_analysis.get('all_paths', [])[:200])}

Changed files diff:
{self._truncate(diff_block, 8000)}

Potentially related files (not in the PR but might be affected):
{self._truncate(related_block, 5000)}
"""
        result = await call_llm_json(_DETECTIVE_SYS, user_prompt)

        # Parse impact nodes
        impact_nodes = self._parse_impact_nodes(result.get("impact_map", []))
        self.store.add_impact_nodes(impact_nodes)

        # Parse findings
        from codeguard.agents.pr_review import _parse_findings
        raw_findings = result.get("findings", [])
        findings = []
        for rf in raw_findings:
            try:
                cat = FindingCategory(rf.get("category", "impact"))
            except ValueError:
                cat = FindingCategory.IMPACT
            try:
                sev = Severity(rf.get("severity", "warning"))
            except ValueError:
                sev = Severity.WARNING
            try:
                conf = Confidence(rf.get("confidence", "likely"))
            except ValueError:
                conf = Confidence.LIKELY

            ev_list = []
            if rf.get("file"):
                ev_list.append(Evidence(
                    file=rf["file"],
                    symbol=rf.get("symbol"),
                    reason=rf.get("evidence_reason", ""),
                    confidence=conf,
                ))
            f = Finding(
                category=cat,
                severity=sev,
                title=rf.get("title", ""),
                description=rf.get("description", ""),
                evidence=ev_list,
                suggested_action=rf.get("suggested_action", ""),
                confidence=conf,
            )
            findings.append(f)
            self.store.add_finding(f)

        result["parsed_impact_nodes"] = impact_nodes
        result["parsed_findings"] = findings
        return result

    def _build_diff(self, pr_files: list[dict], max_files: int = 15) -> str:
        blocks = []
        for f in pr_files[:max_files]:
            patch = f.get("patch", "(no diff)")
            blocks.append(f"### {f['filename']} [{f.get('status', 'modified')}]\n```diff\n{patch[:2000]}\n```")
        return "\n\n".join(blocks)

    def _find_potentially_related(self, changed_paths: list[str], all_paths: list[str]) -> list[str]:
        """Find files that likely import or reference the changed files."""
        # Extract base names of changed files (without extension)
        changed_names = set()
        for p in changed_paths:
            base = p.replace("/", ".").rsplit(".", 1)[0]
            parts = base.split(".")
            changed_names.update(parts[-2:] if len(parts) >= 2 else parts)

        related = []
        for path in all_paths:
            if path in changed_paths:
                continue
            name_lower = path.lower()
            for cn in changed_names:
                if len(cn) > 3 and cn.lower() in name_lower:
                    related.append(path)
                    break

        return related[:15]

    def _parse_impact_nodes(self, raw: list[dict]) -> list[ImpactNode]:
        nodes = []
        for item in raw:
            try:
                conf = Confidence(item.get("confidence", "likely"))
            except ValueError:
                conf = Confidence.LIKELY
            children = self._parse_impact_nodes(item.get("children", []))
            nodes.append(ImpactNode(
                path=item.get("path", ""),
                kind=item.get("kind", "file"),
                relation=item.get("relation", "direct"),
                confidence=conf,
                children=children,
            ))
        return nodes
