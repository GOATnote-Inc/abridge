"""Fail-closed regression harness over a synthetic triage gold set
(physician-owned; clinical sign-off pending — see knowledge.APPROVAL_STATUS).

The cardinal safety metric is the FALSE-NEGATIVE rate: a case the gold set says
must be stopped (BLOCK/ESCALATE) or up-triaged, that Attending instead ALLOWs
or under-triages. FN MUST be 0 -- an unsafe proposal reaching a patient is the
one failure mode this whole system exists to prevent. False positives
(over-blocking a safe proposal) are tracked too, but are a nuisance, not a
safety event.

    python -m attending.evaluate                 # human report, exit 1 if FN>0
    python -m attending.evaluate --json          # machine-readable
    python -m attending.evaluate path/to.jsonl   # custom gold set
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from .encounter import encounter_from_dict, proposed_from_dict
from .supervisor import supervise
from .verdict import Decision

_DEFAULT_GOLDSET = Path(__file__).resolve().parents[2] / "evaluation" / "goldset.jsonl"
_STOP = {Decision.BLOCK.value, Decision.ESCALATE.value}


@dataclass
class CaseResult:
    id: str
    expected_decision: str
    got_decision: str
    expected_esi: int | None
    got_esi: int
    expected_criterion: str | None
    criterion_matched: bool | None
    false_negative: bool     # unsafe miss -- the cardinal sin
    false_positive: bool     # over-block of a safe proposal
    ok: bool


def _load(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def evaluate(path: Path = _DEFAULT_GOLDSET) -> list[CaseResult]:
    results = []
    for c in _load(path):
        enc = encounter_from_dict(c["encounter"])
        proposed = proposed_from_dict(c.get("proposed"))
        exp = c.get("expect", {})
        v = supervise(enc, proposed)

        got_d = v.decision.value
        # `decision` may be a single value or a list of acceptable outcomes
        # (e.g. ["BLOCK","ESCALATE"] when either safe stop is correct).
        raw_d = exp.get("decision")
        exp_decisions = (set(raw_d) if isinstance(raw_d, list)
                         else ({raw_d} if raw_d else set()))
        exp_d = raw_d
        exp_esi = exp.get("recommended_esi")
        exp_crit = exp.get("criterion")

        crit_matched = None
        if exp_crit is not None:
            ids = {f.criterion_id for f in v.findings} | {
                f"ATT-{d.detector}" for d in v.detections if d.fired}
            crit_matched = exp_crit in ids

        # False negative: gold requires a stop (no ALLOW among acceptable
        # outcomes) or a more-acute level, but we let it through / under-triaged.
        fn = False
        requires_stop = bool(exp_decisions) and exp_decisions.issubset(_STOP)
        if requires_stop and got_d == Decision.ALLOW.value:
            fn = True
        if exp_esi is not None and v.recommended_esi > exp_esi:
            fn = True  # recommended less acute than required == unsafe miss

        # False positive: gold says ALLOW only, we stopped it.
        fp = exp_decisions == {Decision.ALLOW.value} and got_d in _STOP

        decision_ok = (not exp_decisions) or (got_d in exp_decisions)
        esi_ok = (exp_esi is None) or (v.recommended_esi == exp_esi)
        crit_ok = crit_matched in (None, True)
        ok = decision_ok and esi_ok and crit_ok and not fn and not fp

        results.append(CaseResult(
            id=c["id"], expected_decision=exp_d, got_decision=got_d,
            expected_esi=exp_esi, got_esi=v.recommended_esi,
            expected_criterion=exp_crit, criterion_matched=crit_matched,
            false_negative=fn, false_positive=fp, ok=ok))
    return results


def summarize(results: list[CaseResult]) -> dict:
    n = len(results)
    return {
        "n": n,
        "passed": sum(r.ok for r in results),
        "false_negatives": sum(r.false_negative for r in results),
        "false_positives": sum(r.false_positive for r in results),
        "fn_rate": sum(r.false_negative for r in results) / n if n else 0.0,
        "fp_rate": sum(r.false_positive for r in results) / n if n else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="attending-eval", description=__doc__)
    ap.add_argument("goldset", nargs="?", default=str(_DEFAULT_GOLDSET))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = evaluate(Path(args.goldset))
    s = summarize(results)

    if args.json:
        print(json.dumps({
            "summary": s,
            "cases": [r.__dict__ for r in results]}, indent=2))
    else:
        print(f"Gold set: {args.goldset}  ({s['n']} cases)\n")
        for r in results:
            mark = "PASS" if r.ok else ("FN!!" if r.false_negative else
                                        ("FP" if r.false_positive else "MISS"))
            esi = f" esi {r.got_esi}(exp {r.expected_esi})" if r.expected_esi else ""
            crit = ""
            if r.expected_criterion:
                crit = f" crit={r.expected_criterion}:{'ok' if r.criterion_matched else 'MISSING'}"
            print(f"  [{mark}] {r.id}: {r.got_decision}"
                  f"(exp {r.expected_decision}){esi}{crit}")
        print(f"\n  passed {s['passed']}/{s['n']}   "
              f"FALSE-NEGATIVES {s['false_negatives']} (must be 0)   "
              f"false-positives {s['false_positives']}")
        if s["false_negatives"]:
            print("\n  \033[91mFAIL: unsafe proposal(s) not stopped — "
                  "fail-closed contract violated.\033[0m")
        elif s["passed"] == s["n"]:
            print("\n  \033[92mAll cases pass; FN=0.\033[0m")

    return 1 if s["false_negatives"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
