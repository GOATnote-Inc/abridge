# Attending

**A communication layer that keeps ED patients continuously informed of
their next step — made deployable by a fail-closed safety supervisor
underneath.**

Post-Cures, results reach a patient's phone the second they finalize; the
dominant ED experience failure is waiting without information. The product
surface is a per-encounter journey panel — the same panel for patient and
nurse — with an always-populated "next step" box grounded in published care
pathways (design: [`docs/JOURNEY.md`](docs/JOURNEY.md)). None of that is
deployable unless every AI-generated string is safe and compliant by
construction, which is what the substrate provides: Attending reviews every
action and every rendering, blocks the unsafe ones, and cites the criterion
or law tripped, with the evidence span quoted.

- **Decision** (`attending.supervise`) — checks an assistive agent's drafts.
  Workflow truth: triage acuity is a *nursing* function under per-hospital
  protocols; the supervised agent drafts a protocol-aligned suggestion for
  the triage RN — it never assigns acuity — and Attending checks the draft
  against the protocol (ESI v4 here). It blocks under-triage drafts and any
  release with an incomplete red-flag workup; an incomplete workup on an
  in-department disposition is a WARN (the workup is still in flight — a
  physician-ratified boundary, `docs/reviews/`). Four failure-mode detectors:
  incomplete audio, transcription error, anchoring, hallucination.
- **Communication** (`attending.comms.supervise_rendering`, backed by
  `src/sitrep`) — every patient/nurse/physician/consultant rendering,
  including the journey panel's own strings. Blocks interpretation and
  minimization in the patient pane, information blocking (Cures Act), missing
  AI disclosure (AB 3030), ungrounded claims, dropped escalations, and the
  disclosure gap (a patient alone with a viewed critical result). Failure
  ledger: [`INVERSION.md`](INVERSION.md), F1–F13.

Both surfaces use one verdict vocabulary (`Decision`/`Finding`/`Severity`)
and fail closed: "not evaluated" never reads as "safe." Every verdict quotes
the source field and character span it acted on, so a reviewer can check the
claim against the input. Evidence: [`docs/SYSTEM_CARD.md`](docs/SYSTEM_CARD.md).

