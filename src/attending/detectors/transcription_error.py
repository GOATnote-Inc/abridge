"""Transcription-error detector: physiologically implausible captured values.

Ambient scribes and manual entry mis-key vitals ("98.6" -> "986", "12/80"
systolic, SpO2 "220"). A value outside the survivable physiologic envelope is
almost certainly a capture error -- and if that value would drive triage, we
must not trust it. Deterministic; no LLM needed.
"""

from __future__ import annotations

from ..encounter import Encounter
from ..verdict import Detection, Severity

# (attr, human, hard_min, hard_max, unit). Outside [hard_min, hard_max] is
# considered incompatible with a talking ED patient -> capture error.
_PLAUSIBLE = [
    ("hr", "HR", 20, 300, "bpm"),
    ("rr", "RR", 3, 80, "/min"),
    ("spo2", "SpO2", 40, 100, "%"),
    ("sbp", "SBP", 40, 300, "mmHg"),
    ("dbp", "DBP", 15, 200, "mmHg"),
    ("temp_c", "Temp", 30.0, 44.0, "C"),
    ("gcs", "GCS", 3, 15, ""),
    ("pain", "Pain", 0, 10, "/10"),
]


def detect_transcription_error(enc: Encounter) -> Detection:
    problems = []
    v = enc.vitals
    for attr, name, lo, hi, unit in _PLAUSIBLE:
        val = getattr(v, attr)
        if val is None:
            continue
        if val < lo or val > hi:
            problems.append(f"{name}={val}{unit} outside plausible [{lo},{hi}]")

    # Unit-confusion heuristic: temp recorded in F but stored as C field.
    if v.temp_c is not None and 95.0 <= v.temp_c <= 108.0:
        problems.append(
            f"Temp={v.temp_c} looks like Fahrenheit stored as Celsius "
            f"(≈{(v.temp_c - 32) * 5 / 9:.1f}C)"
        )
    # SBP/DBP swapped.
    if v.sbp is not None and v.dbp is not None and v.dbp >= v.sbp:
        problems.append(f"DBP {v.dbp} >= SBP {v.sbp} (values may be swapped)")

    if not problems:
        return Detection("transcription_error", False, Severity.INFO,
                         "captured vitals are physiologically plausible")
    return Detection(
        "transcription_error", True, Severity.ESCALATE,
        f"{len(problems)} implausible value(s); a vital driving triage may be "
        f"a capture error",
        evidence="; ".join(problems),
    )
