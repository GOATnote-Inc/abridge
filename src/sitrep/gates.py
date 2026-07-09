"""Deterministic safety gates. One gate per failure mode in INVERSION.md.

These run OUTSIDE the model, on every candidate rendering, every turn.
A gate's behavior at turn 1000 is identical to turn 1 — safety persistence
lives in code, not in a prompt's goodwill (the LostBench thesis).

Severity tiers mirror a dual-layer safety-gated rubric:
  BLOCK -> the rendering must not ship.
  WARN  -> ships with annotation; surfaced to the physician review queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from sitrep.state import EncounterState

# Known staff audiences — the ONLY ones exempt from patient-pane gates.
# Anything else ("patient", "Patient", "caregiver", a typo, a novel pane)
# gets patient-facing protections: unknown audiences fail CLOSED.
STAFF_AUDIENCES = frozenset({"nurse", "physician", "consultant"})


def is_patient_facing(audience: str) -> bool:
    return str(audience).strip().lower() not in STAFF_AUDIENCES


class Severity(Enum):
    BLOCK = "block"
    WARN = "warn"


@dataclass
class Violation:
    gate: str
    severity: Severity
    detail: str
    detail_ref: str | None = None


@dataclass
class Rendering:
    audience: str            # patient | nurse | physician | consultant
    text: str
    refs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lexicons — physician-owned, versioned, reviewed 2026-07-09 (demo scope;
# see docs/reviews/), deliberately explicit.
# ---------------------------------------------------------------------------

INTERPRETATION_PHRASES = [
    "lose sleep over",
    "consistent with",
    "means you have",
    "suggests you have",
    "you probably have",
    "this looks like",
    "probably nothing",
    "nothing serious",
    "nothing to worry about",
    "you will be fine",
    "you'll be fine",
]

FALSE_REASSURANCE_PHRASES = [
    "labs are reassuring",
    "results are reassuring",
    "everything looks fine",
    "everything looks good",
    "everything looks normal",
    "everything is fine",
    "all your tests are normal",
    "all clear",
]

ADVICE_PATTERNS = [
    re.compile(
        r"\byou (?:should|must|need to) "
        r"(?:take|stop|start|skip|increase|decrease|double)\b", re.I),
    re.compile(r"\bstop taking\b", re.I),
    re.compile(r"\bdouble your dose\b", re.I),
    re.compile(r"\bincrease your (?:dose|medication)\b", re.I),
]

AI_DISCLOSURE_MARKERS = [
    "generated with ai",
    "generated using ai",
    "ai-generated",
    "created with ai",
]

HUMAN_PATH_MARKERS = [
    "call button",
    "ask your nurse",
    "speak with your nurse",
    "speak to your nurse",
    "member of your care team",
]

AVAILABILITY_MARKERS = [
    "result is available",
    "results are available",
    "new result",
    # Real-world acknowledgment phrasings (house rule: phrase + test together).
    "results are back",
    "result is back",
    "results have come back",
    "result has come back",
    "ready to view",
]

ESCALATION_ACK_MARKERS = [
    "care team has been notified",
    "care team was notified",
    "team has been alerted",
    "nurse has been alerted",
]

RED_FLAG_PHRASES = [
    "getting worse",
    "pain is worse",
    "can't breathe",
    "cannot breathe",
    "crushing",
    "want to die",
    "kill myself",
    "hurt myself",
    "worst headache",
    "face droop",
    "passing out",
]


def contains_red_flag(patient_msg: str) -> str | None:
    low = patient_msg.lower()
    for phrase in RED_FLAG_PHRASES:
        if phrase in low:
            return phrase
    return None


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gate_no_interpretation(r: Rendering, s: EncounterState) -> list[Violation]:
    """F1 + F8: no interpretation, no prognosis, no false reassurance (patient pane)."""
    if not is_patient_facing(r.audience):
        return []
    low = r.text.lower()
    out: list[Violation] = []
    for phrase in INTERPRETATION_PHRASES:
        if phrase in low:
            out.append(Violation(
                gate="no_interpretation", severity=Severity.BLOCK,
                detail=f"Interpretive/prognostic phrase in patient pane: '{phrase}'",
            ))
    has_critical = any(
        res.flag == "critical" and res.status in ("final", "amended")
        for res in s.results.values()
    )
    if has_critical:
        for phrase in FALSE_REASSURANCE_PHRASES:
            if phrase in low:
                out.append(Violation(
                    gate="no_interpretation", severity=Severity.BLOCK,
                    detail=f"False reassurance with critical result on chart: '{phrase}'",
                ))
    return out


def gate_info_blocking(r: Rendering, s: EncounterState) -> list[Violation]:
    """F2 — the anti-embargo gate. Every final, RELEASED result must be
    acknowledged as available in the patient pane. Suppression, not
    disclosure, is the violation (Cures Act information-blocking rule)."""
    if not is_patient_facing(r.audience):
        return []
    low = r.text.lower()
    out: list[Violation] = []
    for res in s.results.values():
        if res.status not in ("final", "amended") or not res.released:
            continue
        named = res.name.lower() in low
        generic = any(m in low for m in AVAILABILITY_MARKERS)
        if not (named or generic):
            out.append(Violation(
                gate="info_blocking", severity=Severity.BLOCK,
                detail=(
                    f"Final released result '{res.name}' not acknowledged in "
                    f"patient pane — suppression is information blocking."
                ),
                detail_ref=res.id,
            ))
    return out


def gate_no_advice(r: Rendering, s: EncounterState) -> list[Violation]:
    """F4: no directives / medical advice in the patient pane."""
    if not is_patient_facing(r.audience):
        return []
    out: list[Violation] = []
    for pat in ADVICE_PATTERNS:
        m = pat.search(r.text)
        if m:
            out.append(Violation(
                gate="no_advice", severity=Severity.BLOCK,
                detail=f"Directive medical advice in patient pane: '{m.group(0)}'",
            ))
    return out


def gate_compliance(r: Rendering, s: EncounterState) -> list[Violation]:
    """F5: AI disclosure + human contact path on every patient-facing rendering
    (CA AB 3030 pattern, applied everywhere by default)."""
    if not is_patient_facing(r.audience):
        return []
    low = r.text.lower()
    out: list[Violation] = []
    if not any(m in low for m in AI_DISCLOSURE_MARKERS):
        out.append(Violation(
            gate="compliance", severity=Severity.BLOCK,
            detail="Patient-facing rendering lacks AI-generation disclosure.",
        ))
    if not any(m in low for m in HUMAN_PATH_MARKERS):
        out.append(Violation(
            gate="compliance", severity=Severity.BLOCK,
            detail="Patient-facing rendering lacks a clear path to a human.",
        ))
    return out


def gate_grounding(r: Rendering, s: EncounterState) -> list[Violation]:
    """F7: Linked-Evidence mirror. Every ref must resolve to the chart, and
    every chart entity named in the text must carry a supporting ref."""
    out: list[Violation] = []
    known = s.known_ids()
    for ref in r.refs:
        if ref not in known:
            out.append(Violation(
                gate="grounding", severity=Severity.BLOCK,
                detail=f"Reference '{ref}' does not resolve to any chart element.",
                detail_ref=ref,
            ))
    low = r.text.lower()
    supplied = set(r.refs)
    for entity_id, name in s.entity_names().items():
        if name.lower() in low:
            acceptable = s.refs_for_name(name) | {entity_id}
            if not (supplied & acceptable):
                out.append(Violation(
                    gate="grounding", severity=Severity.BLOCK,
                    detail=f"Chart entity '{name}' mentioned without a supporting ref.",
                    detail_ref=entity_id,
                ))
                break  # one uncited-name violation is enough to block
    return out


def gate_escalation(r: Rendering, s: EncounterState) -> list[Violation]:
    """F6 (text half): once escalated, every patient-facing rendering must
    acknowledge that the care team was notified. Silence = dropped escalation."""
    if not is_patient_facing(r.audience) or not s.escalations:
        return []
    low = r.text.lower()
    if not any(m in low for m in ESCALATION_ACK_MARKERS):
        return [Violation(
            gate="escalation", severity=Severity.BLOCK,
            detail="Active escalation not acknowledged in patient-facing rendering.",
        )]
    return []


# -- readability (F9) --------------------------------------------------------

_VOWEL_GROUP = re.compile(r"[aeiouy]+", re.I)
_WORD = re.compile(r"[A-Za-z]+")
_SENTENCE_END = re.compile(r"[.!?]+")


def _syllables(word: str) -> int:
    groups = _VOWEL_GROUP.findall(word)
    count = max(1, len(groups))
    if word.lower().endswith("e") and not word.lower().endswith("le") and count > 1:
        count -= 1
    return count


def flesch_kincaid_grade(text: str) -> float:
    words = _WORD.findall(text)
    if not words:
        return 0.0
    sentences = max(1, len([s for s in _SENTENCE_END.split(text) if s.strip()]))
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * (len(words) / sentences) + 11.8 * (syllables / len(words)) - 15.59


def gate_readability(
    r: Rendering, s: EncounterState, grade_ceiling: float = 8.0
) -> list[Violation]:
    """F9: patient pane above ~8th-grade reading level -> WARN (ships, annotated)."""
    if not is_patient_facing(r.audience):
        return []
    grade = flesch_kincaid_grade(r.text)
    if grade > grade_ceiling:
        return [Violation(
            gate="readability", severity=Severity.WARN,
            detail=f"Patient pane reads at grade {grade:.1f} (ceiling {grade_ceiling}).",
        )]
    return []


# -- state-level gate ---------------------------------------------------------

def check_disclosure_gap(s: EncounterState) -> list[Violation]:
    """F3: critical result released AND viewed by the patient AND not yet
    discussed by a clinician. The Cures-era patient-safety hole: the patient
    is alone with a critical result. This must page the team."""
    out: list[Violation] = []
    for res in s.results.values():
        if (
            res.flag == "critical"
            and res.status in ("final", "amended")
            and res.released
            and res.viewed
            and not res.discussed
        ):
            out.append(Violation(
                gate="disclosure_gap", severity=Severity.BLOCK,
                detail=(
                    f"Patient has viewed critical result '{res.name}' with no "
                    f"documented discussion — alert the care team."
                ),
                detail_ref=res.id,
            ))
    return out


ALL_GATES = [
    gate_no_interpretation,
    gate_info_blocking,
    gate_no_advice,
    gate_compliance,
    gate_grounding,
    gate_escalation,
    gate_readability,
]


def run_gates(rendering: Rendering, state: EncounterState) -> list[Violation]:
    out: list[Violation] = []
    for gate in ALL_GATES:
        out.extend(gate(rendering, state))
    return out
