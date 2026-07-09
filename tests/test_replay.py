"""Replayer tests: F3 (disclosure gap) and F11 (demo determinism)."""

from pathlib import Path

from sitrep.gates import check_disclosure_gap
from sitrep.replay import Replayer, load_scenario

FIXTURE = Path(__file__).parent.parent / "fixtures" / "chest_pain_timeline.json"


def load_replayer() -> Replayer:
    return Replayer(load_scenario(FIXTURE))


# ---------------------------------------------------------------- F3
class TestF3DisclosureGap:
    def test_gap_opens_when_critical_viewed_undiscussed(self):
        rp = load_replayer()
        rp.advance_until("patient_viewed_result")
        gaps = check_disclosure_gap(rp.state)
        assert any(g.detail_ref == "res-trop" for g in gaps), (
            "Patient saw a critical result nobody has discussed — this MUST raise an alertable gap."
        )

    def test_gap_closes_after_documented_discussion(self):
        rp = load_replayer()
        rp.advance_until("result_discussed")
        assert check_disclosure_gap(rp.state) == []

    def test_no_gap_before_view(self):
        rp = load_replayer()
        rp.advance_until("result_released")
        assert check_disclosure_gap(rp.state) == []


# ---------------------------------------------------------------- F6 (state half)
class TestEscalationMonotonic:
    def test_escalations_never_clear(self):
        rp = load_replayer()
        rp.advance_until("red_flag_utterance")
        assert rp.state.escalations, "Red flag must create an escalation."
        rp.advance_to_end()
        assert rp.state.escalations, (
            "Escalations are monotonic: once set, no later event may clear them."
        )


# ---------------------------------------------------------------- F11
class TestF11Determinism:
    def test_two_full_replays_produce_identical_state(self):
        a, b = load_replayer(), load_replayer()
        a.advance_to_end()
        b.advance_to_end()
        assert a.state.snapshot() == b.state.snapshot(), (
            "Replayer must be pure — the demo cannot be un-rehearsable."
        )

    def test_event_order_preserved(self):
        rp = load_replayer()
        rp.advance_to_end()
        kinds = [e["kind"] for e in rp.applied]
        assert kinds.index("order_placed") < kinds.index("result_final")
        assert kinds.index("result_final") < kinds.index("patient_viewed_result")
