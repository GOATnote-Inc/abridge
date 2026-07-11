# The journey tracker — product design (shipped 2026-07-10; clinical content from the verified citation research pass)

*2026-07-10. Direction set by the project's physician owner: the core product
is a communication tool so ED patients constantly know the next step. The
supervisor is the substrate that makes that communication deployable; it is
not the product surface.*

## The clinical problem, stated by workflow truth

- Post-Cures, results reach the patient's portal the moment they finalize —
  a troponin or CT read lands on a phone in an ED bed before anyone has
  talked to the patient.
- The dominant ED experience failure is waiting **without information**:
  nobody tells the patient that the repeat troponin is scheduled for 3 hours
  from now, or that their MRI slipped because an emergent case took the
  scanner. The care is proceeding; the patient can't see it.
- Triage acuity is a **nursing function** governed by clear per-hospital
  protocols. Physicians do not assign ESI. Any agent in this space *assists
  the triage RN with a protocol-aligned draft*; it never assigns acuity, and
  the supervisor checks the draft against the protocol, not the nurse.

## The product

The physical anchor is the ED room whiteboard: every room has one, it is
supposed to carry the plan and the next step, and it is almost never current
because updating it is manual work the RN does not have time for. The journey
panel is that whiteboard, deriving from chart state instead of a marker.


A per-encounter journey panel — the same panel for the patient and the
nurse — showing:

1. **Steps** (done / in process / expected): arrived → triage (RN) → ECG →
   troponin drawn → result → repeat troponin at the protocol interval →
   disposition decision. Each step carries its time window and the pathway
   citation it comes from.
2. **The "next step" box** — always populated. Before the result: "repeat
   troponin scheduled per protocol; continued monitoring." After a critical
   result: what typically happens next per published pathways (monitoring,
   repeat testing, cardiology consultation, admission is often recommended),
   explicitly framed as general pathway information with risk acknowledged —
   never a promise, never a diagnosis, never the patient's individual plan.
3. **Delay events, explained**: "MRI delayed — emergency cases take scanner
   priority; you have not been forgotten; current estimate …" Waiting with
   an explanation is a different clinical experience from waiting in silence.
4. **Labels on every patient-facing string**: AI-generated disclosure,
   informational-not-medical-advice, "your care team makes decisions about
   your care," and the human contact path. Exact statutory wording (AB 3030
   elements, placement) comes from the research pass — no invented legal text.

## How the safety layer fits (substrate, not headline)

- Every journey string is a patient-facing rendering and passes the comms
  gates like any other: disclosure, no interpretation/minimization, results
  named, escalation acknowledged, readability, Unicode folding.
- **New rendering kind `result_context`** (gate semantics change, directed by
  the physician owner 2026-07-10; to be recorded in the review log): when a
  critical result is released and viewed, the disclosure gap continues to
  page the team and continues to block *conversational replies* — but a
  labeled, not-advice, result-naming, team-notified **context panel may
  travel with the result**. Context with the result, never instead of the
  conversation. The bedside discussion requirement is unchanged.
- The decision surface remains for what it is actually for: checking an
  assistive agent's drafts (workup completeness against fired red flags,
  protocol-aligned acuity suggestions for the RN) and refusing unsafe
  releases. It is one beat of the demo, not the spine.

## Journey data (deterministic; schema only until research lands)

`pathway.py` — pure function of chart state + encounter context:

```
JourneyStep: id, label, status(done|active|expected), detail,
             window(str|None), citation(str|None)
DelayEvent:  what, why, revised_estimate, citation(None ok)
Journey:     steps[], delays[], next_box(patient_text, nurse_text),
             labels(required disclosure elements)
```

Chest-pain pathway only for the demo. All step intervals, "what typically
follows an elevated troponin" content, and label wording enter ONLY from the
research pass with citations (ACC/AHA 2021 chest pain guideline, hs-cTn
algorithm timings, AB 3030 elements, FDA CDS informing-vs-directing line) —
nothing clinical is authored from memory.

## Demo choreography (replaces the current stage framing)

1. Patient roomed; journey panel live on patient phone and nurse pane alike.
2. Triage beat (recast): agent drafts a protocol suggestion **for the RN**;
   supervisor checks it against the protocol; RN decides. One beat, honest.
3. ECG done (door-to-ECG window shown) → troponin drawn → next-box says what
   is being waited on and when.
4. Result lands in the portal the second it finalizes (post-Cures reality).
   The gated `result_context` panel travels with it; the disclosure gap pages
   the team for the bedside conversation; conversational replies stay blocked
   until the discussion is documented.
5. A delay event (imaging bumped by an emergent case) renders as an
   explanation, not silence.
6. Rail shows the audit trail — verdicts, criteria, citations — for the
   evaluator audience; patients see the journey, not the rail.

## What blocks on research (no build before it lands)

- AB 3030 exact disclaimer elements/placement + the provider-review exemption.
- FDA CDS non-device framing for a patient-facing "typical next steps" panel.
- Serial troponin intervals by assay type, with guideline sections.
- Post-Cures immediate-release patient-preference evidence; ED
  waiting-information and whiteboard literature (grounds the shared pane).
