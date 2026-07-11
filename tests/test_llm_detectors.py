"""LLM augmentation: opt-in, additive, and fail-soft.

No network here — `llm.judge` is monkeypatched. These tests pin the contract:
augmentation is OFF by default, when ON it can ADD a finding, and any transport
failure degrades to the deterministic floor (never suppresses a finding).
"""

import pytest

from attending import llm
from attending.detectors.anchoring_bias import detect_anchoring
from attending.detectors.hallucination import detect_hallucination
from attending.encounter import Encounter, ProposedTriage, Vitals
from attending.esi import compute_esi
from attending.verdict import Severity


@pytest.fixture
def enable_llm(monkeypatch):
    monkeypatch.setenv("ATTENDING_LLM_AUGMENT", "1")


def _enc():
    return Encounter("T", "twisted ankle, needs xray", age_years=24,
                     vitals=Vitals(hr=80, rr=16, spo2=97, sbp=120))


def test_hooks_none_when_disabled(monkeypatch):
    monkeypatch.delenv("ATTENDING_LLM_AUGMENT", raising=False)
    assert llm.anchoring_hook() is None
    assert llm.hallucination_hook() is None


def test_anchoring_hook_fires_on_confident_verdict(enable_llm, monkeypatch):
    monkeypatch.setattr(llm, "judge", lambda *a, **k: {
        "fired": True, "confidence": 0.9,
        "missed_finding": "syncope buried in transcript", "evidence": "passed out"})
    enc = _enc()
    d = detect_anchoring(enc, ProposedTriage(esi_level=4), compute_esi(enc),
                         llm_augment=llm.anchoring_hook())
    assert d.fired and d.severity is Severity.BLOCK


def test_low_confidence_does_not_fire(enable_llm, monkeypatch):
    # Hedging judge must not over-block (FP hygiene).
    monkeypatch.setattr(llm, "judge", lambda *a, **k: {
        "fired": True, "confidence": 0.3, "missed_finding": "maybe", "evidence": ""})
    enc = _enc()
    d = detect_anchoring(enc, ProposedTriage(esi_level=4), compute_esi(enc),
                         llm_augment=llm.anchoring_hook())
    assert not d.fired


def test_hallucination_hook_degrades_on_transport_error(enable_llm, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMUnavailable("network down")
    monkeypatch.setattr(llm, "judge", boom)
    # Rationale is grounded, so deterministic floor = not fired; a crashing
    # judge must not change that (additive, fail-soft).
    enc = _enc()
    d = detect_hallucination(
        enc, ProposedTriage(esi_level=4, rationale="stable, spo2 97"),
        llm_augment=llm.hallucination_hook())
    assert not d.fired


def test_deterministic_floor_survives_llm(enable_llm, monkeypatch):
    # Deterministic hallucination catch must still fire even if the LLM says no.
    monkeypatch.setattr(llm, "judge", lambda *a, **k: {"fired": False, "confidence": 0.9})
    enc = _enc()
    d = detect_hallucination(
        enc, ProposedTriage(esi_level=4, rationale="reassuring, spo2 was 99"),
        llm_augment=llm.hallucination_hook())
    assert d.fired  # record spo2=97 vs claimed 99 — deterministic catch stands


class _StubResp:
    def __init__(self, stop_reason, text='{"fired": false}'):
        self.stop_reason = stop_reason
        self.content = [type("B", (), {"type": "text", "text": text})()]


def _stub_client(resp):
    create = lambda **kw: resp  # noqa: E731
    messages = type("M", (), {"create": staticmethod(create)})()
    return type("C", (), {"messages": messages})()


def test_refusal_and_truncation_fail_closed(monkeypatch):
    # Documented: schema is NOT guaranteed on refusal/max_tokens -> must raise,
    # so detectors keep their deterministic floor and performers return None.
    for stop in ("refusal", "max_tokens"):
        monkeypatch.setattr(llm, "_client", lambda s=stop: _stub_client(_StubResp(s)))
        try:
            llm.complete_json("sys", "user", schema={"type": "object"})
            raise AssertionError("should have failed closed")
        except llm.LLMUnavailable as e:
            assert stop in str(e)


def test_schema_guaranteed_output_parses_directly(monkeypatch):
    monkeypatch.setattr(llm, "_client",
                        lambda: _stub_client(_StubResp("end_turn")))
    assert llm.complete_json("sys", "user", schema={"type": "object"}) == {"fired": False}
