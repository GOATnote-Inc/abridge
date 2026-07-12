"""FHIR R4 export of supervision artifacts — the resources designed for them.

Verdicts export as DetectedIssue (the flagged-clinical-issue resource CDS
systems use), each bundle carries Provenance (the supervisor as an agent;
quote-anchored citations as entity role ``quotation``; the criteria pack as
entity role ``source`` with an RFC 6920 ``ni:///sha-256;...`` identifier) and
an AuditEvent (the ATNA-derived audit model). Triage acuity exports as
RiskAssessment plus an Observation coded LOINC 75636-1 (Emergency severity
index). Every resource carries ``meta.security`` HTEST ("test health data") —
the standards-native form of this repo's ``synthetic: true`` attestation —
and the exporter refuses non-attested input outright (F13).

Same invariants as the engine: fail-closed (findings are never dropped; a
BLOCK always exports at least one high-severity issue), deterministic
(``recorded`` is caller-supplied — no clock; ids derive from content hashes —
no randomness; identical inputs export byte-identically, F11).

This is a demonstration export, not a certified EHR interface; US Core /
Da Vinci profile conformance is not claimed.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from .verdict import Decision, Severity

if TYPE_CHECKING:  # imported for signatures only
    from .coverage import CoverageCase, CoverageVerdict
    from .verdict import Finding

CRITERION_SYSTEM = (
    "https://github.com/GOATnote-Inc/abridge/blob/main/INVERSION.md"
)
_HTEST = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "code": "HTEST",
    "display": "test health data",
}
_LOINC_ESI = {"system": "http://loinc.org", "code": "75636-1",
              "display": "Emergency severity index [ESI]"}
_RISK_PROBABILITY = "http://terminology.hl7.org/CodeSystem/risk-probability"
_DCM = "http://dicom.nema.org/resources/ontology/DCM"

_SEVERITY_MAP = {  # verdict.Severity -> DetectedIssue.severity (required set)
    Severity.BLOCK: "high",
    Severity.ESCALATE: "moderate",
    Severity.WARN: "moderate",
    Severity.INFO: "low",
}


def _meta() -> dict[str, Any]:
    return {"security": [dict(_HTEST)]}


def _narrative(summary: str) -> dict[str, str]:
    """Minimal generated narrative (dom-6 best practice) — plain text only."""
    safe = (summary.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
    return {"status": "generated",
            "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{safe}</div>'}


def _rid(prefix: str, payload: Any) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return f"urn:attending:{prefix}-{digest}"


def _require_synthetic(flag: object, what: str) -> None:
    if flag is not True:
        raise ValueError(
            f"{what} lacks the 'synthetic: true' attestation — refusing to "
            "export (F13: non-attested data never enters or leaves the "
            "pipeline)"
        )


def _detected_issue(f: Finding, *, subject: dict[str, str],
                    author_display: str) -> dict[str, Any]:
    severity = _SEVERITY_MAP.get(f.severity, "high")  # unknown -> high
    issue: dict[str, Any] = {
        "resourceType": "DetectedIssue",
        "meta": _meta(),
        "text": _narrative(f"{severity}: {f.message}"),
        "status": "final",
        "severity": severity,
        "code": {
            "coding": [{
                "system": CRITERION_SYSTEM,
                "code": f.criterion_id or f.kind,
                "display": f.kind,
            }],
            "text": f.citation or f.kind,
        },
        "detail": f.message,
        "patient": dict(subject),
        "author": {"display": author_display},
    }
    if f.evidence:
        issue["evidence"] = [{"code": [{"text": f.evidence}]}]
    return issue


def _provenance(targets: list[str], *, recorded: str, agent_display: str,
                entities: list[dict[str, Any]],
                policy: list[str] | None = None) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "resourceType": "Provenance",
        "meta": _meta(),
        "text": _narrative(f"Provenance: {agent_display}"),
        "target": [{"reference": t} for t in targets],
        "recorded": recorded,
        "agent": [{"who": {"display": agent_display}}],
    }
    if entities:
        prov["entity"] = entities
    if policy:
        prov["policy"] = policy
    return prov


def _audit_event(*, recorded: str, decision: Decision, entity_what: str,
                 detail: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "resourceType": "AuditEvent",
        "meta": _meta(),
        "text": _narrative(f"Gate execution: {entity_what} — "
                           f"{decision.value}"),
        "type": {"system": _DCM, "code": "110100",
                 "display": "Application Activity"},
        "action": "E",
        "recorded": recorded,
        "outcome": "0",  # the gate executed; a BLOCK is a success, not an error
        "agent": [{
            "who": {"display": "attending supervisor"},
            "requestor": True,
        }],
        "source": {"observer": {"display": "attending"}},
        "entity": [{
            "what": {"display": entity_what},
            "detail": [{"type": k, "valueString": v} for k, v in detail],
        }],
    }


def _bundle(resources: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for r in resources:
        entries.append({
            "fullUrl": _rid(r["resourceType"].lower(), r),
            "resource": r,
        })
    return {"resourceType": "Bundle", "meta": _meta(), "type": "collection",
            "entry": entries}


def triage_export(verdict: Any, encounter: dict[str, Any], *, recorded: str,
                  model_id: str) -> dict[str, Any]:
    """Triage verdict -> Bundle(RiskAssessment, Observation[ESI],
    DetectedIssue*, Provenance, AuditEvent). ``recorded`` is caller-supplied
    (replay purity); ``encounter`` must carry ``synthetic: true``."""
    _require_synthetic(encounter.get("synthetic"), "encounter")
    subject = {"display": f"synthetic patient — encounter "
                          f"{verdict.encounter_id}"}
    agent = (f"Attending supervisor (deterministic ruleset "
             f"{verdict.ruleset_version}; model seam {model_id})")
    esi = int(verdict.attending_esi)
    qualitative = "high" if esi <= 2 else ("moderate" if esi == 3 else "low")

    observation = {
        "resourceType": "Observation",
        "meta": _meta(),
        "text": _narrative(f"Emergency severity index [ESI]: {esi} "
                           f"(deterministic re-derivation)"),
        "status": "final",
        "code": {"coding": [dict(_LOINC_ESI)]},
        "subject": dict(subject),
        "effectiveDateTime": recorded,
        "performer": [{"display": agent}],
        "valueInteger": esi,
        "device": {"display": agent},
    }
    risk = {
        "resourceType": "RiskAssessment",
        "meta": _meta(),
        "text": _narrative(f"Triage risk: attending ESI {esi} — "
                           f"decision {verdict.decision.value}"),
        "status": "final",
        "subject": dict(subject),
        "method": {"text": "Emergency Severity Index v4 (deterministic "
                           "re-derivation)"},
        "performer": {"display": agent},
        "prediction": [{
            "outcome": {"text": f"attending ESI {esi}"},
            "qualitativeRisk": {"coding": [{
                "system": _RISK_PROBABILITY, "code": qualitative,
            }]},
        }],
        "basis": [{"display": f.evidence} for f in verdict.findings
                  if f.evidence],
    }
    issues = [_detected_issue(f, subject=subject, author_display=agent)
              for f in verdict.findings]

    quoted = [{
        "role": "quotation",
        "what": {"display": f.evidence},
    } for f in verdict.findings if f.evidence]
    resources: list[dict[str, Any]] = [risk, observation, *issues]
    targets = [_rid(r["resourceType"].lower(), r) for r in resources]
    resources.append(_provenance(targets, recorded=recorded,
                                 agent_display=agent, entities=quoted))
    resources.append(_audit_event(
        recorded=recorded, decision=verdict.decision,
        entity_what=f"triage verdict — encounter {verdict.encounter_id}",
        detail=[("decision", verdict.decision.value),
                ("ruleset", verdict.ruleset_version),
                ("findings", str(len(verdict.findings)))],
    ))
    return _bundle(resources)


def coverage_export(case: CoverageCase, verdict: CoverageVerdict, *,
                    recorded: str, model_id: str,
                    quotes: tuple[str, ...] = ()) -> dict[str, Any]:
    """Coverage determination verdict -> Bundle(DetectedIssue*, Provenance,
    AuditEvent). The criteria pack rides Provenance as entity role ``source``
    with its sha256 as an RFC 6920 ``ni:`` URI — the audit works even after
    any source system deletes its copy."""
    _require_synthetic(case.synthetic, f"coverage case {case.case_id}")
    subject = {"display": f"synthetic case — {case.case_id}"}
    agent = (f"Attending coverage supervisor (pack {verdict.pack_version}; "
             f"model seam {model_id})")
    issues = [_detected_issue(f, subject=subject, author_display=agent)
              for f in verdict.findings]
    entities: list[dict[str, Any]] = [{
        "role": "source",
        "what": {
            "display": f"criteria pack {verdict.pack_version}",
            "identifier": {
                "system": "urn:ietf:rfc:6920",
                "value": f"ni:///sha-256;{verdict.pack_hash}",
            },
        },
    }]
    entities += [{"role": "quotation", "what": {"display": q}}
                 for q in quotes]
    resources: list[dict[str, Any]] = list(issues)
    targets = [_rid(r["resourceType"].lower(), r) for r in resources]
    resources.append(_provenance(
        targets or [_rid("verdict", verdict.case_id)], recorded=recorded,
        agent_display=agent, entities=entities))
    resources.append(_audit_event(
        recorded=recorded, decision=verdict.decision,
        entity_what=f"coverage determination — case {verdict.case_id}",
        detail=[("decision", verdict.decision.value),
                ("pack_version", verdict.pack_version),
                ("pack_hash", verdict.pack_hash),
                ("findings", str(len(verdict.findings)))],
    ))
    return _bundle(resources)
