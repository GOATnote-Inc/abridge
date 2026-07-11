"""The COVERAGE surface — prior-auth determinations and appeals, supervised.

Third supervised surface beside Decision and Communication: same verdict
vocabulary (Decision/Finding/Severity), same fail-closed posture, new gates
(INVERSION F14-F19). Deterministic throughout — no LLM, no clock (timestamps
are caller-supplied so replay stays pure).

Structural guarantees:
- A DENIAL artifact cannot exist without a physician sign-off token:
  ``build_denial`` raises ``PhysicianSignoffRequired`` before any content is
  assembled (F14). ``determine`` (Mode B) can only APPROVE or ESCALATE —
  unmet or indeterminate evidence escalates to a human, never denies (F16).
- Every clinical claim must carry a resolvable citation: a criteria-clause id
  or an exact note/transcript span whose quote matches the source (F15/F19).
- Cited authorities must exist in the loaded criteria pack (F17); every
  artifact carries pack version + hash, model id, timestamp (F18).

Criteria packs are versioned, hashed JSON documents (see drafts/coverage/ for
the schema); clinical pack CONTENT ships only through the clinical-review-
packet flow with physician sign-off — the loader surfaces approval status,
it never ratifies.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .verdict import Decision, Finding, Severity

# --- errors -------------------------------------------------------------------


class PhysicianSignoffRequired(RuntimeError):
    """F14: the deny path is structurally gated on a physician sign-off token."""


# --- criteria packs -------------------------------------------------------------


@dataclass(frozen=True)
class Clause:
    id: str
    text: str
    evidence_needed: str


@dataclass(frozen=True)
class CoveragePack:
    service: str
    population: str
    version: str
    hash: str                       # sha256 of the pack file bytes
    clauses: dict[str, Clause]
    authority_ids: frozenset[str]
    approval_status: str            # surfaced, never ratified here
    source_path: str


def load_pack(path: str | Path) -> CoveragePack:
    p = Path(path)
    raw = p.read_bytes()
    data = json.loads(raw)
    if data.get("synthetic") is not True:
        raise ValueError(f"pack {p.name}: missing synthetic:true attestation (F13)")
    clauses = {c["id"]: Clause(c["id"], c["text"], c.get("evidence_needed", ""))
               for c in data.get("clauses", [])}
    if not clauses:
        raise ValueError(f"pack {p.name}: no clauses")
    return CoveragePack(
        service=data.get("service", ""),
        population=data.get("population", ""),
        version=str(data.get("version", "")),
        hash=hashlib.sha256(raw).hexdigest(),
        clauses=clauses,
        authority_ids=frozenset(a["id"] for a in data.get("authorities", [])),
        approval_status=str(data.get("status", "UNKNOWN")),
        source_path=str(p),
    )


# --- case + proposal structures ---------------------------------------------------


@dataclass
class CoverageCase:
    case_id: str
    synthetic: bool
    note: str
    transcript: str = ""
    note_facts: dict = field(default_factory=dict)
    # clause_id -> "met" | "unmet" | "indeterminate"
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Cite:
    type: str            # "clause" | "note" | "transcript"
    ref: str             # clause id, or "note:<start>:<end>"
    quote: str = ""      # required for span cites; must match the source


@dataclass(frozen=True)
class Claim:
    text: str
    cites: tuple[Cite, ...] = ()
    # optional machine-checkable facts asserted by this claim (F19)
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CoverageProposal:
    kind: str                        # "appeal" | "determination"
    outcome: str | None              # determinations: "approve" | "deny"
    claims: tuple[Claim, ...] | list
    authorities_cited: tuple[str, ...] | list
    provenance: dict


def make_provenance(pack: CoveragePack, *, model_id: str, timestamp: str) -> dict:
    return {"pack_version": pack.version, "pack_hash": pack.hash,
            "model_id": model_id, "timestamp": timestamp}


# --- gates (each returns findings; BLOCK severity blocks) --------------------------

_SPAN_RE = re.compile(r"^(note|transcript):(\d+):(\d+)$")


def _resolve_span(case: CoverageCase, cite: Cite) -> tuple[bool, str]:
    source = case.note if cite.type == "note" else case.transcript
    # Quote-anchored citation: the performer supplies the exact quote and the
    # DETERMINISTIC engine locates it (models cannot count character offsets;
    # engines can). ref "auto" (or empty) means locate-by-quote.
    if cite.ref in ("auto", ""):
        if not cite.quote:
            return False, "auto cite without a quote"
        if cite.quote in source:
            return True, ""
        return False, (f"quote not found in {cite.type} — "
                       f"\"{cite.quote[:60]}\" is not in the source")
    m = _SPAN_RE.match(cite.ref)
    if not m:
        return False, f"unparseable span ref '{cite.ref}'"
    a, b = int(m.group(2)), int(m.group(3))
    if not (0 <= a < b <= len(source)):
        return False, f"span {cite.ref} out of bounds (source len {len(source)})"
    if cite.quote and source[a:b] != cite.quote:
        return False, (f"frankenfact: quote does not match source at {cite.ref} — "
                       f"source says \"{source[a:b]}\"")
    return True, ""


def gate_coverage_grounding(case: CoverageCase, pack: CoveragePack,
                            proposal: CoverageProposal) -> list[Finding]:
    """F15 + F19 (span half): every claim resolvably cited; quotes must match."""
    out: list[Finding] = []
    for i, claim in enumerate(proposal.claims):
        if not claim.cites:
            out.append(Finding(
                "coverage_grounding", Severity.BLOCK,
                f"claim {i + 1} asserts a clinical fact with no citation: "
                f"\"{claim.text[:80]}\"",
                criterion_id="COV-F15",
                citation="INVERSION F15 — uncited clinical claims are blocked",
            ))
            continue
        for cite in claim.cites:
            if cite.type == "clause":
                if cite.ref not in pack.clauses:
                    out.append(Finding(
                        "coverage_grounding", Severity.BLOCK,
                        f"claim {i + 1} cites unknown clause '{cite.ref}'",
                        criterion_id="COV-F15",
                        citation=f"criteria pack {pack.version}",
                    ))
            else:
                ok, why = _resolve_span(case, cite)
                if not ok:
                    fid = "COV-F19" if "frankenfact" in why else "COV-F15"
                    out.append(Finding(
                        "coverage_grounding", Severity.BLOCK,
                        f"claim {i + 1}: {why}",
                        criterion_id=fid,
                        citation="INVERSION F15/F19 — citations must resolve "
                                 "and quotes must match the source",
                    ))
    return out


def gate_frankenfacts(case: CoverageCase, proposal: CoverageProposal) -> list[Finding]:
    """F19 (facts half): claim-asserted facts must not contradict note_facts."""
    out: list[Finding] = []
    for i, claim in enumerate(proposal.claims):
        for key, val in (claim.facts or {}).items():
            if key in case.note_facts and case.note_facts[key] != val:
                out.append(Finding(
                    "coverage_frankenfact", Severity.BLOCK,
                    f"claim {i + 1} asserts {key}={val!r} but the note records "
                    f"{key}={case.note_facts[key]!r}",
                    criterion_id="COV-F19",
                    citation="INVERSION F19 — artifact facts must match the note",
                ))
    return out


def gate_no_fabricated_authority(pack: CoveragePack,
                                 proposal: CoverageProposal) -> list[Finding]:
    """F17: cited authorities must exist in the pack's authorities list."""
    out: list[Finding] = []
    for auth in proposal.authorities_cited:
        if auth not in pack.authority_ids:
            out.append(Finding(
                "fabricated_authority", Severity.BLOCK,
                f"cited authority '{auth}' is not in criteria pack "
                f"{pack.version} (authorities: {sorted(pack.authority_ids)})",
                criterion_id="COV-F17",
                citation="INVERSION F17 — authorities must come from the pack",
            ))
    return out


