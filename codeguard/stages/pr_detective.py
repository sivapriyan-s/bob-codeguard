"""
codeguard/stages/pr_detective.py
Stage 3 orchestration — runs the PR Detective agent to trace the full
ripple effect of a change through the repository.
"""
from __future__ import annotations
import logging
from typing import Any

from codeguard.core.github_client import GitHubClient
from codeguard.core.evidence_store import EvidenceStore
from codeguard.core.models import PRDetectiveResult
from codeguard.agents.pr_detective import PRDetectiveAgent
from codeguard.agents.repo_analysis import RepoAnalysisAgent

logger = logging.getLogger(__name__)


async def run_pr_detective_stage(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    store: EvidenceStore,
    repo_analysis: dict | None = None,
    on_step: Any = None,
) -> PRDetectiveResult:

    async def step(name: str, status: str, detail: str = "") -> None:
        if on_step:
            await on_step(name, status, detail)
        logger.info("[PRDetective] %s → %s %s", name, status, detail)

    await step("Fetching PR", "running")
    pr = await gh.get_pr(owner, repo, pr_number)
    pr_files = await gh.get_pr_files(owner, repo, pr_number)
    await step("Fetching PR", "done", f"{len(pr_files)} files changed")

    # Ensure we have repo analysis
    if repo_analysis is None:
        await step("Repository Analysis", "running")
        repo_agent = RepoAnalysisAgent(gh, store)
        repo_analysis = await repo_agent.run({"owner": owner, "repo": repo})
        await step("Repository Analysis", "done")

    await step("PR Detective — Impact Tracing", "running")
    detective = PRDetectiveAgent(gh, store)
    det_result = await detective.run({
        "owner": owner,
        "repo": repo,
        "pr": pr,
        "pr_files": pr_files,
        "repo_analysis": repo_analysis,
    })
    await step("PR Detective — Impact Tracing", "done",
               f"{len(det_result.get('direct_dependencies', []))} direct deps found")

    result = PRDetectiveResult(
        pr_number=pr_number,
        impact_map=det_result.get("parsed_impact_nodes", []),
        direct_deps=[d["path"] for d in det_result.get("direct_dependencies", [])],
        indirect_deps=[d["path"] for d in det_result.get("indirect_dependencies", [])],
        affected_apis=[a.get("endpoint", a.get("file", "")) for a in det_result.get("affected_apis", [])],
        affected_tests=[t["path"] for t in det_result.get("affected_tests", [])],
        missing_tests=det_result.get("missing_tests", []),
        affected_docs=[d["path"] for d in det_result.get("affected_docs", [])],
        findings=det_result.get("parsed_findings", []),
        summary=det_result.get("summary", ""),
    )

    await step("PR Detective Stage", "done",
               f"{len(result.direct_deps)} direct · {len(result.indirect_deps)} indirect")
    return result
