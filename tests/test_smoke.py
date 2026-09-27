"""
tests/test_smoke.py
Smoke tests for Bob CodeGuard — no real GitHub/OpenAI calls needed.
Run with:  python -m pytest tests/ -v
"""
from __future__ import annotations
import os
import pytest

# Inject dummy secrets before any app import
os.environ.setdefault("GITHUB_TOKEN", "dummy_token")
os.environ.setdefault("OPENAI_API_KEY", "dummy_key")


# ─── Core models ──────────────────────────────────────────────────────────────

def test_finding_model():
    from codeguard.core.models import Finding, Evidence, Confidence, Severity, FindingCategory
    ev = Evidence(file="src/auth.py", line=42, symbol="login", reason="direct use", confidence=Confidence.CONFIRMED)
    f = Finding(
        category=FindingCategory.SECURITY,
        severity=Severity.CRITICAL,
        title="SQL Injection",
        description="Unsanitised query parameter",
        evidence=[ev],
        suggested_action="Use parameterised queries",
        confidence=Confidence.CONFIRMED,
    )
    assert f.id  # auto-generated
    assert f.severity == Severity.CRITICAL
    assert f.evidence[0].file == "src/auth.py"


def test_doc_drift_model():
    from codeguard.core.models import DocDrift, Severity
    d = DocDrift(
        doc_file="README.md",
        section="API",
        code_truth="POST /api/v2/users",
        doc_current="POST /api/v1/users",
        status="OUTDATED",
        severity=Severity.WARNING,
        suggested_update="Update endpoint to /api/v2/users",
    )
    assert d.status == "OUTDATED"
    assert d.doc_file == "README.md"


def test_codeguard_report_model():
    from codeguard.core.models import CodeGuardReport
    r = CodeGuardReport(
        repository="owner/repo",
        ref="142",
        executive_summary="Test summary.",
        root_cause="Null pointer in auth module.",
    )
    assert r.report_id
    assert r.generated_at.endswith("Z")
    assert r.repository == "owner/repo"


def test_workflow_state_step_update():
    from codeguard.core.models import WorkflowState, WorkflowStep, WorkflowStepStatus
    from codeguard.orchestrator import _build_steps, _update_step
    state = WorkflowState(repository="a/b", mode="full_pr", ref="1")
    state.steps = _build_steps("full_pr")
    assert len(state.steps) >= 5
    _update_step(state, "Repository Analysis", "running", "checking...")
    step = next(s for s in state.steps if s.name == "Repository Analysis")
    assert step.status == WorkflowStepStatus.RUNNING
    assert step.detail == "checking..."


# ─── Evidence store ───────────────────────────────────────────────────────────

def test_evidence_store_accumulation():
    from codeguard.core.evidence_store import EvidenceStore
    from codeguard.core.models import Finding, ImpactNode, DocDrift, Confidence, Severity, FindingCategory

    store = EvidenceStore()

    f = Finding(
        category=FindingCategory.BUG, severity=Severity.WARNING,
        title="Test finding", description="desc",
    )
    store.add_finding(f)

    node = ImpactNode(path="api.py", kind="file", relation="direct", confidence=Confidence.CONFIRMED)
    store.add_impact_node(node)

    drift = DocDrift(doc_file="README.md", section="Intro", code_truth="x", doc_current="y", status="OUTDATED")
    store.add_drift(drift)

    counts = store.summary_counts()
    assert counts["total_findings"] == 1
    assert counts["total_impact_nodes"] == 1
    assert counts["total_drifts"] == 1
    assert counts["by_severity"]["warning"] == 1
    assert counts["by_category"]["bug"] == 1


def test_evidence_store_notes():
    from codeguard.core.evidence_store import EvidenceStore
    store = EvidenceStore()
    store.note("security", "Found hardcoded secret")
    store.note("security", "Missing CSRF token")
    store.note("quality", "Long function body")
    assert len(store.get_notes("security")) == 2
    assert len(store.get_notes("quality")) == 1
    assert store.get_notes("nonexistent") == []


# ─── GitHub client helpers ────────────────────────────────────────────────────

def test_github_parse_repo():
    from codeguard.core.github_client import GitHubClient
    owner, repo = GitHubClient.parse_repo("microsoft/vscode")
    assert owner == "microsoft"
    assert repo == "vscode"

    owner2, repo2 = GitHubClient.parse_repo("  torvalds/linux  ")
    assert owner2 == "torvalds"
    assert repo2 == "linux"


def test_github_parse_repo_invalid():
    from codeguard.core.github_client import GitHubClient
    with pytest.raises(ValueError, match="Invalid repo format"):
        GitHubClient.parse_repo("noslash")


# ─── Orchestrator step builder ───────────────────────────────────────────────

