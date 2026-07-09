"""The Attending: fail-closed supervisor over a proposed ED triage action.

Pipeline (mirrors HealthCraft's offline grader, run online):
  1. Independently compute ESI (esi.compute_esi) -- program-aided, reproducible.
  2. Build a confidence interval over that acuity (confidence).
  3. Run the four failure-mode detectors.
  4. Grade the proposal against the ED triage safety rubric, FAIL CLOSED:
       - under-triage (proposer less acute than Attending) -> BLOCK
       - a fired red flag whose required workup is absent + a
         discharge/fast-track disposition -> BLOCK
       - any detector at BLOCK/ESCALATE severity -> BLOCK/ESCALATE
       - a wide confidence interval whose acute end is sicker than the
         proposal -> ESCALATE to the acute end
  5. recommended_esi = most-acute (smallest) acuity implied by any signal.

"Not evaluated" never reads as "safe": a missing proposal or an
escalating detector fails closed to a human attending.
"""

from __future__ import annotations

from . import knowledge as K
from .confidence import confidence_interval
from .detectors import run_all
from .encounter import Encounter, ProposedTriage
from .esi import compute_esi
from .verdict import Decision, Finding, Severity, Verdict

_DISCHARGE_DISPOSITIONS = {"discharge", "fast_track", "fast track", "waiting_room",
                          "lobby", "home"}


def supervise(enc: Encounter, proposed: ProposedTriage) -> Verdict:
    assessment = compute_esi(enc)
    detections = run_all(enc, proposed, assessment)

    # Input-quality detectors widen the interval toward more acute.
    widen = 0
    for d in detections:
        if d.detector in ("incomplete_audio", "transcription_error") and d.fired:
            widen = max(widen, 1)
    ci = confidence_interval(assessment, widen_to_more_acute=widen)

    findings: list[Finding] = []
    decision = Decision.ALLOW
    # Start from the acute end of Attending's own interval.
    recommended = ci.most_acute

    # --- Rule 1: no proposal at all -> fail closed. ---
    if proposed.esi_level is None:
        decision = Decision.ESCALATE
        findings.append(Finding(
            "no_proposal", Severity.ESCALATE,
            "no triage acuity proposed; cannot clear the patient",
            criterion_id="ATT-000",
            citation=K.CITATIONS["ESI"],
        ))
    else:
        recommended = min(recommended, proposed.esi_level)

    # --- Rule 2: under-triage (proposer less acute than Attending). ---
    if proposed.esi_level is not None and proposed.esi_level > assessment.level:
        decision = Decision.BLOCK
        recommended = min(recommended, assessment.level)
        drivers = "; ".join(assessment.reasons) or "ESI decision tree"
        findings.append(Finding(
            "under_triage", Severity.BLOCK,
            f"proposed ESI {proposed.esi_level} is less acute than the ESI "
            f"{assessment.level} the tree assigns (Decision {assessment.decision_point})",
            criterion_id="ATT-UT1",
            citation=K.CITATIONS.get(
                assessment.red_flags[0].citation if assessment.red_flags else "ESI"),
            evidence=drivers,
        ))

    # --- Rule 3: fired red flag with incomplete workup + unsafe disposition. ---
    disp = (proposed.disposition or "").lower().replace("-", "_")
    orders = set(proposed.orders_lower)
    for rf in assessment.red_flags:
        required = {o.lower() for o in rf.requires_orders}
        if orders & required:
            continue
        sev = Severity.BLOCK if disp in _DISCHARGE_DISPOSITIONS else Severity.WARN
        if sev is Severity.BLOCK:
            decision = Decision.BLOCK
            recommended = min(recommended, rf.esi_floor)
        findings.append(Finding(
            "workup_incomplete", sev,
            f"{rf.label}: required workup {sorted(required)} not ordered"
            + (f"; disposition '{proposed.disposition}' would release the patient"
               if sev is Severity.BLOCK else ""),
            criterion_id=rf.id,
            citation=K.CITATIONS.get(rf.citation, rf.citation),
            evidence=rf.rationale,
        ))

    # --- Rule 4: detectors fail closed. ---
    for d in detections:
        if not d.fired:
            continue
        if d.severity is Severity.ESCALATE:
            if decision is Decision.ALLOW:
                decision = Decision.ESCALATE
            findings.append(Finding(
                "detector", Severity.ESCALATE, d.message,
                criterion_id=f"ATT-{d.detector}", evidence=d.evidence,
                citation=d.citation))
        elif d.severity is Severity.BLOCK:
            decision = Decision.BLOCK
            findings.append(Finding(
                "detector", Severity.BLOCK, d.message,
                criterion_id=f"ATT-{d.detector}", evidence=d.evidence,
                citation=d.citation))

    # --- Rule 5: wide interval whose acute end beats the proposal -> escalate.
    # Only when the acute end could mean the patient is actually urgent
    # (ESI <= 3). Uncertainty entirely within the non-urgent band (ESI 4 vs 5)
    # carries no safety consequence and must not pull a human. ---
    if (proposed.esi_level is not None
            and ci.most_acute < proposed.esi_level
            and ci.most_acute <= 3
            and ci.width >= 1
            and decision is Decision.ALLOW):
        decision = Decision.ESCALATE
        recommended = min(recommended, ci.most_acute)
        findings.append(Finding(
            "low_confidence", Severity.ESCALATE,
            f"acuity uncertain: interval reaches ESI {ci.most_acute} "
            f"(p_point={ci.p_point:.0%}); fail-closed to the acute end",
            criterion_id="ATT-CI1", evidence=ci.basis))

    recommended = max(1, min(5, recommended))
    return Verdict(
        encounter_id=enc.encounter_id,
        decision=decision,
        proposed_esi=proposed.esi_level,
        attending_esi=assessment.level,
        recommended_esi=recommended,
        confidence=ci,
        findings=tuple(findings),
        detections=tuple(detections),
        esi_reasons=assessment.reasons,
        ruleset_version=assessment.ruleset_version,
    )
