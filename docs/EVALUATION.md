# How Attending is evaluated

*The five questions a reviewer should ask of any clinical-AI system, answered
with this repository's own artifacts. Every number here is enforced by
`scripts/evidence_counts.py --check` in CI or pinned by a named test; every
metric definition names its denominator and the script that computes it
(the discipline the Texas AG's 2024 Pieces Technologies settlement made a
legal norm: published accuracy claims must publish their definitions).*

## 1. How is it evaluated?

**Cardinal metric: false negatives, defined exactly.** A false negative is a
gold-set case whose expected decision is BLOCK or ESCALATE that the
supervisor ALLOWs — clinically, **undertriage sensitivity** on the decision
surface (a missed ESI-1/2 is the injury this system exists to prevent).
Computed by `attending.evaluate` over `evaluation/goldset.jsonl` (n=23,
physician-reviewed 2026-07-09); the suite fails if FN > 0. Zero observed
misses is reported as an **exact Clopper–Pearson one-sided 95% upper bound**
(`attending.evaluate.binom_upper`), not as "100%": at n=23 the bound is
~12.2%, which is why the gold set is a **regression gate, not a precision
estimate** — the docs say so wherever the number appears.

**The measurement the gold set cannot provide is pre-registered.**
`evaluation/heldout/PROTOCOL.md` defines a sealed held-out evaluation before
any case exists: blinded clinician author (has not read `src/` or `tests/`),
sha256 seal committed before any scored run, exactly one scored run per seal,
results published regardless of outcome, disagreement transcripts verbatim.
Target n≈300 sizes zero-miss to an upper bound below ~1% (Clopper–Pearson;
the rule-of-three cross-check gives 3/300 = 1%).

**Contamination statement.** The deterministic supervisor has no trainable
parameters — there is nothing to leak a test set into. The only tunable
surface is the versioned ruleset (`knowledge.py`, `RULESET_VERSION`), whose
every change requires human review, and the sealed held-out set is authored
by a clinician who has never seen it. LLM augmentation (off by default) can
add findings but can never suppress or downgrade one, so contamination could
only create false positives, never false negatives.

**Grader design follows the grader trichotomy.** The gates are code-based
graders (deterministic, reproducible, published — they *are* the product).
Where an LLM judges (the optional anchoring/hallucination augment and the
demo performer), the judge is configured independently of the performer
(`ATTENDING_MODEL` seam), any parse failure or refusal degrades to the
deterministic floor (the fail-closed analogue of giving a judge an "Unknown"
escape), and dual-model live runs are archived showing verdict-level
equivalence (`evaluation/live_runs/`, fable-5 vs opus-4.8, byte-compared).

**Grader-vs-clinician agreement** (the meta-evaluation HealthBench and
MedHELM made table stakes) has standing machinery:
`scripts/adjudication_packet.py` renders the gold-set inputs as a blinded,
deterministically-shuffled packet (labels and engine verdicts stripped —
tests assert nothing leaks); the scorer recomputes engine verdicts live and
reports raw agreement, Cohen's κ, the full confusion table, and every
disagreement for verbatim publication. Disclosed limitation: the reviewing
physician saw these cases *with* labels on 2026-07-09, so in-corpus κ is an
optimistic bound — the sealed held-out set provides the unbiased repeat.
Result pending the blinded read; it will be published either way.

**Beyond the gold set:** 22 adversarial attacks (`tests/test_adversarial.py`),
seeded invariant fuzzing (300 generated cases, `tests/test_invariants.py`),
degraded-input behavior (the four detectors widen the confidence interval
toward acute — perturbation makes the supervisor *more* conservative, never
less), and the loop exhibit (`evaluation/exhibit/`) comparing oracle-findings
revision against self-critique on the same performer (7/9 vs 5/9 converged;
N=9, labeled a demonstration — the measurement is the cited literature).

## 2. Are results traceable?

Every verdict is **evidence-linked at the span level**: red-flag findings
carry the source field and character span they fired on; coverage citations
are quote-anchored (the performer supplies the exact quote, the
deterministic engine locates it — models cannot count offsets). The quote is
stored **inside the verdict record**, so the audit outlives the source
system's retention window (ambient-documentation vendors typically delete
source audio in 14–30 days; a verdict here remains checkable after that).

