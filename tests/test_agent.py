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


# --- coverage performer: propose_appeal ----------------------------------------

_PACK_DICT = {
    "schema": "coverage-pack/v1", "synthetic": True,
    "status": "TEST", "service": "speech", "population": "test",
    "version": "0.0.1-test",
    "clauses": [{"id": "T-01", "text": "Documented disorder.",
                 "evidence_needed": "note"}],
    "authorities": [{"id": "EPSDT", "name": "42 USC 1396d(r)",
                     "kind": "public", "paraphrase": "standard"}],
}


def _cov_fixtures(tmp_path):
    import json as _json

    from attending.coverage import CoverageCase, load_pack
    p = tmp_path / "pack.json"
    p.write_text(_json.dumps(_PACK_DICT))
    pack = load_pack(p)
    case = CoverageCase(case_id="TC", synthetic=True,
                        note="Assessment places the child below the 5th "
                             "percentile.",
                        transcript="parent: he cannot ask for water",
                        note_facts={}, evidence={"T-01": "met"})
    return case, pack


def test_propose_appeal_maps_to_quote_anchored_proposal(tmp_path, monkeypatch):
    case, pack = _cov_fixtures(tmp_path)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {
        "claims": [{"text": "Child is below the 5th percentile.",
                    "cites": [
                        {"type": "clause", "ref": "T-01", "quote": ""},
                        {"type": "note", "ref": "auto",
                         "quote": "below the 5th percentile"}]}],
        "authorities_cited": ["EPSDT"],
    })
    prop = agent.propose_appeal(case, pack, {"pack_version": pack.version},
                                "DENIED: not medically necessary.")
    assert prop is not None and prop.kind == "appeal" and prop.outcome is None
    assert prop.claims[0].cites[1].quote == "below the 5th percentile"
    assert prop.authorities_cited == ("EPSDT",)


def test_propose_appeal_revises_through_the_coverage_loop(tmp_path, monkeypatch):
    from attending.loop import run_coverage_loop
    case, pack = _cov_fixtures(tmp_path)
    from attending.coverage import make_provenance
    prov = make_provenance(pack, model_id="test", timestamp="2026-07-12T00:00:00Z")
    drafts = [
        {"claims": [{"text": "Child has severe apraxia.",       # ungrounded
                     "cites": [{"type": "clause", "ref": "T-01",
                                "quote": ""}]}],
         "authorities_cited": ["EPSDT"]},
        {"claims": [{"text": "Child is below the 5th percentile.",
                     "cites": [{"type": "clause", "ref": "T-01", "quote": ""},
                               {"type": "note", "ref": "auto",
                                "quote": "below the 5th percentile"}]}],
         "authorities_cited": ["EPSDT"]},
    ]
    calls = []

    def fake(system, user, **kw):
        calls.append(user)
        return drafts.pop(0)
    monkeypatch.setattr(llm, "complete_json", fake)
    result = run_coverage_loop(
        case, pack,
        lambda fb: agent.propose_appeal(case, pack, prov, "DENIED.", fb))
    assert result.shipped is not None and not result.escalated
    assert len(result.attempts) == 2
    assert result.attempts[0].verdict.decision.value == "BLOCK"
    assert "REVISION FEEDBACK" in calls[1]   # findings fed back verbatim


def test_propose_appeal_fails_closed_on_garbage(tmp_path, monkeypatch):
    case, pack = _cov_fixtures(tmp_path)
    monkeypatch.setattr(llm, "complete_json",
                        lambda *a, **k: {"claims": "not-a-list"})
    assert agent.propose_appeal(case, pack, {}, "letter") is None
