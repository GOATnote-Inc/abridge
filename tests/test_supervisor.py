"""Behavioral tests for the fail-closed supervisor and ESI spine."""

from attending.encounter import Encounter, ProposedTriage, Vitals
from attending.esi import compute_esi
from attending.supervisor import supervise
from attending.verdict import Decision


def enc(cc, proposed_esi=None, **vitals):
    v = Vitals(**{k: vitals[k] for k in vitals if k in Vitals.__dataclass_fields__})
    return Encounter(encounter_id="T", chief_complaint=cc,
                     age_years=vitals.get("age_years", 40), vitals=v)


# --- ESI spine ---

def test_life_saving_is_esi1():
    a = compute_esi(enc("found unresponsive", spo2=85, gcs=6))
    assert a.level == 1 and a.decision_point == "A"


def test_chest_pain_is_high_risk_esi2():
    a = compute_esi(enc("chest pain radiating to left arm"))
    assert a.level == 2
    assert any(rf.id == "RF-ACS" for rf in a.red_flags)


def test_danger_zone_vitals_up_triage_to_2():
    a = compute_esi(enc("cough", hr=118, rr=24, spo2=90))
    assert a.level == 2 and a.danger_zone


def test_ankle_is_esi4():
    a = compute_esi(enc("twisted ankle, needs xray"))
    assert a.level == 4


def test_med_refill_is_esi5():
    a = compute_esi(enc("medication refill"))
    assert a.level == 5


# --- Fail-closed supervisor ---

def test_under_triage_is_blocked():
    e = Encounter("T", "chest pain radiating to left arm", age_years=60,
                  vitals=Vitals(hr=90, rr=16, spo2=98, sbp=140))
    v = supervise(e, ProposedTriage(esi_level=3, orders=("cbc",),
                                    disposition="fast_track"))
    assert v.decision is Decision.BLOCK
    assert v.recommended_esi == 2
    assert any(f.kind == "under_triage" for f in v.findings)


def test_correct_triage_is_allowed():
    e = Encounter("T", "twisted ankle, needs xray", age_years=24,
                  vitals=Vitals(hr=80, rr=16, spo2=99, sbp=120))
    v = supervise(e, ProposedTriage(esi_level=4, orders=("ankle_xray",),
                                    disposition="fast_track"))
    assert v.decision is Decision.ALLOW


def test_no_proposal_escalates():
    e = Encounter("T", "twisted ankle", age_years=24,
                  vitals=Vitals(hr=80, rr=16, spo2=99, sbp=120))
    v = supervise(e, ProposedTriage(esi_level=None))
    assert v.decision is Decision.ESCALATE


def test_incomplete_audio_escalates():
    e = Encounter("T", "fever and confusion", age_years=71,
                  vitals=Vitals(hr=112, temp_c=38.9))  # no rr/spo2/sbp
    v = supervise(e, ProposedTriage(esi_level=2, orders=("lactate",
                  "blood_cultures", "antibiotics"), disposition="main_ed"))
    det = {d.detector: d for d in v.detections}
    assert det["incomplete_audio"].fired
    assert v.decision in (Decision.ESCALATE, Decision.BLOCK)


def test_transcription_error_flagged():
    e = Encounter("T", "palpitations", age_years=50,
                  vitals=Vitals(hr=400, rr=16, spo2=98, sbp=130))
    v = supervise(e, ProposedTriage(esi_level=2, disposition="main_ed"))
    det = {d.detector: d for d in v.detections}
    assert det["transcription_error"].fired


def test_hallucinated_vital_blocks():
    e = Encounter("T", "twisted ankle, needs xray", age_years=24,
                  vitals=Vitals(hr=80, rr=16, spo2=97, sbp=120))
    v = supervise(e, ProposedTriage(
        esi_level=4, orders=("ankle_xray",), disposition="fast_track",
        rationale="reassuring, spo2 was 99 and hr 80"))
    det = {d.detector: d for d in v.detections}
    assert det["hallucination"].fired  # record spo2=97, claim 99
    assert v.decision is Decision.BLOCK


def test_partial_workup_does_not_clear_requirement_groups():
    # Codex P1: ecg alone must not satisfy [["ecg"], ["troponin"]].
    e = Encounter("T", "chest pain radiating to left arm", age_years=60,
                  vitals=Vitals(hr=90, rr=16, spo2=98, sbp=140))
    v = supervise(e, ProposedTriage(esi_level=2, orders=("ecg",),
                                    disposition="discharge"))
    assert v.decision is Decision.BLOCK
    f = next(f for f in v.findings if f.kind == "workup_incomplete")
    assert "troponin" in f.message and "ecg" not in f.message.split("missing")[1]


def test_synonym_alternative_satisfies_a_group():
    e = Encounter("T", "sudden facial droop and slurred speech", age_years=70,
                  vitals=Vitals(hr=88, rr=16, spo2=98, sbp=158))
    v = supervise(e, ProposedTriage(esi_level=2, orders=("stroke_activation",),
                                    disposition="main_ed"))
    assert not any(f.kind == "workup_incomplete" for f in v.findings)


def test_partial_engagement_is_not_anchoring():
    # Ordering the ECG engages the flag: incomplete workup, not anchoring.
    e = Encounter("T", "chest pain radiating to left arm", age_years=60,
                  vitals=Vitals(hr=90, rr=16, spo2=98, sbp=140))
    v = supervise(e, ProposedTriage(esi_level=2, orders=("ecg",),
                                    disposition="main_ed"))
    det = {d.detector: d for d in v.detections}
    assert not det["anchoring_bias"].fired
    assert any(f.kind == "workup_incomplete" for f in v.findings)
