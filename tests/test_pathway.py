"""Journey engine: deterministic, guideline-faithful, gate-compliant."""

from attending import pathway
from attending.comms import supervise_rendering
from attending.verdict import Decision
from sitrep.gates import Rendering
from sitrep.state import EncounterState, Order, Result


def _state(with_result=False, flag="critical"):
    s = EncounterState()
    for name in ("ecg", "troponin", "cbc"):
        s.add_order(Order(id=f"ord-{name}", name=name))
    if with_result:
        s.add_result(Result(id="res-troponin", order_id="ord-troponin",
                            name="troponin", value="0.31", flag=flag,
                            status="final", released=True, viewed=True))
    return s


def test_next_box_is_always_populated():
    for st in (_state(), _state(with_result=True), _state(with_result=True, flag="normal")):
        j = pathway.chest_pain_journey(st)
        assert j.next_box.strip()


def test_guideline_interval_by_assay():
    # AHA/ACC 2021 §4.1 (Class 1): hs 1-3 h; conventional 3-6 h. Never "3-4 h".
    hs = pathway.chest_pain_journey(_state(), assay="high_sensitivity")
    conv = pathway.chest_pain_journey(_state(), assay="conventional")
    assert "1-3 hours" in hs.next_box and "hospital's protocol" in hs.next_box
    assert "3-6 hours" in conv.next_box
    assert "3-4" not in hs.next_box and "3-4" not in conv.next_box


def test_steps_derive_from_chart():
    j = pathway.chest_pain_journey(_state())
    by_id = {s.id: s for s in j.steps}
    assert by_id["ecg"].status == "done"
    assert by_id["troponin_result"].status == "active"
    j2 = pathway.chest_pain_journey(_state(with_result=True))
    assert {s.id: s for s in j2.steps}["troponin_result"].status == "done"


def test_critical_next_box_informs_never_directs():
    j = pathway.chest_pain_journey(_state(with_result=True))
    low = j.patient_text.lower()
    assert "commonly recommend" in low          # attributed general information
    assert "team decides your actual plan" in low
    assert "not medical advice" in low
    for banned in ("you need", "you should", "you have", "your diagnosis"):
        assert banned not in low


def test_delay_event_explains_waiting():
    j = pathway.chest_pain_journey(
        _state(), delays=(pathway.DelayEvent(
            "MRI", "emergency cases take scanner priority",
            revised_estimate="about 2 hours"),))
    assert "delayed" in j.next_box and "not been forgotten" in j.next_box


def test_panel_ships_with_critical_result_while_gap_open():
    """The product moment: labeled result_context travels WITH the released
    critical result even though the disclosure gap is open — while a plain
    message with identical labels is still blocked by the gap."""
    st = _state(with_result=True)  # critical, released, viewed, NOT discussed
    j = pathway.chest_pain_journey(st)
    panel = supervise_rendering(
        Rendering("patient", j.patient_text,
                  ["res-troponin", "ord-ecg", "ord-troponin"],
                  kind="result_context"), st)
    assert panel.decision is Decision.ALLOW, [f.message for f in panel.findings]
    as_message = supervise_rendering(
        Rendering("patient", j.patient_text,
                  ["res-troponin", "ord-ecg", "ord-troponin"]), st)
    assert as_message.decision is Decision.BLOCK
    assert any(f.criterion_id == "SITREP-disclosure_gap" for f in as_message.findings)


def test_unlabeled_result_context_is_blocked():
    st = _state(with_result=True)
    bare = "Your troponin result is 0.31. Guidelines commonly recommend monitoring."
    v = supervise_rendering(
        Rendering("patient", bare, ["res-troponin"], kind="result_context"), st)
    assert v.decision is Decision.BLOCK
    assert any(f.criterion_id == "SITREP-result_context_labels" for f in v.findings)


def test_determinism():
    a = pathway.journey_to_dict(pathway.chest_pain_journey(_state(with_result=True)))
    b = pathway.journey_to_dict(pathway.chest_pain_journey(_state(with_result=True)))
    assert a == b
