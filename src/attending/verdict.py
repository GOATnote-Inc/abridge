"""Output types + terminal rendering for an Attending review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # runtime-cycle-free: confidence.py imports esi, not verdict
    from .confidence import ESIConfidence


class Decision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"  # fail-closed: hand to a human attending


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Detection:
    """One failure-mode detector's finding."""

    detector: str
    fired: bool
    severity: Severity
    message: str
    evidence: str = ""
    citation: str | None = None


@dataclass(frozen=True)
class Finding:
    """A single reason Attending acted on a proposed action."""

    kind: str            # "under_triage" | "workup_incomplete" | "detector" | ...
    severity: Severity
    message: str
    criterion_id: str | None = None
    citation: str | None = None
    evidence: str = ""


@dataclass(frozen=True)
class Verdict:
    encounter_id: str
    decision: Decision
    proposed_esi: int | None
    attending_esi: int          # the safe acuity Attending stands behind
    recommended_esi: int        # fail-closed: most-acute of all signals
    confidence: ESIConfidence   # interval over the acuity; drives fail-closed
    findings: tuple[Finding, ...] = ()
    detections: tuple[Detection, ...] = ()
    esi_reasons: tuple[str, ...] = ()
    ruleset_version: str = ""


_COLOR = {
    Decision.ALLOW: "\033[92m",
    Decision.BLOCK: "\033[91m",
    Decision.ESCALATE: "\033[93m",
}
_RESET = "\033[0m"
_BOLD = "\033[1m"


def render(v: Verdict, color: bool = True) -> str:
    def c(s, code):
        return f"{code}{s}{_RESET}" if color else s

    lines = []
    banner = f" ATTENDING: {v.decision.value} "
    lines.append(c(f"{_BOLD}{banner}{_RESET}", _COLOR[v.decision]))
    lines.append(f"encounter: {v.encounter_id}   ruleset: {v.ruleset_version}")
    lines.append("")
    prop = "none" if v.proposed_esi is None else f"ESI {v.proposed_esi}"
    lines.append(f"  proposed acuity : {prop}")
    lines.append(f"  attending acuity: ESI {v.attending_esi}")
    lines.append(c(f"  recommended     : ESI {v.recommended_esi}  (fail-closed)",
                   _BOLD))
    ci = v.confidence
    lines.append(
        f"  confidence      : {ci.point_label}  "
        f"[{ci.most_acute}..{ci.least_acute}]  p={ci.p_point:.0%}  ({ci.basis})"
    )
    lines.append("")
    if v.esi_reasons:
        lines.append("  why this acuity:")
        for r in v.esi_reasons:
            lines.append(f"    - {r}")
        lines.append("")
    if v.detections:
        fired = [d for d in v.detections if d.fired]
        lines.append(f"  failure-mode detectors ({len(fired)} fired):")
        for d in v.detections:
            mark = "!!" if d.fired else "ok"
            tag = f"[{d.severity.value}]" if d.fired else ""
            lines.append(f"    {mark} {d.detector} {tag} {d.message if d.fired else ''}".rstrip())
            if d.fired and d.evidence:
                lines.append(f"         evidence: {d.evidence}")
        lines.append("")
    if v.findings:
        lines.append("  findings (why Attending acted):")
        for f in v.findings:
            cid = f" {f.criterion_id}" if f.criterion_id else ""
            lines.append(f"    [{f.severity.value}]{cid} {f.message}")
            if f.evidence:
                lines.append(f"         evidence: {f.evidence}")
            if f.citation:
                lines.append(f"         cite: {f.citation}")
        lines.append("")
    if v.decision is Decision.ALLOW:
        lines.append(c("  -> proposal is consistent with the ED triage safety "
                       "rubric.", _COLOR[Decision.ALLOW]))
    else:
        lines.append(c(f"  -> proposal blocked; safe action is ESI "
                       f"{v.recommended_esi}. Escalate to a human attending.",
                       _COLOR[v.decision]))
    return "\n".join(lines)