Built on [HealthCraft](https://github.com/GOATnote-Inc/healthcraft)
(Apache 2.0, arXiv:2605.21496), whose fail-closed grader, FHIR R4 world state,
and clinical tools Attending reuses. Scoped for the *Future of Agentic AI in
Healthcare* hackathon (Abridge × Anthropic × Lightspeed).

## The demo — one encounter, both surfaces

```bash
make demo        # deterministic replay: pure function of the fixture, rehearsable
make demo-live   # identical choreography, drafts from the live Fable 5 performer
make serve       # gateway + browser UI:  /ui (replay)  ·  /ui/playground.html
```

Three surfaces: the replay (hosted at
[goatnote-inc.github.io/abridge](https://goatnote-inc.github.io/abridge/)) is
the walkthrough, byte-identical on every run; the playground
(`/ui/playground.html`, needs the local gateway) accepts your own case or
message — or one-click adversarial presets (under-triage, ECG-only discharge,
"denies chest pain", injection, zero-width evasion) — and renders each verdict
with its criterion, citation, and the highlighted span of your input it acted
on; the API and committed transcripts are the evidence artifacts.

A 58-year-old with chest pressure. Stage A: the agent's ESI-3 fast-track
proposal is blocked (under-triage; ECG/troponin missing; anchored rationale;
a hallucinated SpO2 — with the ACEP citation on the finding). The findings
feed back to the agent; its revised ESI-2 plan ships and writes orders to the
chart. Stage B, 40 minutes later: the troponin results critical and
auto-releases to the portal under the Cures Act; the patient views it and
asks "is it bad?". The care board — the room whiteboard that updates itself —
ships a labeled, guideline-attributed next-steps panel WITH the result
(repeat troponin to watch the trend; monitoring; nurse will go over it;
doctor reviewing). The agent's conversational reply — warm, professional,
subtly minimizing — is blocked, and the disclosure-gap state gate flags the
track board; the RN acknowledges the result with the patient at the bedside
(documented), and only then does a conversational reply ship. Realism note:
an elevated troponin with no new symptoms or ECG changes means
repeat-and-monitor, not an automatic bedside consult. The run ends with
`unsafe artifacts shipped: 0`.

In live mode the drafts come from the model instead of the script. In the
recorded run, the model's first reply was textually compliant and was still
blocked by the disclosure-gap state gate — the gate reads the chart, not the
wording.

## What Attending is — and isn't

Attending supervises **assistive-agent drafts and AI communications**:
protocol-aligned triage suggestions for the RN, workup completeness against
fired red flags, disposition drafts, and every patient/team-facing message
including the journey panel. It is **not** an order-entry CDS (no
contraindication engine yet), not a diagnosis engine, not a triage authority
(the RN is), and it supervises the *agent*, never the clinician. False
positives cost an agent a rewrite — not a mis-triaged patient — which is why
thresholds deliberately sit on the sensitive side.

No agent framework is required. LangChain/LangGraph/LangSmith were
evaluated and rejected or reduced to patterns; the one adoption is native
Anthropic structured outputs, which removes the JSON-parse failure class
without new dependencies: [`docs/adr/0001-framework-adjudication.md`](docs/adr/0001-framework-adjudication.md).

## The deployable unit

`attending.loop` is what a clinic integrates: `run_triage_loop` /
`run_rendering_loop` — propose → verify → **revise on BLOCK** (findings feed
back to the performer verbatim, machine-actionable) → ship on ALLOW, with
fail-closed stops everywhere else: supervisor ESCALATE (degraded input) stops
immediately; chart-state gates stop immediately (a rewrite can't fix the
chart); a revision cap prevents the performer outlasting the rubric; a blocked
artifact is **never** shipped — there is no override parameter.

## The thesis

A clinical agent proposes a triage acuity, some orders, and a disposition.
Attending independently re-derives the safe answer and grades the proposal
**fail-closed** — "not evaluated" never reads as "safe," exactly as HealthCraft's
`compute_reward` treats a missing `safety_critical` result as a violation.

```
$ attending examples/chest_pain_undertriage.json

 ATTENDING: BLOCK
  proposed acuity : ESI 3
  attending acuity: ESI 2
  recommended     : ESI 2  (fail-closed)

  findings (why Attending acted):
    [block] ATT-UT1  proposed ESI 3 is less acute than the ESI 2 the tree assigns
         cite: ACEP Clinical Policy: Suspected NSTE-ACS (Ann Emerg Med 2018)
    [block] RF-ACS   Chest pain ... required workup incomplete — missing
                     ['ecg','troponin']; disposition 'fast_track' would release the patient
```

## How it works

Two layers, deliberately split by what code can and can't do:

**Program-aided (deterministic, reproducible, no API key):**
- **ESI v4 decision tree** (`esi.py`) — the AHRQ/ENA standard US ED triage
  algorithm, walked A→B→C→D. Life-saving vitals → ESI 1; red flags / altered
  mental status / severe pain / danger-zone vitals → ESI 2; resource count →
  ESI 3/4/5. Versioned + `approval_status` so a department board signs off on
  the exact ruleset.
- **Confidence interval over acuity** (`confidence.py`) — hard floors (A/B) are
  tight; the resource estimate (C) is genuinely uncertain and spans levels. The
  supervisor acts on the **most-acute end** of the interval; the interval *is*
  the fail-closed mechanism.
- **Failure-mode detectors** (`detectors/`) for Brandon's four named weaknesses:
  - `incomplete_audio` — missing danger-zone vitals / truncated transcript →
    a lower acuity cannot be *cleared* → escalate.
  - `transcription_error` — physiologically implausible captured values
    (HR 400, F-as-C temp, swapped BP) → don't trust a vital driving triage.
  - `anchoring_bias` — a red flag fired but the proposal is low-acuity with its
    required workup unordered.
  - `hallucination` — numeric claims in the rationale checked against the
    record ("SpO2 98%" when the chart says 97).

**LLM-augmented (Fable 5, optional):** the anchoring and hallucination detectors
expose an `llm_augment` hook so a Claude **Fable 5** pass can extend the
deterministic floor to subtler, non-numeric reasoning — LLM only for what code
can't do. `claude-fable-5` runs natively through HealthCraft's Anthropic client.

## Run it

```bash
make demo          # the two-surface story (replay, deterministic)
make test          # full suite (gold set + mutation-guarded gates)
make goldset       # the safety gate alone — exits 1 on ANY false-negative
make serve         # FastAPI gateway; four-pane UI at /ui  (pip install -e ".[gateway]")
PYTHONPATH=src python3 -m attending.cli examples/chest_pain_undertriage.json
```

CLI exit code is a gate: `0` allow, `2` block, `3` escalate.

## Threat model & known limitations

Stated plainly, because a safety layer that hides its own attack surface isn't one:

- **The fail-closed guarantee has a precise boundary.** It covers the
  decision pipeline (acuity, requirement-group workups, dispositions), the
  chart-state gates, numeric claim grounding, and record-contradicting
  denials ("denies chest pain" on a chest-pressure record is caught
  deterministically). Broader free-text semantics ("no cardiac history" vs.
  the medication list) are optional LLM augmentation — additive-only, off by
  default, and its absence is a disclosed gap, not a silent one.
- **Text lexicons are floors, not fences.** Paraphrase can evade a phrase list
  (`"nothing that should worry you"`). The load-bearing gates are *structural* —
  the disclosure gap, monotonic escalation, grounding-by-reference, numeric
  claim checking, and the ESI tree — which no wording can bypass. House rule:
  a missed phrase gets added with its test in the same change.
- **Clinical values are physician-reviewed, not board-approved.** Every
  threshold, red flag, and pediatric band carries a citation and a
  `RULESET_VERSION`; the full ruleset and gold set were reviewed item-by-item
  by an EM physician on 2026-07-09 (`docs/reviews/`), single-reviewer and
  demonstration-scoped. Hospital governance approval has not happened.
  Do not deploy against patients.
- **No order-level contraindication checking yet.** Attending blocks
  under-triage and missing workup; it does not yet veto a clinically wrong
  *order* (e.g. anticoagulation with a dissection differential) — that layer
  lives in HealthCraft's mutate tools and is future work here.
- **The gateway is a demo surface**: no authn/authz, binds `127.0.0.1`,
  `?live=1` spends API budget if a key is present. Not a deployment posture.
- **LLM augmentation is additive-only** and off by default: it can raise a
  finding the deterministic floor missed, never suppress or downgrade one, and
  any transport failure degrades to the floor.
- **All data is synthetic.** No PHI anywhere; scenario loading refuses
  non-attested or identifier-bearing fixtures (INVERSION F13).

## Validation status & roadmap

What is validated today: regression (23-case synthetic gold set, FN=0 in CI),
mutation coverage (`make mutation` — all 8 gates load-bearing, enforced in
CI), an adversarial pre-publication red-team (secrets/claims/fail-open/ReDoS),
live-model runs whose unsafe drafts were blocked by deterministic gates, and a
structured **physician review of every clinical value and gold case**
(2026-07-09, single EM reviewer — the dated record is
[`docs/reviews/2026-07-09-review.md`](docs/reviews/2026-07-09-review.md); the
blank template for the next round regenerates via `make review-packet` →
`docs/CLINICAL_REVIEW_PACKET.md`). What is **not** validated yet — the honest product
blockers: hospital-governance sign-off, false-positive burden measured against
real ED workflow, clinician-labeled (non-synthetic) cases, and adversarial
paraphrase coverage beyond the current lexicons. Next (full list with rationale in `docs/SYSTEM_CARD.md` §6): (1) a held-out
independently-authored eval set (~300 cases for a ~1% FN upper bound) with
blinded multi-physician adjudication, (2) a discontinuous-encounter state
machine — ED encounters fragment as the *normal case*; verdicts should pend
per episode and adjudicate the stitched whole, (3) FHIR-native chart
ingestion, (4) human red-team hours against the gates.

## Status

Two-surface supervisor + supervised control loop + Fable 5 performer + demo +
gateway + four-pane UI; 152 tests, ruff + mypy clean, gold-set FN=0 enforced in
CI, mutation-checked gates (disabling one fails 6 tests across 5 layers).
Evidence is guideline-level (ESI Handbook v4, ACEP, AHA/ASA, Surviving Sepsis,
Joint Commission, Cures Act, CA AB 3030); criterion→page mapping and all
clinical values **pending physician/board review**.