_PROVENANCE_FIELDS = ("pack_version", "pack_hash", "model_id", "timestamp")


def gate_provenance(pack: CoveragePack, proposal: CoverageProposal) -> list[Finding]:
    """F18: pack version+hash, model id, timestamp — present and matching."""
    out: list[Finding] = []
    prov = proposal.provenance or {}
    for fld in _PROVENANCE_FIELDS:
        if not prov.get(fld):
            out.append(Finding(
                "provenance", Severity.BLOCK,
                f"provenance field '{fld}' missing/empty",
                criterion_id="COV-F18",
                citation="INVERSION F18 — artifacts carry full provenance",
            ))
    if prov.get("pack_hash") and prov["pack_hash"] != pack.hash:
        out.append(Finding(
            "provenance", Severity.BLOCK,
            "provenance pack_hash does not match the loaded pack "
            f"(expected {pack.hash[:12]}…)",
            criterion_id="COV-F18",
            citation="INVERSION F18 — hash pins the exact criteria text",
        ))
    if prov.get("pack_version") and prov["pack_version"] != pack.version:
        out.append(Finding(
            "provenance", Severity.BLOCK,
            f"provenance pack_version {prov['pack_version']!r} != loaded "
            f"{pack.version!r}",
            criterion_id="COV-F18",
            citation="INVERSION F18",
        ))
    return out


def gate_outcome(case: CoverageCase, pack: CoveragePack,
                 proposal: CoverageProposal) -> list[Finding]:
    """F16: a deny outcome is never permitted here (the only deny path is
    build_denial with a physician sign-off token); approvals require every
    clause met — anything unmet or indeterminate escalates to a human."""
    out: list[Finding] = []
    if proposal.outcome == "deny":
        out.append(Finding(
            "outcome", Severity.BLOCK,
            "automated deny attempted — denial requires the physician-signoff "
            "path (build_denial), which this proposal did not and cannot use",
            criterion_id="COV-F16",
            citation="INVERSION F14/F16 — no automated denials",
        ))
    if proposal.kind == "determination" and proposal.outcome == "approve":
        for cid in pack.clauses:
            status = case.evidence.get(cid, "indeterminate")
            if status != "met":
                out.append(Finding(
                    "outcome", Severity.ESCALATE,
                    f"clause {cid} evidence is '{status}' — approval requires "
                    "every clause met; escalate to a human reviewer",
                    criterion_id="COV-F16",
                    citation="INVERSION F16 — indeterminate never resolves "
                             "toward denial (or unearned approval)",
                ))
    return out


