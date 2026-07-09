"""Detector unit tests — word-boundary hygiene on the hallucination claims."""

from attending.detectors.hallucination import detect_hallucination
from attending.encounter import Encounter, ProposedTriage, Vitals


def _enc(**v):
    return Encounter("T", "palpitations", age_years=50, vitals=Vitals(**v))


def test_rr_inside_arrhythmia_is_not_a_claim():
    # "rr" must not match inside "arrhythmia" ("...arrhythmia, recheck in 150...")
    d = detect_hallucination(
        _enc(hr=80, rr=18, spo2=98, sbp=120),
        ProposedTriage(esi_level=2, rationale="concern for arrhythmia, recheck in 150 minutes"),
    )
    assert not d.fired


def test_hr_inside_three_is_not_a_claim():
    d = detect_hallucination(
        _enc(hr=80, rr=18, spo2=98, sbp=120),
        ProposedTriage(esi_level=3, rationale="pain for three 20-minute episodes today"),
    )
    assert not d.fired


def test_real_ungrounded_claim_still_fires():
    d = detect_hallucination(
        _enc(hr=80, rr=18, spo2=97, sbp=120),
        ProposedTriage(esi_level=4, rationale="reassuring, spo2 was 99"),
    )
    assert d.fired
