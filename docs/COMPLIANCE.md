# Compliance posture — HIPAA-aware, FHIR-speaking, zero PHI by construction

*Scope statement up front: this repository is a demonstration and research
codebase. It processes **zero PHI** — all clinical content is synthetic,
enforced mechanically, not by policy. No HIPAA or FHIR "certification" is
claimed, because none exists to claim: HHS recognizes no HIPAA compliance
certification, and HL7 does not certify products. What follows is a design
mapping a deploying covered entity would build on, stated so a reviewer can
verify each row against the code.*

## Zero PHI, enforced

- **Synthetic-only intake (F13):** `load_scenario` requires
  `"synthetic": true` and bans identifier-shaped fields; the FHIR exporter
  (`attending.fhir`) refuses non-attested input outright. HIPAA attaches to
  information about real individuals — fully synthetic data was never PHI,
  which is a stronger position than de-identification (nothing to
  de-identify). Precedent: Synthea/Inferno run the industry's test
  infrastructure on exactly this posture.
- **Safe-Harbor-aligned schema bans:** the banned field shapes (names, MRNs,
  dates of birth, phone numbers, addresses, facility names) track the
  §164.514(b)(2) Safe Harbor identifier categories. This is a lint rule with
  tests, not a promise.
- **Standards-native labeling:** every exported FHIR resource carries
  `meta.security` = `HTEST` ("test health data",
  `v3-ActReason`) so synthetic artifacts are machine-distinguishable from
  PHI by any downstream system — the recognized form of this repo's
  attestation.

## §164.312 technical safeguards → repository mechanisms

*A design mapping, not a compliance claim — the demo has no ePHI to
safeguard; a deployment inherits these hooks inside a covered entity's
boundary under a BAA, where the entity's §164.308 risk analysis must include
this system.*

| §164.312 safeguard | Mechanism here |
|---|---|
| (a) Access control | fail-closed verdicts; every actor named in Provenance/AuditEvent `agent`; user identity/IdP inherited from the deployment |
| (b) Audit controls (required) | every gate decision exportable as FHIR AuditEvent (ATNA-derived model); opt-in `LoopTrace` JSONL of every attempt; deterministic replay reproduces any audited run |
| (c) Integrity | sha256-hashed, versioned criteria packs pinned in provenance; quote-anchored citations make silent content drift detectable; byte-identical replay pinned by tests |
| (d) Person/entity authentication | denials structurally require a physician sign-off token (`PhysicianSignoffRequired`); the signing identity rides `DetectedIssue.mitigation`/Provenance |
| (e) Transmission security | out of demo scope; TLS termination is a stated deployment requirement |

**Minimum necessary (§164.502(b))** maps to the span design: gates read only
the fields their criterion needs, and verdicts quote only the span that
fired — the supervisor neither ingests nor re-emits the rest of the record.

## Regulatory awareness (as of July 2026)

- **HIPAA Security Rule NPRM** (90 FR 898, Jan 6 2025; not yet final):
  would require technology asset inventories that identify AI interacting
  with ePHI, and AI in risk analysis. This repo's inventory answer is one
  line — a single supervisor with versioned rules, hashed knowledge, and an
  exportable audit trail.
- **Section 1557 §92.210** (compliance date May 1 2025): covered entities
  must make reasonable efforts to identify and mitigate discrimination risk
  from patient-care decision-support tools. The mitigation infrastructure
  that rule assumes — evidence spans, criterion-level rationale, audit
  trail — is what the verdicts already carry.
- **Joint Commission × CHAI RUAIH** (Sept 17 2025, voluntary): supervision
  artifacts (verdicts, audit trail, provenance, local-validation gold sets)
  are the evidence its AI-governance elements ask for.

## Prior authorization: the Da Vinci / CMS-0057-F frame

Attending's coverage surface speaks the pipeline's vocabulary and sits at
its gate: **CRD** (is prior auth required + what documentation — CDS Hooks
`order-sign`) → **DTR** (collect the required evidence — the quote-anchored
criteria citations are DTR's job, done adversarially) → **PAS**
(`Claim.use=preauthorization` via `Claim/$submit`; determination in
`ClaimResponse` review actions) — with Attending gating the artifact before
submission and before any denial can be finalized.

Stated precisely: CMS-0057-F's decision clocks (72 h expedited / 7 days
standard) and specific-denial-reason requirement are **in force since
Jan 1 2026**; the four FHIR APIs are due **Jan 1 2027**; the Da Vinci
PAS/CRD/DTR implementation guides are **recommended, not required** by CMS
today (proposed as named standards in CMS-0062-P, Apr 2026). CMS's WISeR
model (live Jan 2026) requires that **all non-payment recommendations be
determined by licensed clinicians** — the same design principle this repo
enforces structurally: `build_denial` raises `PhysicianSignoffRequired`
without a physician's token, and there is no override parameter. CA SB 1120
(H&S §1367.01(k)) and TX SB 815 put the same rule in statute.

## The one-sentence answer

The demo processes zero PHI by construction and is machine-labeled as such;
supervision artifacts export to the FHIR R4 resources designed for them;
HIPAA's technical safeguards map to named repo mechanisms a deployment
inherits behind a BAA — and no certification is claimed, because none
exists.
