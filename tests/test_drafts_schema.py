"""Structural validation of quarantined drafts (drafts/coverage/).

Engineering checks ONLY — parse, attestation, schema shape, referential
integrity. Nothing here ratifies clinical content: that happens exclusively
through the clinical-review-packet flow with physician sign-off.
"""

import json
from pathlib import Path

import pytest

DRAFTS = Path(__file__).parent.parent / "drafts" / "coverage"

pytestmark = pytest.mark.skipif(not DRAFTS.is_dir(), reason="no drafts present")

_FORBIDDEN_KEYS = {"name", "first_name", "last_name", "dob", "date_of_birth",
                   "mrn", "ssn", "address", "phone", "email"}  # F13 hygiene


def _no_identifier_keys(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k.lower() not in _FORBIDDEN_KEYS or path.startswith("$.authorities"), \
                f"identifier-shaped key '{k}' at {path}"
            _no_identifier_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_identifier_keys(v, f"{path}[{i}]")


def test_every_json_draft_attests_synthetic():
    for f in DRAFTS.glob("*.json"):
        data = json.loads(f.read_text())
        assert data.get("synthetic") is True, f.name
        assert "DRAFT" in str(data.get("status", "")) or "draft" in str(
            data.get("version", "")), f"{f.name}: missing quarantine marker"


def test_case_has_no_identifier_shaped_fields():
    data = json.loads((DRAFTS / "case_peds_speech_denial.json").read_text())
    # authorities sections legitimately carry source titles under 'name'
    _no_identifier_keys({k: v for k, v in data.items()})


def test_packs_load_through_the_real_loader():
    from attending.coverage import load_pack
    for pack_file in DRAFTS.glob("pack_*.json"):
        pack = load_pack(pack_file)
        assert pack.clauses and pack.authority_ids
        assert "draft" in pack.version.lower() or "DRAFT" in pack.approval_status


def test_adversarial_fixture_spans_resolve():
    from attending.coverage import Cite, CoverageCase, _resolve_span, load_pack
    case_raw = json.loads((DRAFTS / "case_peds_speech_denial.json").read_text())
    case = CoverageCase(
        case_id=case_raw["id"], synthetic=True,
        note=case_raw["clinical_note"],
        transcript="\n".join(f"{t['speaker']}: {t['text']}"
                             for t in case_raw["encounter_transcript"]),
        note_facts=case_raw["note_facts"])
    fixtures = json.loads((DRAFTS / "adversarial_fixtures.json").read_text())
    pack = load_pack(DRAFTS / "pack_peds_speech_therapy.json")
    clean = next(f for f in fixtures["fixtures"] if f["id"].startswith("ADV-05"))
    for claim in clean["proposal"]["claims"]:
        for cite in claim["cites"]:
            if cite["type"] == "clause":
                assert cite["ref"] in pack.clauses, cite
            else:
                ok, why = _resolve_span(case, Cite(cite["type"], cite["ref"],
                                                   quote=cite.get("quote", "")))
                assert ok, (cite, why)


def test_goldset_candidates_are_marked_pending():
    lines = (DRAFTS / "goldset_candidates.jsonl").read_text().splitlines()
    records = [json.loads(x) for x in lines if x.strip()]
    assert len(records) >= 10
    assert all(r.get("synthetic") for r in records)
    assert all("pending" in r.get("status", "") for r in records)
    decisions = {r["expect"]["decision"] for r in records}
    assert {"BLOCK", "ESCALATE", "ALLOW"} <= decisions
