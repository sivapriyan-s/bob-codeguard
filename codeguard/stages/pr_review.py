"""
codeguard/stages/pr_review.py
Stage 2 orchestration — runs four specialized review agents in parallel,
collects all findings, and synthesizes a recommendation.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from codeguard.core.github_client import GitHubClient
from codeguard.core.evidence_store import EvidenceStore
from codeguard.core.models import PRReviewResult
from codeguard.agents.pr_review import (
    SecurityAgent, CodeQualityAgent, TestAnalysisAgent, RegressionAgent, _build_diff_block
)

logger = logging.getLogger(__name__)


async def run_pr_review_stage(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    store: EvidenceStore,
    repo_analysis: dict | None = None,
    on_step: Any = None,
) -> PRReviewResult:

    async def step(name: str, status: str, detail: str = "") -> None:
        if on_step:
            await on_step(name, status, detail)
        logger.info("[PRReview] %s → %s %s", name, status, detail)

    await step("Fetching PR", "running")
    pr = await gh.get_pr(owner, repo, pr_number)
    pr_files = await gh.get_pr_files(owner, repo, pr_number)
    await step("Fetching PR", "done", f"{len(pr_files)} files changed")

    diff_block = _build_diff_block(pr_files)
    context = {"owner": owner, "repo": repo, "pr": pr, "pr_files": pr_files, "diff_block": diff_block}

    await step("Parallel Review Agents", "running", "Security · CodeQuality · Testing · Regression")

    # Run all four agents in parallel
    sec_agent = SecurityAgent(gh, store)
    qual_agent = CodeQualityAgent(gh, store)
    test_agent = TestAnalysisAgent(gh, store)
    reg_agent = RegressionAgent(gh, store)

    sec_result, qual_result, test_result, reg_result = await asyncio.gather(
        sec_agent.run(context),
        qual_agent.run(context),
        test_agent.run(context),
        reg_agent.run(context),
    )

    await step("Parallel Review Agents", "done",
               f"Security·Quality·Testing·Regression complete")

    # Determine overall recommendation (worst wins)
    recommendations = [r.get("recommendation", "comment") for r in [reg_result]]
    if "request_changes" in recommendations:
        recommendation = "request_changes"
    elif any(f.severity.value == "critical" for f in store.findings):
        recommendation = "request_changes"
    else:
        recommendation = "comment"

    # Collect missing tests and regressions
    missing_tests = test_result.get("missing_tests", [])
    potential_regressions = reg_result.get("potential_regressions", [])

    result = PRReviewResult(
        pr_number=pr_number,
        pr_title=pr["title"],
        files_changed=len(pr_files),
        findings=store.findings,
        missing_tests=missing_tests,
        potential_regressions=potential_regressions,
        recommendation=recommendation,
        summary=reg_result.get("recommendation_reason", ""),
    )

    await step("PR Review Stage", "done", f"{len(store.findings)} findings · {recommendation}")
    return result
