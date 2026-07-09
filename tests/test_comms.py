"""The communication surface speaks Attending's verdict language, fails closed."""

from attending.comms import GATE_CITATIONS, CommsVerdict, _to_finding, supervise_rendering
from attending.verdict import Decision, Severity
from sitrep.gates import Rendering, Violation
from sitrep.gates import Severity as GateSeverity
from sitrep.state import EncounterState, Order, Result


def _state(flag="normal", released=True, viewed=False, discussed=False):
    s = EncounterState(patient={"mrn": "SYN-1"})
    s.add_order(Order(id="ord-tni", name="troponin"))
    s.add_result(Result(id="res-tni", order_id="ord-tni", name="troponin",
                        value="0.02", flag=flag, status="final", released=released,
                        viewed=viewed, discussed=discussed))
    return s


_CLEAN_PATIENT = (
    "Your troponin result is available. This message was generated with AI. "
    "Please press your call button to speak with your nurse."
)


def test_clean_patient_rendering_allows():
    v = supervise_rendering(
        Rendering(audience="patient", text=_CLEAN_PATIENT, refs=["res-tni"]), _state())
    assert isinstance(v, CommsVerdict) and not v.blocked
    assert all(f.severity is not Severity.BLOCK for f in v.findings)


def test_interpretation_blocks_and_cites():
    text = ("Your results are back and this looks like an infection. This message "
            "was generated with AI. Press your call button to reach your nurse.")
    v = supervise_rendering(
        Rendering(audience="patient", text=text, refs=["res-tni"]), _state())
    assert v.decision is Decision.BLOCK
    f = next(f for f in v.findings if f.criterion_id == "SITREP-no_interpretation")
    assert f.citation  # names the rule it protects


def test_disclosure_gap_blocks():
    # Critical result released + viewed + not discussed: patient is alone with it.
    v = supervise_rendering(
        Rendering(audience="patient", text=_CLEAN_PATIENT, refs=["res-tni"]),
        _state(flag="critical", viewed=True, discussed=False))
    assert v.decision is Decision.BLOCK
    ids = {f.criterion_id for f in v.findings}
    assert "SITREP-disclosure_gap" in ids
    gap = next(f for f in v.findings if f.criterion_id == "SITREP-disclosure_gap")
    assert "Cures" in (gap.citation or "")


def test_missing_ai_disclosure_blocks():
    text = "Your troponin result is available. Please rest and someone will visit."
    v = supervise_rendering(
        Rendering(audience="patient", text=text, refs=["res-tni"]), _state())
    assert v.decision is Decision.BLOCK
    assert any(f.criterion_id == "SITREP-compliance" for f in v.findings)


def test_physician_pane_skips_patient_gates():
    v = supervise_rendering(
        Rendering(audience="physician", text="Troponin 0.02, low risk, dispo home.",
                  refs=["res-tni"]), _state())
    assert not v.blocked


def test_warn_maps_to_warn_and_does_not_block():
    f = _to_finding(Violation(gate="readability", severity=GateSeverity.WARN,
                              detail="grade 11.2"))
    assert f.severity is Severity.WARN
    assert f.criterion_id == "SITREP-readability" and f.citation
    # A WARN-only verdict ships.
    assert GATE_CITATIONS["readability"]


class TestAudienceFailsClosed:
    """Red-team pin: only known staff audiences skip patient gates. A mis-cased
    or novel audience must get patient protections, not silently bypass them."""

    _RISKY = "Everything looks fine, nothing to worry about."

    def _verdict(self, audience):
        return supervise_rendering(
            Rendering(audience=audience, text=self._RISKY, refs=[]),
            _state(flag="critical", viewed=True))

    def test_mis_cased_patient_is_still_protected(self):
        for audience in ("Patient", "PATIENT", " patient "):
            assert self._verdict(audience).decision is Decision.BLOCK, audience

    def test_unknown_audience_fails_closed(self):
        v = self._verdict("caregiver")
        assert v.decision is Decision.BLOCK
        assert any(f.criterion_id == "SITREP-disclosure_gap" for f in v.findings)

    def test_known_staff_audiences_stay_exempt(self):
        for audience in ("nurse", "physician", "consultant", "Physician"):
            assert not self._verdict(audience).blocked, audience
