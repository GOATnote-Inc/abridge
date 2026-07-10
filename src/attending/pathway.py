"""Deterministic journey engine — the patient's next-step panel.

Pure function of chart state: no LLM, no clock, no network. Every clinical
string below is a fixed template whose content and timing come from the cited
guideline — nothing is authored from memory (see docs/JOURNEY.md and the
2026-07-10 research pass).

Regulatory posture, deliberately encoded:
- California HSC §1339.75 (AB 3030) triggers on communications that
  generative AI *generates*. This panel is deterministic templates populated
  with chart data, so the statute is not triggered — the AI-noted label is
  carried anyway (AMA HOD policy, Nov 2024: AI-generated patient content
  "disclosed or otherwise noted within the content") plus the §1339.75(a)(2)
  human-contact instructions, so the same panel remains compliant if a
  deployment ever swaps genAI in (or uses the §1339.75(b) provider-review
  exemption, operationalized by the reviewed_by field).
- FDA CDS guidance (Jan 6, 2026, unchanged from 2022 on this point):
  patient-facing *recommendations* are a device. The panel therefore only
  (a) DISPLAYS the care team's ordered plan and its status, and (b) states
  what "published guidelines commonly recommend" with attribution —
  informing, never interpreting, scoring, or directing (21 U.S.C.
  §360j(o)(1)(C)/(D) display / general-information lanes).
"""

from __future__ import annotations

from dataclasses import dataclass

from sitrep.state import EncounterState

# --- Citations (full strings; each step names its source and vintage) --------

CITE_ECG_10MIN = ("2021 AHA/ACC Chest Pain Guideline §2.3.1 (Class 1): ECG "
                  "acquired and reviewed within 10 minutes of arrival")
CITE_TROP_SERIAL = ("2021 AHA/ACC Chest Pain Guideline §4.1 (Class 1): repeat "
                    "troponin 1-3 h after the first sample (high-sensitivity "
                    "assay) or 3-6 h (conventional assay)")
CITE_LOCAL_PROTOCOL = ("2021 AHA/ACC Chest Pain Guideline §4.1 (Class 1): "
                       "institutions implement a clinical decision pathway "
                       "with troponin sampling per their assay")
CITE_SERIAL_ECG = ("2021 AHA/ACC Chest Pain Guideline §2.3.2 (Class 1): serial "
                   "ECGs when the initial ECG is nondiagnostic")
CITE_MONITORING = ("2023 ESC ACS Guidelines (Class I): continuous ECG "
                   "monitoring in suspected ACS")
CITE_DISPO = ("HEART Pathway (Mahler 2015) and 2021 AHA/ACC §4.1: elevated "
              "troponin — cardiology consultation and admission or "
              "observation are commonly recommended")
CITE_TRIAGE = "ESI v4 (AHRQ/ENA) — nursing triage per hospital protocol"

# Repeat-troponin display interval by assay (AHA/ACC 2021 §4.1, Class 1).
TROPONIN_INTERVAL = {
    "high_sensitivity": "1-3 hours after the first blood draw",
    "conventional": "3-6 hours after the first blood draw",
}

# --- Required panel labels (research: SAFE TEMPLATE ELEMENTS 1-5) -----------

PANEL_LABELS = (
    "This panel is generated automatically. It is general information, "
    "not medical advice. Your care team makes all decisions about your "
    "care. To reach a person, press your call button or ask any staff "
    "member. If you feel worse, tell your nurse right away."
)


@dataclass(frozen=True)
class JourneyStep:
    id: str
    label: str
    status: str            # "done" | "active" | "expected"
    detail: str = ""
    window: str | None = None
    citation: str | None = None


@dataclass(frozen=True)
class DelayEvent:
    what: str
    why: str
    revised_estimate: str | None = None


@dataclass(frozen=True)
class Journey:
    steps: tuple[JourneyStep, ...]
    delays: tuple[DelayEvent, ...]
    next_box: str           # patient-facing "the next step is..." text
    nurse_note: str         # same panel, clinical shorthand for the RN
    labels: str = PANEL_LABELS
    reviewed_by: str | None = None   # operationalizes HSC §1339.75(b) review

    @property
    def patient_text(self) -> str:
        """The full patient-facing rendering (next-box + required labels)."""
        return f"{self.next_box} {self.labels}"


def _has_order(state: EncounterState, name: str) -> bool:
    return any(o.name.lower() == name for o in state.orders.values())


def _result(state: EncounterState, name: str):
    for r in state.results.values():
        if r.name.lower() == name and r.status in ("final", "amended"):
            return r
    return None