@pytest.mark.parametrize("mode,min_steps", [
    ("bug_fix", 4),
    ("pr_review", 6),
    ("pr_detective", 4),
    ("doc_sync", 3),
    ("full_pr", 5),
    ("full_issue", 5),
])
def test_build_steps_all_modes(mode, min_steps):
    from codeguard.orchestrator import _build_steps
    steps = _build_steps(mode)
    assert len(steps) >= min_steps, f"mode={mode}: expected >= {min_steps} steps, got {len(steps)}"
    # All steps start as pending
    for s in steps:
        assert s.status.value == "pending"


def test_dynamic_step_addition():
    from codeguard.core.models import WorkflowState
    from codeguard.orchestrator import _build_steps, _update_step
    state = WorkflowState(repository="a/b", mode="bug_fix", ref="5")
    state.steps = _build_steps("bug_fix")
    initial_count = len(state.steps)
    _update_step(state, "New Dynamic Step", "done", "added on the fly")
    assert len(state.steps) == initial_count + 1
    new_step = state.steps[-1]
    assert new_step.name == "New Dynamic Step"
    assert new_step.status.value == "done"


# ─── API endpoints ────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def test_health(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "CodeGuard" in data["service"]


def test_jobs_empty(api_client):
    r = api_client.get("/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_job_not_found(api_client):
    r = api_client.get("/api/jobs/does-not-exist")
    assert r.status_code == 404


def test_analyze_bad_mode(api_client):
    r = api_client.post("/api/analyze", json={"repository": "a/b", "mode": "invalid", "ref": "1"})
    assert r.status_code == 400
    assert "mode" in r.json()["detail"].lower()


def test_analyze_bad_repo(api_client):
    r = api_client.post("/api/analyze", json={"repository": "noslash", "mode": "doc_sync", "ref": "1"})
    assert r.status_code == 400


def test_analyze_missing_ref(api_client):
    r = api_client.post("/api/analyze", json={"repository": "a/b", "mode": "doc_sync", "ref": ""})
    assert r.status_code == 400


def test_analyze_starts_job(api_client):
    r = api_client.post("/api/analyze", json={"repository": "a/b", "mode": "doc_sync", "ref": "3"})
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data["status"] == "pending"


def test_patch_no_bug_fix(api_client):
    """patch endpoint returns 404 for jobs without bug_fix data."""
    # Start a doc_sync job (no bug fix)
    r = api_client.post("/api/analyze", json={"repository": "a/b", "mode": "doc_sync", "ref": "9"})
    job_id = r.json()["job_id"]

    # Force job to done with no bug_fix
    from codeguard import orchestrator as orch
    from codeguard.core.models import CodeGuardReport
    state = orch._jobs[job_id]
    state.status = "done"
    state.report = CodeGuardReport(repository="a/b", ref="9")

    r2 = api_client.post(f"/api/jobs/{job_id}/patch", json={"job_id": job_id, "confirm": False})
    assert r2.status_code == 404


# ─── Diff utility ────────────────────────────────────────────────────────────

def test_unified_diff():
    from codeguard.api.routes import _format_unified_diff
    diff = _format_unified_diff("auth.py", "def login():\n    pass\n", "def login(user):\n    return user\n")
    assert "a/auth.py" in diff
    assert "b/auth.py" in diff
    assert "-def login():" in diff
    assert "+def login(user):" in diff


def test_unified_diff_empty():
    from codeguard.api.routes import _format_unified_diff
    result = _format_unified_diff("f.py", "", "")
    assert result == ""


# ─── Report text builder ──────────────────────────────────────────────────────

def test_report_contains_key_sections():
    """The in-memory report model serialises all expected keys."""
    from codeguard.core.models import (
        CodeGuardReport, Finding, Severity, Confidence, FindingCategory, Evidence
    )
    report = CodeGuardReport(
        repository="acme/app",
        ref="42",
        executive_summary="Two critical security issues found.",
        root_cause="Unsanitised input in login handler.",
        recommended_changes=["Add input validation", "Use parameterised queries"],
        all_findings=[
            Finding(
                category=FindingCategory.SECURITY,
                severity=Severity.CRITICAL,
                title="SQL Injection",
                description="Login handler vulnerable to SQL injection.",
                evidence=[Evidence(file="app/auth.py", line=55, reason="string concat in query", confidence=Confidence.CONFIRMED)],
                suggested_action="Use parameterised queries",
                confidence=Confidence.CONFIRMED,
            )
        ],
    )
    d = report.model_dump()
    assert d["executive_summary"]
    assert d["root_cause"]
    assert len(d["all_findings"]) == 1
    assert d["all_findings"][0]["severity"] == "critical"
    assert d["all_findings"][0]["evidence"][0]["file"] == "app/auth.py"
