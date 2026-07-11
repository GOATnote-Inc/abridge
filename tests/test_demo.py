"""The demo transcript: deterministic, fail-closed, every block cited."""

import copy
import json
from pathlib import Path

import pytest

from attending.demo import run_demo

FIXTURE = Path(__file__).parent.parent / "fixtures" / "demo_chest_pain.json"


@pytest.fixture
def fx():
    return json.loads(FIXTURE.read_text())


def test_stage_a_blocks_then_ships(fx):
    t = run_demo(fx)
    decisions = [a["verdict"]["decision"] for a in t["stage_a"]["attempts"]]
    assert decisions == ["BLOCK", "ALLOW"]
    assert t["stage_a"]["shipped"]["esi_level"] == 2
    # The block carries the guideline citation.
    first = t["stage_a"]["attempts"][0]["verdict"]["findings"]
    assert any("ACEP" in (f.get("citation") or "") for f in first)
    # The hallucinated SpO2 and the anchoring miss were both caught.
    ids = {f["criterion_id"] for f in first}
    assert {"ATT-UT1", "RF-ACS", "ATT-hallucination", "ATT-anchoring_bias"} <= ids


def test_stage_b_gap_forces_human_then_ships(fx):
    t = run_demo(fx)
    first = t["stage_b"]["first_reply"]
    assert first["escalated"] and first["shipped"] is None
    assert "SITREP-disclosure_gap" in first["state_findings"]
    blocked_ids = {f["criterion_id"] for a in first["attempts"]
                   for f in a["verdict"]["findings"]}
    assert {"SITREP-no_interpretation", "SITREP-compliance",
            "SITREP-disclosure_gap"} <= blocked_ids
    # Cures Act named on the gap; AB 3030 named on the disclosure violation.
    cites = " ".join(f.get("citation") or "" for a in first["attempts"]
                     for f in a["verdict"]["findings"])
    assert "Cures" in cites and "AB 3030" in cites
    # After the documented discussion, the compliant message ships.
    final = t["stage_b"]["final_reply"]
    assert final["shipped"] and not final["escalated"]
    assert t["stage_b"]["physician_page"]["shipped"]


def test_replay_is_byte_identical(fx):
    a = json.dumps(run_demo(fx), sort_keys=True)
    b = json.dumps(run_demo(copy.deepcopy(fx)), sort_keys=True)
    assert a == b


def test_summary_integrity(fx):
    s = run_demo(fx)["summary"]
    assert s["unsafe_artifacts_shipped"] == 0
    assert s["artifacts_shipped"] == 6  # plan, journey panel, page, final reply, appeal, approval
    assert len(s["criteria_tripped"]) >= 6
    assert len(s["citations"]) >= 3


def test_stage_a_exhaustion_skips_stage_b(fx):
    bad = copy.deepcopy(fx)
    bad["stage_a"]["drafts"] = bad["stage_a"]["drafts"][:1]  # only the unsafe draft
    t = run_demo(bad)
    assert t["stage_a"]["escalated"] and t["stage_a"]["shipped"] is None
    assert "skipped" in t["stage_b"]
    assert t["summary"]["unsafe_artifacts_shipped"] == 0


def test_checked_in_transcript_is_not_stale():
    """The committed web transcript must match the code's ruleset version —
    guards the exact staleness Codex caught (0.2.0 artifact vs 0.2.1 code)."""
    from attending import knowledge as K
    t = json.loads((Path(__file__).parent.parent / "web" / "demo_transcript.json").read_text())
    versions = {a["verdict"]["ruleset_version"] for a in t["stage_a"]["attempts"]}
    assert versions == {K.RULESET_VERSION}, (
        f"stale demo transcript {versions}; regenerate: "
        "PYTHONPATH=src python3 -m attending.demo --json > web/demo_transcript.json")


def test_journey_panel_ships_with_result_before_discussion(fx):
    t = run_demo(fx)
    sb = t["stage_b"]
    assert sb["journey_pre"]["next_box"].strip()          # never an empty box
    panel = sb["result_context_panel"]
    assert panel["shipped"] and not panel["escalated"]
    assert "not medical advice" in panel["shipped"]
    assert "1-3 hours" in sb["journey_pre"]["next_box"]   # hs-cTn guideline interval
    # And the conversational reply is STILL blocked until the discussion.
    assert sb["first_reply"]["escalated"]
    assert t["summary"]["artifacts_shipped"] == 6


def test_stage_c_coverage_scene(fx):
    t = run_demo(fx)
    sc = t["stage_c"]
    assert sc["pack"]["version"] == "0.1.0-draft"
    assert "DRAFT" in sc["pack"]["status"]        # quarantine status surfaced
    # The vague denial letter fails provenance, authority, grounding, outcome.
    audit_ids = {f["criterion_id"] for f in sc["denial_audit"]["findings"]}
    assert {"COV-F15", "COV-F16", "COV-F17", "COV-F18"} <= audit_ids
    assert sc["denial_audit"]["decision"] == "BLOCK"
    # Adversarial appeal blocked, revision ships with citations.
    assert [a["verdict"]["decision"] for a in sc["appeal"]["attempts"]] == ["BLOCK", "ALLOW"]
    assert "[SLT-01]" in sc["appeal"]["artifact_text"]
    # Mode B approves with citations; auto-deny is structurally impossible.
    assert sc["mode_b"]["decision"] == "ALLOW"
    assert sc["f14"]["raised"] is True and "F14" in sc["f14"]["error"]
    assert t["summary"]["artifacts_shipped"] == 6
    assert t["summary"]["unsafe_artifacts_shipped"] == 0
