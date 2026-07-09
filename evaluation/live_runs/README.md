# Live-run evidence artifacts

Raw, uncurated transcripts of the two-surface demo with a LIVE model behind
the same deterministic gates as replay mode. Committed as evidence, not prose:
each file carries the performer model id, every draft verbatim, every verdict
with criteria and citations, and the summary integrity counts.

| File | Date | Performer | Outcome |
|---|---|---|---|
| `2026-07-09-fable5-two-surface.json` | 2026-07-09 | `claude-fable-5` | Stage A: correct ESI-2 ACS plan ALLOWed on attempt 1. Stage B: a textually flawless patient reply still BLOCKed by `SITREP-disclosure_gap` (chart-state gate) until the documented bedside discussion; final reply shipped. `unsafe_artifacts_shipped: 0`. |

Reproduce (spends API budget; requires `ANTHROPIC_API_KEY` in `.env`):

    PYTHONPATH=src python3 -m attending.demo --live --json \
      > evaluation/live_runs/$(date +%F)-<model>-two-surface.json

Provenance notes: the choreography (timeline events, chart state, gate config)
is identical to replay mode — only the drafts come from the model. Replay-mode
transcripts are deterministic and live at `web/demo_transcript.json`. Live
outputs vary run to run; that variance is the point — the gates hold anyway.
