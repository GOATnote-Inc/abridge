"""Attending CLI: encounter/transcript in -> fail-closed triage verdict out.

    python -m attending.cli examples/chest_pain_undertriage.json
    python -m attending.cli --json examples/sepsis_incomplete.json   # machine-readable

Input JSON: {"encounter": {...}, "proposed": {...}}  (see examples/).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .encounter import encounter_from_dict, proposed_from_dict
from .supervisor import supervise
from .verdict import render


def _verdict_to_dict(v) -> dict:
    def conv(o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return {k: conv(val) for k, val in dataclasses.asdict(o).items()}
        if isinstance(o, (list, tuple)):
            return [conv(x) for x in o]
        return o
    return {
        "encounter_id": v.encounter_id,
        "decision": v.decision.value,
        "proposed_esi": v.proposed_esi,
        "attending_esi": v.attending_esi,
        "recommended_esi": v.recommended_esi,
        "confidence": {
            "point": v.confidence.point,
            "most_acute": v.confidence.most_acute,
            "least_acute": v.confidence.least_acute,
            "p_point": v.confidence.p_point,
            "basis": v.confidence.basis,
        },
        "findings": [conv(f) for f in v.findings],
        "detections": [conv(d) for d in v.detections],
        "esi_reasons": list(v.esi_reasons),
        "ruleset_version": v.ruleset_version,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="attending", description=__doc__)
    ap.add_argument("input", help="path to encounter JSON, or '-' for stdin")
    ap.add_argument("--json", action="store_true", help="emit JSON verdict")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--llm", action="store_true",
                    help="enable Fable 5 augmentation of the anchoring/hallucination "
                         "detectors (needs ANTHROPIC_API_KEY in .env)")
    args = ap.parse_args(argv)

    if args.llm:
        import os
        os.environ["ATTENDING_LLM_AUGMENT"] = "1"

    raw = sys.stdin.read() if args.input == "-" else open(args.input).read()
    data = json.loads(raw)
    enc = encounter_from_dict(data.get("encounter", data))
    proposed = proposed_from_dict(data.get("proposed"))

    v = supervise(enc, proposed)
    if args.json:
        print(json.dumps(_verdict_to_dict(v), indent=2))
    else:
        print(render(v, color=not args.no_color))
    # Exit code doubles as a gate: 0 allow, 2 block, 3 escalate.
    return {"ALLOW": 0, "BLOCK": 2, "ESCALATE": 3}[v.decision.value]


if __name__ == "__main__":
    raise SystemExit(main())
