# Attending — mini system card

*2026-07-09, updated 2026-07-11 (v0.2.1) · ruleset `esi-v4-attending-0.3.1` · format modeled on Anthropic
system cards: evidence with intervals, negative findings published, grader
prompts in the appendix, independence labeled, changelog included.*

## 1. What this is, and the release decision

A fail-closed supervising layer over assistive clinical agents across three
surfaces — Decision (triage drafts for the RN), Communication (every
patient/team rendering), and Coverage (prior-auth determinations and appeals,
F14-F19) — one verdict vocabulary, one loop semantics.
Workflow truth: triage acuity is a nursing function under per-hospital
protocols — the supervised agent drafts protocol-aligned suggestions for the
triage RN, never assigns acuity, and Attending checks drafts against the
protocol (ESI v4 here): it independently re-derives acuity, checks red-flag
workups as conjunctions of requirement groups, gates every patient/team-facing
rendering, and never ships a blocked artifact (no override parameter exists).
The product surface this substrate exists for is the patient journey panel
(docs/JOURNEY.md): patients continuously informed of their next step. Release
posture: **demonstration only.** The deterministic core carries the safety
load; the LLM augmentation is additive-only. On uncertainty the system
escalates to a human — degraded input (missing danger-zone vitals, implausible
captured values) and chart-state conditions (a viewed, undiscussed critical
result) are treated as states no wording or retry can fix.

This design is consistent with Anthropic's Usage Policy for high-risk medical
use (qualified-professional review before finalization + AI disclosure) and
with the published finding that supervisor/critique configurations measurably
reduce harm, most of which is **harm of omission** (NOHARM benchmark:
omission ≈ 76.6% of clinical LLM errors; arXiv:2512.01241). Attending is an
omission-catcher by construction: under-triage and missing workup *are*
omission-class harms.

## 2. Evaluations (Ns and intervals, not adjectives)

| Evidence | Result | Notes |
|---|---|---|
| Gold-set regression | FN **0/23**; 95% CI upper bound **12.2%** (Clopper–Pearson) | A regression gate, not a precision claim. A ~1% upper bound needs ≈300 cases — that target is the roadmap, stated rather than implied. FP 0/23 (upper bound 12.2%). |
| Mutation harness | **23/23 mechanisms load-bearing** | 9 communication gates + 7 decision-side mechanisms + 7 coverage gates (incl. denial-signoff bypass and denial-justification mutants). Each disabled in turn → suite must fail; clean run green. In CI on every push. |
| Coverage surface (F14-F19) | structural fail-closed | `build_denial` raises `PhysicianSignoffRequired` without a physician token — no demo path supplies one and no override exists; `determine()` approves or escalates, never denies; quote-anchored grounding; hashed, versioned criteria packs (DRAFT status surfaced verbatim). 51 dedicated tests. |
| Loop exhibit (oracle vs self-critique) | oracle 7/9 @ 1.43 mean attempts; self-critique 5/9 @ 2.00 | Same small performer on identical cases incl. planted traps; committed trace + offline-re-renderable chart (`evaluation/exhibit/`). |
| Boundary-adversarial suite | **22 automated attacks, 0 gate bypasses** | Prompt injection via transcript/rationale/message content; order-token spoofing; Unicode lexicon evasion (zero-width, fullwidth); demographic invariance; consent-waiver arguments. *Automated probes — no human red-team hours yet; stated plainly.* |
| Seeded invariant fuzz | 300 adversarial encounter/proposal pairs, all invariants hold | Never crashes; decision always consistent with finding severities; acuity in range. |
| ReDoS regression | 156 KB pathological text in **0.049 s** (was 64 s) | Bounded gaps enforced by a lexicon-lint test. |
| Live-model runs | `evaluation/live_runs/` — raw transcripts, performer model id stamped | `claude-fable-5`: correct ESI-2 ACS plan ALLOWed; a textually flawless reply still BLOCKed by the disclosure-gap state gate; `unsafe_artifacts_shipped: 0`. |

