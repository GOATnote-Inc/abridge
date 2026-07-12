# Held-out coverage evaluation — protocol (no cases exist yet, by design)

*Status: protocol only. This document intentionally precedes any case
authoring. The repository's own gold sets are regression pins authored
alongside the rules they test; this protocol defines the measurement they
cannot provide.*

## Purpose

Estimate the coverage supervisor's false-negative rate on cases it was not
built against, with a pre-registered procedure that cannot be quietly
adjusted after seeing results. Target: **n ≈ 300** cases, sized so that
zero observed false negatives would bound the FN rate below ~1% (exact
Clopper–Pearson, 95%; `attending.evaluate.binom_upper(0, 300) < 0.01`;
rule-of-three cross-check: 3/300 = 1%).

**Contamination statement:** the supervisor under test has no trainable
parameters — nothing can memorize this set. Its only tunable surface is the
versioned, human-reviewed ruleset, and the single-run rule above forbids
adjusting that ruleset against this set between seal and run.

## Blinding

- Cases are authored by a clinician (pediatrician or pediatric
  subspecialist) who **has not read `src/` or `tests/`** and has not been
  told the gate implementations, thresholds, or failure taxonomies beyond
  what `AUTHORING_TEMPLATE.md` states in clinical language.
- The author receives: the template, the two criteria packs' *clause text*
  (clinical content only — no ids-to-gate mapping), and nothing else from
  this repository.
- The author signs the attestation block in the template for every batch:
  no repository code was read; all content is synthetic; no real patient
  informed any case (F13 applies in full: `synthetic: true`, no
  identifier-shaped fields).

## Seal procedure

1. Author delivers the case set as JSONL to a neutral holder (not the
   engineer who wrote the gates).
2. The set is archived as a tarball; its **sha256 is committed to this
   repository** (`evaluation/heldout/SEAL.txt`: hash, case count, date,
   author role) **before any scored run**.
3. Any post-seal edit to any case invalidates the seal; a corrected set is
   a NEW seal with a new hash and its own single run.

## Single-run rule

- Exactly **one scored evaluation** per sealed set, run from a tagged repo
  commit recorded alongside the results.
- No case, threshold, or gate may change between seal and run.
- Findings from the run may motivate engine changes — those changes are
  evaluated against the *next* sealed set, never re-scored against this one.

## Reporting — regardless of outcome

- Published in this directory: per-case verdicts, FN/FP counts with exact
  Clopper–Pearson intervals, the repo tag, the seal hash, and every
  disagreement transcript verbatim.
- A bad result is published with the same prominence as a good one. The
  purpose of the seal is to make that promise mechanical rather than
  aspirational.

## Roles

| Role | Constraint |
|---|---|
| Case author | clinician; blinded to implementation; signs attestation |
| Seal holder | receives set, computes and commits hash; not the gate author |
| Runner | executes the single scored run from the tagged commit |
| Reviewer of disagreements | physician; rulings recorded per case |
