"""
codeguard/orchestrator.py
Main CodeGuard Orchestrator — coordinates all stages for a given job,
manages workflow state, and produces the final unified report.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from codeguard.core.github_client import GitHubClient
from codeguard.core.evidence_store import EvidenceStore
from codeguard.core.models import (
    WorkflowState, WorkflowStep, WorkflowStepStatus, CodeGuardReport
)
from codeguard.agents.repo_analysis import RepoAnalysisAgent
from codeguard.stages.bug_fix import run_bug_fix_stage
from codeguard.stages.pr_review import run_pr_review_stage
from codeguard.stages.pr_detective import run_pr_detective_stage
from codeguard.stages.doc_sync import run_doc_sync_stage
from codeguard.reports.generator import generate_report

logger = logging.getLogger(__name__)

# In-memory job registry {job_id: WorkflowState}
_jobs: dict[str, WorkflowState] = {}


def get_job(job_id: str) -> WorkflowState | None:
    return _jobs.get(job_id)


def list_jobs() -> list[WorkflowState]:
    return list(_jobs.values())


async def run_codeguard(
    repository: str,
    mode: str,
    ref: str,
    job_id: str | None = None,
) -> WorkflowState:
    """
    Entry point for a CodeGuard analysis job.

    mode:
      - "bug_fix"      → Stage 1: analyze a GitHub issue
      - "pr_review"    → Stage 2: review a PR
      - "pr_detective" → Stage 3: trace PR impact
      - "doc_sync"     → Stage 4: documentation sync
      - "full_pr"      → Stages 2 + 3 + 4 for a PR (most common)
      - "full_issue"   → Stages 1 + 4 for a bug issue

    ref:  issue number or PR number (as string)
    job_id: optional pre-assigned job id (for background task continuity)
    """
    gh = GitHubClient()
    store = EvidenceStore()
    owner, repo = GitHubClient.parse_repo(repository)

    # Build initial workflow steps based on mode
    steps = _build_steps(mode)
    state = WorkflowState(
        repository=repository,
        mode=mode,
        ref=ref,
        steps=steps,
        status="running",
    )
    if job_id:
        state.job_id = job_id  # type: ignore[assignment]
    _jobs[state.job_id] = state

    async def on_step(name: str, status: str, detail: str = "") -> None:
        _update_step(state, name, status, detail)

    try:
        # ── Step 1: Repository Analysis (always first) ────────────────────────
        await on_step("Repository Analysis", "running")
        repo_agent = RepoAnalysisAgent(gh, store)
        repo_analysis = await repo_agent.run({"owner": owner, "repo": repo})
        await on_step("Repository Analysis", "done",
                      f"{repo_analysis.get('language')} · {repo_analysis.get('framework')}")

        bug_fix_result = None
        pr_review_result = None
        pr_detective_result = None
        doc_sync_result = None
        pr_files: list[dict] = []

        ref_int = int(ref) if ref.isdigit() else 0

        # ── Stage 1: Bug Fix ──────────────────────────────────────────────────
        if mode in ("bug_fix", "full_issue") and ref_int:
            bug_fix_result = await run_bug_fix_stage(
                gh, owner, repo, ref_int, store, on_step=on_step
            )

        # ── Stages 2/3/4: PR-based ────────────────────────────────────────────
        if mode in ("pr_review", "full_pr") and ref_int:
            pr_review_result = await run_pr_review_stage(
                gh, owner, repo, ref_int, store,
                repo_analysis=repo_analysis, on_step=on_step
            )

        if mode in ("pr_detective", "full_pr") and ref_int:
            pr_detective_result = await run_pr_detective_stage(
                gh, owner, repo, ref_int, store,
                repo_analysis=repo_analysis, on_step=on_step
            )
            # Grab PR files for doc sync
            try:
                pr_files = await gh.get_pr_files(owner, repo, ref_int)
            except Exception:
                pr_files = []

        if mode in ("doc_sync", "full_pr", "full_issue"):
            doc_sync_result = await run_doc_sync_stage(
                gh, owner, repo, store,
                repo_analysis=repo_analysis,
                pr_files=pr_files,
                on_step=on_step,
            )

        # ── Generate unified report ───────────────────────────────────────────
        await on_step("Generating Report", "running")
        report = await generate_report(
            owner=owner,
            repo=repo,
            ref=ref,
            store=store,
            bug_fix=bug_fix_result,
            pr_review=pr_review_result,
            pr_detective=pr_detective_result,
            doc_sync=doc_sync_result,
        )
        await on_step("Generating Report", "done",
                      f"{len(store.findings)} findings · {len(store.drifts)} drifts")

        state.report = report
        state.status = "done"

    except Exception as exc:
        logger.exception("CodeGuard job %s failed", state.job_id)
        state.error = str(exc)
        state.status = "error"
        _update_step(state, "Error", "error", str(exc))

    return state


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_steps(mode: str) -> list[WorkflowStep]:
    base = [WorkflowStep(name="Repository Analysis")]

    if mode == "bug_fix":
        return base + [
            WorkflowStep(name="Bug Investigation"),
            WorkflowStep(name="Fix Proposal"),
            WorkflowStep(name="Generating Report"),
        ]
    if mode == "pr_review":
        return base + [
            WorkflowStep(name="Fetching PR"),
            WorkflowStep(name="Security Agent"),
            WorkflowStep(name="Code Quality Agent"),
            WorkflowStep(name="Test Analysis Agent"),
            WorkflowStep(name="Regression Agent"),
            WorkflowStep(name="Generating Report"),
        ]
    if mode == "pr_detective":
        return base + [
            WorkflowStep(name="Fetching PR"),
            WorkflowStep(name="PR Detective — Impact Tracing"),
            WorkflowStep(name="Generating Report"),
        ]
    if mode == "doc_sync":
        return base + [
            WorkflowStep(name="Documentation Sync"),
            WorkflowStep(name="Generating Report"),
        ]
    if mode == "full_pr":
        return base + [
            WorkflowStep(name="Fetching PR"),
            WorkflowStep(name="Parallel Review Agents"),
            WorkflowStep(name="PR Detective — Impact Tracing"),
            WorkflowStep(name="Documentation Sync"),
            WorkflowStep(name="Generating Report"),
        ]
    if mode == "full_issue":
        return base + [
            WorkflowStep(name="Bug Investigation"),
            WorkflowStep(name="Fix Proposal"),
            WorkflowStep(name="Documentation Sync"),
            WorkflowStep(name="Generating Report"),
        ]
    return base + [WorkflowStep(name="Generating Report")]


def _update_step(state: WorkflowState, name: str, status: str, detail: str = "") -> None:
    for step in state.steps:
        if step.name == name:
            step.status = WorkflowStepStatus(status)
            step.detail = detail
            return
    # Step not pre-declared — add it dynamically
    state.steps.append(WorkflowStep(
        name=name,
        status=WorkflowStepStatus(status),
        detail=detail,
    ))
