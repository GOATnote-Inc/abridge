"""Deterministic ESI v4 acuity assignment -- Attending's independent opinion.

This re-derives triage acuity straight from the ESI v4 decision tree
(A -> B -> C -> D). It is program-aided: no LLM in this path, so it is
reproducible and auditable. The proposing agent's acuity is graded against
*this*; when they disagree in the unsafe direction (proposer less acute),
Attending blocks.

Implausible-vitals quarantine: a captured vital outside the physiologic
envelope (knowledge.VITAL_PLAUSIBLE_RANGES, same bounds as the
transcription_error detector) is almost certainly a capture error. Such a
value is EXCLUDED from the life-saving / danger-zone / altered / pain
computations, so a mis-keyed HR of 400 cannot FABRICATE an ESI 1 the patient
hasn't earned. The quarantined vitals are surfaced on the assessment; the
transcription_error detector still fires ESCALATE on them, so the net
behavior is "escalate for re-measurement", never "trust the impossible value".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from . import knowledge as K
from .encounter import Encounter, Vitals


@dataclass(frozen=True)
class RedFlagHit:
    id: str
    label: str
    esi_floor: int
    # Conjunction of disjunction-groups: every group must be satisfied by at
    # least one of its member order names (see knowledge.normalize_requires).
    requires_orders: tuple[tuple[str, ...], ...]
    citation: str
    rationale: str
    matched: str  # the phrase that triggered it


@dataclass(frozen=True)
class EsiAssessment:
    level: int                          # 1..5, Attending's independent acuity
    decision_point: str                 # "A" | "B" | "C"
    reasons: tuple[str, ...] = ()       # human-readable drivers
    red_flags: tuple[RedFlagHit, ...] = ()
    resource_estimate: tuple[int, int] | None = None  # (min, max) if Decision C
    danger_zone: tuple[str, ...] = ()   # danger-zone vitals that fired
    ruleset_version: str = K.RULESET_VERSION
    # Captured vitals excluded from this assessment as physiologically
    # implausible (probable capture errors). Empty when all vitals plausible.
    quarantined_vitals: tuple[str, ...] = ()


def quarantine_implausible_vitals(
    v: Vitals,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(attrs, human-readable notes) for captured vitals outside the
    physiologic envelope. Bounds are shared with the transcription_error
    detector via knowledge.VITAL_PLAUSIBLE_RANGES."""
    attrs: list[str] = []
    notes: list[str] = []
    for attr, (lo, hi, unit) in K.VITAL_PLAUSIBLE_RANGES.items():
        val = getattr(v, attr, None)
        if val is None:
            continue
        if val < lo or val > hi:
            attrs.append(attr)
            notes.append(
                f"Quarantined implausible {attr}={val}{unit} (outside "
                f"[{lo},{hi}]): excluded from acuity computation as a "
                f"probable capture error; re-measure before trusting it"
            )
    return tuple(attrs), tuple(notes)


def _danger_zone(v: Vitals, age: float | None) -> list[str]:
    # Peds bands carry extra str metadata (label/citation); only the numeric
    # hr_gt / rr_gt / spo2_lt keys are read here.
    thresh: dict[str, Any] = K.DANGER_ZONE_ADULT
    if age is not None:
        for age_max in sorted(K.DANGER_ZONE_PEDS):
            if age <= age_max:
                thresh = K.DANGER_ZONE_PEDS[age_max]
                break
    hits = []
    if v.hr is not None and v.hr > thresh["hr_gt"]:
        hits.append(f"HR {v.hr} > {thresh['hr_gt']}")
    if v.rr is not None and v.rr > thresh["rr_gt"]:
        hits.append(f"RR {v.rr} > {thresh['rr_gt']}")
    if v.spo2 is not None and v.spo2 < thresh["spo2_lt"]:
        hits.append(f"SpO2 {v.spo2} < {thresh['spo2_lt']}")
    return hits


