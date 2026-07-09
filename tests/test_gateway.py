"""Gateway contract: the supervised loop over HTTP, fail-closed at the edge.

Skips entirely when the gateway extra is not installed (CI installs only the
core/dev deps — same pattern as the healthcraft integration suite). Locally:

    .venv/bin/python -m pip install fastapi uvicorn httpx

No test here ever invokes the live performer (that path needs a real key).
"""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import attending  # noqa: E402
from attending import gateway  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "chest_pain_undertriage.json"

# A safe revision for the chest-pain encounter (mirrors the demo fixture's
# second draft): correct acuity, ACS workup ordered, monitored bed.
SAFE_DRAFT = {
    "esi_level": 2,
    "orders": ["ecg", "troponin", "cbc"],
    "disposition": "main_ed",
    "rationale": "Possible ACS: ECG within 10 minutes, serial troponin, monitored bed.",
}

COMPLIANT_TEXT = (
    "Your troponin result is ready to view. This update was generated with AI. "
    "Press your call button to speak with your nurse."
)


def _chart(flag="normal", viewed=False, discussed=False):
    return {
        "orders": [{"id": "ord-troponin", "name": "troponin"}],
        "results": [{
            "id": "res-troponin", "order_id": "ord-troponin", "name": "troponin",
            "value": "0.31", "flag": flag, "status": "final",
            "released": True, "viewed": viewed, "discussed": discussed,
        }],
        "escalations": [],
    }


@pytest.fixture(scope="module")
def client():
    return TestClient(gateway.create_app())


@pytest.fixture
def example():
    return json.loads(EXAMPLE.read_text())


# --- module contract ----------------------------------------------------------


def test_no_module_level_app():
    # The app must never be built at import time (lazy optional dependency).
    assert not hasattr(gateway, "app")


def test_create_app_without_fastapi_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastapi", None)  # makes `import fastapi` fail
    with pytest.raises(gateway.GatewayUnavailable, match="gateway"):
        gateway.create_app()


# --- /health -------------------------------------------------------------------


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": attending.__version__}


# --- /supervise/triage: the pure screener --------------------------------------


def test_supervise_triage_blocks_chest_pain_undertriage(client, example):
    r = client.post("/supervise/triage", json=example)
    assert r.status_code == 200
    v = r.json()
    assert v["decision"] == "BLOCK"
    assert any(f["criterion_id"] == "ATT-UT1" for f in v["findings"])
    # A block always carries its citation.
    ut1 = next(f for f in v["findings"] if f["criterion_id"] == "ATT-UT1")
    assert ut1["citation"]


def test_supervise_triage_empty_proposal_escalates(client, example):
    # {} is a valid "no acuity proposed" — fail-closed semantic, not a client bug.
    r = client.post("/supervise/triage", json={"encounter": example["encounter"], "proposed": {}})
    assert r.status_code == 200
    v = r.json()
    assert v["decision"] == "ESCALATE"
    assert any(f["criterion_id"] == "ATT-000" for f in v["findings"])


# --- /loop/triage: propose -> verify -> revise -> ship --------------------------


def test_loop_triage_ships_safe_draft_on_second_attempt(client, example):
    body = {"encounter": example["encounter"], "drafts": [example["proposed"], SAFE_DRAFT]}
    r = client.post("/loop/triage", json=body)
    assert r.status_code == 200
    out = r.json()
    assert [a["verdict"]["decision"] for a in out["attempts"]] == ["BLOCK", "ALLOW"]
    assert len(out["attempts"]) == 2
    assert not out["escalated"]
    assert out["shipped"]["esi_level"] == 2


