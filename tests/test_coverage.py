"""Coverage surface — tests first, per the INVERSION F14-F19 ledger rows.

Engineering test vectors only (clinical goldset candidates live quarantined in
drafts/ pending physician sign-off). Every case here is synthetic:true.
"""

import pytest

from attending.coverage import (
    Cite,
    Claim,
    CoverageCase,
    CoverageProposal,
    PhysicianSignoff,
    PhysicianSignoffRequired,
    build_appeal,
    build_denial,
    determine,
    load_pack,
    make_provenance,
    supervise_determination,
)
from attending.loop import run_coverage_loop
from attending.verdict import Decision

# --- shared vectors -----------------------------------------------------------

_PACK_DICT = {
    "schema": "coverage-pack/v1",
    "synthetic": True,
    "status": "TEST — engineering vector",
    "service": "outpatient speech-language therapy",
    "population": "test",
    "version": "0.0.1-test",
    "clauses": [
        {"id": "T-01", "text": "Documented disorder via standardized assessment.",
         "evidence_needed": "assessment score in note"},
        {"id": "T-02", "text": "Functional impact documented.",
         "evidence_needed": "functional deficit in note"},
        {"id": "T-03", "text": "Skilled service required.",
         "evidence_needed": "clinician statement"},
    ],
    "authorities": [
        {"id": "EPSDT", "name": "42 U.S.C. 1396d(r) (EPSDT)", "kind": "public",
         "paraphrase": "correct-or-ameliorate standard"},
        {"id": "ASHA", "name": "ASHA practice guidance", "kind": "public",
         "paraphrase": "skilled SLT criteria"},
    ],
}

_NOTE = ("Standardized assessment places expressive language below the 5th "
         "percentile. The patient cannot request basic needs. Skilled "
         "speech-language therapy 2x/week is required; caregiver-implemented "
         "strategies alone have been insufficient.")


def _pack(tmp_path):
    import json
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(_PACK_DICT))
    return load_pack(p)


def _case():
    return CoverageCase(
        case_id="TC-1", synthetic=True, note=_NOTE, transcript="",
        note_facts={"percentile": "<5", "therapy_frequency_per_week": 2},
        evidence={"T-01": "met", "T-02": "met", "T-03": "met"},
    )


def _prov(pack):
    return make_provenance(pack, model_id="test-model", timestamp="2026-07-11T00:00:00Z")


def _span(text, needle):
    i = text.index(needle)
    return f"note:{i}:{i + len(needle)}", needle


def _good_claims():
    ref1, q1 = _span(_NOTE, "below the 5th percentile")
    ref2, q2 = _span(_NOTE, "cannot request basic needs")
    return [
        Claim("Assessment shows expressive language below the 5th percentile.",
              cites=(Cite("clause", "T-01"), Cite("note", ref1, quote=q1))),
        Claim("The patient cannot request basic needs.",
              cites=(Cite("note", ref2, quote=q2),)),
    ]


def _proposal(pack, **kw):
    base = dict(kind="appeal", outcome=None, claims=_good_claims(),
                authorities_cited=("EPSDT",), provenance=_prov(pack))
    base.update(kw)
    return CoverageProposal(**base)


# --- pack loader --------------------------------------------------------------

def test_pack_loads_with_hash_and_version(tmp_path):
    pack = _pack(tmp_path)
    assert pack.version == "0.0.1-test"
    assert len(pack.hash) == 64            # sha256 hex of the file bytes
    assert set(pack.clauses) == {"T-01", "T-02", "T-03"}
    assert pack.authority_ids == {"EPSDT", "ASHA"}


def test_pack_requires_synthetic_attestation(tmp_path):
    import json
    bad = dict(_PACK_DICT)
    bad.pop("synthetic")
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="synthetic"):
        load_pack(p)


# --- F14: no denial without physician sign-off (structural) -------------------

