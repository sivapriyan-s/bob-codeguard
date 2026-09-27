"""
codeguard/core/models.py
Shared data models used across all CodeGuard stages.
"""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import uuid
from datetime import datetime, timezone


# ─── Confidence / Severity ───────────────────────────────────────────────────

class Confidence(str, Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    POTENTIAL = "potential"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    INFO = "info"


class FindingCategory(str, Enum):
    BUG = "bug"
    SECURITY = "security"
    CODE_QUALITY = "code_quality"
    TESTING = "testing"
    REGRESSION = "regression"
    DOCUMENTATION = "documentation"
    IMPACT = "impact"
    API = "api"


# ─── Evidence ────────────────────────────────────────────────────────────────

class Evidence(BaseModel):
    file: str
    line: int | None = None
    symbol: str | None = None
    snippet: str | None = None
    reason: str
    confidence: Confidence = Confidence.CONFIRMED


# ─── Finding ─────────────────────────────────────────────────────────────────

class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    category: FindingCategory
    severity: Severity
    title: str
    description: str
    evidence: list[Evidence] = Field(default_factory=list)
    suggested_action: str = ""
    confidence: Confidence = Confidence.CONFIRMED


# ─── Impact Node ─────────────────────────────────────────────────────────────

class ImpactNode(BaseModel):
    path: str
    kind: str  # "file" | "function" | "class" | "api" | "db" | "test" | "doc"
    relation: str  # "direct" | "indirect" | "caller" | "consumer" | "test" | "doc"
    confidence: Confidence = Confidence.CONFIRMED
    children: list[ImpactNode] = Field(default_factory=list)


# ─── Stage Results ────────────────────────────────────────────────────────────

class BugFixResult(BaseModel):
    issue_number: int | None = None
    issue_title: str = ""
    root_cause: str = ""
    affected_files: list[str] = Field(default_factory=list)
    changes_made: list[dict[str, Any]] = Field(default_factory=list)
    tests_added: list[str] = Field(default_factory=list)
    validation_result: str = ""
    potential_side_effects: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class PRReviewResult(BaseModel):
    pr_number: int
    pr_title: str = ""
    files_changed: int = 0
    findings: list[Finding] = Field(default_factory=list)
    missing_tests: list[str] = Field(default_factory=list)
    potential_regressions: list[str] = Field(default_factory=list)
    recommendation: str = ""  # "approve" | "request_changes" | "comment"
    summary: str = ""


class PRDetectiveResult(BaseModel):
    pr_number: int
    impact_map: list[ImpactNode] = Field(default_factory=list)
    direct_deps: list[str] = Field(default_factory=list)
    indirect_deps: list[str] = Field(default_factory=list)
    affected_apis: list[str] = Field(default_factory=list)
    affected_tests: list[str] = Field(default_factory=list)
    missing_tests: list[str] = Field(default_factory=list)
    affected_docs: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""


class DocDrift(BaseModel):
    doc_file: str
    section: str
    code_truth: str
    doc_current: str
    status: str  # "OUTDATED" | "MISSING" | "ACCURATE"
    severity: Severity = Severity.WARNING
    suggested_update: str = ""


class DocSyncResult(BaseModel):
    drifts: list[DocDrift] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""


# ─── CodeGuard Report ─────────────────────────────────────────────────────────

class CodeGuardReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    repository: str = ""
    ref: str = ""  # issue number, PR number, or commit SHA
    executive_summary: str = ""
    root_cause: str = ""
    changed_components: list[str] = Field(default_factory=list)
    all_findings: list[Finding] = Field(default_factory=list)
    impact_map: list[ImpactNode] = Field(default_factory=list)
    regression_risks: list[str] = Field(default_factory=list)
    documentation_drifts: list[DocDrift] = Field(default_factory=list)
    recommended_changes: list[str] = Field(default_factory=list)
    validation_results: str = ""
    # Stage sub-results
    bug_fix: BugFixResult | None = None
    pr_review: PRReviewResult | None = None
    pr_detective: PRDetectiveResult | None = None
    doc_sync: DocSyncResult | None = None


# ─── Workflow Status ──────────────────────────────────────────────────────────

class WorkflowStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"


class WorkflowStep(BaseModel):
    name: str
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    detail: str = ""


class WorkflowState(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    repository: str = ""
    mode: str = ""  # "bug_fix" | "pr_review" | "pr_detective" | "doc_sync" | "full"
    ref: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)
    report: CodeGuardReport | None = None
    error: str | None = None
    status: str = "pending"  # "pending" | "running" | "done" | "error"
