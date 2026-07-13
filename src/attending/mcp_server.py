"""Attending as an MCP server — connect YOUR Claude and try to get an
unsafe action past the gates.

Five tools wrap the same deterministic engines the replay, gateway, and CLI
use. A BLOCK verdict is a SUCCESSFUL supervision result (refusal with named
findings, citations, and evidence spans) — never a tool error; `isError` is
reserved for genuine execution failures, per current MCP guidance.

Transports:
  python -m attending.mcp_server            # stdio (Claude Code / Desktop)
  python -m attending.mcp_server --http     # streamable-http on :8000/mcp
The FastAPI gateway also mounts this server at /mcp when the extra is
installed (`pip install -e .[gateway,mcp]`), so `make serve` exposes REST
and MCP from one process.

Requires the optional extra:  pip install -e .[mcp]
"""

from __future__ import annotations

import sys
from typing import Any

from pydantic import BaseModel

from . import coverage as cov
from .encounter import Encounter, ProposedTriage, Vitals
from .knowledge import RULESET_VERSION
from .supervisor import supervise

try:  # pragma: no cover - import guard exercised implicitly
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "the MCP surface needs the optional extra: pip install -e .[mcp]"
    ) from exc

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

_GUIDANCE_BLOCK = (
    "BLOCK is a successful supervision result, not a tool failure: read the "
    "findings (criterion id, citation, evidence span), revise the proposal "
    "to satisfy EVERY cited criterion, and resubmit. There is no override "
    "parameter."
)
_GUIDANCE_ALLOW = "Proposal is consistent with the rubric; it may proceed."
_GUIDANCE_ESCALATE = (
    "ESCALATE means a human decides: input quality or chart state makes "
    "this unsafe to automate — no rewording can fix it. Route to a person."
)

mcp = FastMCP(
    "attending",
    stateless_http=True,
    instructions=(
        "Attending is a deterministic, fail-closed clinical-safety "
        "supervisor. Call the supervise_* tools BEFORE committing any ED "
        "triage action, patient-facing message, or prior-auth artifact. "
        + _GUIDANCE_BLOCK
        + " All inputs must be synthetic — never real patient data."
    ),
)


class Finding(BaseModel):
    criterion_id: str | None
    severity: str
    message: str
    citation: str | None
    evidence: str = ""


class TriageVerdict(BaseModel):
    decision: str                 # ALLOW | BLOCK | ESCALATE
    guidance: str
    proposed_esi: int | None
    attending_esi: int
    recommended_esi: int
    esi_reasons: list[str]
    findings: list[Finding]
    ruleset_version: str


class CoverageVerdictOut(BaseModel):
    decision: str
    guidance: str
    findings: list[Finding]
    pack_version: str
    pack_status: str


def _guidance(decision: str) -> str:
    return {"ALLOW": _GUIDANCE_ALLOW, "ESCALATE": _GUIDANCE_ESCALATE}.get(
        decision, _GUIDANCE_BLOCK)


def _findings(fs: Any) -> list[Finding]:
    return [Finding(criterion_id=f.criterion_id, severity=f.severity.value,
                    message=f.message, citation=f.citation,
                    evidence=getattr(f, "evidence", "") or "")
            for f in fs]


@mcp.tool(annotations=_READ_ONLY)
def supervise_triage(
    chief_complaint: str,
    proposed_esi: int | None = None,
    orders: list[str] | None = None,
    disposition: str | None = None,
    rationale: str | None = None,
    age_years: float | None = None,
    transcript: str | None = None,
    hr: float | None = None,
    rr: float | None = None,
    spo2: float | None = None,
    sbp: float | None = None,
    dbp: float | None = None,
    temp_c: float | None = None,
    pain: float | None = None,
    gcs: float | None = None,
) -> TriageVerdict:
    """Grade a proposed ED triage action against fail-closed safety gates
    (independent ESI v4 re-derivation, red-flag workup completeness,
    degraded-input detectors). Propose an acuity (1-5), orders, and a
    disposition (resus|main_ed|fast_track|discharge) for a synthetic
    encounter. BLOCK is a successful supervision result — revise and
    resubmit; do not treat it as an error."""
    enc = Encounter(
        encounter_id="MCP", chief_complaint=chief_complaint,
        age_years=age_years, transcript=transcript,
        vitals=Vitals(
            hr=int(hr) if hr is not None else None,
            rr=int(rr) if rr is not None else None,
            spo2=int(spo2) if spo2 is not None else None,
            sbp=int(sbp) if sbp is not None else None,
            dbp=int(dbp) if dbp is not None else None,
            temp_c=temp_c,
            pain=int(pain) if pain is not None else None,
            gcs=int(gcs) if gcs is not None else None),
    )
    v = supervise(enc, ProposedTriage(
        esi_level=proposed_esi,
        orders=tuple(o.lower() for o in (orders or ())),
        disposition=disposition, rationale=rationale))
    return TriageVerdict(
        decision=v.decision.value, guidance=_guidance(v.decision.value),
        proposed_esi=v.proposed_esi, attending_esi=v.attending_esi,
        recommended_esi=v.recommended_esi,
        esi_reasons=list(v.esi_reasons), findings=_findings(v.findings),
        ruleset_version=v.ruleset_version,
    )