# --- the verdict ---------------------------------------------------------------


@dataclass(frozen=True)
class CoverageVerdict:
    case_id: str
    decision: Decision
    findings: tuple[Finding, ...]
    pack_version: str
    pack_hash: str

    @property
    def blocked(self) -> bool:
        return self.decision is Decision.BLOCK


def supervise_determination(case: CoverageCase, pack: CoveragePack,
                            proposal: CoverageProposal) -> CoverageVerdict:
    findings: list[Finding] = []
    findings += gate_provenance(pack, proposal)
    findings += gate_no_fabricated_authority(pack, proposal)
    findings += gate_coverage_grounding(case, pack, proposal)
    findings += gate_frankenfacts(case, proposal)
    findings += gate_outcome(case, pack, proposal)

    if any(f.severity is Severity.BLOCK for f in findings):
        decision = Decision.BLOCK
    elif any(f.severity is Severity.ESCALATE for f in findings):
        decision = Decision.ESCALATE
    else:
        decision = Decision.ALLOW
    return CoverageVerdict(case.case_id, decision, tuple(findings),
                           pack.version, pack.hash)


# --- artifact builders ------------------------------------------------------------


@dataclass(frozen=True)
class PhysicianSignoff:
    name: str
    credential: str
    date: str


def _render_claims(claims) -> str:
    lines = []
    for c in claims:
        refs = " ".join(f"[{x.ref}]" if x.type == "clause" else f"[{x.ref}]"
                        for x in c.cites)
        lines.append(f"- {c.text} {refs}".rstrip())
    return "\n".join(lines)


def build_appeal(case: CoverageCase, pack: CoveragePack,
                 proposal: CoverageProposal) -> dict:
    """Mode A artifact: an appeal letter whose every claim carries its
    citations inline. Caller must have an ALLOW verdict first (the demo loop
    enforces this; the builder renders, it does not judge)."""
    text = (
        f"APPEAL — {pack.service} (criteria pack {pack.version})\n\n"
        f"{_render_claims(proposal.claims)}\n\n"
        f"Authorities: {', '.join(proposal.authorities_cited)}\n"
    )
    return {"type": "appeal", "case_id": case.case_id, "text": text,
            "provenance": dict(proposal.provenance), "signoff": None}


def determine(case: CoverageCase, pack: CoveragePack, *, model_id: str,
              timestamp: str) -> dict:
    """Mode B: run the criteria forward. APPROVE (all clauses met, each cited)
    or ESCALATE — this function is structurally incapable of denying."""
    statuses = {cid: case.evidence.get(cid, "indeterminate")
                for cid in pack.clauses}
    if all(s == "met" for s in statuses.values()):
        lines = [f"- {pack.clauses[cid].text} — evidence met [{cid}]"
                 for cid in pack.clauses]
        text = (f"APPROVAL — {pack.service} (criteria pack {pack.version})\n\n"
                + "\n".join(lines) + "\n")
        artifact = {"type": "approval", "case_id": case.case_id, "text": text,
                    "provenance": make_provenance(pack, model_id=model_id,
                                                  timestamp=timestamp),
                    "signoff": None}
        return {"decision": "ALLOW", "artifact": artifact, "statuses": statuses}
    not_met = {c: s for c, s in statuses.items() if s != "met"}
    return {"decision": "ESCALATE", "artifact": None, "statuses": statuses,
            "reason": (f"clauses not affirmatively met: {not_met} — routed to a "
                       "human reviewer; automated denial does not exist here")}


def build_denial(case: CoverageCase, pack: CoveragePack, *,
                 physician_signoff: PhysicianSignoff | None, model_id: str,
                 timestamp: str) -> dict:
    """F14: the ONLY path to a denial artifact — and it is gated, structurally,
    on a physician sign-off token. No token, no artifact, no exceptions."""
    if physician_signoff is None or not (physician_signoff.name
                                         and physician_signoff.credential
                                         and physician_signoff.date):
        raise PhysicianSignoffRequired(
            "denial artifacts require a physician sign-off token "
            "(name, credential, date) — INVERSION F14")
    statuses = {cid: case.evidence.get(cid, "indeterminate")
                for cid in pack.clauses}
    text = (f"DENIAL (physician-signed) — {pack.service} "
            f"(criteria pack {pack.version})\n\n"
            + "\n".join(f"- {pack.clauses[c].text}: evidence {s} [{c}]"
                        for c, s in statuses.items()) + "\n")
    return {"type": "denial", "case_id": case.case_id, "text": text,
            "provenance": make_provenance(pack, model_id=model_id,
                                          timestamp=timestamp),
            "signoff": {"name": physician_signoff.name,
                        "credential": physician_signoff.credential,
                        "date": physician_signoff.date}}
