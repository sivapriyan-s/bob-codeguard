"""
codeguard/agents/doc_sync.py
Documentation Sync Agent — compares actual source code against documentation
and detects drift: outdated examples, wrong parameters, missing features, etc.
"""
from __future__ import annotations
import asyncio
from typing import Any

from codeguard.core.llm import call_llm_json
from codeguard.core.models import (
    Finding, Evidence, Confidence, Severity, FindingCategory, DocDrift
)
from .base import BaseAgent


_DOC_SYNC_SYS = """\
You are a documentation synchronization agent for Bob CodeGuard.
Compare source code against documentation and identify drift.

Return JSON with exactly these keys:
{
  "drifts": [
    {
      "doc_file": "README.md",
      "section": "Installation",
      "code_truth": "what the code actually does/requires",
      "doc_current": "what the documentation currently says",
      "status": "OUTDATED|MISSING|ACCURATE",
      "severity": "critical|warning|suggestion|info",
      "suggested_update": "proposed documentation update text"
    }
  ],
  "findings": [
    {
      "category": "documentation",
      "severity": "critical|warning|suggestion|info",
      "title": "...",
      "description": "...",
      "file": "...",
      "symbol": "...",
      "snippet": "...",
      "evidence_reason": "...",
      "suggested_action": "...",
      "confidence": "confirmed|likely|potential"
    }
  ],
  "summary": "2-3 sentence documentation sync summary"
}

Focus on:
- API endpoints documented but changed or removed in code
- Function parameters that differ between code and docs
- Configuration keys that changed
- Setup instructions that are wrong
- New public APIs/functions not documented
- Architecture descriptions that no longer match code

Only report real discrepancies grounded in the provided code and docs.
"""


class DocSyncAgent(BaseAgent):
    name = "DocSyncAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        owner: str = context["owner"]
        repo: str = context["repo"]
        repo_analysis: dict = context.get("repo_analysis", {})
        pr_files: list[dict] = context.get("pr_files", [])

        self.log.info("Running documentation sync for %s/%s", owner, repo)

        # Collect doc files
        doc_paths = repo_analysis.get("doc_files", [])
        # Also get all .md files from the tree
        all_paths = repo_analysis.get("all_paths", [])
        for p in all_paths:
            if p.lower().endswith(".md") and p not in doc_paths:
                doc_paths.append(p)
        doc_paths = doc_paths[:8]  # limit

        # Collect source files for comparison
        api_files = repo_analysis.get("api_files", [])
        source_paths = list({*api_files, *repo_analysis.get("entry_points", [])})[:8]

        # If we have PR files, focus on changed files and their docs
        if pr_files:
            changed_src = [f["filename"] for f in pr_files if not f["filename"].lower().endswith(".md")]
            source_paths = list({*changed_src, *source_paths})[:10]

        # Read all files in parallel
        all_to_read = list({*doc_paths, *source_paths})
        tasks = {
            path: asyncio.create_task(self.safe_get_file(owner, repo, path))
            for path in all_to_read
        }
        results = await asyncio.gather(*tasks.values())
        file_contents = {p: c for p, c in zip(tasks.keys(), results) if c}

        # Build doc block and source block
        doc_block = ""
        for p in doc_paths:
            if p in file_contents:
                doc_block += f"\n### {p}\n{self._truncate(file_contents[p], 2000)}\n"

        source_block = ""
        for p in source_paths:
            if p in file_contents:
                source_block += f"\n### {p}\n```\n{self._truncate(file_contents[p], 2000)}\n```\n"

        user_prompt = f"""
Repository: {owner}/{repo}
Language: {repo_analysis.get('language', 'unknown')}
Framework: {repo_analysis.get('framework', '')}

=== DOCUMENTATION FILES ===
{doc_block or "(no documentation found)"}

=== SOURCE CODE FILES ===
{source_block or "(no source files found)"}
"""
        result = await call_llm_json(_DOC_SYNC_SYS, user_prompt)

        # Parse drifts
        drifts: list[DocDrift] = []
        for rd in result.get("drifts", []):
            try:
                sev = Severity(rd.get("severity", "warning"))
            except ValueError:
                sev = Severity.WARNING
            drift = DocDrift(
                doc_file=rd.get("doc_file", ""),
                section=rd.get("section", ""),
                code_truth=rd.get("code_truth", ""),
                doc_current=rd.get("doc_current", ""),
                status=rd.get("status", "OUTDATED"),
                severity=sev,
                suggested_update=rd.get("suggested_update", ""),
            )
            drifts.append(drift)
            self.store.add_drift(drift)

        # Parse findings
        findings: list[Finding] = []
        for rf in result.get("findings", []):
            try:
                cat = FindingCategory(rf.get("category", "documentation"))
            except ValueError:
                cat = FindingCategory.DOCUMENTATION
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
                    snippet=rf.get("snippet"),
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

        result["parsed_drifts"] = drifts
        result["parsed_findings"] = findings
        return result
