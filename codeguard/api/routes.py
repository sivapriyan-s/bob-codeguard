"""
codeguard/api/routes.py
FastAPI routes for the CodeGuard REST API.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from codeguard.orchestrator import run_codeguard, get_job, list_jobs
from codeguard.core.models import WorkflowState, CodeGuardReport

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ─── Request / Response schemas ───────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    repository: str   # "owner/repo"
    mode: str         # "bug_fix" | "pr_review" | "pr_detective" | "doc_sync" | "full_pr" | "full_issue"
    ref: str          # issue or PR number as string


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class PatchRequest(BaseModel):
    job_id: str       # completed bug_fix job
    confirm: bool = False  # must be True to actually apply


# ─── Helpers ──────────────────────────────────────────────────────────────────

VALID_MODES = {"bug_fix", "pr_review", "pr_detective", "doc_sync", "full_pr", "full_issue"}


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=JobResponse)
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks) -> JobResponse:
    """Start a CodeGuard analysis job. Returns job_id immediately; poll /jobs/{id} for status."""
    if request.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Choose from: {sorted(VALID_MODES)}")

    if "/" not in request.repository:
        raise HTTPException(status_code=400, detail="repository must be in 'owner/repo' format")

    if not request.ref.strip():
        raise HTTPException(status_code=400, detail="ref (PR/issue number) is required")

    # Pre-create state so client can poll immediately
    from codeguard import orchestrator as orch
    placeholder = WorkflowState(
        repository=request.repository,
        mode=request.mode,
        ref=request.ref.strip(),
        status="pending",
    )
    orch._jobs[placeholder.job_id] = placeholder

    background_tasks.add_task(
        _run_job,
        placeholder.job_id,
        request.repository,
        request.mode,
        request.ref.strip(),
    )

    return JobResponse(
        job_id=placeholder.job_id,
        status="pending",
        message=f"CodeGuard analysis started for {request.repository} ({request.mode})",
    )


async def _run_job(job_id: str, repository: str, mode: str, ref: str) -> None:
    """Background coroutine that runs the full CodeGuard analysis."""
    try:
        await run_codeguard(repository, mode, ref, job_id=job_id)
    except Exception as exc:
        logger.exception("Job %s failed at top level", job_id)
        from codeguard import orchestrator as orch
        if job_id in orch._jobs:
            orch._jobs[job_id].status = "error"
            orch._jobs[job_id].error = str(exc)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    """
    Server-Sent Events stream for real-time workflow progress.
    The client receives step updates as they happen, and a final 'done' event
    with the complete report payload.

    Usage (JS):
        const es = new EventSource(`/api/jobs/${jobId}/stream`);
        es.onmessage = e => console.log(JSON.parse(e.data));
    """
    state = get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    return StreamingResponse(
        _sse_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator(job_id: str) -> AsyncGenerator[str, None]:
    """Yield SSE events for job step updates until completion."""
    last_step_count = 0
    last_status = ""
    timeout_secs = 600  # 10 min max
    elapsed = 0.0
    poll_interval = 0.8

    while elapsed < timeout_secs:
        state = get_job(job_id)
        if not state:
            yield _sse_event({"type": "error", "message": "Job not found"})
            return

        # Emit any new steps
        current_steps = state.steps
        if len(current_steps) > last_step_count or state.status != last_status:
            payload = {
                "type": "progress",
                "status": state.status,
                "steps": [s.model_dump() for s in current_steps],
            }
            yield _sse_event(payload)
            last_step_count = len(current_steps)
            last_status = state.status

        if state.status == "done":
            report_data = state.report.model_dump() if state.report else {}
            yield _sse_event({"type": "done", "report": report_data})
            return

        if state.status == "error":
            yield _sse_event({"type": "error", "message": state.error or "Unknown error"})
            return

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    yield _sse_event({"type": "error", "message": "Stream timeout after 10 minutes"})


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    """Poll the status of a CodeGuard job."""
    state = get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return state.model_dump()


@router.get("/jobs")
async def list_all_jobs() -> list[dict]:
    """List all CodeGuard jobs (most recent first)."""
    jobs = list_jobs()
    jobs.sort(key=lambda j: j.job_id, reverse=True)
    return [
        {
            "job_id": j.job_id,
            "repository": j.repository,
            "mode": j.mode,
            "ref": j.ref,
            "status": j.status,
            "steps_done": sum(1 for s in j.steps if s.status.value == "done"),
            "steps_total": len(j.steps),
        }
        for j in jobs[:50]
    ]


@router.get("/jobs/{job_id}/report")
async def get_report(job_id: str) -> dict:
    """Get the final report for a completed job."""
    state = get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if state.status != "done":
        raise HTTPException(status_code=202, detail=f"Job status: {state.status}")
    if not state.report:
        raise HTTPException(status_code=500, detail="Job done but no report found")
    return state.report.model_dump()


@router.post("/jobs/{job_id}/patch")
async def apply_patch(job_id: str, request: PatchRequest) -> dict:
    """
    Preview or apply the code changes proposed by a Bug Fix job.

    With confirm=false (default): returns the proposed changes without applying.
    With confirm=true: returns the diff to apply (real file writes require local repo checkout).

    Note: CodeGuard proposes changes based on GitHub source. To apply them,
    the developer should have the repository checked out locally.
    """
    state = get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if state.status != "done":
        raise HTTPException(status_code=202, detail=f"Job not complete (status: {state.status})")

    report = state.report
    if not report or not report.bug_fix:
        raise HTTPException(status_code=404, detail="No bug fix data in this job. Run in bug_fix or full_issue mode.")

    changes = report.bug_fix.changes_made or []
    if not changes:
        return {"message": "No code changes were proposed.", "changes": []}

    if not request.confirm:
        return {
            "message": f"{len(changes)} change(s) proposed. Set confirm=true to get apply-ready patch.",
            "preview": True,
            "changes": changes,
        }

    # Return structured patch for developer to apply
    patch_output = []
    for ch in changes:
        patch_output.append({
            "file": ch.get("file", ""),
            "type": ch.get("type", "modify"),
            "description": ch.get("description", ""),
            "search": ch.get("search", ""),
            "replacement": ch.get("replacement", ""),
            "patch": _format_unified_diff(
                ch.get("file", "unknown"),
                ch.get("search", ""),
                ch.get("replacement", ""),
            ),
        })

    return {
        "message": f"Patch ready for {len(patch_output)} file(s). Apply manually or via git.",
        "preview": False,
        "changes": patch_output,
    }


def _format_unified_diff(filename: str, old: str, new: str) -> str:
    """Produce a minimal unified diff string for display."""
    if not old and not new:
        return ""
    old_lines = old.splitlines(keepends=True) if old else []
    new_lines = new.splitlines(keepends=True) if new else []
    import difflib
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "\n".join(diff)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "Bob CodeGuard", "version": "1.0.0"}
