# Attending — Operating Charter

Fail-closed supervising layer over a clinical triage agent. Attending is the **screener**,
never the performer: it grades a proposing agent's triage action, it does not propose one.
Built on HealthCraft (Apache-2.0, arXiv:2605.21496). Hackathon: Abridge × Anthropic × Lightspeed.

## Architecture

`supervisor.supervise(encounter, proposal) -> Verdict{ALLOW|ESCALATE|BLOCK}`:

1. `esi.py` — independently re-derives ESI v4 acuity (decision tree A→B→C→D), values from `knowledge.py` (versioned, cited).
2. `confidence.py` — interval over that acuity; supervisor acts on the **most-acute end** (the interval *is* the fail-closed mechanism).
3. `detectors/` — four failure modes: `incomplete_audio`, `transcription_error`, `anchoring_bias`, `hallucination`; input-quality hits widen the interval toward acute.
4. Verdict cites the exact criterion (`ATT-*` / red-flag id) tripped. Exit codes: 0 allow, 2 block, 3 escalate.
5. `evaluate.py` + `evaluation/goldset.jsonl` — the regression gate (see contract below).

## Commands

```bash
PYTHONPATH=src python3 -m pytest -q                          # tests (gold set included)
PYTHONPATH=src python3 -m attending.evaluate                 # safety gate; exit 1 if FN>0
PYTHONPATH=src python3 -m attending.cli <case.json>          # supervise one case (--json)
PYTHONPATH=src python3 -m attending.demo [--live] [--json]   # three-act demo (make demo)
PYTHONPATH=src python3 -m attending.mcp_server [--http]      # MCP surface ([mcp] extra)
make check                                                   # lint + mypy + tests + goldsets + counts
make mutation                                                # 23 fault-injected mechanisms (CI-required)
```

The repo is also a Claude Code plugin marketplace (`.claude-plugin/`,
`plugins/attending/` — MCP server + clinical-safety-supervisor skill);
`tests/test_plugin.py` pins the packaging against drift.

The deployable unit is `attending.loop` (`run_triage_loop` / `run_rendering_loop`):
propose → verify → revise-on-BLOCK → ship-on-ALLOW; ESCALATE and chart-state
gates stop immediately; a blocked artifact is never shipped (no override
parameter — do not add one). The performer lives in `attending.agent` and never
grades; the supervisor never proposes.

## The fail-closed contract (non-negotiable)

- **"Not evaluated" never reads as "safe."** Missing proposal, degraded input, unhandled uncertainty → ESCALATE/BLOCK, never ALLOW.
- **YOU MUST keep gold-set false negatives at 0.** An FN = an unsafe proposal ALLOWed — the one failure this system exists to prevent. `evaluation/goldset.jsonl` + `tests/test_goldset.py` are the gate; no change may land that raises FN. FPs are a nuisance, not a safety event — never trade an FN for an FP.
- **Tests-first:** any behavior change ships with a gold-set case derived from a real failure mode, added before or with the change.

## Deterministic / LLM split

- The ESI spine, confidence interval, and detector floor are **program-aided: no LLM, no API key, reproducible**.
- **IMPORTANT: never move a safety decision into a non-deterministic path.** the configured model (`ATTENDING_MODEL`, default `claude-opus-4-8`) may only AUGMENT the anchoring/hallucination detectors via their `llm_augment` hooks, and any LLM failure must degrade gracefully to the deterministic floor (augment can add findings, never suppress or downgrade one).

## Clinical safety

- Every rule carries a citation (see `knowledge.py` header). Rule **values** — thresholds, red flags, peds bands — are `DRAFT — pending physician/board sign-off`; never present them as authoritative or drop the approval-status surfacing.
- **YOU MUST NOT silently weaken or delete a safety criterion.** Changes to `knowledge.py` or the grading rubric require explicit human review; bump `RULESET_VERSION`.

## Model seam

One knob selects the model for everything LLM-shaped (screener judges and
the demo performer): `ATTENDING_MODEL`, default `claude-opus-4-8`, read in
`llm.model_name()`. Never hardcode a model id elsewhere.

