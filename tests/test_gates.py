"""Gate tests, organized by inversion-ledger failure mode (see INVERSION.md).

Each test class name maps to a failure mode F1..F9. These are written FIRST
(TDD red phase). The gates they specify are deterministic middleware — they
must behave identically at turn 1 and turn 1000, which is the whole point.
"""

import pytest

from sitrep.gates import (
    Rendering,
    Severity,
    run_gates,
)
from sitrep.state import EncounterState, Order, Result


@pytest.fixture
def state_with_critical_troponin() -> EncounterState:
    """52M chest pain; troponin resulted CRITICAL, released, not yet discussed."""
    s = EncounterState(patient={"age": 52, "sex": "M", "chief_complaint": "chest pain"})
    s.add_order(Order(id="ord-trop", name="Troponin I", status="completed"))
    s.add_result(
        Result(
            id="res-trop",
            order_id="ord-trop",
            name="Troponin I",
            value="0.42 ng/mL",
            flag="critical",
            status="final",
            released=True,
            viewed=False,
            discussed=False,
        )
    )
    return s


def blocked(violations):
    return [v for v in violations if v.severity == Severity.BLOCK]


def gates_fired(violations):
    return {v.gate for v in violations}


# ---------------------------------------------------------------- F1
class TestF1NoInterpretation:
    """Patient pane must never interpret or prognose."""

    @pytest.mark.parametrize(
        "text",
        [
            "Your troponin result is consistent with a heart attack.",
            "This likely means you have had an MI.",
            "Your result suggests you have cardiac damage.",
            "Don't worry, this is probably nothing serious.",
        ],
    )
    def test_interpretation_blocked_in_patient_pane(self, state_with_critical_troponin, text):
        r = Rendering(audience="patient", text=text, refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        assert "no_interpretation" in gates_fired(blocked(v))

    def test_neutral_definition_passes(self, state_with_critical_troponin):
        text = (
            "A new Troponin I result is available in your record. "
            "Troponin is a protein your care team uses to check the heart. "
            "Dr. Dent is coming to talk with you about this result. "
            "This update was generated with AI — press your call button to speak with your nurse."
        )
        r = Rendering(audience="patient", text=text, refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        assert "no_interpretation" not in gates_fired(v)

    def test_clinician_pane_exempt(self, state_with_critical_troponin):
        r = Rendering(
            audience="physician",
            text="Troponin 0.42 — concerning for NSTEMI, cards consult pending.",
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "no_interpretation" not in gates_fired(v)


# ---------------------------------------------------------------- F2
class TestF2AntiEmbargo:
    """Cures Act: suppression is the violation. A final, released result must be
    acknowledged as available in the patient pane. Hiding it = information blocking."""

    def test_suppression_blocked(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "We are still waiting on your blood tests. Nothing new to share yet. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=[],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "info_blocking" in gates_fired(blocked(v))

    def test_acknowledgment_passes(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "A new Troponin I result is available in your record. "
                "Dr. Dent will discuss it with you shortly. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "info_blocking" not in gates_fired(v)

    def test_unreleased_result_not_required(self):
        s = EncounterState(patient={"age": 52})
        s.add_order(Order(id="ord-ct", name="CT Chest", status="in-progress"))
        s.add_result(
            Result(
                id="res-ct", order_id="ord-ct", name="CT Chest", value="",
                flag="pending", status="preliminary", released=False,
            )
        )
        r = Rendering(
            audience="patient",
            text=(
                "Your CT scan is being reviewed by the radiologist. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=["res-ct"],
        )
        v = run_gates(r, s)
        assert "info_blocking" not in gates_fired(v)


# ---------------------------------------------------------------- F4
class TestF4NoAdvice:
    @pytest.mark.parametrize(
        "text",
        [
            "You should take an aspirin now.",
            "You must stop taking your blood thinner.",
            "Double your dose of metoprolol tonight.",
        ],
    )
    def test_directives_blocked_in_patient_pane(self, state_with_critical_troponin, text):
        full = text + " This update was generated with AI — press your call button to speak with your nurse."
        r = Rendering(audience="patient", text=full, refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        assert "no_advice" in gates_fired(blocked(v))

    def test_referral_to_team_passes(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "A new Troponin I result is available. If you have questions, "
                "you can ask your nurse at any time. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "no_advice" not in gates_fired(v)


# ---------------------------------------------------------------- F5
class TestF5Compliance:
    def test_missing_ai_disclosure_blocked(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text="A new Troponin I result is available. Press your call button to speak with your nurse.",
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "compliance" in gates_fired(blocked(v))

    def test_missing_human_path_blocked(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text="A new Troponin I result is available. This update was generated with AI.",
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "compliance" in gates_fired(blocked(v))

    def test_clinician_panes_exempt(self, state_with_critical_troponin):
        r = Rendering(audience="nurse", text="Troponin 0.42 critical, resulted 14:32.", refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        assert "compliance" not in gates_fired(v)


# ---------------------------------------------------------------- F7
class TestF7Grounding:
    def test_unresolvable_ref_blocked(self, state_with_critical_troponin):
        r = Rendering(
            audience="nurse",
            text="CBC resulted: WBC 14.",
            refs=["res-cbc-does-not-exist"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "grounding" in gates_fired(blocked(v))

    def test_known_result_name_without_ref_blocked(self, state_with_critical_troponin):
        # Mentions Troponin I but supplies no supporting ref: uncited claim.
        r = Rendering(audience="nurse", text="Troponin I is back.", refs=[])
        v = run_gates(r, state_with_critical_troponin)
        assert "grounding" in gates_fired(blocked(v))

    def test_cited_claim_passes(self, state_with_critical_troponin):
        r = Rendering(audience="nurse", text="Troponin I resulted critical at 0.42.", refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        assert "grounding" not in gates_fired(v)


# ---------------------------------------------------------------- F8
class TestF8FalseReassurance:
    def test_everything_fine_with_critical_on_chart_blocked(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "Good news — everything looks fine so far! "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=[],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "no_interpretation" in gates_fired(blocked(v))


# ---------------------------------------------------------------- F9
class TestF9Readability:
    def test_graduate_level_prose_warns(self, state_with_critical_troponin):
        text = (
            "Your quantitative cardiac biomarker determination demonstrates "
            "a significantly supranormal concentration necessitating expeditious "
            "cardiological evaluation and continuous telemetric observation. "
            "This update was generated with AI — press your call button to speak with your nurse. "
            "A new Troponin I result is available."
        )
        r = Rendering(audience="patient", text=text, refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        fired = [x for x in v if x.gate == "readability"]
        assert fired and fired[0].severity == Severity.WARN

    def test_plain_language_no_warning(self, state_with_critical_troponin):
        text = (
            "A new Troponin I result is available. It is a blood test that checks the heart. "
            "Dr. Dent will come talk with you soon. "
            "This update was generated with AI — press your call button to speak with your nurse."
        )
        r = Rendering(audience="patient", text=text, refs=["res-trop"])
        v = run_gates(r, state_with_critical_troponin)
        assert "readability" not in gates_fired(v)


class TestF2AvailabilityLexicon:
    """Colloquial acknowledgments count for NON-critical results — suppression,
    not phrasing, is the violation. CRITICAL results require the name."""

    @staticmethod
    def _noncritical_state():
        s = EncounterState(patient={"age": 40})
        s.add_order(Order(id="ord-cbc", name="CBC", status="completed"))
        s.add_result(Result(id="res-cbc", order_id="ord-cbc", name="CBC",
                            value="normal", flag="normal", status="final",
                            released=True))
        return s

    @pytest.mark.parametrize("ack", [
        "Your results are back.",
        "Your result is back.",
        "Your results have come back.",
        "Your result is ready to view.",
    ])
    def test_colloquial_acknowledgment_passes_for_noncritical(self, ack):
        r = Rendering(
            audience="patient",
            text=(
                f"{ack} Dr. Dent will discuss it with you shortly. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=["res-cbc"],
        )
        v = run_gates(r, self._noncritical_state())
        assert "info_blocking" not in gates_fired(v)

    def test_critical_result_requires_acknowledgment_by_name(self, state_with_critical_troponin):
        # Generic availability phrasing must NOT satisfy a CRITICAL result.
        r = Rendering(
            audience="patient",
            text=(
                "Your results are back. Dr. Dent will discuss them with you shortly. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "info_blocking" in gates_fired(blocked(v))

    def test_critical_result_named_passes(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "A new Troponin I result is available in your record. "
                "Dr. Dent will discuss it with you shortly. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=["res-trop"],
        )
        v = run_gates(r, state_with_critical_troponin)
        assert "info_blocking" not in gates_fired(v)


class TestParaphraseLexicon:
    """Judge-probe paraphrases (Codex review) — added with tests per house rule."""

    def test_lose_sleep_over_is_interpretation(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "This is not something to lose sleep over. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=[],
        )
        assert "no_interpretation" in gates_fired(blocked(run_gates(r, state_with_critical_troponin)))

    def test_reassuring_labs_is_false_reassurance_with_critical(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=(
                "Your labs are reassuring overall. "
                "This update was generated with AI — press your call button to speak with your nurse."
            ),
            refs=[],
        )
        assert "no_interpretation" in gates_fired(blocked(run_gates(r, state_with_critical_troponin)))


class TestRealisticMinimization:
    """A plausible, well-written draft — warm, professional — must still block
    when it minimizes a critical result. The gates are not strawman detectors."""

    def test_gentle_minimization_blocks_with_critical(self, state_with_critical_troponin):
        r = Rendering(
            audience="patient",
            text=("Your test came back a little elevated, which can happen for many "
                  "reasons. Try not to worry tonight - the team will check on you "
                  "in the morning."),
            refs=["res-trop"],
        )
        assert "no_interpretation" in gates_fired(blocked(run_gates(r, state_with_critical_troponin)))

    def test_same_empathy_is_fine_on_a_benign_chart(self):
        s = EncounterState(patient={"age": 30})
        s.add_order(Order(id="ord-cbc", name="CBC", status="completed"))
        s.add_result(Result(id="res-cbc", order_id="ord-cbc", name="CBC",
                            value="normal", flag="normal", status="final", released=True))
        r = Rendering(
            audience="patient",
            text=("Your CBC result is available and there is nothing urgent in it — "
                  "try not to worry. This update was generated with AI. Press your "
                  "call button to speak with your nurse."),
            refs=["res-cbc"],
        )
        # FALSE_REASSURANCE is critical-gated: benign chart -> no interpretation block.
        assert "no_interpretation" not in gates_fired(run_gates(r, s))


def test_generated_automatically_is_a_valid_disclosure(state_with_critical_troponin):
    # Deployed-precedent phrasing (UCSD label, Tai-Seale JAMA Netw Open 2024):
    # "generated automatically" satisfies the AI-disclosure requirement.
    r = Rendering(
        audience="patient",
        text=(
            "A new Troponin I result is available. This message was generated "
            "automatically. Press your call button to speak with your nurse."
        ),
        refs=["res-trop"],
    )
    fired = gates_fired(run_gates(r, state_with_critical_troponin))
    assert "compliance" not in fired or all(
        "disclosure" not in v.detail for v in run_gates(r, state_with_critical_troponin)
        if v.gate == "compliance")
