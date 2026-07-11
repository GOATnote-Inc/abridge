"""Runtime LLM augmentation for the anchoring + hallucination detectors.

Per Anthropic's eval guidance, the LLM here is a *screener judge*, not a
performer: isolated per-dimension prompts, forced-then-discarded reasoning, a
structured verdict, and a screener model distinct from whatever generated the
proposal. It is strictly ADDITIVE to the deterministic detector floor — it can
raise a finding the code missed, never suppress or downgrade one — and it
degrades to a no-op when no key / SDK / network is available.

Enablement is explicit and OFF by default (so the test suite and the
deterministic CLI never make network calls): set env ATTENDING_LLM_AUGMENT=1
(or pass --llm to the CLI). The runtime key is read from a plain-text `.env`
in the repo root or from the environment; its value is never logged.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from .encounter import Encounter, ProposedTriage

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODEL = "claude-opus-4-8"
_KEY_ENV = "ANTHROPIC_API_KEY"


class LLMUnavailable(RuntimeError):
    """Raised when augmentation is requested but cannot run (no key/SDK)."""


def _candidate_env_files() -> list[Path]:
    """Ordered plain-text .env locations, first-set-wins per key.

    ATTENDING_ENV_FILE lets the key live in a shared store (e.g. a project's
    canonical .env) without copying the secret into the repo.
    """
    paths: list[Path] = []
    override = os.environ.get("ATTENDING_ENV_FILE")
    if override:
        paths.append(Path(override))
    paths.append(_REPO_ROOT / ".env")
    paths.append(Path.cwd() / ".env")
    return paths


def _load_dotenv() -> None:
    """Populate os.environ from plain-text .env file(s) for keys not already set.

    Values are loaded into the process environment only; never printed.
    A `.env.rtf` (RTF-wrapped) is deliberately ignored — it cannot be parsed
    as KEY=value and would leak markup, so we require plain `.env`.
    """
    for env_path in _candidate_env_files():
        if not env_path.is_file():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def augmentation_enabled() -> bool:
    return os.environ.get("ATTENDING_LLM_AUGMENT", "").lower() in {"1", "true", "yes", "on"}


def model_name() -> str:
    """The single model seam: every LLM call (screener judges and the demo
    performer) resolves its model here. ATTENDING_MODEL is the one knob;
    the legacy ATTENDING_LLM_MODEL name is honored for compatibility."""
    return (os.environ.get("ATTENDING_MODEL")
            or os.environ.get("ATTENDING_LLM_MODEL")
            or _DEFAULT_MODEL)


def _client():
    """Return an Anthropic client, or raise LLMUnavailable."""
    _load_dotenv()
    key = os.environ.get(_KEY_ENV)
    if not key:
        raise LLMUnavailable(f"{_KEY_ENV} not set")
    try:
        import anthropic  # imported lazily; optional [llm] dependency
    except ImportError as e:  # pragma: no cover - env-dependent
        raise LLMUnavailable("anthropic SDK not installed (pip install '.[llm]')") from e
    return anthropic.Anthropic(api_key=key)


def complete_json(
    system: str,
    user: str,
    *,
    schema: dict,
    max_tokens: int = 1024,
    model: str | None = None,
) -> dict:
    """One schema-constrained completion (Claude structured outputs, GA).

    Constrained decoding deletes the malformed-JSON/missing-block parsing
    failure class outright — no regex extraction. Fail-closed branches kept
    for the two documented cases where the schema is NOT guaranteed:
    `stop_reason == "refusal"` and `stop_reason == "max_tokens"`. Numeric
    ranges and string lengths are not constrained server-side, so the local
    validation in each caller remains authoritative.
    """
    client = _client()
    # Temperature omitted deliberately: frontier models reject temp=0
    # and the SDK default is fine for a low-variance structured judgment.
    try:
        resp = client.messages.create(
            model=model or model_name(),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except TypeError as e:  # pragma: no cover - env-dependent
        raise LLMUnavailable(
            "anthropic SDK too old for structured outputs "
            "(pip install -U anthropic)") from e
    if resp.stop_reason in ("refusal", "max_tokens"):
        # Documented: schema compliance is NOT guaranteed on these stops.
        raise LLMUnavailable(f"no schema-guaranteed output "
                             f"(stop_reason={resp.stop_reason})")
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return json.loads(text)


def judge(system: str, user: str, *, schema: dict, max_tokens: int = 1024) -> dict:
    """One isolated judge call (screener role). Returns the schema-shaped verdict.

    Fail-closed on transport: callers wrap this; on any exception the detector
    keeps its deterministic result (augmentation is additive, so a failed judge
    simply adds nothing).
    """
    return complete_json(system, user, schema=schema, max_tokens=max_tokens)


# --- Per-dimension judge prompts (empirical, structured, reason-then-discard) ---

_ANCHORING_SYSTEM = """You are an emergency-medicine triage safety reviewer. You \
review ONE thing: whether a proposing agent ANCHORED — fixated on the presenting \
complaint and failed to act on a clinically significant finding elsewhere in the \
encounter (a later-mentioned red flag, a concerning vital, a dangerous mechanism).

