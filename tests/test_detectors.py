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


def test_denying_the_presenting_red_flag_fires_without_llm():
    # Codex P1 example: "denies chest pain" on a chest-pressure record must be
    # caught by the DETERMINISTIC floor (no key, no augmentation).
    enc = Encounter("T", "chest pressure radiating to left arm", age_years=58,
                    vitals=Vitals(hr=96, rr=18, spo2=97, sbp=148))
    d = detect_hallucination(
        enc, ProposedTriage(esi_level=4, rationale="patient denies chest pain today"))
    assert d.fired and "denies a finding" in d.evidence


def test_legitimate_course_note_is_not_a_contradiction():
    enc = Encounter("T", "chest pressure radiating to left arm", age_years=58,
                    vitals=Vitals(hr=96, rr=18, spo2=97, sbp=148))
    d = detect_hallucination(
        enc, ProposedTriage(esi_level=2, orders=("ecg", "troponin"),
                            rationale="no further chest pain since arrival, monitoring"))
    assert not d.fired


def test_denial_without_record_assertion_is_fine():
    enc = Encounter("T", "twisted ankle", age_years=24,
                    vitals=Vitals(hr=80, rr=16, spo2=99, sbp=120))
    d = detect_hallucination(
        enc, ProposedTriage(esi_level=4, rationale="denies chest pain, denies fever"))
    assert not d.fired
