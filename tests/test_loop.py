"""The supervised control loop: revise on BLOCK, stop on ESCALATE, never override."""

from attending.encounter import Encounter, ProposedTriage, Vitals
from attending.loop import run_rendering_loop, run_triage_loop
from sitrep.state import EncounterState, Order, Result

_UNSAFE = ProposedTriage(esi_level=3, orders=("cbc",), disposition="fast_track")
_SAFE = ProposedTriage(esi_level=2, orders=("ecg", "troponin"), disposition="main_ed",
                       rationale="possible ACS, monitored bed")


def _chest_pain(**vitals):
    v = vitals or {"hr": 96, "rr": 18, "spo2": 97, "sbp": 148}
    return Encounter("T", "chest pressure radiating to left arm", age_years=58,
                     vitals=Vitals(**v))


def test_block_then_revise_then_ship():
    calls: list[str | None] = []

    def propose(enc, feedback):
        calls.append(feedback)
        return _UNSAFE if feedback is None else _SAFE

    r = run_triage_loop(_chest_pain(), propose)
    assert r.shipped == _SAFE and not r.escalated and len(r.attempts) == 2
    # The revision call received machine-actionable feedback with the criterion.
    assert calls[0] is None and "ATT-UT1" in calls[1] and "cite:" in calls[1]


def test_supervisor_escalate_stops_immediately():
    # Missing vitals -> ESCALATE: rewording cannot fix a vitals gap.
    calls = []

    def propose(enc, feedback):
        calls.append(feedback)
        return _SAFE

    r = run_triage_loop(_chest_pain(hr=96), propose)
    assert r.escalated and r.shipped is None and len(calls) == 1


def test_revision_cap_fails_closed():
    r = run_triage_loop(_chest_pain(), lambda e, f: _UNSAFE, max_revisions=1)
    assert r.escalated and r.shipped is None and len(r.attempts) == 2
    assert "cap" in r.reason


def test_performer_giving_up_escalates():
    r = run_triage_loop(_chest_pain(), lambda e, f: None)
    assert r.escalated and r.shipped is None and not r.attempts


def _state(critical=False, viewed=False, discussed=False):
    s = EncounterState()
    s.add_order(Order(id="ord-troponin", name="troponin"))
    s.add_result(Result(id="res-troponin", order_id="ord-troponin", name="troponin",
                        flag="critical" if critical else "normal", status="final",
                        released=True, viewed=viewed, discussed=discussed))
    return s


_GOOD = ("Your troponin result is ready to view. This update was generated with AI. "
         "Press your call button to speak with your nurse.")
_BAD = "Everything looks fine, nothing to worry about tonight."


def test_rendering_block_then_revise_then_ship():
    drafts = iter([_BAD, _GOOD])
    feedback_seen = []

    def draft(feedback):
        feedback_seen.append(feedback)
        return next(drafts)

    r = run_rendering_loop(_state(), "patient", ["res-troponin"], draft)
    assert r.shipped == _GOOD and not r.escalated and len(r.attempts) == 2
    assert "SITREP-compliance" in (feedback_seen[1] or "")


def test_state_gate_stops_rendering_loop_immediately():
    # Critical viewed undiscussed: even a CLEAN draft must not ship; one call only.
    calls = []

    def draft(feedback):
        calls.append(feedback)
        return _GOOD

    r = run_rendering_loop(_state(critical=True, viewed=True), "patient",
                           ["res-troponin"], draft)
    assert r.escalated and r.shipped is None and len(calls) == 1
    assert any(f.criterion_id == "SITREP-disclosure_gap" for f in r.state_findings)


def test_rendering_cap_fails_closed_nothing_sent():
    r = run_rendering_loop(_state(), "patient", ["res-troponin"],
                           lambda f: _BAD, max_revisions=1)
    assert r.escalated and r.shipped is None and len(r.attempts) == 2
