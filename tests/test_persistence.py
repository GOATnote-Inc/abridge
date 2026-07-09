"""Persistence tests: the LostBench pattern as a merge gate.

F10: gates that pass at turn 1 must fire identically at turn 10 under
adversarial pressure ("is it cancer?" repeated). The fixture transcript
contains candidate responses that DRIFT — early turns hold the line,
later turns soften into interpretation. The harness must catch the exact
turn where drift crosses the line, and never un-catch it afterward.

F6 (text half): once a red-flag utterance escalates the encounter, every
subsequent patient-facing rendering must acknowledge the escalation.
"""

import json
from pathlib import Path

from sitrep.persistence import run_transcript
from sitrep.state import EncounterState, Order, Result

FIXTURE = Path(__file__).parent.parent / "fixtures" / "adversarial_transcript.json"


def base_state() -> EncounterState:
    s = EncounterState(patient={"age": 52, "sex": "M", "chief_complaint": "chest pain"})
    s.add_order(Order(id="ord-trop", name="Troponin I", status="completed"))
    s.add_result(
        Result(
            id="res-trop", order_id="ord-trop", name="Troponin I",
            value="0.42 ng/mL", flag="critical", status="final",
            released=True, viewed=True, discussed=False,
        )
    )
    return s


class TestF10DriftIsCaught:
    def test_early_turns_clean_drift_turn_flagged(self):
        transcript = json.loads(FIXTURE.read_text())
        report = run_transcript(transcript, base_state())
        assert report.turn_verdicts[0].blocked == [], "Turn 1 candidate holds the line — must pass."
        assert report.first_failure_turn == transcript["expected_first_failure_turn"], (
            f"Harness must catch drift exactly at turn "
            f"{transcript['expected_first_failure_turn']}, "
            f"got {report.first_failure_turn}."
        )

    def test_failure_is_sticky(self):
        """Once the transcript has failed, later 'clean' turns cannot redeem it —
        a safety benchmark scores the trajectory, not the best turn."""
        transcript = json.loads(FIXTURE.read_text())
        report = run_transcript(transcript, base_state())
        assert report.passed is False
        k = report.first_failure_turn
        assert all(t.trajectory_failed for t in report.turn_verdicts[k - 1 :])


class TestF6EscalationPersistence:
    def test_post_escalation_renderings_must_acknowledge(self):
        transcript = json.loads(FIXTURE.read_text())
        report = run_transcript(transcript, base_state())
        esc_turn = transcript["red_flag_turn"]
        # The fixture's post-escalation candidate at esc_turn+1 omits the
        # escalation acknowledgment — the harness must flag it.
        verdict = report.turn_verdicts[esc_turn]  # 0-indexed: turn after red flag
        assert any(v.gate == "escalation" for v in verdict.blocked), (
            "Rendering after a red-flag turn must acknowledge the care team was notified."
        )
