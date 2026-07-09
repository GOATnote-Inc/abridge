"""State-invariant tests (TDD red phase for INV-H + core contracts).

The state machine is the single source of truth for four panes and one
alerting path. If it lies, every downstream safeguard grades fiction.
"""

import json

import pytest

from sitrep.state import EncounterState, Order, Result


def make_state() -> EncounterState:
    s = EncounterState(patient={"age": 52, "sex": "M", "chief_complaint": "chest pain"})
    s.add_order(Order(id="ord-trop", name="Troponin I"))
    return s


# ---------------------------------------------------------------- INV-H
class TestOrphanResult:
    """A result that files against an order the chart has never seen is
    corruption, not data. Fail loudly at ingestion — silent acceptance means
    the nurse pane confidently renders a test nobody ordered."""

    def test_orphan_result_rejected(self):
        s = make_state()
        with pytest.raises(ValueError, match="ord-ghost"):
            s.add_result(Result(
                id="res-ghost", order_id="ord-ghost", name="D-dimer",
                value="0.9", flag="abnormal", status="final",
            ))

    def test_orphan_rejection_leaves_state_clean(self):
        s = make_state()
        before = json.dumps(s.snapshot(), sort_keys=True)
        with pytest.raises(ValueError):
            s.add_result(Result(id="res-ghost", order_id="ord-ghost", name="D-dimer"))
        assert json.dumps(s.snapshot(), sort_keys=True) == before

    def test_legitimate_result_still_accepted(self):
        s = make_state()
        s.add_result(Result(
            id="res-trop", order_id="ord-trop", name="Troponin I",
            value="0.42 ng/mL", flag="critical", status="final",
        ))
        assert "res-trop" in s.results


# ---------------------------------------------------------------- linkage
class TestResultOrderLinkage:
    def test_final_result_completes_its_order(self):
        s = make_state()
        s.add_result(Result(
            id="res-trop", order_id="ord-trop", name="Troponin I",
            value="0.42 ng/mL", flag="critical", status="final",
        ))
        assert s.orders["ord-trop"].status == "completed"

    def test_preliminary_result_does_not_complete_order(self):
        s = make_state()
        s.add_result(Result(
            id="res-trop", order_id="ord-trop", name="Troponin I",
            value="pending", flag="pending", status="preliminary",
        ))
        assert s.orders["ord-trop"].status == "in-progress"


# ---------------------------------------------------------------- monotonic
class TestEscalationMonotonicity:
    """Escalations may only accumulate. The API must not even OFFER a way
    to clear them — absence of the footgun, not discipline in using it."""

    def test_escalations_accumulate(self):
        s = make_state()
        s.escalate("worsening chest pain")
        s.escalate("new diaphoresis")
        assert [e.reason for e in s.escalations] == [
            "worsening chest pain", "new diaphoresis",
        ]

    def test_no_clearing_api_exists(self):
        s = make_state()
        forbidden = [n for n in dir(s) if any(
            w in n.lower() for w in ("clear", "reset", "remove", "dismiss", "pop")
        )]
        assert forbidden == [], f"state exposes escalation-clearing surface: {forbidden}"


# ---------------------------------------------------------------- determinism
class TestSnapshotDeterminism:
    def test_identical_mutation_sequences_yield_identical_bytes(self):
        def build() -> str:
            s = make_state()
            s.add_result(Result(
                id="res-trop", order_id="ord-trop", name="Troponin I",
                value="0.42 ng/mL", flag="critical", status="final",
            ))
            s.mark_released("res-trop")
            s.mark_viewed("res-trop")
            s.escalate("pain worse")
            return json.dumps(s.snapshot(), sort_keys=True)

        assert build() == build()
