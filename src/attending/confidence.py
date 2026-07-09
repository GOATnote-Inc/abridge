"""Confidence interval over the assigned ESI level.

Brandon's requirement: triage should be "confidence interval driven". The ESI
tree has two very different kinds of certainty:

  * Decision A/B (life-saving vitals, danger-zone vitals, matched red flag) are
    hard, near-certain floors -> tight interval.
  * Decision C (resource count estimated from the complaint) is genuinely
    uncertain -> the interval spans the levels implied by the resource range.

Detectors that degrade the input (incomplete audio, transcription error) widen
the interval by one level toward *more* acute. The supervisor then acts on the
most-acute end of the interval -- the interval is the mechanism of fail-closed.

Note: "most_acute" is the numerically smallest ESI (1 = sickest).
"""

from __future__ import annotations

from dataclasses import dataclass

from .esi import EsiAssessment, resources_to_level


@dataclass(frozen=True)
class ESIConfidence:
    point: int              # most likely ESI
    most_acute: int         # lower ESI number reachable within uncertainty
    least_acute: int        # higher ESI number reachable
    p_point: float          # rough probability mass on the point estimate
    basis: str

    @property
    def point_label(self) -> str:
        return f"ESI {self.point}"

    @property
    def width(self) -> int:
        return self.least_acute - self.most_acute


def confidence_interval(
    a: EsiAssessment, *, widen_to_more_acute: int = 0
) -> ESIConfidence:
    """Build the interval, optionally widening `widen_to_more_acute` levels."""
    if a.decision_point in ("A", "B"):
        # A hard floor is already the conservative answer; do NOT widen it below
        # itself on input-quality degradation. The detector escalates on its own
        # severity instead of manufacturing a more-acute level.
        point = a.level
        basis = f"deterministic acuity floor (Decision {a.decision_point})"
        return ESIConfidence(point, point, point, p_point=0.9, basis=basis)

    # Decision C: interval from the resource-count range.
    lo, hi = a.resource_estimate or (1, 2)
    levels = sorted({resources_to_level(lo), resources_to_level(hi),
                     resources_to_level(round((lo + hi) / 2))})
    most_acute, least_acute = levels[0], levels[-1]
    point = a.level
    # Detector-driven widening: push the acute end down, never up.
    if widen_to_more_acute:
        most_acute = max(1, most_acute - widen_to_more_acute)
    span = least_acute - most_acute
    p_point = 0.8 if span == 0 else (0.55 if span == 1 else 0.4)
    basis = f"resource estimate {lo}-{hi} (Decision C)"
    if widen_to_more_acute:
        basis += f"; widened {widen_to_more_acute} level(s) by input-quality detectors"
    return ESIConfidence(point, most_acute, least_acute, p_point, basis)