class TestF14Denial:
    def test_denial_without_signoff_raises(self, tmp_path):
        with pytest.raises(PhysicianSignoffRequired):
            build_denial(_case(), _pack(tmp_path), physician_signoff=None,
                         model_id="test-model", timestamp="2026-07-11T00:00:00Z")

    def test_denial_with_signoff_carries_it(self, tmp_path):
        art = build_denial(
            _case(), _pack(tmp_path),
            physician_signoff=PhysicianSignoff("A. Physician", "MD", "2026-07-11"),
            model_id="test-model", timestamp="2026-07-11T00:00:00Z")
        assert art["signoff"]["name"] == "A. Physician"
        assert art["type"] == "denial"


# --- F15: unsupported clinical claim ------------------------------------------

class TestF15Grounding:
    def test_claim_with_no_cites_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=_good_claims() + [
            Claim("The patient also has severe apraxia.", cites=())])
        v = supervise_determination(_case(), pack, p)
        assert v.decision is Decision.BLOCK
        assert any(f.criterion_id == "COV-F15" for f in v.findings)

    def test_unknown_clause_ref_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=[
            Claim("Meets criteria.", cites=(Cite("clause", "T-99"),))])
        v = supervise_determination(_case(), pack, p)
        assert any(f.criterion_id == "COV-F15" for f in v.findings)

    def test_out_of_bounds_span_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=[
            Claim("x", cites=(Cite("note", "note:9000:9010", quote="x"),))])
        v = supervise_determination(_case(), pack, p)
        assert any(f.criterion_id == "COV-F15" for f in v.findings)


# --- F16: indeterminate never resolves toward denial ---------------------------

class TestF16Indeterminate:
    def test_indeterminate_evidence_escalates(self, tmp_path):
        pack = _pack(tmp_path)
        case = _case()
        case.evidence["T-03"] = "indeterminate"
        outcome = determine(case, pack, model_id="test-model",
                            timestamp="2026-07-11T00:00:00Z")
        assert outcome["decision"] == "ESCALATE"
        assert outcome["artifact"] is None      # never a deny

    def test_deny_outcome_in_proposal_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, kind="determination", outcome="deny")
        v = supervise_determination(_case(), pack, p)
        assert v.decision is Decision.BLOCK
        assert any(f.criterion_id == "COV-F16" for f in v.findings)

    def test_unmet_evidence_escalates_not_denies(self, tmp_path):
        pack = _pack(tmp_path)
        case = _case()
        case.evidence["T-02"] = "unmet"
        outcome = determine(case, pack, model_id="test-model",
                            timestamp="2026-07-11T00:00:00Z")
        assert outcome["decision"] == "ESCALATE" and outcome["artifact"] is None


# --- F17: fabricated authority --------------------------------------------------

class TestF17Authority:
    def test_authority_not_in_pack_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, authorities_cited=("EPSDT", "MADE-UP-BULLETIN-7"))
        v = supervise_determination(_case(), pack, p)
        assert v.decision is Decision.BLOCK
        assert any(f.criterion_id == "COV-F17" for f in v.findings)


# --- F18: provenance -------------------------------------------------------------

class TestF18Provenance:
    @pytest.mark.parametrize("missing", ["pack_version", "pack_hash", "model_id", "timestamp"])
    def test_missing_field_blocks(self, tmp_path, missing):
        pack = _pack(tmp_path)
        prov = dict(_prov(pack))
        prov[missing] = ""
        p = _proposal(pack, provenance=prov)
        v = supervise_determination(_case(), pack, p)
        assert any(f.criterion_id == "COV-F18" for f in v.findings)

    def test_wrong_hash_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        prov = dict(_prov(pack))
        prov["pack_hash"] = "0" * 64
        v = supervise_determination(_case(), pack, _proposal(pack, provenance=prov))
        assert any(f.criterion_id == "COV-F18" for f in v.findings)


# --- F19: frankenfacts ------------------------------------------------------------

