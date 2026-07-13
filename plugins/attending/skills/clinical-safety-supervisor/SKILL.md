---
name: clinical-safety-supervisor
description: Supervise clinical agent actions before committing them. Use whenever proposing, drafting, or finalizing an ED triage action (acuity, orders, disposition), a patient- or team-facing clinical message, or a prior-authorization appeal or determination. Calls Attending's deterministic fail-closed gates via MCP; teaches how to respond to BLOCK and ESCALATE verdicts (revise to satisfy every cited criterion; never soften, never bypass — there is no override parameter). Synthetic data only.
license: Apache-2.0
metadata:
  version: "0.3.0"
allowed-tools: mcp__attending__supervise_triage mcp__attending__supervise_patient_message mcp__attending__supervise_coverage_appeal mcp__attending__coverage_preset mcp__attending__list_gates
---

# Clinical-safety supervisor (Attending)

You are working alongside **Attending**, a deterministic, fail-closed
clinical-safety supervisor. It grades proposals; it never proposes. Your
job when this skill is active: **never commit a clinical action or
clinical text without a supervision verdict.**

## The procedure

1. **Draft** your proposal (triage action, patient message, or appeal).
2. **Submit it** to the matching tool BEFORE presenting or committing it:
   - `supervise_triage` — acuity (ESI 1–5), orders, disposition, rationale,
     plus the encounter's chief complaint, age, and vitals.
   - `supervise_patient_message` — the exact text, the audience, and the
     `chart_preset` that matches the scenario.
   - `supervise_coverage_appeal` — claims with quote-anchored cites (copy
     quotes VERBATIM from the note/transcript; `ref: "auto"` — the engine
     locates them; clause ids link criteria but cannot ground facts).
3. **Read the verdict**, then:
   - **ALLOW** → proceed; keep the verdict's ruleset/pack version with
     the artifact.
   - **BLOCK** → a successful supervision result, **not an error**. Read
     every finding (criterion id, citation, evidence span), revise the
     proposal to satisfy EVERY cited criterion, and resubmit. Do not
     argue with the gate, do not drop the safety-relevant content, do
     not retry the identical proposal.
   - **ESCALATE** → stop. A human decides: input quality or chart state
     makes this unsafe to automate, and no rewording fixes it. Say so
     plainly and route to a person.

## Hard rules

- There is **no override parameter** anywhere. Do not simulate one.
- Never lower an acuity or soften a disposition to make a verdict pass;
  satisfy the missing workup instead (the findings name exactly what is
  missing — e.g. `RF-ACS … missing ['ecg', 'troponin']`).
- Never present blocked patient-facing text to a patient pane.
- All inputs must be **synthetic** — never real patient data (the tools
  refuse non-synthetic input where they can detect it; you must not try).
- `list_gates` shows the full failure-mode ledger (F1–F19) if you need
  to understand what is checked and why.

## Worked example

Draft: *58-year-old, chest pressure radiating to the left arm — propose
ESI 4, fast track, no orders.* → `supervise_triage` returns **BLOCK**:
`ATT-UT1` (independent tree says ESI 2), `RF-ACS` (workup incomplete —
missing `['ecg', 'troponin']`). Correct response: revise to ESI 2,
orders `["ecg", "troponin"]`, disposition `main_ed`, resubmit → ALLOW.
Wrong responses: retrying ESI 4 with different wording; calling the
block a tool failure; dropping the chest-pain history to dodge the flag
(the hallucination and anchoring detectors read the record, not your
rationale).

## Demo presets

`coverage_preset("vague_denial" | "unsupported_claim" | "auto_deny")`
runs the committed prior-auth scenarios; `auto_deny` demonstrates the
structural rule: a denial artifact without a physician sign-off token is
impossible (`PhysicianSignoffRequired` raises — denials are
physician-owned, per the same principle CMS's WISeR model and CA SB 1120
put in policy).