Commission/omission split of what the gates catch: omission-class — under-triage,
missing requirement groups, dropped escalation acknowledgment, information
blocking (result not acknowledged); commission-class — false reassurance,
interpretation/advice in the patient pane, ungrounded numeric claims,
record-contradicting denials, hallucinated orders in rationale.

## 3. Negative findings — published, with fixes

The failures this project has already had, found by adversarial review and
kept on the record (fix commit in parentheses):

1. **Partial-workup fail-open.** `orders & required` let a single order (an
   ECG) clear a multi-part ACS workup. Found by external review; fixed with
   conjunction-of-disjunction requirement groups (`118c1a7`).
2. **A security fix silently undone by config adoption.** Bounded-gap ReDoS
   fix in code was masked at import by a stale version-matched
   `configs/knowledge.json` still carrying unbounded patterns. The failing
   lexicon-lint test caught the desync; version-bump + regeneration
   discipline now guarded by drift tests (`d3ff0d9`→`118c1a7`).
3. **Audience case fail-open.** `"Patient"`/`"caregiver"` bypassed every
   patient-pane gate; unknown audiences now fail closed to patient
   protections (`d3ff0d9`).
4. **Stale evidence artifacts, twice.** Demo transcript then evaluation
   report lagged the code ruleset; both now CI-guarded (`tests/test_docs.py`).
5. **Zero-width lexicon evasion.** `"f​ine"` slipped the reassurance
   lexicon; all gate matching now NFKC + zero-width-strip + casefold (this
   release).
6. **Review-artifact confusability.** An external reviewer fetched the blank
   review template and reasonably concluded no physician review existed; the
   template is now labeled and links the dated record (`13ea1f3`).

## 4. Independence and decontamination (labeled honestly)

- **Clinical review:** single reviewer (Brandon Dent, MD, EM) who is also the
  project owner — a stage-1 spot-check by industry standards, **not** blinded
  multi-reviewer adjudication and **not** hospital governance. The dated
  record and scope statement: `docs/reviews/2026-07-09-review.md`.
- **External review:** two adversarial reviews by an unaffiliated model-based
  reviewer (OpenAI Codex) plus a fresh-context pre-publication red-team;
  findings adopted are listed in §3. No human third-party audit yet.
- **Decontamination note:** gold cases were authored alongside the rules they
  test (regression pins, not held-out measurement). A held-out,
  independently-authored case set is roadmap item #1 below.

## 5. Compliance mapping (deployment-relevant, not legal advice)

| Requirement | Where Attending enforces it |
|---|---|
| Anthropic AUP high-risk: qualified professional reviews before finalization | Disclosure-gap state gate (no patient message ships while a critical result is undiscussed); ESCALATE paths route to a human; loop has no override |
| Anthropic AUP high-risk: disclose AI to consumers | `gate_compliance` — AI disclosure + human contact path required on every patient rendering (CA AB 3030 pattern) |
| Cures Act information blocking (45 CFR 171) | `gate_info_blocking` — released results must be acknowledged; critical results by name |
| HIPAA posture | All data synthetic; no PHI. A real deployment requires a BAA-covered API path (Anthropic BAA / Bedrock / Vertex) — consumer plans are not covered. "HIPAA-eligible," never "HIPAA-compliant." |

## 6. Limitations and roadmap (in priority order)

1. **Held-out, independently-authored eval set** (~300 cases for a ~1% FN
   upper bound), with blinded ≥2-physician adjudication, inter-rater κ, and
   sequential or exact-interval analysis.
