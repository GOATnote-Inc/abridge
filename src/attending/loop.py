"""The supervised control loop: propose -> verify -> revise -> ship or escalate.

This is the deployable unit. A performer (any agent) proposes; Attending
verifies; on BLOCK the findings — criterion IDs, citations, evidence — are fed
back verbatim as revision feedback (the gates are machine-actionable, not just
human-readable); on ALLOW the artifact ships. Fail-closed guarantees:

- A blocked artifact is NEVER shipped. There is no override parameter.
- The performer must satisfy the rubric, not outlast it: after
  ``max_revisions`` the loop stops and escalates to a human.
- A supervisor ESCALATE (degraded input, irreducible uncertainty) stops the
  loop immediately — rewording cannot fix a vitals gap; a human can.
- On the communication surface, STATE gates (e.g. the disclosure gap) also
  stop the loop immediately: no text can fix the chart. The caller must act
  (page the team, document the discussion), then re-enter.
- A performer that returns None (gave up / unparseable output) escalates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sitrep.gates import Rendering
from sitrep.state import EncounterState

from .comms import CommsVerdict, supervise_rendering
from .coverage import (
    CoverageCase,
    CoveragePack,
    CoverageProposal,
    CoverageVerdict,
    supervise_determination,
)
from .encounter import Encounter, ProposedTriage
from .supervisor import supervise
from .verdict import Decision, Finding, Severity, Verdict

# Chart-state gate criteria: a rewrite cannot satisfy these; a human must act.
STATE_GATE_CRITERIA = {"SITREP-disclosure_gap"}


def format_feedback(findings: Iterable[Finding]) -> str:
    """Render blocking findings as revision feedback for the performer."""
    lines = []
    for f in findings:
        cite = f" (cite: {f.citation})" if f.citation else ""
        lines.append(f"[{f.criterion_id or f.kind}] {f.message}{cite}")
    return "\n".join(lines)


# --- Decision surface -------------------------------------------------------

ProposeFn = Callable[[Encounter, "str | None"], "ProposedTriage | None"]


@dataclass(frozen=True)
class TriageAttempt:
    proposal: ProposedTriage
    verdict: Verdict


@dataclass(frozen=True)
class TriageLoopResult:
    attempts: tuple[TriageAttempt, ...]
    shipped: ProposedTriage | None   # None => escalated to a human
    escalated: bool
    reason: str


def run_triage_loop(
    enc: Encounter, propose: ProposeFn, max_revisions: int = 2
) -> TriageLoopResult:
    attempts: list[TriageAttempt] = []
    feedback: str | None = None
    for _ in range(max_revisions + 1):
        proposal = propose(enc, feedback)
        if proposal is None:
            return TriageLoopResult(
                tuple(attempts), None, True,
                "performer produced no usable proposal — fail closed to a human",
            )
        verdict = supervise(enc, proposal)
        attempts.append(TriageAttempt(proposal, verdict))
        if verdict.decision is Decision.ALLOW:
            return TriageLoopResult(tuple(attempts), proposal, False, "allowed")
        if verdict.decision is Decision.ESCALATE:
            return TriageLoopResult(
                tuple(attempts), None, True,
                "supervisor escalated: degraded input or irreducible uncertainty "
                "needs a human, not a reworded plan",
            )
        feedback = format_feedback(verdict.findings)
    return TriageLoopResult(
        tuple(attempts), None, True,
        f"revision cap ({max_revisions}) exhausted — fail closed to a human attending",
    )


# --- Communication surface ---------------------------------------------------

DraftFn = Callable[["str | None"], "str | None"]


@dataclass(frozen=True)
class RenderingAttempt:
    text: str
    verdict: CommsVerdict


@dataclass(frozen=True)
class RenderingLoopResult:
    attempts: tuple[RenderingAttempt, ...]
    shipped: str | None              # None => nothing was sent
    escalated: bool
    reason: str
    state_findings: tuple[Finding, ...] = ()  # chart-state gates that fired


def run_rendering_loop(
    state: EncounterState,
    audience: str,
    refs: Iterable[str],
    draft: DraftFn,
    max_revisions: int = 2,
    kind: str = "message",
) -> RenderingLoopResult:
    attempts: list[RenderingAttempt] = []
    feedback: str | None = None
    refs = list(refs)
    for _ in range(max_revisions + 1):
        text = draft(feedback)
        if text is None:
            return RenderingLoopResult(
                tuple(attempts), None, True,
                "performer produced no usable draft — nothing was sent",
            )
        verdict = supervise_rendering(
            Rendering(audience=audience, text=text, refs=refs, kind=kind), state)
        attempts.append(RenderingAttempt(text, verdict))
        if not verdict.blocked:
            return RenderingLoopResult(tuple(attempts), text, False, "allowed")
        state_hits = tuple(
            f for f in verdict.findings if f.criterion_id in STATE_GATE_CRITERIA
        )
        if state_hits:
            return RenderingLoopResult(
                tuple(attempts), None, True,
                "chart-state gate: no wording can fix the chart — human action "
                "required before any message ships",
                state_findings=state_hits,
            )
        feedback = format_feedback(
            f for f in verdict.findings if f.severity is Severity.BLOCK
        )
    return RenderingLoopResult(
        tuple(attempts), None, True,
        f"revision cap ({max_revisions}) exhausted — nothing was sent",
    )


# --- Coverage surface ---------------------------------------------------------

CoverageProposeFn = Callable[["str | None"], "CoverageProposal | None"]


@dataclass(frozen=True)
class CoverageAttempt:
    proposal: CoverageProposal
    verdict: CoverageVerdict


@dataclass(frozen=True)
class CoverageLoopResult:
    attempts: tuple[CoverageAttempt, ...]
    shipped: CoverageProposal | None
    escalated: bool
    reason: str


def run_coverage_loop(
    case: CoverageCase,
    pack: CoveragePack,
    propose: CoverageProposeFn,
    max_revisions: int = 2,
) -> CoverageLoopResult:
    """Same loop semantics as the other two surfaces: BLOCK feeds the findings
    back verbatim; ESCALATE stops immediately (a human decides — automated
    denial does not exist); a None proposal escalates fail-closed."""
    attempts: list[CoverageAttempt] = []
    feedback: str | None = None
    for _ in range(max_revisions + 1):
        proposal = propose(feedback)
        if proposal is None:
            return CoverageLoopResult(
                tuple(attempts), None, True,
                "performer produced no usable proposal — fail closed to a human")
        verdict = supervise_determination(case, pack, proposal)
        attempts.append(CoverageAttempt(proposal, verdict))
        if verdict.decision is Decision.ALLOW:
            return CoverageLoopResult(tuple(attempts), proposal, False, "allowed")
        if verdict.decision is Decision.ESCALATE:
            return CoverageLoopResult(
                tuple(attempts), None, True,
                "evidence indeterminate or unmet — human review required; "
                "automated denial does not exist on this surface")
        feedback = format_feedback(verdict.findings)
    return CoverageLoopResult(
        tuple(attempts), None, True,
        f"revision cap ({max_revisions}) exhausted — routed to a human")
