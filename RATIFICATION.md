# Ratification record — coverage drafts (clinical-review-packet flow)

*Source: the six flagged items in `drafts/coverage/README.md` §"Physician
review — look here first", quoted verbatim. Scope: demonstration; single
physician reviewer; state-plan variables remain site-configurable and so
labeled. Nothing below is wired into live gates, goldsets, or demos until the
explicit "ratified" command; promotion is executed by
`scripts/promote_ratified.py` in a single commit carrying a `Ratified-by:`
trailer.*

---

## Item 1 — SLT-01 cutoff and SLT-04 re-evaluation interval

> **`SLT-01` cutoff** ("1.5 SD below the mean / ~7th percentile") and
> **`SLT-04` re-evaluation interval** are marked *state-plan variables* —
> placeholders at guideline level, not invented rules; the operative state's
> published standard must be substituted.

**Decision:** ______________________________________________

## Item 2 — Composite state-manual authorities

> **Composite state-manual authorities** (`AUTH-STATE-EPSDT-*-MANUALS`)
> paraphrase typical public manuals without naming a state; swap in the
> actual state manual before any real use.

**Decision:** ______________________________________________

## Item 3 — GSC-07 approval/denial sign-off asymmetry

> **`GSC-07`:** clean *approvals* ALLOW without physician sign-off (approval
> extends care — the safe direction; denial always requires sign-off). This
> asymmetry is a policy decision awaiting review.

**Decision:** ______________________________________________

## Item 4 — Signed deny on indeterminate evidence still escalates

> **`ADV-03` / `GSC-04`:** a *signed* deny on admittedly indeterminate
> evidence still ESCALATEs rather than ships — sign-off does not cure an
> evidence gap. Confirm this is the intended posture.

**Decision:** ______________________________________________

## Item 5 — EPSDT floor clauses as blocking rules

> **EPSDT floor clauses** (`SLT-06` / `DME-06`) assert that restorative-only
> / maintenance-exclusion / convenience-item rationales cannot alone support
> an under-21 denial — paraphrased from 42 U.S.C. § 1396d(r) and the CMS
> 2014 EPSDT guide; confirm the legal paraphrase before demoing it as a
> blocking rule.

**Decision:** ______________________________________________

## Item 6 — Denial-letter identifier hygiene tradeoff

> The **denial letter** deliberately carries no dates or reference numbers
> (identifier hygiene) — slightly less realistic than a live payer letter;
> its vagueness (no clause-level citation) is the audited property and is
> intact.

**Decision:** ______________________________________________

---

## Signature

- **Name:** ______________________________________________
- **Date:** ______________________________________________
- **Role:** physician reviewer (single-reviewer, demonstration scope;
  hospital/board governance not implied)
