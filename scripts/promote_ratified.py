#!/usr/bin/env python3
"""Clinical-review-packet promotion — inert until the physician's "ratified".

Dry-run (default): executes every quarantined goldset candidate through the
real engine against the current drafts, normalizes hash/criterion formats in
memory, and reports per-candidate actual-vs-expected plus anything that
depends on an unresolved ratification ruling. Changes nothing on disk.

Execute (--ratified --name ... --date ...): performs the promotion in the
working tree, to be committed as ONE commit with a Ratified-by trailer:
  1. flip both pack `status` fields to the physician-reviewed string
     (state-plan-variable labels preserved verbatim in clause text);
  2. recompute pack sha256 (status flip changes bytes) and re-pin the hash
     in every candidate/fixture provenance (raw hex — engine format);
  3. map descriptive criterion ids to engine ids (COV-F14..F19);
  4. write evaluation/goldset_coverage.jsonl with status "ratified";
  5. leave case/pack/fixture files in place (paths are load-bearing for the
     demo, gateway presets, and exhibit) — quarantine is expressed by the
     status field, which every consumer surfaces.

Item-4 conditionality: candidates expecting a SIGNED deny on indeterminate
evidence to ESCALATE (rather than BLOCK) require the physician's Item-4
ruling to confirm that posture; pass --item4-escalate to include them,
otherwise they are promoted with the engine's current BLOCK expectation and
the difference is reported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from attending import coverage as cov  # noqa: E402
from attending import evaluate_coverage as ec  # noqa: E402

DRAFTS = REPO / "drafts" / "coverage"
OUT = REPO / "evaluation" / "goldset_coverage.jsonl"
PACKS = ["pack_peds_speech_therapy.json", "pack_peds_dme_adaptive_equipment.json"]

CRITERION_MAP = {
    "COV-unsupported-claim": "COV-F15",
    "COV-out-of-range-span": "COV-F15",
    "COV-fabricated-authority": "COV-F17",
    "COV-missing-provenance": "COV-F18",
    "COV-indeterminate-evidence": "COV-F16",
    "COV-auto-deny": "COV-F16",
    "COV-auto-deny-no-signoff": "COV-F16",
    "COV-frankenfact": "COV-F19",
    "COV-vague-denial": "COV-F15",
    "COV-vague-denial-audit": "COV-F15",
    "COV-epsdt-floor": "COV-F16",
}


def _normalize(rec: dict, pack_hashes: dict[str, str]) -> dict:
    rec = json.loads(json.dumps(rec))  # deep copy
    prov = rec.get("proposal", {}).get("provenance")
    if prov:
        h = str(prov.get("pack_hash", ""))
        if h.startswith("sha256:"):
            h = h.split(":", 1)[1]
        # re-pin to the CURRENT bytes of the referenced pack
        prov["pack_hash"] = pack_hashes.get(rec.get("pack_ref", ""), h)
    # Quote-anchored spans: materialize missing quotes ONCE from the authored
    # offsets/turn numbers, then re-reference as "auto" so the deterministic
    # engine locates them — authored offsets stop being load-bearing, and
    # every cite becomes self-verifying (empty quotes can hide frankenfacts).
    ref_case = rec.get("case_ref")
    note = transcript = ""
    turns: list = []
    if isinstance(ref_case, str):
        raw_case = json.loads((DRAFTS / f"{ref_case}.json").read_text())
        note = raw_case.get("clinical_note", "")
        turns = raw_case.get("encounter_transcript", [])
        transcript = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
    elif isinstance(ref_case, dict):
        note = ref_case.get("summary", "")
    import re as _re
    for claim in rec.get("proposal", {}).get("claims", []):
        for cite in claim.get("cites", []):
            if cite.get("type") not in ("note", "transcript"):
                continue
            if not cite.get("quote"):
                src = note if cite["type"] == "note" else transcript
                m = _re.match(r"^(?:note|transcript):(\d+):(\d+)$",
                              str(cite.get("ref", "")))
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    if 0 <= a < b <= len(src):
                        cite["quote"] = src[a:b]
                else:
                    m2 = _re.match(r"^transcript:(\d+)$", str(cite.get("ref", "")))
                    if m2 and turns:
                        n = int(m2.group(1))
                        turn = next((t for t in turns if t.get("turn") == n), None)
                        if turn:
                            cite["quote"] = turn["text"]
            if cite.get("quote"):
                cite["ref"] = "auto"
    crit = rec.get("expect", {}).get("criterion")
    clause_ids = {c["id"] for p in PACKS
                  for c in json.loads((DRAFTS / p).read_text()).get("clauses", [])}
    if crit in CRITERION_MAP:
        rec["expect"]["criterion"] = CRITERION_MAP[crit]
    elif crit in clause_ids:
        # Clause-cited intent (e.g. the EPSDT floor): the engine finding that
        # fires is the outcome gate; preserve clinical intent in the note.
        rec["note"] = rec.get("note", "") + f" [intent criterion: {crit}]"
        rec["expect"]["criterion"] = "COV-F16"
    return rec


def _pack_hashes() -> dict[str, str]:
    return {p.removesuffix(".json"):
            hashlib.sha256((DRAFTS / p).read_bytes()).hexdigest()
            for p in PACKS}


def _candidates() -> list[dict]:
    return [json.loads(x) for x in
            (DRAFTS / "goldset_candidates.jsonl").read_text().splitlines()
            if x.strip()]


def dry_run(item4_escalate: bool) -> int:
    hashes = _pack_hashes()
    ec._PACK_CACHE.clear()
    needs_ruling, mismatches = [], []
    print(f"{'id':8s} {'expect':22s} {'actual':10s} finding_ids")
    for raw in _candidates():
        rec = _normalize(raw, hashes)
        verdict = cov.supervise_determination(
            ec._load_case(rec), ec._load_pack(rec), ec._proposal(rec))
        exp = rec["expect"]["decision"]
        got = verdict.decision.value
        ids = sorted(f.criterion_id for f in verdict.findings if f.criterion_id)
        crit = rec["expect"].get("criterion")
        signoff = rec["proposal"].get("physician_signoff")
        flag = ""
        if exp == "ESCALATE" and got == "BLOCK" and signoff:
            flag = "ITEM-4 RULING NEEDED" if not item4_escalate else "item4:apply"
            needs_ruling.append(rec["id"])
        elif got != exp or (crit and crit not in ids):
            mismatches.append(rec["id"])
            flag = "MISMATCH"
        print(f"{rec['id']:8s} {str(exp):22s} {got:10s} {ids} "
              f"crit={crit} {flag}")
    print(f"\npack hashes (current bytes): "
          f"{ {k: v[:12] for k, v in hashes.items()} }")
    print(f"needs Item-4 ruling: {needs_ruling or 'none'}")
    print(f"true mismatches: {mismatches or 'none'}")
    return 1 if mismatches else 0


def execute(name: str, date: str, item4_escalate: bool) -> int:
    status = (f"physician-reviewed ({name}, {date}; single-reviewer, "
              "demonstration scope — state-plan variables remain "
              "site-configurable and so labeled) — board governance pending")
    for p in PACKS:
        path = DRAFTS / p
        data = json.loads(path.read_text())
        data["status"] = status
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    hashes = _pack_hashes()  # AFTER the status flip

    # Re-pin embedded hashes in the adversarial fixtures (drafts stay in
    # place; their provenance must match the ratified pack bytes).
    fx_path = DRAFTS / "adversarial_fixtures.json"
    fx = json.loads(fx_path.read_text())
    for f in fx.get("fixtures", []):
        prov = f.get("proposal", {}).get("provenance")
        if prov and prov.get("pack_hash"):
            prov["pack_hash"] = hashes.get(
                fx.get("pack_ref", "pack_peds_speech_therapy"),
                prov["pack_hash"])
    fx_path.write_text(json.dumps(fx, indent=1, ensure_ascii=False) + "\n")

    promoted = []
    for raw in _candidates():
        rec = _normalize(raw, hashes)
        if (rec["expect"]["decision"] == "ESCALATE"
                and rec["proposal"].get("physician_signoff")
                and not item4_escalate):
            rec["expect"]["decision"] = "BLOCK"
            rec["expect"]["criterion"] = "COV-F16"
            rec["note"] = (rec.get("note", "")
                           + " [expectation held at BLOCK: Item-4 ruling not applied]")
        rec["status"] = f"ratified ({name}, {date})"
        promoted.append(rec)
    with open(OUT, "w") as fh:
        for rec in promoted:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"promoted {len(promoted)} cases -> {OUT.relative_to(REPO)}")
    print("next: run the harness, make check, both demo flows, then commit "
          "with the Ratified-by trailer.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ratified", action="store_true",
                    help="execute the promotion (requires --name and --date)")
    ap.add_argument("--name")
    ap.add_argument("--date")
    ap.add_argument("--item4-escalate", action="store_true",
                    help="physician ruled: signed deny on indeterminate "
                         "evidence ESCALATES (enables those expectations)")
    args = ap.parse_args()
    if args.ratified:
        if not (args.name and args.date):
            ap.error("--ratified requires --name and --date")
        return execute(args.name, args.date, args.item4_escalate)
    return dry_run(args.item4_escalate)


if __name__ == "__main__":
    raise SystemExit(main())
