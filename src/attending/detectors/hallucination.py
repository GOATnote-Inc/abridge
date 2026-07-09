"""Hallucination detector: rationale claims not grounded in the record.

Deterministic floor, two checks (no LLM, no key):
  1. NUMERIC claims — vital values asserted in the rationale ("SpO2 was 98%")
     that contradict the record or were never captured.
  2. NEGATION CONTRADICTIONS — the rationale explicitly denies a finding the
     record asserts ("denies chest pain" when the chief complaint is chest
     pressure). Detected by running the SAME red-flag patterns that fired on
     the encounter over negated spans of the rationale.

The `llm_augment` hook lets Fable 5 extend this floor to broader semantic
grounding ("no cardiac history" vs. the medication list). Augmentation is
ADDITIVE-ONLY: it can raise a finding, never suppress one, and its failure
leaves the deterministic floor untouched.
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


# Strong denial cues only ("no further chest pain" is a legitimate clinical
# course note, not a record contradiction — precision matters here).
_NEGATION_CUES = re.compile(
    r"\b(?:denies|denied|no history of|no complaints? of|without any)\b", re.I)
_NEGATION_WINDOW = 60  # chars of rationale examined after a denial cue


def _negation_contradictions(enc: Encounter, rationale: str) -> list[str]:
    """Rationale spans that DENY a finding the record asserts.

    For every red flag that fired on the encounter, re-run its patterns over
    the text right after each denial cue in the rationale. A hit means the
    proposer is denying the very finding that made this patient high-risk.
    """
    from ..esi import match_red_flags  # local import; no cycle (esi <- knowledge)

    fired = match_red_flags(enc)
    if not fired:
        return []
    spans = [rationale[m.end():m.end() + _NEGATION_WINDOW]
             for m in _NEGATION_CUES.finditer(rationale)]
    if not spans:
        return []
    from .. import knowledge as K
    problems = []
    by_id = {rf["id"]: rf["patterns"] for rf in K.RED_FLAGS}
    for hit in fired:
        for span in spans:
            if any(re.search(pat, span) for pat in by_id.get(hit.id, ())):
                problems.append(
                    f"rationale denies a finding the record asserts "
                    f"({hit.id}: record matched '{hit.matched}')")
                break
    return problems


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

    if rationale:
        problems.extend(_negation_contradictions(enc, rationale))

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
