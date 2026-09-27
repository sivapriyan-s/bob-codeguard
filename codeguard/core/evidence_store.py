"""
codeguard/core/evidence_store.py
In-memory evidence collector for a single CodeGuard run.
Agents append findings/evidence here; the orchestrator reads them.
"""
from __future__ import annotations
import logging
from collections import defaultdict

from .models import Evidence, Finding, ImpactNode, DocDrift

logger = logging.getLogger(__name__)


class EvidenceStore:
    """Thread-safe-enough evidence accumulator for async workflows."""

    def __init__(self) -> None:
        self._findings: list[Finding] = []
        self._impact_nodes: list[ImpactNode] = []
        self._drifts: list[DocDrift] = []
        self._raw: dict[str, list[str]] = defaultdict(list)  # category → messages

    # ── findings ──────────────────────────────────────────────────────────────

    def add_finding(self, finding: Finding) -> None:
        self._findings.append(finding)
        logger.debug("Finding added [%s/%s]: %s", finding.severity, finding.category, finding.title)

    def add_findings(self, findings: list[Finding]) -> None:
        for f in findings:
            self.add_finding(f)

    @property
    def findings(self) -> list[Finding]:
        return list(self._findings)

    # ── impact map ────────────────────────────────────────────────────────────

    def add_impact_node(self, node: ImpactNode) -> None:
        self._impact_nodes.append(node)

    def add_impact_nodes(self, nodes: list[ImpactNode]) -> None:
        for n in nodes:
            self.add_impact_node(n)

    @property
    def impact_nodes(self) -> list[ImpactNode]:
        return list(self._impact_nodes)

    # ── doc drifts ────────────────────────────────────────────────────────────

    def add_drift(self, drift: DocDrift) -> None:
        self._drifts.append(drift)

    def add_drifts(self, drifts: list[DocDrift]) -> None:
        for d in drifts:
            self.add_drift(d)

    @property
    def drifts(self) -> list[DocDrift]:
        return list(self._drifts)

    # ── raw notes ─────────────────────────────────────────────────────────────

    def note(self, category: str, message: str) -> None:
        self._raw[category].append(message)

    def get_notes(self, category: str) -> list[str]:
        return list(self._raw.get(category, []))

    # ── helpers ───────────────────────────────────────────────────────────────

    def summary_counts(self) -> dict[str, int]:
        from collections import Counter
        by_sev: Counter = Counter()
        by_cat: Counter = Counter()
        for f in self._findings:
            by_sev[f.severity.value] += 1
            by_cat[f.category.value] += 1
        return {
            "total_findings": len(self._findings),
            "total_impact_nodes": len(self._impact_nodes),
            "total_drifts": len(self._drifts),
            "by_severity": dict(by_sev),
            "by_category": dict(by_cat),
        }
