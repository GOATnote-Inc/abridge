"""FHIR R4 export — the supervision artifacts in the resources designed for
them (DetectedIssue, Provenance, AuditEvent, RiskAssessment, Observation).

The exporter is held to the same invariants as the engine: fail-closed (a
BLOCK can never launder into a benign export; findings are never dropped),
synthetic-only (F13 — non-attested input refuses to export), deterministic
(caller-supplied `recorded`, content-derived ids, byte-identical re-export).
"""

import json

import pytest

from attending import fhir
from attending.coverage import CoverageCase, CoverageVerdict
from attending.verdict import Decision, Finding, Severity

_ENC = {
    "synthetic": True,
    "encounter_id": "SYN-001",
    "chief_complaint": "chest pressure radiating to left arm",
    "vitals": {"hr": 104, "rr": 18, "spo2": 97, "sbp": 142},
}

_FINDINGS = (
    Finding("under_triage", Severity.BLOCK,
            "proposed ESI 3 below attending ESI 2",
            criterion_id="ATT-ESI-DELTA", citation="ESI v4 handbook",
            evidence="chest pressure radiating to left arm"),
    Finding("workup_incomplete", Severity.ESCALATE,
            "missing troponin", criterion_id="ATT-WORKUP",
            citation="AHA/ACC 2021 chest pain guideline"),
)


class _V:  # minimal Verdict stand-in (only fields the exporter reads)
    encounter_id = "SYN-001"
    decision = Decision.BLOCK
    attending_esi = 2
    recommended_esi = 2
    proposed_esi = 3
    findings = _FINDINGS
    ruleset_version = "0.3.1-test"


_REC = "2026-07-12T00:00:00Z"


def _bundle():
    return fhir.triage_export(_V(), _ENC, recorded=_REC, model_id="test-model")


def _resources(bundle, rtype):
    return [e["resource"] for e in bundle["entry"]
            if e["resource"]["resourceType"] == rtype]


def test_bundle_shape_and_required_fields():
    b = _bundle()
    assert b["resourceType"] == "Bundle" and b["type"] == "collection"
    for e in b["entry"]:
        assert e["fullUrl"].startswith("urn:")
    ra = _resources(b, "RiskAssessment")[0]
    assert ra["status"] == "final" and "subject" in ra
    obs = _resources(b, "Observation")[0]
    assert obs["code"]["coding"][0] == {
        "system": "http://loinc.org", "code": "75636-1",
        "display": "Emergency severity index [ESI]"}
    assert obs["valueInteger"] == 2
    prov = _resources(b, "Provenance")[0]
    assert prov["recorded"] == _REC and prov["target"] and prov["agent"]
    ae = _resources(b, "AuditEvent")[0]
    assert ae["recorded"] == _REC and ae["source"]["observer"]
    assert all("requestor" in a for a in ae["agent"])


def test_every_resource_carries_htest_security_label():
    for e in _bundle()["entry"]:
        labels = e["resource"]["meta"]["security"]
        assert any(s["code"] == "HTEST" for s in labels)


def test_block_verdict_exports_high_severity_and_drops_nothing():
    issues = _resources(_bundle(), "DetectedIssue")
    assert len(issues) == len(_FINDINGS)          # no finding ever dropped
    by_crit = {i["code"]["coding"][0]["code"]: i for i in issues}
    assert by_crit["ATT-ESI-DELTA"]["severity"] == "high"      # BLOCK
    assert by_crit["ATT-WORKUP"]["severity"] == "moderate"     # ESCALATE
    assert all(i["status"] == "final" for i in issues)


def test_evidence_quote_travels_inside_the_issue():
    issues = _resources(_bundle(), "DetectedIssue")
    withq = [i for i in issues if i.get("evidence")]
    assert withq, "evidence spans must survive export"
    assert (withq[0]["evidence"][0]["code"][0]["text"]
            == "chest pressure radiating to left arm")


def test_export_is_deterministic():
    a, b = _bundle(), _bundle()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_recorded_is_required_no_clock_fallback():
    with pytest.raises(TypeError):
        fhir.triage_export(_V(), _ENC, model_id="test-model")  # type: ignore[call-arg]


def test_non_synthetic_input_refuses_to_export():
    enc = dict(_ENC)
    enc["synthetic"] = False
    with pytest.raises(ValueError):
        fhir.triage_export(_V(), enc, recorded=_REC, model_id="test-model")
    with pytest.raises(ValueError):
        fhir.triage_export(_V(), {k: v for k, v in _ENC.items()
                                  if k != "synthetic"},
                           recorded=_REC, model_id="test-model")


def test_coverage_export_carries_pack_hash_as_rfc6920_ni_uri():
    case = CoverageCase(case_id="TC-1", synthetic=True, note="note text",
                        transcript="", note_facts={}, evidence={})
    cv = CoverageVerdict(
        case_id="TC-1", decision=Decision.BLOCK,
        findings=(Finding("outcome", Severity.BLOCK, "automated deny attempted",
                          criterion_id="COV-F16", citation="INVERSION F16"),),
        pack_version="0.1.0-draft", pack_hash="ab" * 32)
    b = fhir.coverage_export(case, cv, recorded=_REC, model_id="test-model",
                             quotes=("caregiver-implemented strategies",))
    prov = _resources(b, "Provenance")[0]
    ids = [ent.get("what", {}).get("identifier", {}).get("value", "")
           for ent in prov["entity"]]
    assert any(v == "ni:///sha-256;" + "ab" * 32 for v in ids)
    roles = {ent["role"] for ent in prov["entity"]}
    assert {"source", "quotation"} <= roles
    issues = _resources(b, "DetectedIssue")
    assert issues and issues[0]["severity"] == "high"


def test_coverage_export_refuses_non_synthetic_case():
    case = CoverageCase(case_id="TC-1", synthetic=False, note="",
                        transcript="", note_facts={}, evidence={})
    cv = CoverageVerdict(case_id="TC-1", decision=Decision.ALLOW, findings=(),
                         pack_version="x", pack_hash="ab" * 32)
    with pytest.raises(ValueError):
        fhir.coverage_export(case, cv, recorded=_REC, model_id="test-model")


def test_committed_demo_export_regenerates_byte_identically():
    import pathlib
    import subprocess
    import sys
    repo = pathlib.Path(__file__).resolve().parents[1]
    committed = repo / "evaluation" / "fhir_export_demo.json"
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "fhir_demo_export.py"),
         "--stdout"],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == committed.read_text()
