"""
codeguard/stages/bug_fix.py
Stage 1 orchestration — runs repository analysis + bug investigation in sequence,
applies code changes where possible, generates regression test suggestions.
"""
from __future__ import annotations
import logging
from typing import Any

from codeguard.core.github_client import GitHubClient
from codeguard.core.evidence_store import EvidenceStore
from codeguard.core.models import BugFixResult
from codeguard.agents.repo_analysis import RepoAnalysisAgent
from codeguard.agents.bug_investigation import BugInvestigationAgent

logger = logging.getLogger(__name__)


async def run_bug_fix_stage(
    gh: GitHubClient,
    owner: str,
    repo: str,
    issue_number: int,
    store: EvidenceStore,
    on_step: Any = None,
) -> BugFixResult:
    """
    Full Bug Fix stage pipeline.
    on_step(name, status, detail) callback for workflow step updates.
    """

    async def step(name: str, status: str, detail: str = "") -> None:
        if on_step:
            await on_step(name, status, detail)
        logger.info("[BugFix] %s → %s %s", name, status, detail)

    await step("Fetching issue", "running")
    issue = await gh.get_issue(owner, repo, issue_number)
    await step("Fetching issue", "done", f"#{issue_number}: {issue['title']}")

    await step("Repository Analysis", "running")
    repo_agent = RepoAnalysisAgent(gh, store)
    repo_analysis = await repo_agent.run({"owner": owner, "repo": repo})
    await step("Repository Analysis", "done", f"{repo_analysis.get('language')} / {repo_analysis.get('framework')}")

    await step("Bug Investigation", "running")
    bug_agent = BugInvestigationAgent(gh, store)
    investigation = await bug_agent.run({
        "owner": owner,
        "repo": repo,
        "issue": issue,
        "repo_analysis": repo_analysis,
    })
    await step("Bug Investigation", "done", f"Root cause identified: {investigation.get('root_cause', '')[:80]}")

    # Build result
    result = BugFixResult(
        issue_number=issue_number,
        issue_title=issue["title"],
        root_cause=investigation.get("root_cause", ""),
        affected_files=investigation.get("affected_files", []),
        changes_made=investigation.get("code_changes", []),
        tests_added=[t.get("description", "") for t in investigation.get("test_suggestions", [])],
        validation_result="Code changes proposed. Apply with the patch endpoint.",
        potential_side_effects=investigation.get("potential_side_effects", []),
        findings=store.findings,
    )

    await step("Bug Fix Stage", "done", f"{len(result.affected_files)} files affected")
    return result
