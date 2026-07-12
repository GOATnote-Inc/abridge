"""Coverage-surface goldset harness (ratified cases only).

Mirrors the triage harness semantics exactly: the cardinal metric is the
false-negative rate — a case the gold set says must be stopped that the
supervisor ALLOWs — reported with the exact Clopper-Pearson upper bound.

Reads evaluation/goldset_coverage.jsonl, which EXISTS ONLY AFTER the
physician has ratified the quarantined candidates through the clinical-
review-packet flow (scripts/promote_ratified.py). Absent file -> clean
no-op exit 0, so wiring this into `make goldset`/CI before ratification
changes nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import coverage as cov
from .evaluate import binom_upper
from .verdict import Decision

_REPO = Path(__file__).resolve().parents[2]
_GOLDSET = _REPO / "evaluation" / "goldset_coverage.jsonl"
_DRAFTS = _REPO / "drafts" / "coverage"
_STOP = {Decision.BLOCK.value, Decision.ESCALATE.value}


def _evidence(rec: dict) -> dict:
    # Fail-closed default: absent evidence is INDETERMINATE, never "met".
    # A candidate that needs met clauses must say so explicitly — the
    # physician rules per-clause evidence during ratification.
    return (rec.get("evidence")
            or {cid: "indeterminate" for cid in _load_pack(rec).clauses})


def _load_case(rec: dict) -> cov.CoverageCase:
    ref = rec["case_ref"]
    if isinstance(ref, dict):  # inline mini-case (e.g. the DME cross-pack one)
        return cov.CoverageCase(
            case_id=ref.get("service", "inline-case"), synthetic=True,
            note=ref.get("summary", ""), transcript="",
            note_facts=ref.get("note_facts", {}),
            evidence=_evidence(rec),
        )
    raw = json.loads((_DRAFTS / f"{ref}.json").read_text())
    return cov.CoverageCase(
        case_id=raw["id"], synthetic=True, note=raw["clinical_note"],
        transcript="\n".join(f"{t['speaker']}: {t['text']}"
                             for t in raw.get("encounter_transcript", [])),
        note_facts=raw.get("note_facts", {}),
        evidence=_evidence(rec),
    )


_PACK_CACHE: dict[str, cov.CoveragePack] = {}


def _load_pack(rec: dict) -> cov.CoveragePack:
    ref = rec["pack_ref"]
    if ref not in _PACK_CACHE:
        _PACK_CACHE[ref] = cov.load_pack(_DRAFTS / f"{ref}.json")
    return _PACK_CACHE[ref]


def _proposal(rec: dict) -> cov.CoverageProposal:
    p = rec["proposal"]
    return cov.CoverageProposal(
        kind=p.get("kind", "appeal"),
        outcome=p.get("outcome"),
        claims=tuple(
            cov.Claim(c["text"],
                      cites=tuple(cov.Cite(x["type"], x.get("ref", "auto"),
                                           quote=x.get("quote", ""))
                                  for x in c.get("cites", [])),
                      facts=c.get("facts", {}))
            for c in p.get("claims", [])),
        authorities_cited=tuple(p.get("authorities_cited", [])),
        provenance=dict(p.get("provenance", {})),
        physician_signoff=p.get("physician_signoff"),  # Item-4 state travels
    )


def evaluate(path: Path = _GOLDSET) -> list[dict]:
    results = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        verdict = cov.supervise_determination(
            _load_case(rec), _load_pack(rec), _proposal(rec))
        exp = rec["expect"]
        raw_d = exp.get("decision")
        exp_decisions = set(raw_d) if isinstance(raw_d, list) else {raw_d}
        got = verdict.decision.value
        crit = exp.get("criterion")
        ids = {f.criterion_id for f in verdict.findings}
        crit_ok = crit is None or crit in ids
        requires_stop = exp_decisions <= _STOP
        fn = requires_stop and got == Decision.ALLOW.value
        fp = exp_decisions == {Decision.ALLOW.value} and got in _STOP
        ok = (got in exp_decisions) and crit_ok and not fn and not fp
        results.append({"id": rec["id"], "expected": raw_d, "got": got,
                        "criterion": crit, "criterion_ok": crit_ok,
                        "finding_ids": sorted(x for x in ids if x),
                        "false_negative": fn, "false_positive": fp, "ok": ok})
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not _GOLDSET.is_file():
        print("coverage goldset: none ratified yet (drafts remain quarantined) "
              "— nothing to evaluate")
        return 0
    results = evaluate()
    n = len(results)
    fn = sum(r["false_negative"] for r in results)
    fp = sum(r["false_positive"] for r in results)
    passed = sum(r["ok"] for r in results)
    if args.json:
        print(json.dumps({"n": n, "passed": passed, "fn": fn, "fp": fp,
                          "cases": results}, indent=2))
    else:
        for r in results:
            mark = "PASS" if r["ok"] else ("FN!!" if r["false_negative"]
                                           else ("FP" if r["false_positive"] else "MISS"))
            print(f"  [{mark}] {r['id']}: {r['got']} (exp {r['expected']}) "
                  f"crit={r['criterion']}:{'ok' if r['criterion_ok'] else 'MISSING'}")
        print(f"\n  coverage goldset: {passed}/{n} passed   FALSE-NEGATIVES {fn} "
              f"(must be 0)   false-positives {fp}")
        print(f"  FN rate {fn/n:.1%} (95% CI upper bound "
              f"{binom_upper(fn, n):.1%}, Clopper-Pearson, n={n})")
    # Every expectation is a regression pin: ANY mismatch fails, not just the
    # cardinal FN (a BLOCK-vs-ESCALATE flip is still a behavior change).
    return 1 if passed != n else 0


if __name__ == "__main__":
    raise SystemExit(main())
