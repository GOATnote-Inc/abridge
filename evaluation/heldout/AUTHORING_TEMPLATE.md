# Case authoring template — held-out coverage set

*For the clinician author. You do not need to read any code, and per the
protocol you must not. Everything below is clinical. Every case you write
must be fully synthetic — invented by you, resembling no specific patient.*

## What one case is

A prior-authorization situation for a pediatric Medicaid service (speech
therapy, or adaptive equipment/DME), with enough clinical documentation
that a reviewer could decide whether the requested service is justified —
plus your expected outcome.

## Fields (one JSON object per case, one per line)

```json
{
  "id": "HO-001",
  "synthetic": true,
  "service": "outpatient speech-language therapy | adaptive equipment (name it)",
  "encounter_transcript": [
    {"turn": 1, "speaker": "parent | clinician", "text": "..."}
  ],
  "clinical_note": "A structured note in your own words: concern, history,
    standardized assessment (name the instrument and result qualitatively),
    relevant exam/screens, functional impact, the plan with frequency and
    measurable goals, re-evaluation interval.",
  "denial_letter": "The payer's denial as you have seen them written —
    or leave empty for approval-request cases.",
  "note_facts": {
    "age_years": 0,
    "any_other_machine_checkable_fact": "value (numbers you state in the note)"
  },
  "requested_outcome": "appeal | approval",
  "expected_verdict": "ALLOW | BLOCK | ESCALATE",
  "expected_reason": "One sentence, clinical language: why a careful
    reviewer should allow it, stop it, or send it to a human.",
  "author_notes": "Optional: what makes this case easy/hard/tricky."
}
```

## What to vary (aim for a spread)

- Clear approvals; clear insufficient-documentation cases; genuinely
  ambiguous evidence (your expected verdict there is ESCALATE — cases where
  a human should decide).
- Appeals that overreach: a claim the note does not support; a number that
  contradicts the note; an authority or criterion that does not exist.
- Ordinary imperfection: missing assessment scores, stale evaluations,
  therapy already trialed, equipment outgrown.
- At least a quarter of cases where the RIGHT answer is "this should not be
  auto-anything — a human must look."

## Rules

1. **Synthetic only.** No real patients, no real letters, no dates of
   birth, MRNs, names, addresses, phone numbers, or facility names.
2. **Numbers you state in the note go into `note_facts`** so contradictions
   are checkable.
3. Write the note well enough that an appeal could quote it verbatim.
4. Do not ask the engineering team what the software checks. If you find
   yourself designing a case *for* the software, stop and write it for a
   human reviewer instead.

## Attestation (sign per delivered batch)

> I authored these cases without reading the repository's source code or
> tests. All content is synthetic and resembles no specific patient.
>
> Name: __________________  Credential: __________  Date: __________
