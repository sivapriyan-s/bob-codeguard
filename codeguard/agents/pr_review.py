"""
codeguard/agents/pr_review.py
Parallel PR Review Agents — security, code quality, testing, regression.
Each agent analyzes the PR diff + related source and emits findings.
"""
from __future__ import annotations
import asyncio
from typing import Any

from codeguard.core.llm import call_llm_json
from codeguard.core.models import (
    Finding, Evidence, Confidence, Severity, FindingCategory
)
from .base import BaseAgent


# ─── Shared helpers ────────────────────────────────────────────────────────────

def _build_diff_block(pr_files: list[dict], max_files: int = 15) -> str:
    """Build a readable diff block from PR file data."""
    blocks = []
    for f in pr_files[:max_files]:
        status = f.get("status", "modified")
        patch = f.get("patch", "(binary or no diff)")
        blocks.append(f"### {f['filename']} [{status}]\n```diff\n{patch[:3000]}\n```")
    return "\n\n".join(blocks)


def _parse_findings(raw_findings: list[dict], default_category: FindingCategory) -> list[Finding]:
    findings = []
    for rf in raw_findings:
        try:
            cat = FindingCategory(rf.get("category", default_category.value))
        except ValueError:
            cat = default_category
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
                line=rf.get("line"),
                symbol=rf.get("symbol"),
                snippet=rf.get("snippet"),
                reason=rf.get("evidence_reason", ""),
                confidence=conf,
            ))

        findings.append(Finding(
            category=cat,
            severity=sev,
            title=rf.get("title", ""),
            description=rf.get("description", ""),
            evidence=ev_list,
            suggested_action=rf.get("suggested_action", ""),
            confidence=conf,
        ))
    return findings


# ─── Security Agent ────────────────────────────────────────────────────────────

_SECURITY_SYS = """\
You are a security-focused code reviewer for Bob CodeGuard.
Analyze the PR diff for security vulnerabilities and return JSON:
{
  "findings": [
    {
      "category": "security",
      "severity": "critical|warning|suggestion|info",
      "title": "short title",
      "description": "detailed description",
      "file": "file path",
      "line": null,
      "symbol": "function or class",
      "snippet": "relevant code",
      "evidence_reason": "why this is a security risk",
      "suggested_action": "how to fix",
      "confidence": "confirmed|likely|potential"
    }
  ]
}
Focus on: injection, auth bypass, insecure deserialization, secrets in code,
missing auth checks, CORS issues, SQL injection, XSS, CSRF, broken access control.
Only report findings grounded in actual changed code.
"""


class SecurityAgent(BaseAgent):
    name = "SecurityAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        diff_block = context["diff_block"]
        pr = context["pr"]
        owner, repo = context["owner"], context["repo"]

        user_prompt = f"""
PR #{pr['number']}: {pr['title']}

Changed files diff:
{self._truncate(diff_block, 10000)}
"""
        result = await call_llm_json(_SECURITY_SYS, user_prompt)
        findings = _parse_findings(result.get("findings", []), FindingCategory.SECURITY)
        self.store.add_findings(findings)
        return {"findings": findings}


# ─── Code Quality Agent ────────────────────────────────────────────────────────

_QUALITY_SYS = """\
You are a code quality reviewer for Bob CodeGuard.
Analyze the PR diff for code quality issues and return JSON:
{
  "findings": [
    {
      "category": "code_quality",
      "severity": "critical|warning|suggestion|info",
      "title": "short title",
      "description": "detailed description",
      "file": "file path",
      "line": null,
      "symbol": "function or class",
      "snippet": "relevant code",
      "evidence_reason": "why this is a quality issue",
      "suggested_action": "how to improve",
      "confidence": "confirmed|likely|potential"
    }
  ]
}
Focus on: duplicated logic, overly complex functions, poor naming, missing error handling,
magic numbers, violated SOLID principles, dead code, N+1 queries, missing type hints.
Only report findings grounded in actual changed code.
"""


