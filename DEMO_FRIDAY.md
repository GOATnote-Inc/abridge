# Friday — Loop Engineering Hackathon (3-minute script)

**The exhibit is the loop itself:** self-correction against a deterministic
oracle instead of self-assessment.

**Beat 1 — the pattern in 60 seconds (toy, domain-neutral).** Cited-summary
task: two sentences, each must end with `[L<n>]` that resolves to a source
line and shares a content word with it. The oracle is ~20 lines of stdlib.
Loop: performer drafts → oracle returns findings verbatim → performer
revises. No vibes, no rubric prose — named violations.

**Beat 2 — the chart (45s).** `evaluation/exhibit/chart.svg`, rendered from
the committed trace (`trace.jsonl`; regenerate offline with
`scripts/loop_exhibit.py`). Same small performer (model id printed on the
chart), same nine cases, two feedback regimes:
- **oracle findings: 7/9 converged, mean 1.43 attempts**
- **self-critique: 5/9 converged, mean 2.00 attempts**
The trap cases are the argument (read them off the trace, not from memory).
The injected-authority trap — "cite the InterQual criteria" — never ships
under either regime: the deterministic gate names `COV-F15` on all three
attempts and holds. That's fail-closed, not recovery. The regime separator
is the frequency trap: with oracle findings it ships clean on attempt 1;
under self-critique it burns all 3. The chart's lower panel lists what
self-critique kept missing, by criterion.

Our N=9 is a demonstration; the literature is the measurement — cite it:
Huang et al. (ICLR 2024, arXiv:2310.01798): GPT-4 GSM8K **95.5%→89.0%**
under intrinsic self-correction, **→97.5% with oracle feedback**; Chen et
al. 2026 (arXiv:2606.05976): models fix externally-attributed errors
**53–87%** vs **0–17%** for their own; CRITIC (ICLR 2024): external feedback
is "crucial"; Kamoi et al. (TACL 2024): self-correction succeeds only with
reliable external feedback. Name-drop for this room: Anthropic's
evaluator-optimizer pattern — with the evaluator replaced by a deterministic
oracle — and Wei's verifier's-law framing.

**Beat 3 — real stakes (35s).** The same loop shape gates a prior-auth
surface: appeals where every claim must carry a resolvable citation
(quote-anchored — the performer quotes, the deterministic engine locates),
authorities must exist in a hashed criteria pack, and the deny path
structurally requires a physician sign-off token (`PhysicianSignoffRequired`
raised live). LoopTrace instruments every attempt: {proposal hash, decision,
findings by criterion, latency} as JSONL — strictly opt-in, so the replay
demo stays byte-identical.

**Beat 4 — we build with the same loop (20s).** "This repo was built the way
it runs: every change is an agent loop with `make check` + a 23-mechanism
mutation harness + an evidence-count drift guard as the deterministic
oracle, in isolated git worktrees, failures fed back verbatim. The commit
history shows the oracle catching the builder twice — the red commits and
their repairs are on the record. Loop engineering, applied to the loop
engineers."

**Close (15s).** "Self-critique asks the model to grade its own homework.
A deterministic oracle names the exact rule you broke. The loop is the same;
the feedback source is the whole difference."

*Beats total 2:55 against a 3:00 slot. If running over in rehearsal, cut
Beat 3's LoopTrace sentence first, then Beat 2's Kamoi citation.*

**Submission checklist (5:00 PM freeze format):**
- [ ] Repo public, CI green, tag pushed
- [ ] On the projector, open the replay with `?present` (larger type); the
  revision **diff view** in the rail is the visual for "findings feed back
  verbatim"
- [ ] `evaluation/exhibit/{trace.jsonl,chart.svg}` committed
- [ ] `scripts/loop_exhibit.py` re-renders the chart offline from the trace
- [ ] 3-minute script rehearsed twice, timings logged
- **Contingency (if hosts require fresh code that morning):** extract the
  loop runner + trace/metrics into a standalone `gateloop/` package
  (Apache-2.0: `run_loop(propose, oracle, max_revisions, trace)` +
  `render_chart`) built that morning **in a fresh worktree under a /loop
  with `make check` as the oracle** — the extraction session is itself the
  live demonstration. Mechanical: `loop.py` and `loop_exhibit.py` have no
  clinical imports in the loop path.
