"""Anchoring-bias detector.

Anchoring = the proposer fixates on the first / dominant complaint and discounts
a red flag mentioned later in the encounter. Deterministic proxy: a red flag
fired, but the proposal's acuity and orders don't reflect it (low ESI, none of
the flag's required workup ordered). The `llm_augment` hook lets a Fable 5 pass
re-read the transcript independently to catch subtler anchoring the proxy misses.
"""

from __future__ import annotations

from collections.abc import Callable

from ..encounter import Encounter, ProposedTriage
from ..esi import EsiAssessment
from ..verdict import Detection, Severity

# Optional LLM re-reader: (encounter, proposed) -> (fired, message, evidence).
LlmReReader = Callable[[Encounter, ProposedTriage], "tuple[bool, str, str]"]


def detect_anchoring(
    enc: Encounter,
    proposed: ProposedTriage,
    assessment: EsiAssessment,
    llm_augment: LlmReReader | None = None,
) -> Detection:
    unaddressed = []
    orders = set(proposed.orders_lower)
    for rf in assessment.red_flags:
        required = {o.lower() for o in rf.requires_orders}
        if not (orders & required):
            unaddressed.append(f"{rf.id} ({rf.label}) fired but no {sorted(required)} ordered")

    proposer_low = proposed.esi_level is not None and proposed.esi_level >= 3
    fired = bool(unaddressed) and proposer_low

    if llm_augment is not None:
        try:
            lf, lmsg, lev = llm_augment(enc, proposed)
            if lf:
                return Detection("anchoring_bias", True, Severity.BLOCK,
                                 lmsg, evidence=lev)
        except Exception:
            pass  # LLM augmentation is best-effort; deterministic floor stands.

    if not fired:
        return Detection("anchoring_bias", False, Severity.INFO,
                         "no unaddressed red flag inconsistent with the proposal")
    return Detection(
        "anchoring_bias", True, Severity.BLOCK,
        "proposal appears anchored on the presenting complaint; a red flag is "
        "unaddressed at a low acuity",
        evidence="; ".join(unaddressed),
    )