class CodeQualityAgent(BaseAgent):
    name = "CodeQualityAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        diff_block = context["diff_block"]
        pr = context["pr"]

        user_prompt = f"""
PR #{pr['number']}: {pr['title']}

Changed files diff:
{self._truncate(diff_block, 10000)}
"""
        result = await call_llm_json(_QUALITY_SYS, user_prompt)
        findings = _parse_findings(result.get("findings", []), FindingCategory.CODE_QUALITY)
        self.store.add_findings(findings)
        return {"findings": findings}


# ─── Test Analysis Agent ───────────────────────────────────────────────────────

_TEST_SYS = """\
You are a test coverage reviewer for Bob CodeGuard.
Analyze the PR diff and identify testing issues. Return JSON:
{
  "findings": [
    {
      "category": "testing",
      "severity": "critical|warning|suggestion|info",
      "title": "short title",
      "description": "detailed description",
      "file": "file path",
      "line": null,
      "symbol": "function or class",
      "snippet": "relevant code",
      "evidence_reason": "why a test is needed or missing",
      "suggested_action": "what test to add",
      "confidence": "confirmed|likely|potential"
    }
  ],
  "missing_tests": ["description of each missing test case"],
  "test_files_added": ["test files that were added in this PR"]
}
Focus on: missing unit tests for new functions, edge cases not covered,
no tests for bug fixes, deleted tests without replacement.
Only report findings grounded in actual changed code.
"""


class TestAnalysisAgent(BaseAgent):
    name = "TestAnalysisAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        diff_block = context["diff_block"]
        pr = context["pr"]

        user_prompt = f"""
PR #{pr['number']}: {pr['title']}

Changed files diff:
{self._truncate(diff_block, 10000)}
"""
        result = await call_llm_json(_TEST_SYS, user_prompt)
        findings = _parse_findings(result.get("findings", []), FindingCategory.TESTING)
        self.store.add_findings(findings)
        return {
            "findings": findings,
            "missing_tests": result.get("missing_tests", []),
        }


# ─── Regression Analysis Agent ────────────────────────────────────────────────

_REGRESSION_SYS = """\
You are a regression risk analyst for Bob CodeGuard.
Analyze the PR diff and the broader repository context for regression risks. Return JSON:
{
  "findings": [
    {
      "category": "regression",
      "severity": "critical|warning|suggestion|info",
      "title": "short title",
      "description": "detailed description",
      "file": "file path",
      "line": null,
      "symbol": "function or class",
      "snippet": "relevant code",
      "evidence_reason": "why this is a regression risk",
      "suggested_action": "how to mitigate",
      "confidence": "confirmed|likely|potential"
    }
  ],
  "potential_regressions": ["description of each regression risk"],
  "recommendation": "approve|request_changes|comment",
  "recommendation_reason": "brief explanation"
}
Focus on: changed public APIs, removed parameters, changed return types,
changed behaviour of shared utilities, database schema changes, config changes.
"""


class RegressionAgent(BaseAgent):
    name = "RegressionAgent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        diff_block = context["diff_block"]
        pr = context["pr"]

        user_prompt = f"""
PR #{pr['number']}: {pr['title']}
Author: {pr.get('user', {}).get('login', 'unknown')}
Base branch: {pr.get('base', {}).get('ref', 'main')}

Changed files diff:
{self._truncate(diff_block, 10000)}
"""
        result = await call_llm_json(_REGRESSION_SYS, user_prompt)
        findings = _parse_findings(result.get("findings", []), FindingCategory.REGRESSION)
        self.store.add_findings(findings)
        return {
            "findings": findings,
            "potential_regressions": result.get("potential_regressions", []),
            "recommendation": result.get("recommendation", "comment"),
            "recommendation_reason": result.get("recommendation_reason", ""),
        }
