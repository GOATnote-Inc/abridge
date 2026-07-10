"""One encounter, both surfaces — the Attending demo driver.

Stage A (decision): an agent proposes triage; Attending blocks the under-triage
citing ESI/ACEP and the tripped detectors; the revised proposal ships and its
orders are written to the chart.

Stage B (communication): the journey panel is live from the first order —
the patient always has a populated "next step" box. The troponin results
CRITICAL and auto-releases (post-Cures); the panel updates WITH the result as
a labeled, guideline-attributed result_context rendering (gated, shipped);
the agent's conversational reply — subtly minimizing — is blocked; the
disclosure gap pages the team for the bedside discussion; only after the
documented discussion does a conversational reply ship.

Modes:
  replay (default) — scripted drafts from the fixture; pure function of the
      fixture (no clock, randomness, or network) so the demo replays
      byte-identically (INVERSION F11).
  --live — the drafts come from the Fable 5 performer (`attending.agent`);
      the choreography and every gate are identical.

    python -m attending.demo                # replay, terminal narrative
    python -m attending.demo --json         # machine-readable transcript
    python -m attending.demo --live         # real model behind the same gates
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sitrep.state import EncounterState, Order, Result

from . import agent, pathway
from .cli import _verdict_to_dict
from .encounter import Encounter, encounter_from_dict, proposed_from_dict
from .loop import (
    RenderingLoopResult,
    TriageLoopResult,
    run_rendering_loop,
    run_triage_loop,
)
from .verdict import Decision

_DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "demo_chest_pain.json"


# --- performers --------------------------------------------------------------


def _scripted_proposer(drafts: list[dict]):
    """Replay performer: yields fixture drafts in order; None when exhausted."""
    queue = [proposed_from_dict(d) for d in drafts]

    def propose(enc: Encounter, feedback: str | None):
        return queue.pop(0) if queue else None

    return propose


def _scripted_drafter(texts: list[str]):
    queue = list(texts)

    def draft(feedback: str | None):
        return queue.pop(0) if queue else None

    return draft


# --- transcript helpers -------------------------------------------------------


def _comms_verdict_dict(v: Any) -> dict:
    return {
        "audience": v.audience,
        "decision": v.decision.value,
        "findings": [
            {
                "criterion_id": f.criterion_id,
                "severity": f.severity.value,
                "message": f.message,
                "citation": f.citation,
                "evidence": f.evidence,
            }
            for f in v.findings
        ],
    }


def _triage_result_dict(r: TriageLoopResult) -> dict:
    return {
        "attempts": [
            {
                "proposal": {
                    "esi_level": a.proposal.esi_level,
                    "orders": list(a.proposal.orders),
                    "disposition": a.proposal.disposition,
                    "rationale": a.proposal.rationale,
                },
                "verdict": _verdict_to_dict(a.verdict),
            }
            for a in r.attempts
        ],
        "shipped": None if r.shipped is None else {
            "esi_level": r.shipped.esi_level,
            "orders": list(r.shipped.orders),
            "disposition": r.shipped.disposition,
        },
        "escalated": r.escalated,
        "reason": r.reason,
    }


def _rendering_result_dict(r: RenderingLoopResult) -> dict:
    return {
        "attempts": [
            {"text": a.text, "verdict": _comms_verdict_dict(a.verdict)}
            for a in r.attempts
        ],
        "shipped": r.shipped,
        "escalated": r.escalated,
        "reason": r.reason,
        "state_findings": [f.criterion_id for f in r.state_findings],
    }


def _collect_summary(transcript: dict) -> dict:
    criteria: list[str] = []
    citations: list[str] = []
    blocked = 0
    shipped = 0
    unsafe_shipped = 0

    def eat_verdict(vd: dict, decision_key: str = "decision") -> None:
        nonlocal blocked
        if vd[decision_key] != Decision.ALLOW.value:
            blocked += 1
        for f in vd.get("findings", []):
            cid = f.get("criterion_id")
            if cid and cid not in criteria:
                criteria.append(cid)
            cite = f.get("citation")
            if cite and cite not in citations:
                citations.append(cite)

    stage_a = transcript["stage_a"]
    for a in stage_a["attempts"]:
        eat_verdict(a["verdict"])
    if stage_a["shipped"]:
        shipped += 1
        if stage_a["attempts"][-1]["verdict"]["decision"] != Decision.ALLOW.value:
            unsafe_shipped += 1
    for key in ("result_context_panel", "first_reply", "physician_page",
                "final_reply"):
        r = transcript.get("stage_b", {}).get(key)
        if not r:
            continue
        for a in r["attempts"]:
            eat_verdict(a["verdict"])
        if r["shipped"] is not None:
            shipped += 1
            if a["verdict"]["decision"] != Decision.ALLOW.value:
                unsafe_shipped += 1
    return {
        "artifacts_shipped": shipped,
        "verdicts_blocked": blocked,
        "criteria_tripped": criteria,
        "citations": citations,
        "unsafe_artifacts_shipped": unsafe_shipped,
    }


# --- the choreography ---------------------------------------------------------


def run_demo(fixture: dict, live: bool = False) -> dict:
    enc = encounter_from_dict(fixture["encounter"])
    stage_a_cfg = fixture["stage_a"]
    stage_b_cfg = fixture["stage_b"]

    # ---- Stage A: decision surface.
    if live:
        propose = agent.propose_triage
    else:
        propose = _scripted_proposer(stage_a_cfg["drafts"])
    triage = run_triage_loop(enc, propose, max_revisions=len(stage_a_cfg["drafts"]))

    transcript: dict = {
        "fixture": fixture["id"],
        "synthetic": True,  # all demo output derives from attested fixtures
        "mode": "live" if live else "replay",
        # Evidence provenance: which model drafted (live mode only; replay is
        # scripted and stays a pure function of the fixture).
        **({"performer_model": agent.agent_model()} if live else {}),
        "title": fixture.get("title", ""),
        # Verbatim encounter for UI consumers (nurse arrival card: CC + vitals).
        "encounter": fixture["encounter"],
        "stage_a": _triage_result_dict(triage),
        "stage_b": {},
    }

    if triage.shipped is None:
        transcript["stage_b"] = {
            "skipped": "decision surface escalated to a human — no automated "
            "communication proceeds"
        }
        transcript["summary"] = _collect_summary(transcript)
        return transcript

    # ---- Chart state: shipped orders. The journey panel is live from the
    # first order — the patient always has a populated "next step" box.
    state = EncounterState(patient={"encounter_id": enc.encounter_id})
    for order in triage.shipped.orders:
        state.add_order(Order(id=f"ord-{order}", name=order))
    journey_pre = pathway.chest_pain_journey(state)

    # ---- The result lands and auto-releases (post-Cures reality).
    state.add_result(Result(
        id="res-troponin", order_id="ord-troponin", name="troponin",
        value="0.31", flag="critical", status="final",
        released=True, viewed=True, discussed=False,
    ))

    # ---- The journey panel updates WITH the result: a labeled, not-advice,
    # guideline-attributed next-steps panel (kind="result_context") travels
    # with the released result. It passes the same gates as any patient
    # rendering; the disclosure gap still pages the team below, and
    # conversational replies stay blocked until the bedside discussion.
    journey_post = pathway.chest_pain_journey(state)
    panel = run_rendering_loop(
        state, "patient", ["res-troponin", "ord-ecg", "ord-troponin"],
        _scripted_drafter([journey_post.patient_text]),
        max_revisions=0, kind="result_context")

    # ---- Stage B, first reply: blocked by text gates AND the disclosure gap.
    if live:
        def first_draft(feedback: str | None):
            return agent.draft_patient_message(enc, stage_b_cfg["event"], feedback)
    else:
        first_draft = _scripted_drafter([stage_b_cfg["draft_blocked"]])
    first_reply = run_rendering_loop(
        state, "patient", ["res-troponin"], first_draft, max_revisions=0)

    # The disclosure gap must page the team — that is the gate's meaning.
    state.escalate("patient viewed critical troponin with no documented discussion")
    page = run_rendering_loop(
        state, "physician", ["res-troponin"],
        _scripted_drafter([stage_b_cfg["physician_page"]]), max_revisions=0)

    # Human action the system cannot substitute: the bedside discussion.
    state.mark_discussed("res-troponin")

    # ---- Stage B, final reply: same gates, now satisfiable.
    if live:
        situation = (
            stage_b_cfg["event"]
            + " UPDATE: a clinician has now discussed the result with the patient "
            "at the bedside, and the care team has been notified."
        )

        def final_draft(feedback: str | None):
            return agent.draft_patient_message(enc, situation, feedback)
    else:
        final_draft = _scripted_drafter([stage_b_cfg["draft_final"]])
    final_reply = run_rendering_loop(
        state, "patient", ["res-troponin"], final_draft, max_revisions=2)

    transcript["stage_b"] = {
        "event": stage_b_cfg["event"],
        "journey_pre": pathway.journey_to_dict(journey_pre),
        "journey_post": pathway.journey_to_dict(journey_post),
        "result_context_panel": _rendering_result_dict(panel),
        "first_reply": _rendering_result_dict(first_reply),
        "escalation": "care team paged — disclosure gap",
        "physician_page": _rendering_result_dict(page),
        "discussion": stage_b_cfg["discussion"],
        "final_reply": _rendering_result_dict(final_reply),
    }
    transcript["summary"] = _collect_summary(transcript)
    return transcript


# --- terminal narrative --------------------------------------------------------

_RESET, _BOLD, _DIM = "\033[0m", "\033[1m", "\033[2m"
_RED, _GREEN, _YELLOW = "\033[91m", "\033[92m", "\033[93m"


def _print_comms(label: str, r: dict, color: bool) -> None:
    def c(s: str, code: str) -> str:
        return f"{code}{s}{_RESET}" if color else s

    print(c(f"--- {label} ---", _BOLD))
    for a in r["attempts"]:
        v = a["verdict"]
        tone = _GREEN if v["decision"] == "ALLOW" else _RED
        print(f'  draft: "{a["text"]}"')
        print(c(f"  -> {v['decision']}", tone))
        for f in v["findings"]:
            print(f"       [{f['severity']}] {f['criterion_id']}: {f['message']}")
            if f.get("citation"):
                print(c(f"           cite: {f['citation']}", _DIM))
    if r["escalated"]:
        print(c(f"  == {r['reason']}", _YELLOW))
    elif r["shipped"] is not None:
        print(c("  == shipped", _GREEN))
    print()


def render_transcript(t: dict, color: bool = True) -> None:
    def c(s: str, code: str) -> str:
        return f"{code}{s}{_RESET}" if color else s

    print(c(f"\n=== {t['title']}  [{t['mode']}] ===\n", _BOLD))
    print(c(f"STAGE A — {'decision surface (triage)'}", _BOLD))
    for i, a in enumerate(t["stage_a"]["attempts"], 1):
        p = a["proposal"]
        print(f"\n  attempt {i}: ESI {p['esi_level']}, orders={p['orders']}, "
              f"dispo={p['disposition']}")
        print(f'  rationale: "{p["rationale"]}"')
        # Reuse nothing fancy: decision + findings from the dict.
        v = a["verdict"]
        tone = _GREEN if v["decision"] == "ALLOW" else _RED
        print(c(f"  -> {v['decision']}  (recommended ESI {v['recommended_esi']})", tone))
        for f in v["findings"]:
            sev = getattr(f["severity"], "value", f["severity"])
            print(f"       [{sev}] {f['criterion_id']}: {f['message']}")
            if f.get("citation"):
                print(c(f"           cite: {f['citation']}", _DIM))
    if t["stage_a"]["escalated"]:
        print(c(f"\n  == {t['stage_a']['reason']}", _YELLOW))
    else:
        s = t["stage_a"]["shipped"]
        print(c(f"\n  == shipped: ESI {s['esi_level']}, orders={s['orders']}, "
                f"dispo={s['disposition']}", _GREEN))
    print()

    sb = t["stage_b"]
    if "skipped" in sb:
        print(c(f"STAGE B skipped: {sb['skipped']}", _YELLOW))
    else:
        print(c("STAGE B — communication surface", _BOLD))
        print(f"\n  {sb['event']}\n")
        _print_comms("patient reply, first draft", sb["first_reply"], color)
        print(c(f"  ** {sb['escalation']} **\n", _YELLOW))
        _print_comms("physician pane — page", sb["physician_page"], color)
        print(f"  {sb['discussion']}\n")
        _print_comms("patient reply, after discussion", sb["final_reply"], color)

    s = t["summary"]
    print(c("SUMMARY", _BOLD))
    print(f"  artifacts shipped:        {s['artifacts_shipped']}")
    print(f"  unsafe drafts blocked:    {s['verdicts_blocked']}")
    print(f"  distinct criteria tripped: {len(s['criteria_tripped'])} "
          f"{s['criteria_tripped']}")
    print(f"  rules & laws cited:       {len(s['citations'])}")
    for cite in s["citations"]:
        print(c(f"    - {cite}", _DIM))
    print(c(f"  unsafe artifacts shipped: {s['unsafe_artifacts_shipped']}",
            _GREEN if s["unsafe_artifacts_shipped"] == 0 else _RED))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="attending-demo", description=__doc__)
    ap.add_argument("fixture", nargs="?", default=str(_DEFAULT_FIXTURE))
    ap.add_argument("--live", action="store_true",
                    help="drafts come from the Fable 5 performer (needs key)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args(argv)

    fixture = json.loads(Path(args.fixture).read_text())
    try:
        transcript = run_demo(fixture, live=args.live)
    except Exception as exc:  # live-mode transport errors, malformed fixtures
        print(f"demo error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(transcript, indent=2))
    else:
        render_transcript(transcript, color=not args.no_color)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