You are a screener, so bias toward patient safety, but do NOT invent concerns: \
only fire when a SPECIFIC, clinically significant finding in the provided encounter \
is genuinely unaddressed by the proposal. General "could be more thorough" is NOT \
anchoring.

Verdict fields: fired (did anchoring occur), confidence (0.0-1.0),
missed_finding (short name of the unaddressed finding), evidence (quote or
paraphrase from the encounter)."""

_HALLUCINATION_SYSTEM = """You are an emergency-medicine documentation auditor. You \
check ONE thing: does the proposing agent's RATIONALE assert any clinical fact that \
is NOT supported by, or that CONTRADICTS, the structured record provided? Examples: \
claims a normal vital the record never captured, claims "denies chest pain" when the \
chief complaint is chest pain, invents history.

Only fire on a concrete ungrounded/contradicted claim. Do not fire on reasonable \
clinical inference clearly labeled as such.

Verdict fields: fired (was any claim ungrounded), confidence (0.0-1.0),
ungrounded_claims (each ungrounded/contradicted claim), evidence (why it is
unsupported by the record)."""


_ANCHORING_SCHEMA = {
    "type": "object",
    "properties": {
        "fired": {"type": "boolean"},
        "confidence": {"type": "number"},
        "missed_finding": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["fired", "confidence", "missed_finding", "evidence"],
    "additionalProperties": False,
}

_GROUNDING_SCHEMA = {
    "type": "object",
    "properties": {
        "fired": {"type": "boolean"},
        "confidence": {"type": "number"},
        "ungrounded_claims": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "string"},
    },
    "required": ["fired", "confidence", "ungrounded_claims", "evidence"],
    "additionalProperties": False,
}


def _encounter_brief(enc: Encounter) -> str:
    v = enc.vitals.present()
    return (
        f"Chief complaint: {enc.chief_complaint}\n"
        f"Age: {enc.age_years}  Sex: {enc.sex}  Arrival: {enc.arrival_mode}\n"
        f"Captured vitals: {v or 'none'}\n"
        f"Structured facts: {enc.structured_facts or 'none'}\n"
        f"Transcript: {enc.transcript or 'none'}\n"
        f"History: {enc.history or 'none'}"
    )


def _proposal_brief(p: ProposedTriage) -> str:
    return (
        f"Proposed ESI: {p.esi_level}\nOrders: {list(p.orders)}\n"
        f"Disposition: {p.disposition}\nRationale: {p.rationale or 'none'}"
    )


_MIN_CONFIDENCE = 0.6  # avoid over-blocking on a hedging judge (FP hygiene)


def anchoring_hook() -> Callable[[Encounter, ProposedTriage], tuple[bool, str, str]] | None:
    """Return an anchoring re-reader, or None if augmentation is off/unavailable."""
    if not augmentation_enabled():
        return None

    def _hook(enc: Encounter, proposed: ProposedTriage) -> tuple[bool, str, str]:
        v = judge(_ANCHORING_SYSTEM,
                  f"ENCOUNTER:\n{_encounter_brief(enc)}\n\n"
                  f"PROPOSAL:\n{_proposal_brief(proposed)}",
                  schema=_ANCHORING_SCHEMA)
        fired = bool(v.get("fired")) and float(v.get("confidence", 0)) >= _MIN_CONFIDENCE
        msg = ("LLM re-read: proposal appears anchored — unaddressed finding: "
               f"{v.get('missed_finding', '')}")
        return fired, msg, str(v.get("evidence", ""))

    return _hook


def hallucination_hook() -> Callable[[Encounter, ProposedTriage], tuple[bool, str, str]] | None:
    """Return a grounding checker, or None if augmentation is off/unavailable."""
    if not augmentation_enabled():
        return None

    def _hook(enc: Encounter, proposed: ProposedTriage) -> tuple[bool, str, str]:
        user = (f"STRUCTURED RECORD:\n{_encounter_brief(enc)}\n\n"
                f"PROPOSAL:\n{_proposal_brief(proposed)}")
        v = judge(_HALLUCINATION_SYSTEM, user, schema=_GROUNDING_SCHEMA)
        fired = bool(v.get("fired")) and float(v.get("confidence", 0)) >= _MIN_CONFIDENCE
        claims = v.get("ungrounded_claims") or []
        msg = f"LLM grounding: ungrounded claim(s): {claims}"
        return fired, msg, str(v.get("evidence", ""))

    return _hook
