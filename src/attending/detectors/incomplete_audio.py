"""Incomplete-audio detector: missing intake needed to clear a low acuity.

If we cannot see the data required to *rule out* a higher acuity, we cannot
safely assign a lower one. Missing danger-zone vitals or a truncated transcript
therefore push toward escalation rather than a confident low ESI.
Deterministic; no LLM needed.
"""

from __future__ import annotations

import re

from ..encounter import Encounter
from ..verdict import Detection, Severity

# Markers an ASR/scribe leaves when it drops audio.
_INAUDIBLE = [r"\[inaudible\]", r"\[unintelligible\]", r"\binaudible\b",
              r"\.\.\.$", r"\bcut off\b", r"<unk>"]
# Vitals required before a danger-zone (Decision D) call can be made.
_REQUIRED_VITALS = ("hr", "rr", "spo2", "sbp")


def detect_incomplete_audio(enc: Encounter) -> Detection:
    problems = []
    missing = [k for k in _REQUIRED_VITALS if getattr(enc.vitals, k) is None]
    if missing:
        problems.append("missing vitals: " + ", ".join(missing))
    if not enc.chief_complaint.strip():
        problems.append("no chief complaint captured")
    if enc.age_years is None:
        problems.append("age missing (danger-zone thresholds are age-based)")

    truncated = False
    if enc.transcript:
        for pat in _INAUDIBLE:
            if re.search(pat, enc.transcript.strip(), re.IGNORECASE):
                truncated = True
                problems.append(f"transcript gap marker: /{pat}/")
                break

    if not problems:
        return Detection("incomplete_audio", False, Severity.INFO,
                         "required intake fields are present")

    # Missing danger-zone vitals or truncation => can't clear a low acuity.
    sev = Severity.ESCALATE if (missing or truncated) else Severity.WARN
    return Detection(
        "incomplete_audio", True, sev,
        "intake is incomplete; a lower acuity cannot be safely cleared",
        evidence="; ".join(problems),
    )