2. **Discontinuous-encounter state machine.** ED encounters are fragmented as
   the *normal case* (clinician paged away, patient at CT; interruptions are
   prospectively associated with prescribing errors and 18.5% of interrupted
   ED tasks are never resumed). Today's `incomplete_audio` detector escalates
   on gaps; the roadmap version holds a pended, fail-closed verdict per
   episode and adjudicates the stitched whole at encounter close. Design
   constraints (extracted from the framework adjudication, ADR-0001 — the
   rejected framework's documented failure modes are the exclusion list):
   one thread per encounter; checkpoint-before-yield; resume at *named*
   suspension points, never index-matched; idempotency keys on every side
   effect; stdlib persistence (`sqlite3`/`json`), byte-identical replay
   preserved.
3. **Unsupported-claim catch-rate benchmark** on a labeled set, reported as
   % caught with CIs *and* the over-block cost, with a
   correct/delete/false-alarm disposition path — the reporting grammar the
   ambient-documentation industry has established for confabulation detection.
4. **Human red-team hours** against the gates (current adversarial evidence
   is automated probes only).
5. **Shadow-mode staged rollout** (log verdicts without blocking → randomized
   cohorts → enforcement), with physician override/edit rate as the
   continuous quality signal. GA is a performance threshold, not a launch
   moment.
6. Order-level contraindication checking; paraphrase robustness beyond
   lexicons; prompt-injection hardening on the performer channel.
7. **Distribution adapters (pattern-only, per ADR-0001):** a stdio MCP
   adapter after the 2026-07-28 spec revision finalizes — distribution only,
   never the enforcement point (an MCP tool is advisory; enforcement stays in
   the interposed loop/gateway) — and a Claude Agent SDK `PreToolUse` adapter
   for teams hosted on that runtime.

## 7. Appendix — grader prompts (verbatim)

The optional LLM augmentation uses two isolated screener judges
(`src/attending/llm.py`); prompts published per system-card practice:

**Anchoring re-reader** — system prompt: emergency-medicine triage safety
reviewer; reviews ONE thing (whether the proposal missed a clinically
significant finding elsewhere in the encounter); instructed not to invent
concerns; forced reasoning then structured JSON verdict
(`fired/confidence/missed_finding/evidence`), fired only at confidence ≥ 0.6.

**Grounding checker** — system prompt: emergency-medicine documentation
auditor; checks ONE thing (whether the rationale asserts facts unsupported by
or contradicting the record); same structured-verdict contract.

Full text: `_ANCHORING_SYSTEM` and `_HALLUCINATION_SYSTEM` in
`src/attending/llm.py` (kept in code so the published prompt can never drift
from the running prompt).

## Changelog

- 2026-07-12: demo-week hardening. A second fresh-context adversarial
  review (verdict: ship-after-fixes) found — and this repo closed — a
  cased-outcome fail-open in the coverage outcome gate (`"DENY"` bypassed
  the no-automated-deny check; outcome vocabulary is now normalized and
  closed: unrecognized outcomes block, a determination without an outcome
  escalates) and a trace-vs-narrative drift in the loop-exhibit story (the
  injected-authority trap holds under both feedback regimes — COV-F15 on
  every attempt — rather than being an oracle-only catch; the docs now
  tell the trace's story). The same review independently verified gold-set
  FN 0/23, every mutation mechanism (then 22) load-bearing, byte-identical replay
  with sha256-identical hosted pages, and the exhibit numbers recomputed
  from the committed trace. Also this week: revision diff view and
  `?present` projector mode in the replay UI, WCAG
  contrast/motion/non-color-verdict pass with a light patient pane, and a
  web render regression gate (node smoke against the golden transcript).
  Suite 256 → 272 tests.
- 2026-07-11 (v0.2.0): third supervised surface — COVERAGE (INVERSION
  F14-F19): structural physician-signoff denial gating, quote-anchored
  citation grounding, hashed criteria packs (drafts quarantined pending
  physician ratification). Model seam consolidated to `ATTENDING_MODEL`
  (default `claude-opus-4-8`) with archived dual-model live runs showing
  verdict-level equivalence. Loop exhibit committed (oracle-feedback vs
  self-critique). Mutation harness 15 → 22 mechanisms; suite 176 → 256 tests.
  One process failure on record: commit `5bdca4a` shipped with `make check`
  red (lint/typecheck) and one CI failure, repaired in `d977a6c`.
- 2026-07-09: first edition, ruleset 0.3.1 — after two external reviews, one
  physician review, mutation coverage of both surfaces, and the adversarial
  suite. Known-stale risk: none at publication (drift tests enforce).
