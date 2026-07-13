"""Synthetic chart presets for the MCP surface (and the coverage fixture
loader) — the same shapes the playground's chart() builder produces, so a
judge's MCP session exercises exactly what the web playground exercises.
Stdlib + sitrep only; no MCP imports here."""

from __future__ import annotations

import json
from pathlib import Path

from sitrep.state import EncounterState, Order, Result

_PRESETS = ("none", "normal", "critical", "discussed", "escalated")


def build_chart(preset: str) -> tuple[EncounterState, list[str]]:
    """Chart preset -> (EncounterState, refs). Fail-closed: unknown preset
    raises rather than guessing."""
    if preset not in _PRESETS:
        raise ValueError(
            f"unknown chart_preset {preset!r} — one of {_PRESETS}")
    s = EncounterState(patient={"age": 58, "sex": "M",
                                "chief_complaint": "chest pressure"})
    if preset == "none":
        return s, []
    if preset == "normal":
        s.add_order(Order(id="ord-cbc", name="cbc", status="completed"))
        s.add_result(Result(id="res-cbc", order_id="ord-cbc", name="cbc",
                            value="normal", flag="normal", status="final",
                            released=True, viewed=False, discussed=False))
        return s, ["res-cbc"]
    s.add_order(Order(id="ord-troponin", name="troponin", status="completed"))
    s.add_result(Result(id="res-troponin", order_id="ord-troponin",
                        name="troponin", value="0.31", flag="critical",
                        status="final", released=True, viewed=True,
                        discussed=(preset in ("discussed", "escalated"))))
    if preset == "escalated":
        s.escalate("patient viewed critical troponin")
    return s, ["res-troponin"]


def load_coverage_fixture():
    """The committed synthetic pediatric speech-therapy case + DRAFT pack."""
    from . import coverage as cov
    drafts = Path(__file__).resolve().parents[2] / "drafts" / "coverage"
    pack = cov.load_pack(drafts / "pack_peds_speech_therapy.json")
    raw = json.loads((drafts / "case_peds_speech_denial.json").read_text())
    case = cov.CoverageCase(
        case_id=raw["id"], synthetic=True, note=raw["clinical_note"],
        transcript="\n".join(f"{t['speaker']}: {t['text']}"
                             for t in raw.get("encounter_transcript", [])),
        note_facts=raw["note_facts"],
        evidence={cid: "met" for cid in pack.clauses})
    return case, pack
