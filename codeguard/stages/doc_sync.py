"""
codeguard/stages/doc_sync.py
Stage 4 orchestration — runs documentation sync agent against the repo.
"""
from __future__ import annotations
import logging
from typing import Any

from codeguard.core.github_client import GitHubClient
from codeguard.core.evidence_store import EvidenceStore
from codeguard.core.models import DocSyncResult
from codeguard.agents.doc_sync import DocSyncAgent
from codeguard.agents.repo_analysis import RepoAnalysisAgent

logger = logging.getLogger(__name__)


async def run_doc_sync_stage(
    gh: GitHubClient,
    owner: str,
    repo: str,
    store: EvidenceStore,
    repo_analysis: dict | None = None,
    pr_files: list[dict] | None = None,
    on_step: Any = None,
) -> DocSyncResult:

    async def step(name: str, status: str, detail: str = "") -> None:
        if on_step:
            await on_step(name, status, detail)
        logger.info("[DocSync] %s → %s %s", name, status, detail)

    if repo_analysis is None:
        await step("Repository Analysis", "running")
        repo_agent = RepoAnalysisAgent(gh, store)
        repo_analysis = await repo_agent.run({"owner": owner, "repo": repo})
        await step("Repository Analysis", "done")

    await step("Documentation Sync", "running")
    doc_agent = DocSyncAgent(gh, store)
    doc_result = await doc_agent.run({
        "owner": owner,
        "repo": repo,
        "repo_analysis": repo_analysis,
        "pr_files": pr_files or [],
    })
    await step("Documentation Sync", "done",
               f"{len(doc_result.get('parsed_drifts', []))} drifts detected")

    result = DocSyncResult(
        drifts=doc_result.get("parsed_drifts", []),
        findings=doc_result.get("parsed_findings", []),
        summary=doc_result.get("summary", ""),
    )

    await step("Doc Sync Stage", "done")
    return result