def test_loop_triage_exhaustion_fails_closed(client, example):
    # Only the unsafe draft: the performer never satisfies the rubric -> escalate.
    body = {"encounter": example["encounter"], "drafts": [example["proposed"]]}
    r = client.post("/loop/triage", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["escalated"] and out["shipped"] is None


# --- /supervise/rendering: the communication surface ----------------------------


def test_rendering_missing_ai_disclosure_blocks_and_cites_ab3030(client):
    body = {
        "audience": "patient",
        "text": "Your troponin result is ready to view. "
                "Press your call button to speak with your nurse.",
        "refs": ["res-troponin"],
        "chart": _chart(),
    }
    r = client.post("/supervise/rendering", json=body)
    assert r.status_code == 200
    v = r.json()
    assert v["decision"] == "BLOCK"
    hits = [f for f in v["findings"] if f["criterion_id"] == "SITREP-compliance"]
    assert hits and any("AB 3030" in (f["citation"] or "") for f in hits)


def test_rendering_disclosure_gap_blocks_even_compliant_text(client):
    # Critical result released + viewed + undiscussed: no wording can fix the chart.
    body = {
        "audience": "patient",
        "text": COMPLIANT_TEXT,
        "refs": ["res-troponin"],
        "chart": _chart(flag="critical", viewed=True, discussed=False),
    }
    r = client.post("/supervise/rendering", json=body)
    assert r.status_code == 200
    v = r.json()
    assert v["decision"] == "BLOCK"
    gap = [f for f in v["findings"] if f["criterion_id"] == "SITREP-disclosure_gap"]
    assert gap and "Cures" in (gap[0]["citation"] or "")


def test_rendering_compliant_text_on_clean_chart_allows(client):
    body = {
        "audience": "patient",
        "text": COMPLIANT_TEXT,
        "refs": ["res-troponin"],
        "chart": _chart(flag="critical", viewed=True, discussed=True),
    }
    r = client.post("/supervise/rendering", json=body)
    assert r.status_code == 200
    assert r.json()["decision"] == "ALLOW"


# --- /demo -----------------------------------------------------------------------


def test_demo_replay_ships_nothing_unsafe(client):
    r = client.get("/demo")
    assert r.status_code == 200
    t = r.json()
    assert t["mode"] == "replay"
    assert t["summary"]["unsafe_artifacts_shipped"] == 0
    assert t["stage_a"]["shipped"]["esi_level"] == 2


# --- malformed input: 4xx with a message, never a guessed verdict ----------------


def test_non_object_body_is_422(client):
    r = client.post("/supervise/triage", json="not an object")
    assert r.status_code == 422


def test_missing_proposed_key_is_400(client, example):
    r = client.post("/supervise/triage", json={"encounter": example["encounter"]})
    assert r.status_code == 400
    assert "proposed" in r.json()["detail"]


def test_prose_vitals_are_400(client):
    body = {
        "encounter": {"encounter_id": "X", "chief_complaint": "chest pain", "vitals": "stable"},
        "proposed": {"esi_level": 3},
    }
    r = client.post("/supervise/triage", json=body)
    assert r.status_code == 400
    assert "malformed encounter" in r.json()["detail"]


def test_out_of_scale_esi_is_400(client, example):
    r = client.post(
        "/supervise/triage",
        json={"encounter": example["encounter"], "proposed": {"esi_level": 0}},
    )
    assert r.status_code == 400
    assert "esi_level" in r.json()["detail"]


def test_loop_with_no_drafts_is_400(client, example):
    r = client.post("/loop/triage", json={"encounter": example["encounter"], "drafts": []})
    assert r.status_code == 400
    assert "draft" in r.json()["detail"]


def test_unknown_performer_is_400(client, example):
    body = {"encounter": example["encounter"], "drafts": [SAFE_DRAFT], "performer": "other"}
    r = client.post("/loop/triage", json=body)
    assert r.status_code == 400
    assert "performer" in r.json()["detail"]


def test_orphan_result_chart_is_400(client):
    chart = _chart()
    chart["orders"] = []  # result now references an order the chart never placed
    r = client.post(
        "/supervise/rendering",
        json={"audience": "patient", "text": COMPLIANT_TEXT,
              "refs": ["res-troponin"], "chart": chart},
    )
    assert r.status_code == 400
    assert "Orphan result" in r.json()["detail"]


def test_stringly_typed_discussed_is_400_not_fail_open(client):
    # "discussed": "false" is truthy — coercing it would silently SUPPRESS the
    # disclosure gap (fail-open). It must be rejected instead.
    chart = _chart(flag="critical", viewed=True)
    chart["results"][0]["discussed"] = "false"
    r = client.post(
        "/supervise/rendering",
        json={"audience": "patient", "text": COMPLIANT_TEXT,
              "refs": ["res-troponin"], "chart": chart},
    )
    assert r.status_code == 400
    assert "discussed" in r.json()["detail"]


def test_unknown_audience_is_400_not_gate_bypass(client):
    # An unrecognized audience would skip every patient-pane gate (fail-open);
    # the edge rejects it instead of screening leniently.
    r = client.post(
        "/supervise/rendering",
        json={"audience": "marketing", "text": "hi", "refs": [], "chart": _chart()},
    )
    assert r.status_code == 400
    assert "audience" in r.json()["detail"]


def test_float_esi_is_rejected(client, example):
    r = client.post("/supervise/triage", json={
        "encounter": example["encounter"], "proposed": {"esi_level": 3.0}})
    assert r.status_code == 400