The provenance chain, artifact by artifact:

| Artifact | Where | What it pins |
|---|---|---|
| Ruleset version | every `Verdict.ruleset_version` | which reviewed rules decided |
| Criteria-pack hash | coverage provenance (`pack_version` + sha256) | which clause text decided |
| Model id | live transcripts (`performer_model`), provenance packs | which model proposed |
| Loop trace | `LoopTrace` (opt-in JSONL): proposal hash, decision, findings by criterion, latency | every attempt, replayable |
| Live runs | `evaluation/live_runs/` + provenance README | dated, model-stamped transcripts |
| Replay | `make demo` byte-identical; golden pinned by `tests/test_demo.py`; hosted pages sha256-identical to the repo | what the audience sees is what the code does |
| FHIR export | `attending.fhir` — verdicts as DetectedIssue, lineage as Provenance (pack hash as RFC 6920 `ni:///sha-256;…`), audit as AuditEvent | the same chain in the resources auditors consume |

Reproduce any headline number from a tag: `git checkout v0.2.1 && make
check` (gold set, mutation, counts). Corrections are on the record — the
SYSTEM_CARD changelog retains the two red-gate commits and the 2026-07-12
review's findings rather than rewriting them.

## 3. Is the test coverage relevant?

**Coverage is necessary, not sufficient; the sufficiency metric is fault
injection.** Line coverage finds unexecuted code but does not evidence test
effectiveness (Inozemtseva & Holmes, ICSE 2014); what predicts real-fault
detection is mutation adequacy (Just et al., FSE 2014; Google ICSE-SEIP
2018). And safety mechanisms specifically are *not invoked during normal
operation* — the only way to test a gate is to break something (the
fault-injection rationale of ISO 26262; IEC 61508 calls the result
diagnostic coverage).

So the headline claim is **mechanism-level mutation adequacy: 23/23
fault-injected safety mechanisms are detected** — disabling any gate via the
`ATTENDING_MUTATE_GATE` conftest hook fails at least one named test with the
other mechanisms intact (single-fault logic), and the clean run passes
(`make mutation`, run in CI). In ISO 14971 §7.2 terms: each mechanism is a
risk control, and its killing tests are the documented verification of that
control's *effectiveness*, not merely its implementation.

Line coverage is reported as the gap-finder it is: safety-path modules run
95–100% (supervisor 95%, esi 99%, coverage gates 98%, sitrep gates 99%,
loop 97%, comms and pathway 100%, detectors 90–100%); repository-wide 84%.
`evaluate_coverage.py` shows 0% by design — it is the ratified-goldset
harness and no ratified goldset exists yet (quarantine is working).

**Fine-grained round 1 (2026-07-12, `mutmut` on `coverage.py`):** 814
operator-level mutants, **487 killed (59.8%) by the module's dedicated
51-test suite alone** (config in `pyproject.toml [tool.mutmut]`; the
number is deliberately per-module-suite — the full suite exercises this
code further but would blur which tests carry which control). The round's
real yield was five test gaps in load-bearing logic, all now pinned
(`TestMutationRoundGaps`): **two fail-open inversions that a redundant
gate was masking** (`_resolve_span` returning ok on unknown cite types and
unparseable refs — invisible to the mechanism-level harness because the
chart-evidence rule blocked those cases anyway; the single-fault lesson,
live), a `continue`→`break` that would have reported only the first
violating claim, a crash path on claim facts absent from the note, span
boundary off-by-ones, and unasserted verdict traceability fields.
Surviving mutants, classified: message/citation string mutations in
branches without field-level assertions (cosmetic to safety semantics),
fail-closed-direction vocabulary variants (a stricter gate is not a
weaker one), and equivalents (e.g. `+=`→`=` on the first accumulation
after an empty init).

