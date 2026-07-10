"""The performer: a minimal LLM clinical agent for Attending to supervise.

Screener/performer separation is the architecture: this module PROPOSES and
DRAFTS; it never grades. Its prompts do state the safety policy — prompting is
necessary — but the guarantee lives in the deterministic gates outside the
model (prompts drift under pressure; middleware does not). The supervisor's
findings are fed back verbatim between attempts via `attending.loop`.

Model: ATTENDING_AGENT_MODEL if set, else the session model (claude-fable-5).
Any transport/parse failure returns None, which the loop treats as "performer
gave up" and fails closed to a human.
"""

from __future__ import annotations

import os

from . import llm
from .encounter import Encounter, ProposedTriage
from .llm import _encounter_brief  # same package; the brief is the shared record view


def agent_model() -> str:
    return os.environ.get("ATTENDING_AGENT_MODEL", llm.model_name())


_TRIAGE_SYSTEM = """You are an emergency-department triage agent. Given one \
encounter record, propose a triage action. Ground every statement in the record \
provided — never assert a vital or history item that is not shown.

Fields: esi_level (integer 1-5), orders (array of short lowercase order
tokens, e.g. "ecg", "troponin", "ct_head", "cbc"), disposition (one of
resus|main_ed|fast_track|discharge), rationale (grounded in the record).
If REVISION FEEDBACK is present, your previous proposal was blocked by the \
safety supervisor: revise to satisfy EVERY cited criterion."""

_PATIENT_MSG_SYSTEM = """You draft a patient-portal message for an emergency \
department. Policy: acknowledge available results by name; no interpretation, \
prognosis, advice, or reassurance; include the exact phrase "generated with AI" \
and tell the patient to press their call button to reach their nurse; if the \
care team has been notified, say so; write at or below an 8th-grade level.

Field: text (the complete patient-portal message).
If REVISION FEEDBACK is present, your previous draft was blocked by the safety \
supervisor: revise to satisfy EVERY cited criterion."""


# Server guarantees shape; value ranges/vocabulary stay client-validated
# (the API does not constrain numeric ranges, and enum casing is not
# guaranteed — so the existing coercion below remains authoritative).
_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "esi_level": {"type": ["integer", "null"]},
        "orders": {"type": "array", "items": {"type": "string"}},
        "disposition": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
    "required": ["esi_level", "orders", "disposition", "rationale"],
    "additionalProperties": False,
}

_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def _with_feedback(user: str, feedback: str | None) -> str:
    if feedback:
        user += f"\n\nREVISION FEEDBACK (from the safety supervisor):\n{feedback}"
    return user


def propose_triage(enc: Encounter, feedback: str | None = None) -> ProposedTriage | None:
    """LLM triage proposal. None on any transport/parse failure (fail closed)."""
    try:
        out = llm.complete_json(
            _TRIAGE_SYSTEM,
            _with_feedback(f"ENCOUNTER RECORD:\n{_encounter_brief(enc)}", feedback),
            schema=_TRIAGE_SCHEMA,
            model=agent_model(),
        )
        esi = out.get("esi_level")
        return ProposedTriage(
            esi_level=int(esi) if esi is not None else None,
            orders=tuple(str(o).lower() for o in out.get("orders") or ()),
            disposition=str(out["disposition"]) if out.get("disposition") else None,
            rationale=str(out["rationale"]) if out.get("rationale") else None,
        )
    except Exception:
        return None  # loop escalates — a misbehaving performer never ships


def draft_patient_message(
    enc: Encounter, situation: str, feedback: str | None = None
) -> str | None:
    """LLM patient-pane draft. None on any transport/parse failure."""
    try:
        user = (
            f"ENCOUNTER RECORD:\n{_encounter_brief(enc)}\n\n"
            f"SITUATION:\n{situation}\n\nDraft the patient-portal reply."
        )
        out = llm.complete_json(_PATIENT_MSG_SYSTEM, _with_feedback(user, feedback),
                                schema=_MESSAGE_SCHEMA, model=agent_model())
        text = out.get("text")
        return str(text) if text else None
    except Exception:
        return None
