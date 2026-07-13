"""The MCP surface — the judge connects THEIR Claude and tries to get an
unsafe action past the gates. Same invariants as every other surface:
BLOCK is a successful structured result (never an error), unknown
vocabulary refuses rather than guesses, verdicts are deterministic.

Skipped where the [mcp] extra is absent (CI installs it).
"""

import pytest

pytest.importorskip("mcp")

from attending import mcp_server  # noqa: E402


def test_five_tools_registered():
    import anyio
    tools = anyio.run(mcp_server.mcp.list_tools)
    names = {t.name for t in tools}
    assert names == {"supervise_triage", "supervise_patient_message",
                     "supervise_coverage_appeal", "coverage_preset",
                     "list_gates"}
    for t in tools:
        assert len(t.description or "") < 2048   # Claude Code truncates at 2KB
        assert t.annotations and t.annotations.readOnlyHint is True


def test_triage_block_is_a_successful_structured_verdict():
    v = mcp_server.supervise_triage(
        chief_complaint="Chest pressure radiating to left arm, sweating",
        proposed_esi=3, orders=["cbc", "bmp"], disposition="fast_track",
        age_years=58, hr=96, rr=18, spo2=97, sbp=148, pain=6)
    assert v.decision == "BLOCK"
    assert "revise" in v.guidance and "override" in v.guidance
    ids = {f.criterion_id for f in v.findings}
    assert "RF-ACS" in ids                       # missing ecg+troponin, named
    assert any("ecg" in f.message for f in v.findings)
    assert v.ruleset_version


def test_triage_clean_case_allows():
    v = mcp_server.supervise_triage(
        chief_complaint="Twisted right ankle, swollen, cannot bear weight",
        proposed_esi=4, orders=["ankle_xray"], disposition="fast_track",
        age_years=24, hr=82, rr=16, spo2=99, sbp=122, pain=5)
    assert v.decision == "ALLOW"
    assert v.findings == []


def test_patient_message_disclosure_gap_blocks_compliant_text():
    out = mcp_server.supervise_patient_message(
        text=("Your troponin result is ready to view. This update was "
              "generated with AI. Press your call button to speak with "
              "your nurse."),
        audience="patient", chart_preset="critical")
    assert out["decision"] == "BLOCK"
    assert any("disclosure" in (f["criterion_id"] or "").lower()
               or "disclosure" in f["message"].lower()
               for f in out["findings"])


def test_patient_message_unknown_chart_preset_refuses():
    with pytest.raises(ValueError, match="unknown chart_preset"):
        mcp_server.supervise_patient_message(
            text="hello", audience="patient", chart_preset="banana")


def test_coverage_appeal_uncited_claim_blocks_with_chart_evidence_rule():
    v = mcp_server.supervise_coverage_appeal(
        claims=[{"text": "The patient has severe childhood apraxia of speech.",
                 "cites": [{"type": "clause", "ref": "SLT-01", "quote": ""}]}],
        authorities_cited=["AUTH-EPSDT-1396D-R"])
    assert v.decision == "BLOCK"
    assert any(f.criterion_id == "COV-F15" for f in v.findings)
    assert v.pack_status                          # DRAFT status surfaced


def test_coverage_preset_parity_with_gateway_impl():
    from attending.gateway import _coverage_preset_impl
    assert (mcp_server.coverage_preset("auto_deny")
            == _coverage_preset_impl("auto_deny"))
    assert mcp_server.coverage_preset("auto_deny")["f14"]["raised"] is True


def test_list_gates_returns_the_ledger():
    rows = mcp_server.list_gates()
    ids = {r["id"] for r in rows}
    assert {"F14", "F15", "F16", "F17", "F18", "F19"} <= ids
    assert all(r["failure_mode"] and r["mechanism"] for r in rows)


def test_verdicts_are_deterministic():
    a = mcp_server.supervise_triage(chief_complaint="cough", proposed_esi=4,
                                    disposition="fast_track")
    b = mcp_server.supervise_triage(chief_complaint="cough", proposed_esi=4,
                                    disposition="fast_track")
    assert a == b