**Fine-grained round 2 (same day, `esi.py` — the decision spine):** 268
mutants; the goldset/invariants/knowledge/adversarial suites alone killed
69.4%, and the round exposed the sharpest gap yet: **no test pinned the
exact boundary of any physician-reviewed clinical threshold** — `GCS ≤8`
vs `<8` survived, `SpO2 <90` vs `≤90` survived, and so on for every
life-saving vital. `tests/test_esi_boundaries.py` now pins each threshold
at and adjacent to its reviewed value (a silent one-unit drift is exactly
the "silently weaken a safety criterion" failure the charter forbids),
plus the altered-consciousness interval, danger-zone strict inequalities,
the peds band edge, plausibility-envelope edges (a vital *at* the bound
is a patient, not a typo), the multi-vital quarantine walk, and the
pipeline property that a quarantined capture-error HR of 400 cannot mint
an ESI-1. Final kill: **223/268 (83.2%)**; survivors are
getattr-default/label-string equivalents and falsy-equivalent rewrites,
classified the same way. `sitrep/gates.py` round queued.

**Known limits, stated:** whole-mechanism disables are coarse mutants — a
subtle within-mechanism boundary bug can escape them (and ~17% of real
faults couple to no mutant at all, Just 2014) — which is exactly what
round 1 above demonstrated. A mechanism killed by one test is
single-point verification; the current spread is 1–26 killing tests per
mechanism, reported as diagnostic detail, never as the headline.

## 4. Are results medically valid and evidence-based?

Every clinical rule value carries its citation in `knowledge.py` (ESI v4
handbook; AHA/ACC 2021 chest-pain guideline §4.1 for troponin intervals —
1–3 h high-sensitivity, 3–6 h conventional; ESC 2023 monitoring class I;
HEART-pathway disposition language attributed as "guidelines commonly
recommend"). Rule values are labeled **physician-reviewed (single-reviewer,
demonstration scope; board governance pending — do-not-deploy stands)**;
the review is a dated record with per-ruling trade-offs
(`docs/reviews/2026-07-09-review.md` and addenda), not an adjective.

**Omissions are the dominant severe-error class in clinical AI** (NOHARM,
arXiv:2512.01241: ~77% of severe errors are omissions) — and the
supervisor's failure classes are omission-shaped by design: requirement
groups name the *missing* workup elements (Rule 3); the disclosure-gap gate
fires on the *absence* of a documented discussion; the care-board panel
ships *with* the released result or not at all. Evidence-linking alone
catches fabrications; these gates catch what isn't there.

**What is not claimed:** no external validation has occurred yet (the Epic
Sepsis Model's external AUC of 0.63 against a claimed 0.76–0.83 is the
cautionary precedent this repo takes seriously); the sealed held-out run is
the pre-registered first step, and its result will be published whichever
way it lands. Single-reviewer review is demonstration scope, not board
governance. A passing grade here is not a guarantee of behavior in
deployment — regression gates bound what recurs, not what is possible.

## 5. Are common FHIR and HIPAA-compliant methods used where appropriate?

Yes — deliberately and without overclaiming. `attending.fhir` exports
supervision artifacts to the FHIR R4 resources designed for them
(DetectedIssue for flagged issues, Provenance with quote-anchored citations
as entity role `quotation` and the criteria pack as `source` carrying its
sha256 as an RFC 6920 `ni:` URI, AuditEvent on the ATNA-derived model,
RiskAssessment plus an Observation coded LOINC 75636-1 for triage acuity);
every exported resource carries the `HTEST` ("test health data") security
label — the standards-native form of this repo's `synthetic: true`
attestation — and the exporter refuses non-attested input. The committed
example (`evaluation/fhir_export_demo.json`) regenerates byte-identically
(`tests/test_fhir.py`) and validates against the **official HL7 FHIR
Validator** (v6.9.11, FHIR 4.0.1, run 2026-07-12): **0 errors**; the four
remaining warnings are the validator noting it cannot resolve this repo's
own criterion CodeSystem URI (the codes live in `INVERSION.md`, not a
published FHIR CodeSystem — by design), plus two informational notes on
example-strength bindings. The HIPAA posture — zero PHI by construction,
Safe-Harbor-aligned schema bans, §164.312 safeguard mapping, deployment
behind a covered entity's BAA — is `docs/COMPLIANCE.md`. No FHIR or HIPAA
certification exists or is claimed (HHS recognizes none; HL7 does not
certify products).