def chest_pain_journey(
    state: EncounterState,
    *,
    assay: str = "high_sensitivity",
    delays: tuple[DelayEvent, ...] = (),
) -> Journey:
    """The chest-pain (possible ACS) journey, derived from the chart.

    Display + attributed general information only. The "next step" box always
    has content: before a result it says what is being waited on and the
    guideline window; after an elevated result it states what published
    pathways commonly recommend and that the care team decides the plan.
    """
    interval = TROPONIN_INTERVAL.get(assay, TROPONIN_INTERVAL["high_sensitivity"])
    ecg_done = _has_order(state, "ecg")
    trop_ordered = _has_order(state, "troponin")
    trop = _result(state, "troponin")

    steps = [
        JourneyStep("arrived", "Arrived and registered", "done"),
        JourneyStep("triage", "Triage by your nurse", "done",
                    detail="Acuity assigned by the triage nurse under the "
                           "hospital's protocol.",
                    citation=CITE_TRIAGE),
        JourneyStep("ecg", "ECG (heart tracing)",
                    "done" if ecg_done else "expected",
                    window="within 10 minutes of arrival",
                    citation=CITE_ECG_10MIN),
        JourneyStep("troponin_1", "First troponin blood test",
                    "done" if trop and trop.released else
                    ("active" if trop_ordered else "expected"),
                    detail="A blood test your care team uses to check the heart."),
    ]

    if trop is None:
        steps.append(JourneyStep(
            "troponin_result", "Troponin result", "active",
            detail="Results appear here the moment the laboratory finalizes "
                   "them.",
        ))
        steps.append(JourneyStep(
            "troponin_repeat", "Repeat troponin", "expected",
            window=f"typically {interval}, per your hospital's protocol",
            citation=CITE_TROP_SERIAL,
        ))
        next_box = (
            "The next step is: your troponin result. You are on a heart "
            "monitor while you wait. Published guidelines commonly include "
            f"a repeat troponin, typically {interval}. Your hospital's "
            "protocol sets the exact time."
        )
        nurse_note = (f"Chest-pain pathway. Awaiting troponin #1; repeat due "
                      f"{interval} ({'hs' if assay == 'high_sensitivity' else 'conventional'} "
                      f"assay). ECG {'done' if ecg_done else 'PENDING — 10-min window'}.")
    else:
        critical = trop.flag == "critical"
        steps.append(JourneyStep(
            "troponin_result", f"Troponin result: {trop.value} ng/mL", "done",
            detail="Your care team has been notified.",
        ))
        if critical:
            steps.append(JourneyStep(
                "next_steps", "Clinician discussion and continued care", "active",
                detail="A clinician will talk with you about this result.",
                citation=CITE_DISPO,
            ))
            next_box = (
                "Your care team has been notified about this result. A "
                "clinician will talk with you about it. For results like "
                "this, published guidelines commonly recommend: staying on "
                "the heart monitor, repeat ECG tracings, a repeat troponin "
                "blood test, and a visit from the heart team. Many patients "
                "are admitted or observed. Your team decides your actual "
                "plan and will explain it to you."
            )
            nurse_note = ("Troponin CRITICAL " + trop.value + " — pt-visible via "
                          "portal. Gate paged MD for bedside discussion. "
                          "Commonly recommended per HEART/AHA-ACC/ESC: continuous "
                          "monitoring, serial ECG + troponin, cards consult, "
                          "admit/obs. Confirm plan documented.")
        else:
            steps.append(JourneyStep(
                "troponin_repeat", "Repeat troponin", "expected",
                window=f"typically {interval}, per your hospital's protocol",
                citation=CITE_TROP_SERIAL,
            ))
            next_box = (
                "The next step is: a repeat troponin blood test, typically "
                f"{interval}, per your hospital's protocol. You stay on the "
                "monitor between tests."
            )
            nurse_note = (f"Troponin #1 resulted ({trop.value}). Repeat due "
                          f"{interval}. Continue monitoring.")

    if delays:
        d = delays[-1]
        next_box += (
            f" One update on timing: your {d.what} is delayed — {d.why}. "
            "You have not been forgotten."
            + (f" Current estimate: {d.revised_estimate}." if d.revised_estimate else "")
        )
        nurse_note += f" DELAY: {d.what} — {d.why}."

    return Journey(tuple(steps), tuple(delays), next_box, nurse_note)


def journey_to_dict(j: Journey) -> dict:
    return {
        "steps": [s.__dict__ for s in j.steps],
        "delays": [d.__dict__ for d in j.delays],
        "next_box": j.next_box,
        "nurse_note": j.nurse_note,
        "labels": j.labels,
        "patient_text": j.patient_text,
        "reviewed_by": j.reviewed_by,
    }
