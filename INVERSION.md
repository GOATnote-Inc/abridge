# INVERSION.md — design by failure mode

> "Invert, always invert." We do not ask how the agent helps.
> We enumerate how it harms a patient, breaks the law, or dies on stage —
> then write the test that makes each failure impossible to ship silently.

Every gate is **deterministic middleware outside the model** (LostBench thesis:
models fail safety persistence under multi-turn pressure, so persistence lives
in code, not prompts). Tests are the ledger. CI is the enforcement.

| # | Failure (how we lose) | Gate | Severity | Test |
|---|----------------------|------|----------|------|
| F1 | Patient pane interprets/prognoses ("consistent with cancer", "you'll be fine") | `gate_no_interpretation` | BLOCK | `test_gates.py::TestF1*` |
| F2 | Agent hides/delays a released result → information blocking (Cures Act). **The anti-embargo gate**: suppression is the violation, not disclosure. | `gate_info_blocking` | BLOCK | `test_gates.py::TestF2*` |
| F3 | Critical result viewed by patient, never discussed, nobody alerted | `check_disclosure_gap` (state gate) | BLOCK | `test_replay.py::TestF3*` |
| F4 | Patient pane gives medical advice/directives ("you should take…") | `gate_no_advice` | BLOCK | `test_gates.py::TestF4*` |
| F5 | AI-generated patient communication lacks AI disclosure + human path (CA AB 3030 pattern) | `gate_compliance` | BLOCK | `test_gates.py::TestF5*` |
| F6 | Red-flag utterance not escalated, or escalation silently dropped on a later turn | `gate_escalation` + monotonic state | BLOCK | `test_persistence.py::TestF6*` |
| F7 | Fabrication: text references orders/results not in the chart (grounding / Linked-Evidence mirror) | `gate_grounding` | BLOCK | `test_gates.py::TestF7*` |
| F8 | False reassurance while a critical result is on the chart ("everything looks fine") | folded into `gate_no_interpretation` | BLOCK | `test_gates.py::TestF8*` |
| F9 | Patient text above ~8th-grade reading level (health-literacy failure) | `gate_readability` | WARN | `test_gates.py::TestF9*` |
| F10 | Multi-turn erosion: gates hold at turn 1, drift is missed by turn 10 ("is it cancer?" ×10) | persistence harness over full transcripts | BLOCK | `test_persistence.py::TestF10*` |
| F11 | Demo-day failure: replayer nondeterminism → un-rehearsable demo | replayer is pure/deterministic over fixture timelines | — | `test_replay.py::TestF11*`, `test_scenario_loader.py::TestFullRunDeterminism` |
| F12 | Orphan result files against an order the chart never saw → panes render a test nobody ordered | `EncounterState.add_result` rejects at ingestion | BLOCK (raise) | `test_state.py::TestOrphanResult` |
| F13 | Non-attested or identifier-bearing scenario data enters the pipeline (PHI-shaped habits) | `load_scenario` requires `"synthetic": true`, bans identifier keys | BLOCK (raise) | `test_scenario_loader.py::TestSyntheticAttestation` |

Two-tier severity by design: **BLOCK** stops the render; **WARN** ships with
annotation — mirrors the dual-layer safety-gated rubric pattern.

Non-goals (explicitly out, to stay inside the CDS non-device lane):
- No diagnosis, no treatment recommendation, no disposition prediction.
- No result delays of any kind. Context travels *with* the result, never instead of it.
