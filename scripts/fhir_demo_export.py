#!/usr/bin/env python3
"""Regenerate the committed FHIR R4 demo export deterministically.

Runs the committed demo fixture through the real supervisor and exports the
triage verdict plus a coverage verdict as FHIR bundles. `recorded` is a fixed
timestamp (replay purity — the export must be byte-identical on every run;
tests/test_fhir.py pins this file against regeneration).

Usage: fhir_demo_export.py [--stdout]   (default: writes evaluation/fhir_export_demo.json)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from attending import fhir, supervisor  # noqa: E402
from attending.encounter import (  # noqa: E402
    ProposedTriage,
    encounter_from_dict,
)

_RECORDED = "2026-07-12T00:00:00Z"  # fixed: the export is a pinned artifact
_MODEL = "deterministic (no LLM in the export path)"


def main() -> int:
    fixture = json.loads(
        (REPO / "fixtures" / "demo_chest_pain.json").read_text())
    enc_dict = dict(fixture["encounter"])
    enc_dict["synthetic"] = fixture["synthetic"]  # attestation is top-level
    encounter = encounter_from_dict(fixture["encounter"])
    draft = fixture["stage_a"]["drafts"][0]
    proposal = ProposedTriage(
        esi_level=draft.get("esi_level"),
        orders=tuple(draft.get("orders", ())),
        disposition=draft.get("disposition"),
        rationale=draft.get("rationale"),
    )
    verdict = supervisor.supervise(encounter, proposal)
    triage_bundle = fhir.triage_export(
        verdict, enc_dict, recorded=_RECORDED, model_id=_MODEL)

    out = {
        "_note": (
            "FHIR R4 demonstration export — synthetic data only (every "
            "resource carries meta.security HTEST). Not a certified EHR "
            "interface; profile conformance not claimed. Regenerate: "
            "scripts/fhir_demo_export.py"
        ),
        "triage": triage_bundle,
    }
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if "--stdout" in sys.argv:
        sys.stdout.write(text)
    else:
        (REPO / "evaluation" / "fhir_export_demo.json").write_text(text)
        print(f"wrote evaluation/fhir_export_demo.json "
              f"({len(text.encode())} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
