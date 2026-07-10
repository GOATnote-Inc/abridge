# ADR-0001: LangChain/LangGraph and Anthropic integration surface

*2026-07-10 · Status: decided · Full research with per-claim URLs preceded
this; condensed here with the strongest citation per verdict.*

## Decision bar

Every candidate had to pass three tests, in order: **(1) error surface** — it
must *remove* a failure class, not add capability; **(2) EBM anchor** — the
removed failure class must map to documented clinical harm; **(3) determinism
preserved** — byte-identical replay, mutation-testability, and no opaque layer
between a rule and its verdict. Complexity with no error-surface reduction is
rejected regardless of appeal.

Clinical anchors: ED work is interruption-driven (6–12/hr; interruptions
prospectively associated with prescribing errors — Westbrook et al., BMJ Qual
Saf 2018; 18.5% of interrupted ED tasks never resumed — AAEM position
statement); handoff failure is a Joint Commission sentinel-event root cause
(SEA 58, 2017); and false alarms kill — 85–99% of clinical alarms need no
intervention, and alarm fatigue was tied to 80 deaths in 98 reported events
(SEA 50, 2013). These cut both ways: fragmented-encounter handling is a real
need, and a supervisor that over-fires recreates alarm fatigue in software.

## Verdicts

| Candidate | Verdict | Deciding evidence |
|---|---|---|
| LangGraph as runtime for the supervised loop | **REJECT** | Its "time travel" *re-executes* LLM/API calls ("may produce different results" — their docs), i.e. strictly weaker than this repo's byte-identical replay; docs place the determinism/idempotency burden on *your* code; ~30 transitive packages (incl. a hard `langsmith` dep) against a `dependencies = []` core; two serializer RCE advisories + checkpoint-format breaks across minor versions. The framework demands the property we already have and returns less of it. |
| LangGraph checkpointer for the discontinuous-encounter state machine | **ADAPT PATTERN ONLY** | The clinical need is real (SEA 58; 18.5% task non-return). Take the pattern — one thread per encounter, checkpoint-before-yield, resume at *named* suspension points, idempotency keys on side effects — in stdlib (`sqlite3`/`json`). Their own docs are the catalog of failure modes to exclude by construction: "the runtime restarts the entire node from the beginning… Do not perform non-idempotent operations before `interrupt()`"; resume values matched to interrupts *by index* (silent misrouting); parallel-interrupt ID collisions. |
| LangChain 1.x middleware/guardrails vs. our gates | **REJECT** | Structurally isomorphic to what exists (`before/after model` ≈ detector/gate placement), but only applies to agents running *inside* `create_agent` — Attending supervises foreign agents; adopting it would couple gate placement to one framework's loop. HITL middleware inherits interrupt re-execution semantics. |
| Native Anthropic structured outputs | **ADOPTED** (this repo, 2026-07-10, live-verified on `claude-fable-5`) | GA, no beta header, zero new packages (`anthropic` was already the optional extra). Constrained decoding deletes the malformed-JSON/regex-extraction failure class. Fail-closed branches retained for the two documented no-guarantee cases (`stop_reason ∈ {refusal, max_tokens}` → `LLMUnavailable` → detectors keep the deterministic floor; performers return None → loop escalates). Numeric ranges are not constrained server-side → local validation (e.g. the 0.6 confidence gate) remains authoritative. EBM anchor: parse failures were spurious escalations; every avoidable false escalation feeds alarm fatigue (SEA 50). |
| Supervisor as MCP server | **ADAPT PATTERN, DEFERRED** | An MCP *tool* is advisory — a calling agent can simply not call it, so enforcement at that layer is fail-open by construction (every shipping safety precedent is a *gateway*, not a peer tool). Also the 2026-07-28 MCP spec revision is explicitly breaking (stateless core, new required headers). Plan: a thin stdio adapter for *distribution* only — never the enforcement point — after the spec finalizes. Precedent that healthcare MCP servers are a sanctioned shape: `anthropics/healthcare` ships seven. |
| Claude Agent SDK hooks | **ADAPT PATTERN ONLY** | The SDK's evaluation order (deterministic hooks first — "a hook deny applies even in `bypassPermissions` mode" — model-classifier `auto` after) independently validates this architecture. But it carries documented fail-open edges ("hooks may not fire when the agent hits the `max_turns` limit") and would put an entire agent runtime inside clinical middleware. Offer a `PreToolUse` adapter for teams hosted on that runtime; never inherit it in core. |
| LangSmith-style tracing | **REJECT** | Capture already exists (committed, diffable JSON transcripts; deterministic graders — Anthropic's own doctrine: "choose deterministic graders where possible"). The marginal value is eval UI; the marginal cost is PHI egress to a SaaS whose self-hosting is enterprise-gated. |

## Consequences

- `llm.py`/`agent.py` use `output_config` JSON-schema constrained decoding;
  `_extract_json` regex parsing deleted; `anthropic>=0.116` is the tested
  floor for the optional `[llm]` extra.
- Roadmap item "discontinuous-encounter state machine" (SYSTEM_CARD §6.2) now
  carries its design constraints, sourced from the rejected framework's own
  documented failure modes.
- No LangChain/LangGraph/LangSmith dependency; the core remains
  `dependencies = []`.
