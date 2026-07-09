"""Input schema for an ED triage encounter under Attending supervision.

An Encounter is what arrives from the front door / ambient scribe. A
ProposedTriage is what the *proposing* clinical agent (e.g. HealthCraft's
TriageAgent) wants to do with it. Attending independently re-derives the
safe acuity, runs failure-mode detectors, and grades the proposal fail-closed.

All fields are Optional because real intake is incomplete -- and detecting
that incompleteness is itself a safety signal (see detectors.incomplete_audio).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Vitals:
    """A single vitals snapshot. None == not captured (not 'normal')."""

    hr: int | None = None        # heart rate, bpm
    rr: int | None = None        # respiratory rate, /min
    spo2: int | None = None      # oxygen saturation, %
    sbp: int | None = None       # systolic BP, mmHg
    dbp: int | None = None       # diastolic BP, mmHg
    temp_c: float | None = None  # temperature, Celsius
    pain: int | None = None      # 0-10
    gcs: int | None = None       # Glasgow Coma Scale, 3-15

    def present(self) -> dict[str, float]:
        """Vitals that were actually captured."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class Encounter:
    encounter_id: str
    chief_complaint: str
    age_years: float | None = None
    sex: str | None = None
    vitals: Vitals = field(default_factory=Vitals)
    transcript: str | None = None          # ambient/scribe transcript, may be partial
    history: str | None = None
    arrival_mode: str | None = None        # "ambulance" | "walk_in"
    # Ground-truth structured record used to catch hallucinations: any claim in
    # the proposer's rationale that contradicts or is absent here is ungrounded.
    structured_facts: dict = field(default_factory=dict)

    @property
    def text_blob(self) -> str:
        """All free text a red-flag rule might match against."""
        return " ".join(
            p for p in (self.chief_complaint, self.transcript, self.history) if p
        ).lower()


@dataclass(frozen=True)
class ProposedTriage:
    """What the proposing clinical agent wants to do -- the thing under review."""

    esi_level: int | None = None           # 1 (most acute) .. 5 (least)
    orders: tuple[str, ...] = ()           # e.g. ("ecg", "troponin", "cxr")
    disposition: str | None = None         # "resus"|"main_ed"|"fast_track"|"discharge"
    rationale: str | None = None

    @property
    def orders_lower(self) -> tuple[str, ...]:
        return tuple(o.lower() for o in self.orders)


def encounter_from_dict(d: dict) -> Encounter:
    v = d.get("vitals", {}) or {}
    return Encounter(
        encounter_id=str(d.get("encounter_id", "unknown")),
        chief_complaint=d.get("chief_complaint", ""),
        age_years=d.get("age_years"),
        sex=d.get("sex"),
        vitals=Vitals(**{k: v[k] for k in v if k in Vitals.__dataclass_fields__}),
        transcript=d.get("transcript"),
        history=d.get("history"),
        arrival_mode=d.get("arrival_mode"),
        structured_facts=d.get("structured_facts", {}) or {},
    )


def proposed_from_dict(d: dict | None) -> ProposedTriage:
    if not d:
        return ProposedTriage()
    return ProposedTriage(
        esi_level=d.get("esi_level"),
        orders=tuple(d.get("orders", []) or ()),
        disposition=d.get("disposition"),
        rationale=d.get("rationale"),
    )
