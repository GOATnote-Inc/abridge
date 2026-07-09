"""Hallucination detector: numeric claims in the rationale not grounded in record.

Deterministic first pass: pull numeric vital claims out of the proposer's
free-text rationale (e.g. "SpO2 was 98%", "afebrile at 37.0") and check them
against the structured record. A value that contradicts the record -- or that
is asserted when the record never captured it -- is ungrounded and blocks the
claim. The `llm_augment` hook lets Fable 5 extend this to non-numeric factual
claims ("no cardiac history", "denies chest pain") checked against the chart.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..encounter import Encounter, ProposedTriage
from ..verdict import Detection, Severity

LlmGrounder = Callable[[Encounter, ProposedTriage], "tuple[bool, str, str]"]

# claim-keyword -> (vitals attr, tolerance). Tolerance guards rounding.
_NUMERIC_CLAIMS = {
    "spo2": ("spo2", 1), "o2 sat": ("spo2", 1), "sat": ("spo2", 1),
    "hr": ("hr", 2), "heart rate": ("hr", 2), "pulse": ("hr", 2),
    "rr": ("rr", 1), "respiratory rate": ("rr", 1),
    "sbp": ("sbp", 3), "systolic": ("sbp", 3),
    "temp": ("temp_c", 0.3), "temperature": ("temp_c", 0.3),
}


def _record_value(enc: Encounter, attr: str):
    val = getattr(enc.vitals, attr, None)
    if val is None:
        val = enc.structured_facts.get(attr)
    return val


def detect_hallucination(
    enc: Encounter,
    proposed: ProposedTriage,
    llm_augment: LlmGrounder | None = None,
) -> Detection:
    rationale = (proposed.rationale or "").lower()
    problems = []
    if rationale:
        for phrase, (attr, tol) in _NUMERIC_CLAIMS.items():
            # \b guards: without them "rr" matches inside "arrhythmia" and
            # "hr" inside "three", fabricating claims from innocent prose.
            for m in re.finditer(
                rf"\b{re.escape(phrase)}\b\D{{0,12}}?(\d{{1,3}}(?:\.\d)?)", rationale
            ):
                claimed = float(m.group(1))
                actual = _record_value(enc, attr)
                if actual is None:
                    problems.append(
                        f"claims {phrase}≈{m.group(1)} but record has no {attr}")
                elif abs(float(actual) - claimed) > tol:
                    problems.append(
                        f"claims {phrase}={m.group(1)} but record {attr}={actual}")

    if llm_augment is not None:
        try:
            lf, lmsg, lev = llm_augment(enc, proposed)
            if lf:
                return Detection("hallucination", True, Severity.BLOCK, lmsg,
                                 evidence=lev)
        except Exception:
            pass

    if not problems:
        return Detection("hallucination", False, Severity.INFO,
                         "numeric claims in rationale are grounded in the record")
    return Detection(
        "hallucination", True, Severity.BLOCK,
        "proposal rationale asserts values not grounded in the record",
        evidence="; ".join(problems),
    )
