"""Seeded fuzz over the supervisor's safety invariants.

Not property-based-testing theater: a deterministic (seed=2026) sweep of ~300
randomized encounter/proposal pairs — adversarial mixes of red-flag text,
missing/implausible vitals, junk orders — asserting the invariants that define
fail-closed behavior. Catches crash-class and consistency-class regressions
that example-based tests miss.
"""

import random

from attending.encounter import Encounter, ProposedTriage, Vitals
from attending.supervisor import supervise
from attending.verdict import Decision, Severity

_COMPLAINTS = [
    "chest pressure radiating to left arm", "twisted ankle", "medication refill",
    "fever and confusion", "worst headache of my life", "vomiting blood",
    "suicidal, wants to die", "sudden facial droop", "abdominal pain and vomiting",
    "pregnant with pelvic pain", "cough", "", "chest pain and wants to die",
    "diabetic, vomiting, glucose 480", "back pain with saddle numbness",
]
_ORDERS = ["ecg", "troponin", "cbc", "bmp", "ct_head", "lactate", "blood_cultures",
           "antibiotics", "ankle_xray", "psych_eval", "1:1_observation",
           "stroke_activation", "epinephrine", "", "xyz_bogus_order"]
_DISPOS = ["discharge", "fast_track", "main_ed", "resus", None, "lobby", "WeIrD"]


def _maybe(rng, lo, hi, p_none=0.25, p_wild=0.1):
    r = rng.random()
    if r < p_none:
        return None
    if r < p_none + p_wild:
        return rng.choice([0, -5, 9999, 400])  # implausible / hostile
    return rng.randint(lo, hi)


def _case(rng):
    enc = Encounter(
        "FZ", rng.choice(_COMPLAINTS),
        age_years=rng.choice([None, 0.05, 2, 9, 24, 58, 91]),
        vitals=Vitals(
            hr=_maybe(rng, 40, 140), rr=_maybe(rng, 8, 40),
            spo2=_maybe(rng, 70, 100), sbp=_maybe(rng, 70, 220),
            pain=rng.choice([None, 0, 5, 7, 10]),
            gcs=rng.choice([None, 3, 9, 14, 15]),
        ),
        transcript=rng.choice([None, "some history [inaudible]", "clear story"]),
    )
    proposed = ProposedTriage(
        esi_level=rng.choice([None, 1, 2, 3, 4, 5]),
        orders=tuple(rng.sample(_ORDERS, rng.randint(0, 4))),
        disposition=rng.choice(_DISPOS),
        rationale=rng.choice([None, "stable", "denies chest pain",
                              "spo2 was 99", "concern for arrhythmia 150"]),
    )
    return enc, proposed


def test_supervisor_invariants_hold_under_fuzz():
    rng = random.Random(2026)
    for i in range(300):
        enc, proposed = _case(rng)
        v = supervise(enc, proposed)  # invariant 0: never raises

        assert v.decision in (Decision.ALLOW, Decision.BLOCK, Decision.ESCALATE)
        assert 1 <= v.recommended_esi <= 5
        assert 1 <= v.attending_esi <= 5
        # Fail-closed consistency: the decision is exactly what the findings say.
        has_block = any(f.severity is Severity.BLOCK for f in v.findings)
        has_esc = any(f.severity is Severity.ESCALATE for f in v.findings)
        if v.decision is Decision.ALLOW:
            assert not has_block and not has_esc, f"case {i}: ALLOW with stops"
        if v.decision is Decision.BLOCK:
            assert has_block, f"case {i}: BLOCK without a block finding"
        if v.decision is Decision.ESCALATE:
            assert has_esc and not has_block, f"case {i}: inconsistent ESCALATE"
        # Recommended acuity is never LESS acute than the safe assessment
        # when the proposal was blocked for under-triage.
        if any(f.kind == "under_triage" for f in v.findings):
            assert v.recommended_esi <= v.attending_esi
