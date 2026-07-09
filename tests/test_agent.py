"""The performer's parsing/coercion contract (transport mocked, no network)."""

from attending import agent, llm
from attending.encounter import Encounter, Vitals


def _enc():
    return Encounter("T", "chest pressure", age_years=58,
                     vitals=Vitals(hr=96, rr=18, spo2=97, sbp=148))


def test_valid_output_coerces_types(monkeypatch):
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "esi_level": "2", "orders": ["ECG", "Troponin"],
        "disposition": "main_ed", "rationale": "possible ACS"})
    p = agent.propose_triage(_enc())
    assert p.esi_level == 2                       # str -> int
    assert p.orders == ("ecg", "troponin")        # lowercased
    assert p.disposition == "main_ed"


def test_garbage_output_returns_none_fail_closed(monkeypatch):
    monkeypatch.setattr(llm, "complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("no JSON")))
    assert agent.propose_triage(_enc()) is None   # loop escalates on None


def test_unparseable_esi_returns_none(monkeypatch):
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"esi_level": "urgent"})
    assert agent.propose_triage(_enc()) is None


def test_transport_unavailable_returns_none(monkeypatch):
    def boom(*a, **k):
        raise llm.LLMUnavailable("no key")
    monkeypatch.setattr(llm, "complete_json", boom)
    assert agent.propose_triage(_enc()) is None
    assert agent.draft_patient_message(_enc(), "situation") is None


def test_feedback_is_threaded_into_the_prompt(monkeypatch):
    seen = {}

    def spy(system, user, **kw):
        seen["user"] = user
        return {"esi_level": 2, "orders": ["ecg"], "disposition": "main_ed",
                "rationale": "ok"}
    monkeypatch.setattr(llm, "complete_json", spy)
    agent.propose_triage(_enc(), feedback="[ATT-UT1] under-triage (cite: ACEP)")
    assert "REVISION FEEDBACK" in seen["user"] and "ATT-UT1" in seen["user"]
