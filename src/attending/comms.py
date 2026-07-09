"""Communication-surface supervision — the second half of Attending.

Attending's triage layer (`supervise`) governs what a clinical agent DECIDES.
This layer governs what it SAYS: it runs sitrep's deterministic communication
gates over a candidate rendering and maps each `sitrep.Violation` into
Attending's shared verdict vocabulary (`Finding` / `Severity` / `Decision`), so
the decision and communication surfaces speak one language and a single UI can
render both. Every blocked rendering names the guideline or law it protects.

Dependency direction is one-way: `attending` depends on `sitrep`, never the
reverse — sitrep stays a self-contained, stdlib-only gate library.
"""

from __future__ import annotations

from dataclasses import dataclass

from sitrep.gates import Rendering, Violation, check_disclosure_gap, is_patient_facing, run_gates
from sitrep.gates import Severity as GateSeverity
from sitrep.state import EncounterState

from .verdict import Decision, Finding, Severity

# What each gate is protecting — so a block can cite the rule, not just fire.
GATE_CITATIONS: dict[str, str] = {
    "no_interpretation": "Scope of practice: no diagnosis/prognosis in patient pane "
    "(CDS non-device lane, 21st Century Cures Act §3060)",
    "info_blocking": "21st Century Cures Act information-blocking rule (45 CFR Part 171)",
    "no_advice": "Scope of practice: no directive medical advice in patient pane",
    "compliance": "CA AB 3030: AI disclosure + human contact path in clinical comms",
    "grounding": "No-fabrication / Linked-Evidence: every claim traces to the chart",
    "escalation": "Escalation persistence: a raised escalation must stay acknowledged",
    "readability": "Health literacy: patient text at/below ~8th-grade (AHRQ plain language)",
    "disclosure_gap": "Cures-era safety: patient alone with a viewed critical result "
    "(21st Century Cures Act patient-access rule)",
}

_SEVERITY_MAP = {
    GateSeverity.BLOCK: Severity.BLOCK,
    GateSeverity.WARN: Severity.WARN,
}


@dataclass(frozen=True)
class CommsVerdict:
    """Verdict over one rendering. Reuses Attending's Decision/Finding vocabulary;
    omits the ESI fields (those belong to the triage surface, not this one)."""

    audience: str
    decision: Decision            # ALLOW | BLOCK (comms never ESCALATEs a triage acuity)
    findings: tuple[Finding, ...]

    @property
    def blocked(self) -> bool:
        return self.decision is Decision.BLOCK


def _to_finding(v: Violation) -> Finding:
    return Finding(
        kind=f"comms_gate:{v.gate}",
        severity=_SEVERITY_MAP.get(v.severity, Severity.WARN),
        message=v.detail,
        criterion_id=f"SITREP-{v.gate}",
        citation=GATE_CITATIONS.get(v.gate),
        evidence=v.detail_ref or "",
    )


def supervise_rendering(rendering: Rendering, state: EncounterState) -> CommsVerdict:
    """Fail-closed supervision of one patient/team-facing rendering.

    Runs the per-rendering gates plus the state-level disclosure-gap check.
    Any BLOCK-severity violation blocks the rendering; WARN-only ships
    (annotated) but is still surfaced as a Finding. No violations -> ALLOW.
    """
    violations = list(run_gates(rendering, state))
    # The disclosure gap is a property of the chart, not this text, but a
    # patient-facing rendering is exactly the moment it must not slip through.
    if is_patient_facing(rendering.audience):
        violations.extend(check_disclosure_gap(state))

    findings = tuple(_to_finding(v) for v in violations)
    blocked = any(f.severity is Severity.BLOCK for f in findings)
    decision = Decision.BLOCK if blocked else Decision.ALLOW
    return CommsVerdict(audience=rendering.audience, decision=decision, findings=findings)
