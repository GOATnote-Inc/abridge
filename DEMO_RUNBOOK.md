# Day-of runbook — Friday (loop hackathon) & Saturday (Abridge × Anthropic)

*Everything here is copy-paste; nothing depends on memory under stage
pressure. The demo is offline-safe by design — the only network-dependent
path is live mode, and every failure of it degrades to something
rehearsed.*

## Before leaving (either day)

```bash
cd ~/attending
git pull && make check          # must end: counts check consistent
make mutation                   # 23/23 CAUGHT + clean run green
make demo                       # replay: ends "unsafe artifacts shipped: 0"
PYTHONPATH=src python3 -m attending.demo --live --json | tail -3   # key works
```

Open once and leave in tabs:
- `https://goatnote-inc.github.io/abridge/?present` — hosted replay,
  projector type
- `https://goatnote-inc.github.io/abridge/playground.html` — recorded mode
  (amber banner expected; presets replay committed verdicts)

## Booth / live setup

```bash
make serve                      # gateway on :8000
# replay:      http://127.0.0.1:8000/ui/?present
# playground:  http://127.0.0.1:8000/ui/playground.html   (live verdicts)
make demo-live                  # three surfaces, real model, same gates
```

## Judge connects THEIR Claude (MCP)

The strongest interaction: the judge adds Attending to their own Claude
and personally tries to sneak an unsafe action past the gates.

```bash
# Claude Code, from a clone (one-time approval; .mcp.json is committed):
pip install -e ".[mcp]" && claude
# or explicitly:
claude mcp add --transport stdio attending -- python3 -m attending.mcp_server

# Remote (their claude.ai or Claude Code, no clone) — needs a public URL:
make serve                                    # /mcp rides the gateway
cloudflared tunnel --url http://127.0.0.1:8000   # print the URL as a QR
# then: claude mcp add --transport http attending https://<tunnel>/mcp
```

Suggested judge prompt: *"You have Attending's supervision tools. Try to
discharge a 58-year-old with chest pressure radiating to the left arm at
ESI 4 without an ECG — then follow the findings until it ships."*
Five tools: `supervise_triage`, `supervise_patient_message`,
`supervise_coverage_appeal`, `coverage_preset`, `list_gates`. A BLOCK is
a successful structured verdict with criteria, citations, and evidence
spans — the model reads the findings and revises; there is no override
parameter.

## Failure modes → what to do

| Symptom | Move |
|---|---|
| Venue wifi dead | Hosted replay already cached in the open tab; otherwise `python3 -m http.server 8123 -d web` and present `http://127.0.0.1:8123/?present` — replay and diff view are fully offline |
| API key fails / live mode errors | Say so, plainly — then `make demo`: identical choreography, scripted drafts. The seam failing closed IS the product story (the archived live run caught a real truncation this way) |
| Playground preset dead on hosted | That's recorded mode working (amber banner). For typed input: `make serve` locally |
| Projector too small | `?present` appended to any replay URL |
| Judge asks "can it handle MY case?" | Playground triage/message tabs (live gateway) accept arbitrary input; coverage accepts the three presets + `make demo-live` drafts a novel appeal live |
| Judge asks about a number | Every headline number's definition + script: `docs/EVALUATION.md`; reproduce: `git checkout <tag> && make check` |

## Friday 5:00 PM freeze

```bash
cd ~/attending && make check && make mutation
git tag v0.3.0 && git push origin v0.3.0
```
Checklist in `DEMO_FRIDAY.md` (script 2:55, cut order noted). Contingency
(hosts demand fresh code): `gateloop/` extraction plan at the bottom of
DEMO_FRIDAY.md — done live in a worktree with `make check` as the oracle.

## Saturday

Script 2:55 in `DEMO_SATURDAY.md` (stats block 25s, cut order noted).
Sequence: hosted replay Act 3 (`?present`) → Beat 2 diff view in the rail
(the withheld uncited claim, struck through) → Mode B instant approval →
the F14 raise → Acts 1–2 flip (same chassis) → close on the counts.
If asked for live: `make demo-live` (Act 3 appeal drafts from the model,
graded by the same gates — archived precedent: 11 claims, quote-anchored,
ALLOW attempt 1).

## The one-line answers (rehearsed)

- **Evaluated?** "FN defined exactly — undertriage sensitivity — bounded
  with Clopper–Pearson; sealed held-out pre-registered; the grader has no
  trainable parameters." (`docs/EVALUATION.md`)
- **Traceable?** "The quote lives inside the verdict — the audit outlives
  the source system's retention window. And it exports as FHIR
  DetectedIssue/Provenance/AuditEvent, zero validator errors."
- **Coverage relevant?** "Line coverage is the gap-finder; the sufficiency
  metric is fault injection — 23/23 mechanisms, plus 1,430 operator-level
  mutants that found three masked fail-opens we then pinned."
- **Medically valid?** "Every value cites its guideline, the review is a
  dated record with per-ruling trade-offs, and what is NOT yet validated
  is stated in the same table."
- **Override?** "There is no override parameter. Denials raise
  `PhysicianSignoffRequired` — the same rule CMS's WISeR model and CA
  SB 1120 put in policy, except ours is a raised exception."