@mcp.tool(annotations=_READ_ONLY)
def supervise_patient_message(
    text: str,
    audience: str = "patient",
    chart_preset: str = "critical",
) -> dict:
    """Grade a patient/team-facing message against the communication gates
    (Cures Act anti-embargo, AI disclosure, no interpretation or false
    reassurance in the patient pane, disclosure-gap chart state).
    chart_preset selects a synthetic chart: 'none' (empty), 'normal'
    (released normal CBC), 'critical' (released critical troponin, viewed,
    NOT yet discussed), 'discussed' (same, after a documented bedside
    discussion). BLOCK is a successful supervision result."""
    from sitrep.gates import Rendering

    from .comms import supervise_rendering
    from .mcp_charts import build_chart
    state, refs = build_chart(chart_preset)
    cv = supervise_rendering(
        Rendering(audience=audience, text=text, refs=refs), state)
    return {
        "decision": cv.decision.value,
        "guidance": _guidance(cv.decision.value),
        "audience": cv.audience,
        "findings": [f.model_dump() for f in _findings(cv.findings)],
        "note": ("a blocked rendering never reaches the patient; "
                 "chart-state findings cannot be fixed by rewording"),
    }


@mcp.tool(annotations=_READ_ONLY)
def supervise_coverage_appeal(
    claims: list[dict],
    authorities_cited: list[str] | None = None,
) -> CoverageVerdictOut:
    """Grade a prior-auth APPEAL against the coverage gates using the
    committed synthetic pediatric speech-therapy case and DRAFT criteria
    pack. Each claim: {"text": str, "cites": [{"type": "clause"|"note"|
    "transcript", "ref": str, "quote": str}]}. Every claim needs chart
    evidence — a quote copied VERBATIM from the note/transcript (type
    note/transcript, ref "auto"); clause ids link criteria but cannot
    ground facts. Authorities must exist in the pack. Provenance is
    auto-pinned by this demo tool (the provenance gate is exercised via
    coverage_preset). BLOCK is a successful supervision result."""
    from .mcp_charts import load_coverage_fixture
    case, pack = load_coverage_fixture()
    prov = cov.make_provenance(pack, model_id="mcp-judge-session",
                               timestamp="2026-07-18T00:00:00Z")
    proposal = cov.CoverageProposal(
        kind="appeal", outcome=None,
        claims=tuple(
            cov.Claim(str(c.get("text", "")),
                      cites=tuple(cov.Cite(str(x.get("type", "note")),
                                           str(x.get("ref", "auto")),
                                           quote=str(x.get("quote", "")))
                                  for x in c.get("cites") or ()))
            for c in claims),
        authorities_cited=tuple(authorities_cited or ()),
        provenance=prov)
    v = cov.supervise_determination(case, pack, proposal)
    return CoverageVerdictOut(
        decision=v.decision.value, guidance=_guidance(v.decision.value),
        findings=_findings(v.findings), pack_version=v.pack_version,
        pack_status=pack.approval_status)


@mcp.tool(annotations=_READ_ONLY)
def coverage_preset(name: str) -> dict:
    """Run a one-click coverage scenario: 'vague_denial' (audit a payer's
    letter — blocks on four gate families at once), 'unsupported_claim'
    (an appeal with one uncited claim), or 'auto_deny' (the structural
    F14 raise: denial without a physician sign-off token is impossible —
    there is no override parameter)."""
    from .gateway import _coverage_preset_impl
    return _coverage_preset_impl(name)


@mcp.tool(annotations=_READ_ONLY)
def list_gates() -> list[dict]:
    """The failure-mode ledger: every supervised failure class (F1-F19)
    with its enforcement mechanism — what this supervisor checks and how."""
    import re
    from pathlib import Path
    rows = []
    text = (Path(__file__).resolve().parents[2] / "INVERSION.md").read_text()
    for line in text.splitlines():
        m = re.match(r"\|\s*(F\d+)\s*\|(.+?)\|(.+?)\|(.+?)\|", line)
        if m:
            rows.append({"id": m.group(1), "failure_mode": m.group(2).strip(),
                         "mechanism": m.group(3).strip(),
                         "action": m.group(4).strip()})
    return rows


def main() -> None:
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


# Ruleset version surfaces in every triage verdict; assert the import is real.
_ = RULESET_VERSION

if __name__ == "__main__":
    main()