## Repo etiquette

- Stage files by name — never `git add -A` / `git add .`. Do not commit unless asked.
- **`main` is the only branch.** Branches exist only as momentary vehicles
  (a review diff, a worktree lane) and are deleted the same day; no other
  files or repos unless absolutely needed (owner directive, 2026-07-13).
- **Never read `.env`** (runtime-only Anthropic key lives there, plain text, gitignored). Use `.env.example` to check key names.

## Communication safety gates (`src/sitrep`)

Attending has three surfaces (Decision, Communication, Coverage — see
INVERSION F14-F19 for the coverage ledger). The triage layer above governs what the agent
**decides**; `sitrep` governs what it **says** — `run_gates(rendering, state)`
over patient/nurse/physician/consultant panes, mapped into this repo's shared
`Finding`/`Severity`/`Decision` vocabulary by `attending/comms.py`. Failure
modes and their tests are the ledger: `INVERSION.md` (F1–F13). Dependency is
one-way: `attending` imports `sitrep`, never the reverse (sitrep stays
stdlib-only). Invariants (every one has a test; do not regress):

- **Anti-embargo:** never delay/hide/soften a RELEASED result. Suppression is
  the violation (Cures Act information blocking). Context travels *with* the
  result, never instead of it.
- **Gates are middleware, not prompts.** Safety persistence lives in
  `sitrep/gates.py`; never move gate logic into a system prompt (models drift
  under multi-turn pressure — the LostBench thesis).
- **Escalations are monotonic** — `EncounterState` has no clear method by design.
- **Patient pane ceiling:** no interpretation/prognosis/advice/false
  reassurance; every patient rendering carries an AI disclosure AND a human
  path (AB 3030); every named chart entity carries a supporting ref (grounding).
- **Sticky trajectory scoring:** a clean later turn never redeems a failing
  earlier one. **The replayer stays pure** (no clock/randomness/network) so the
  demo replays byte-identically.
- If a gate lexicon misses a phrase seen in the wild, ADD THE PHRASE AND A TEST
  in the same change. Lexicons are physician-owned and versioned (reviewed 2026-07-09, demo scope).

## Orchestration doctrine (one Claude drives other Claudes)

One long-lived **orchestrator session** owns this repo: it holds context,
makes decisions, and is the only thing that runs git. Everything else is
delegated:

- **Investigate in subagents; keep this context for decisions.** Research,
  broad reads, and reviews run as background subagents that return a
  conclusion, not a file dump. Adversarial review happens in FRESH context
  (a reviewer that sees only the diff + criteria, told to report
  correctness-affecting gaps only).
- **Nothing is "done" without pasted evidence** from a check that ran:
  `make check` output, exit code, verdict JSON, screenshot. If there is no
  check, build the check first — the oracle before the army.
- **Every mistake becomes a written rule** — append it to this file, a test,
  or a guard script in the same change; never just accept a chat
  correction. (The counts guard, the lexicon-lint test, and the mutation
  registry all exist because of this ratchet.)
- **Delegate like a brief, not a pairing:** goal + constraints + acceptance
  criteria up front; workers own **disjoint files**; if parallel work keeps
  colliding, re-decompose or go single-threaded. After two failed
  corrections, start fresh with a better brief instead of arguing
  in-context.
- **Worktree lanes** for parallel implementation: `git worktree add
  ../attending-wt-<lane> -b <lane>`, gate inside the lane with `make check`
  + `make mutation`, then `git merge --ff-only` from the orchestrator and
  `git worktree remove` — lane branches die the same day (main-only
  doctrine). Lanes never run git themselves (two writers + git has burned
  us before).
- **/loop cadence:** iterative build work runs as a /loop with `make check`
  as the oracle — implement → run the gate → feed failures back verbatim →
  revise. Same propose→verify→revise shape as `attending.loop`; the
  development process and the product make the same argument. For long
  waits (CI, Pages, background runs) use notifications/watches, never
  polling.
