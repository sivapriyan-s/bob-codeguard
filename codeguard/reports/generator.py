"""
codeguard/reports/generator.py
Synthesizes all stage results into a unified CodeGuard report with
executive summary and evidence-backed findings.
"""
from __future__ import annotations
import logging
from typing import Any

from codeguard.core.llm import call_llm_json
from codeguard.core.models import (
    CodeGuardReport, Finding, ImpactNode, DocDrift,
    BugFixResult, PRReviewResult, PRDetectiveResult, DocSyncResult,
    Severity,
)
from codeguard.core.evidence_store import EvidenceStore

logger = logging.getLogger(__name__)

_SUMMARY_SYS = """\
You are a senior engineering lead writing an executive summary for a CodeGuard analysis report.
Given findings, root cause, and impact data, write a concise, evidence-based summary.

Return JSON:
{
  "executive_summary": "3-5 sentence plain-English summary of what was found and recommended",
  "recommended_changes": ["actionable recommendation 1", "actionable recommendation 2", ...],
  "regression_risks": ["risk 1", "risk 2", ...]
}
"""


async def generate_report(
    owner: str,
    repo: str,
    ref: str,
    store: EvidenceStore,
    bug_fix: BugFixResult | None = None,
    pr_review: PRReviewResult | None = None,
    pr_detective: PRDetectiveResult | None = None,
    doc_sync: DocSyncResult | None = None,
) -> CodeGuardReport:

    findings = store.findings
    impact_nodes = store.impact_nodes
    drifts = store.drifts

    # Collect changed components
    changed_components: list[str] = []
    if pr_review:
        # will be set from pr_files in orchestrator
        pass
    if bug_fix:
        changed_components.extend(bug_fix.affected_files)
    if pr_detective:
        changed_components.extend(pr_detective.direct_deps[:5])

    # Collect regression risks
    regression_risks: list[str] = []
    if pr_review:
        regression_risks.extend(pr_review.potential_regressions)
    if pr_detective:
        regression_risks.extend([
            f.description for f in pr_detective.findings
            if f.category.value == "regression"
        ])

    # Ask LLM for executive summary
    findings_text = "\n".join(
        f"[{f.severity.value.upper()}] {f.title}: {f.description[:120]}"
        for f in findings[:30]
    )
    drifts_text = "\n".join(
        f"- {d.doc_file}/{d.section}: {d.status}"
        for d in drifts[:10]
    )
    root_cause = (bug_fix.root_cause if bug_fix else "") or (
        pr_detective.summary if pr_detective else ""
    )

    user_prompt = f"""
Repository: {owner}/{repo}
Reference: {ref}

Root Cause / Context:
{root_cause or 'N/A'}

Findings ({len(findings)} total):
{findings_text or 'None'}

Documentation Drifts ({len(drifts)} total):
{drifts_text or 'None'}

Regression Risks:
{chr(10).join(f'- {r}' for r in regression_risks[:5]) or 'None'}
"""

    summary_data = await call_llm_json(_SUMMARY_SYS, user_prompt)

    report = CodeGuardReport(
        repository=f"{owner}/{repo}",
        ref=ref,
        executive_summary=summary_data.get("executive_summary", ""),
        root_cause=root_cause,
        changed_components=list(set(changed_components))[:20],
        all_findings=findings,
        impact_map=impact_nodes,
        regression_risks=regression_risks,
        documentation_drifts=drifts,
        recommended_changes=summary_data.get("recommended_changes", []),
        validation_results=bug_fix.validation_result if bug_fix else "",
        bug_fix=bug_fix,
        pr_review=pr_review,
        pr_detective=pr_detective,
        doc_sync=doc_sync,
    )

    logger.info(
        "Report generated: %s findings, %s drifts, %s impact nodes",
        len(findings), len(drifts), len(impact_nodes),
    )
    return report
