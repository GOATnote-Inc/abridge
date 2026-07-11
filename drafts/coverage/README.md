# synthetic: true
# status: DRAFT — pending physician review (clinical-review-packet flow)

# Coverage surface — QUARANTINED DRAFTS

**Nothing in this directory is wired into live gates.** No code under `src/`
imports from `drafts/`; no test, detector, gate, or goldset consumes these
files. Content leaves this quarantine and enters the product **only** through
the clinical review packet with physician sign-off (the same flow that governs
`knowledge.py` rule values and the sitrep lexicons). Until then, every file
here is a proposal, not a rule.

Everything is fully **synthetic** (F13 / INV-J): every JSON artifact carries a
top-level `"synthetic": true` attestation, and no artifact contains
identifier-shaped patient data — no names, DOB, MRN, SSN, addresses, or phone
numbers, and none of the banned patient-payload keys
(`name/mrn/dob/ssn/phone/address`). The child in the case is only ever "the
patient" / "your son". (The `name` field inside pack `authorities` entries is
the *source* name — a statute or guideline title per the coverage-pack schema —
not patient data.)

**Why JSON, not YAML:** the repo core is stdlib-only (`json` is stdlib; YAML
would add a dependency). Schema fields are identical to the specified YAML
schema — field-for-field, only the serialization differs.

## Inventory

| File | What it is |
|---|---|
| `case_peds_speech_denial.json` | One synthetic case: ambient encounter transcript (28 turns, parent + SLP), structured clinical note, a deliberately vague payer denial letter (the artifact the demo audits), and `note_facts` for frankenfact checking. |
| `pack_peds_speech_therapy.json` | Candidate criteria pack, clauses `SLT-01`…`SLT-06`, anchored in EPSDT's correct-or-ameliorate framing. Paraphrased public sources only. |
| `pack_peds_dme_adaptive_equipment.json` | Second pack (adaptive stroller / gait trainer), clauses `DME-01`…`DME-06`, same schema. |
| `adversarial_fixtures.json` | Five structured coverage proposals: four adversarial (unsupported claim, fabricated authority, deny-on-indeterminate, auto-deny without sign-off) plus one clean appeal for the happy path. |
| `goldset_candidates.jsonl` | Twelve goldset candidates (`GSC-01`…`GSC-12`), one JSON per line, mirroring `evaluation/goldset.jsonl`'s `expect.decision`/`expect.criterion` shape. |

## Conventions

- **Cite refs:** `{"type": "clause", "ref": "SLT-01"}` — a clause id in the
  referenced pack; `{"type": "note", "ref": "note:<start>:<end>"}` — a
  character span (Python slice indices) into the case's `clinical_note`;
  `{"type": "transcript", "ref": "transcript:<n>"}` — a 1-based turn index into
  `encounter_transcript`. All note spans in the fixtures and goldset were
  computed against the actual note text (length 2586 chars) and resolve — except
  `GSC-11`'s span, which is deliberately out of range.
- **`pack_hash`** = `sha256` over the pack file bytes at authoring time
  (`shasum -a 256 <pack>.json`):
  - `pack_peds_speech_therapy.json` → `ca5c2e8a442e7860405193b70d2b68ba9732c1f6dc53488876b675243ea4fc59`
  - `pack_peds_dme_adaptive_equipment.json` → `59d345bb07d68d9381a455e9e2c94e5f950ad10062fa874e6bbb6f1817aa2e2c`
  Any edit to a pack invalidates these; recompute and update fixtures/goldset together.
- **`adversarial_fixtures.json` is an object wrapping `fixtures`**, not a bare
  array, so the file can carry the top-level attestation — mirroring
  `sitrep.replay.load_scenario`, which rejects bare lists precisely so
  attestation can never be skipped.
- **Candidate criterion ids** (`COV-unsupported-claim`, `COV-fabricated-authority`,
  `COV-missing-provenance`, `COV-indeterminate-evidence`,
  `COV-auto-deny-no-signoff`, `COV-frankenfact`, `COV-vague-denial`) are
  *proposed* names, wired to nothing yet. A pack clause id (`SLT-06` in
  `GSC-12`) can also be the tripped criterion, exactly like `RF-*` ids in the
  triage goldset.

## Fail-closed mapping (unchanged from the triage surface)

- Indeterminate evidence → **ESCALATE** (physician review + records request).
  Never a denial, signed or not.
- A denial is an adverse benefit determination: **no physician sign-off, no
  denial** — BLOCK, with no override parameter.
- An adverse determination must cite the specific clause(s) not met; boilerplate
  "not medically necessary" with zero clause-level cites is itself a BLOCK
  (`COV-vague-denial` — the machine form of the case's denial letter).
- Unsupported, unresolvable, or note-contradicting claims BLOCK in *either*
  direction, including approvals with fabricated authorities.

## Physician review — look here first

1. **`SLT-01` cutoff** ("1.5 SD below the mean / ~7th percentile") and
   **`SLT-04` re-evaluation interval** are marked *state-plan variables* —
   placeholders at guideline level, not invented rules; the operative state's
   published standard must be substituted.
2. **Composite state-manual authorities** (`AUTH-STATE-EPSDT-*-MANUALS`)
   paraphrase typical public manuals without naming a state; swap in the actual
   state manual before any real use.
3. **`GSC-07`:** clean *approvals* ALLOW without physician sign-off (approval
   extends care — the safe direction; denial always requires sign-off). This
   asymmetry is a policy decision awaiting review.
4. **`ADV-03` / `GSC-04`:** a *signed* deny on admittedly indeterminate
   evidence still ESCALATEs rather than ships — sign-off does not cure an
   evidence gap. Confirm this is the intended posture.
5. **EPSDT floor clauses** (`SLT-06` / `DME-06`) assert that restorative-only /
   maintenance-exclusion / convenience-item rationales cannot alone support an
   under-21 denial — paraphrased from 42 U.S.C. § 1396d(r) and the CMS 2014
   EPSDT guide; confirm the legal paraphrase before demoing it as a blocking rule.
6. The **denial letter** deliberately carries no dates or reference numbers
   (identifier hygiene) — slightly less realistic than a live payer letter; its
   vagueness (no clause-level citation) is the audited property and is intact.