class TestF19Frankenfacts:
    def test_span_quote_mismatch_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        ref, _ = _span(_NOTE, "below the 5th percentile")
        p = _proposal(pack, claims=[
            Claim("Assessment shows the 50th percentile.",
                  cites=(Cite("note", ref, quote="the 50th percentile"),))])
        v = supervise_determination(_case(), pack, p)
        assert v.decision is Decision.BLOCK
        assert any(f.criterion_id == "COV-F19" for f in v.findings)

    def test_numeric_contradiction_with_note_facts_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=_good_claims() + [
            Claim("Therapy is provided 5 times per week.",
                  cites=(Cite("clause", "T-03"),),
                  facts={"therapy_frequency_per_week": 5})])
        v = supervise_determination(_case(), pack, p)
        assert any(f.criterion_id == "COV-F19" for f in v.findings)


# --- happy paths -----------------------------------------------------------------

def test_clean_appeal_allows_and_builds(tmp_path):
    pack = _pack(tmp_path)
    p = _proposal(pack)
    v = supervise_determination(_case(), pack, p)
    assert v.decision is Decision.ALLOW, [f.message for f in v.findings]
    art = build_appeal(_case(), pack, p)
    assert art["type"] == "appeal" and "[T-01]" in art["text"]
    assert art["provenance"]["pack_hash"] == pack.hash


def test_mode_b_all_met_approves_with_citations(tmp_path):
    pack = _pack(tmp_path)
    outcome = determine(_case(), pack, model_id="test-model",
                        timestamp="2026-07-11T00:00:00Z")
    assert outcome["decision"] == "ALLOW"
    art = outcome["artifact"]
    assert art["type"] == "approval"
    assert all(f"[{cid}]" in art["text"] for cid in ("T-01", "T-02", "T-03"))
    assert art["provenance"]["pack_version"] == pack.version


# --- the loop ---------------------------------------------------------------------

def test_coverage_loop_block_feeds_back_then_ships(tmp_path):
    pack = _pack(tmp_path)
    seen = []
    bad = _proposal(pack, authorities_cited=("MADE-UP",))
    good = _proposal(pack)

    def propose(feedback):
        seen.append(feedback)
        return bad if feedback is None else good

    r = run_coverage_loop(_case(), pack, propose)
    assert r.shipped is good and len(r.attempts) == 2
    assert "COV-F17" in (seen[1] or "")


def test_coverage_loop_escalate_stops(tmp_path):
    pack = _pack(tmp_path)
    case = _case()
    case.evidence["T-01"] = "indeterminate"
    calls = []

    def propose(feedback):
        calls.append(feedback)
        return _proposal(pack, kind="determination", outcome="approve")

    r = run_coverage_loop(case, pack, propose)
    assert r.escalated and r.shipped is None and len(calls) == 1


def test_coverage_loop_none_escalates(tmp_path):
    pack = _pack(tmp_path)
    r = run_coverage_loop(_case(), pack, lambda f: None)
    assert r.escalated and not r.attempts


class TestQuoteAnchoredCites:
    """Performers cite exact quotes; the deterministic engine locates them."""

    def test_auto_cite_with_exact_quote_resolves(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=[
            Claim("Assessment is below the 5th percentile.",
                  cites=(Cite("note", "auto", quote="below the 5th percentile"),))])
        v = supervise_determination(_case(), pack, p)
        assert v.decision is Decision.ALLOW, [f.message for f in v.findings]

    def test_auto_cite_with_absent_quote_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=[
            Claim("x", cites=(Cite("note", "auto", quote="text that is not there"),))])
        v = supervise_determination(_case(), pack, p)
        assert any(f.criterion_id == "COV-F15" for f in v.findings)

    def test_auto_cite_without_quote_blocks(self, tmp_path):
        pack = _pack(tmp_path)
        p = _proposal(pack, claims=[Claim("x", cites=(Cite("note", "auto"),))])
        v = supervise_determination(_case(), pack, p)
        assert any(f.criterion_id == "COV-F15" for f in v.findings)