def _life_saving(enc: Encounter) -> list[str]:
    v, hits = enc.vitals, []
    if v.gcs is not None and v.gcs <= 8:
        hits.append(K.LIFE_SAVING_VITALS["gcs_le_8"][0])
    if v.spo2 is not None and v.spo2 < 90:
        hits.append(K.LIFE_SAVING_VITALS["spo2_lt_90"][0])
    if v.rr is not None and v.rr >= 40:
        hits.append(K.LIFE_SAVING_VITALS["rr_ge_40"][0])
    if v.rr is not None and v.rr <= 8:
        hits.append(K.LIFE_SAVING_VITALS["rr_le_8"][0])
    if v.sbp is not None and v.sbp < 80:
        hits.append(K.LIFE_SAVING_VITALS["sbp_lt_80"][0])
    if v.hr is not None and v.hr >= 150:
        hits.append(K.LIFE_SAVING_VITALS["hr_ge_150"][0])
    blob = enc.text_blob
    for phrase in K.LIFE_SAVING_PHRASES:
        if phrase in blob:
            hits.append(f'"{phrase}" noted')
    return hits


def match_red_flags(enc: Encounter) -> list[RedFlagHit]:
    blob = enc.text_blob
    hits = []
    for rf in K.RED_FLAGS:
        for pat in rf["patterns"]:
            m = re.search(pat, blob)
            if m:
                hits.append(
                    RedFlagHit(
                        id=rf["id"],
                        label=rf["label"],
                        esi_floor=rf["esi_floor"],
                        requires_orders=K.normalize_requires(rf["requires_orders"]),
                        citation=rf["citation"],
                        rationale=rf["rationale"],
                        matched=m.group(0),
                    )
                )
                break
    return hits


def _altered(enc: Encounter) -> str | None:
    if enc.vitals.gcs is not None and 8 < enc.vitals.gcs < 15:
        return f"GCS {enc.vitals.gcs} (acute alteration)"
    blob = enc.text_blob
    for p in K.ALTERED_PHRASES:
        if p in blob:
            return f'"{p}" noted'
    return None


def estimate_resources(enc: Encounter) -> tuple[int, int]:
    blob = enc.text_blob
    for keywords, lo, hi in K.RESOURCE_ESTIMATES:
        if any(kw in blob for kw in keywords):
            return (lo, hi)
    return K.RESOURCE_DEFAULT


def resources_to_level(n: int) -> int:
    if n <= 0:
        return 5
    if n == 1:
        return 4
    return 3


def compute_esi(enc: Encounter) -> EsiAssessment:
    """Walk the ESI v4 tree. Returns Attending's independent acuity."""
    # Quarantine physiologically implausible captured vitals FIRST so a
    # capture error can never fabricate a life-saving / danger-zone finding.
    # The transcription_error detector (run by the supervisor) still fires
    # ESCALATE on the raw values, so quarantine == "re-measure", not "ignore".
    quarantined, q_notes = quarantine_implausible_vitals(enc.vitals)
    if quarantined:
        enc = replace(
            enc, vitals=replace(enc.vitals, **{a: None for a in quarantined})
        )

    # Decision A: immediate life-saving intervention?
    lsi = _life_saving(enc)
    if lsi:
        return EsiAssessment(
            1, "A", reasons=tuple(lsi) + q_notes,
            quarantined_vitals=quarantined,
        )

    # Decision B: high-risk red flag, altered mental status, severe pain, or
    # danger-zone vitals -> should-not-wait -> ESI 2.
    reasons: list[str] = []
    red = match_red_flags(enc)
    reasons.extend(f"{h.id}: {h.label} (matched '{h.matched}')" for h in red)
    alt = _altered(enc)
    if alt:
        reasons.append(f"Altered mental status: {alt}")
    if enc.vitals.pain is not None and enc.vitals.pain >= 7:
        reasons.append(f"Severe pain {enc.vitals.pain}/10")
    dz = _danger_zone(enc.vitals, enc.age_years)
    if dz:
        reasons.append("Danger-zone vitals: " + ", ".join(dz))
    if reasons:
        # Honor a more-acute red-flag floor if one is ever defined (all
        # current flags floor at 2; airway/hemodynamic collapse reaches
        # ESI 1 through Decision A vitals/phrases).
        level = min([2] + [h.esi_floor for h in red])
        return EsiAssessment(
            level, "B", reasons=tuple(reasons) + q_notes,
            red_flags=tuple(red), danger_zone=tuple(dz),
            quarantined_vitals=quarantined,
        )

    # Decision C: resource count.
    lo, hi = estimate_resources(enc)
    mid = round((lo + hi) / 2)
    level = resources_to_level(mid)
    return EsiAssessment(
        level, "C",
        reasons=(f"Estimated {lo}-{hi} resources -> ESI {level}",) + q_notes,
        resource_estimate=(lo, hi),
        quarantined_vitals=quarantined,
    )
