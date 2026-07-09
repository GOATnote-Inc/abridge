"""Adapter: HealthCraft's TriageAgent as a REAL proposing agent for Attending.

HealthCraft (Apache-2.0, arXiv:2605.21496) ships an in-process A2A triage
agent (``healthcraft.agents_assemble.agent_triage.agent.TriageAgent``) that
ingests a FHIR Bundle and emits a ``TriagePlan``: a differential, decision-rule
runs with risk levels, and a disposition recommendation. This module turns
that plan into Attending's ``ProposedTriage`` so the supervisor can grade a
live proposer instead of JSON fixtures.

Layering (deliberate):

- **Pure mapping** (no healthcraft import): ``esi_to_int``, ``esi_from_risk``,
  ``map_disposition``, ``orders_for_rules``, ``propose_from_plan``,
  ``fhir_bundle_from_encounter``. Unit-testable in isolation.
- **Live adapter**: ``propose_with_healthcraft(encounter)`` lazily imports
  healthcraft (appending ``$HEALTHCRAFT_HOME/src`` to ``sys.path``
  if needed), seeds a deterministic Mercy Point world (seed=42, cached),
  runs the TriageAgent, and maps the plan. Raises ``HealthcraftUnavailable``
  with a clear message when healthcraft cannot be imported.

Mapping decisions (documented so a reviewer can audit the vocabulary):

- **ESI**: TriagePlan carries risk levels, not ESI. We map the *worst*
  decision-rule risk to ESI (high -> 2, moderate/intermediate -> 3,
  low/very_low -> 4). An explicit ``esi_level`` on a plan-like object
  (HealthCraft's ``ESILevel`` IntEnum, an int, or a numeric string) wins.
  A reasoner conflict caps ESI at 3 (acuity genuinely uncertain). No risk
  and no explicit level -> ``esi_level=None`` -- Attending fails closed
  (Rule 1: no proposal -> ESCALATE), which is exactly the right verdict
  for a proposer that could not commit to an acuity.
- **Disposition**: HealthCraft recommends admit/observation/discharge/
  physician_review (agent) or admitted/discharged/transferred (entity
  enum). Attending's vocab is resus|main_ed|fast_track|discharge.
  admit/observation/physician_review/transfer -> "main_ed" ("resus" when
  ESI 1); discharge(d)/home -> "discharge". Unknown strings pass through
  lowercased so the supervisor's own discharge-word list ("lobby",
  "waiting_room", ...) still sees them -- the adapter never launders an
  unrecognized release intent into a safe-looking bucket.
- **Orders**: the TriagePlan orders nothing directly; the decision rules it
  ran imply the workup. We translate rule names into Attending's order
  vocabulary (HEART/TIMI/Sgarbossa -> ecg+troponin; Wells/PERC/sPESI ->
  ecg+d_dimer; qSOFA/NEWS2/MEWS/CURB-65 -> lactate+blood_cultures;
  Ottawa SAH/PECARN/ABCD2 -> ct_head; ...). Only rules that actually
  *scored* (risk_level present) count as evidence of a performed workup;
  an unscoreable rule is not an order. Explicit ``orders`` on a plan-like
  object are appended verbatim.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from ..encounter import Encounter, ProposedTriage

# Where a source checkout of HealthCraft lives when it is not pip-installed.
# Override with HEALTHCRAFT_HOME; defaults to a sibling checkout under $HOME.
_HEALTHCRAFT_HOME = Path(os.environ.get("HEALTHCRAFT_HOME", str(Path.home() / "healthcraft")))
HEALTHCRAFT_SRC = _HEALTHCRAFT_HOME / "src"
WORLD_CONFIG = _HEALTHCRAFT_HOME / "configs" / "world" / "mercy_point_v1.yaml"
WORLD_SEED = 42


class HealthcraftUnavailable(RuntimeError):
    """Raised when the HealthCraft package (or its world config) is missing."""


# ---------------------------------------------------------------------------
# Pure mapping — no healthcraft import anywhere below this line
# ---------------------------------------------------------------------------

# Decision-rule risk level -> ESI acuity. Worst (smallest) wins across runs.
_RISK_TO_ESI: dict[str, int] = {
    "high": 2,
    "moderate": 3,
    "intermediate": 3,
    "low": 4,
    "very_low": 4,
}

# HealthCraft disposition vocabulary -> Attending disposition vocabulary.
# Unknown values deliberately pass through (lowercased) — see module docstring.
_DISPOSITION_MAP: dict[str, str] = {
    "admit": "main_ed",
    "admitted": "main_ed",
    "observation": "main_ed",
    "physician_review": "main_ed",
    "transfer": "main_ed",
    "transferred": "main_ed",
    "resuscitation": "resus",
    "resus": "resus",
    "fast_track": "fast_track",
    "fast track": "fast_track",
    "discharge": "discharge",
    "discharged": "discharge",
    "home": "discharge",
}

# Rule-name keyword -> orders implied by having run that rule. Keywords are
# matched as substrings of the lowercased rule name; first matching row wins
# per rule. Order names use Attending's knowledge.py vocabulary where one
# exists (ecg, troponin, ct_head, lactate, blood_cultures, ...).
_RULE_ORDER_TABLE: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("heart score", "timi", "sgarbossa"), ("ecg", "troponin")),
    (("wells", "perc", "spesi"), ("ecg", "d_dimer")),
    (("ottawa sah",), ("ct_head",)),
    (("qsofa", "news2", "mews", "curb-65", "curb65"), ("lactate", "blood_cultures")),
    (("pecarn", "glasgow coma", "abcd2"), ("ct_head",)),
    (("c-spine", "nexus"), ("ct_cspine",)),
    (("ottawa ankle",), ("xr_ankle",)),
    (("ottawa knee",), ("xr_knee",)),
    (("blatchford", "aims65", "rockall"), ("cbc", "type_and_screen")),
    (("alvarado",), ("ct_abdomen",)),
    (("syncope",), ("ecg",)),
)


def esi_to_int(value: Any) -> int | None:
    """Coerce an ESI-ish value (HealthCraft ``ESILevel`` IntEnum, int, numeric
    string) to an int in 1..5, else None. Never raises."""
    if value is None or isinstance(value, bool):
        return None
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    return level if 1 <= level <= 5 else None


def esi_from_risk(risk_level: Any) -> int | None:
    """Map a decision-rule risk level ('high'/'moderate'/...) to an ESI int."""
    if not isinstance(risk_level, str):
        return None
    return _RISK_TO_ESI.get(risk_level.strip().lower())


def map_disposition(recommendation: Any, esi_level: int | None = None) -> str | None:
    """Map a HealthCraft disposition recommendation to Attending's vocab.

    ESI 1 upgrades an in-department disposition to "resus". Unknown values
    pass through lowercased (never silently sanitized).
    """
    if recommendation is None:
        return None
    rec = str(recommendation).strip().lower().replace("-", "_")
    if not rec:
        return None
    mapped = _DISPOSITION_MAP.get(rec, rec)
    if mapped == "main_ed" and esi_level == 1:
        return "resus"
    return mapped


def orders_for_rules(rule_names: Any) -> tuple[str, ...]:
    """Translate HealthCraft decision-rule names into Attending order strings.

    Deduplicated, insertion-ordered. Unrecognized rules contribute nothing.
    """
    orders: list[str] = []
    seen: set[str] = set()
    for name in rule_names or ():
        lowered = str(name).lower()
        for keywords, implied in _RULE_ORDER_TABLE:
            if any(k in lowered for k in keywords):
                for order in implied:
                    if order not in seen:
                        seen.add(order)
                        orders.append(order)
                break
    return tuple(orders)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a dict or an attribute-bearing object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _scored_rule_runs(plan_like: Any) -> list[tuple[str, str]]:
    """Collect ``(rule_name, risk_level)`` for every rule run that scored.

    Sources, in order: ``reasoning.runs`` (full multi-rule output), then the
    legacy single-rule ``rule_result``. Runs without a risk_level are skipped
    (an unscoreable rule is evidence of nothing).
    """
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(name: Any, risk: Any) -> None:
        if not name or not isinstance(risk, str) or not risk.strip():
            return
        key = str(name).lower()
        if key in seen:
            return
        seen.add(key)
        pairs.append((str(name), risk.strip().lower()))

    reasoning = _get(plan_like, "reasoning")
    for run in _get(reasoning, "runs") or ():
        add(_get(run, "rule_name"), _get(run, "risk_level"))

    rule_result = _get(plan_like, "rule_result")
    if rule_result is not None:
        result = _get(rule_result, "result") or {}
        add(_get(rule_result, "rule"), _get(result, "risk_level"))

    return pairs


def propose_from_plan(plan_like: Any) -> ProposedTriage:
    """Map a HealthCraft ``TriagePlan`` (or any plan-like dict/object with the
    same field names) into Attending's ``ProposedTriage``.

    Pure function: no healthcraft import, no I/O. See module docstring for
    the mapping decisions.
    """
    scored = _scored_rule_runs(plan_like)

    # --- ESI: explicit level wins; else worst scored risk; conflict caps at 3.
    esi = esi_to_int(_get(plan_like, "esi_level"))
    if esi is None:
        risk_esis = [e for _, risk in scored if (e := esi_from_risk(risk)) is not None]
        esi = min(risk_esis) if risk_esis else None

    reasoning = _get(plan_like, "reasoning")
    has_conflict = bool(_get(reasoning, "has_conflict", False))
    if has_conflict:
        esi = 3 if esi is None else min(esi, 3)

    # --- Orders: workup implied by every *scored* rule + any explicit orders.
    orders = list(orders_for_rules(name for name, _ in scored))
    for extra in _get(plan_like, "orders") or ():
        text = str(extra)
        if text and text not in orders:
            orders.append(text)

    # --- Disposition.
    disposition_obj = _get(plan_like, "disposition")
    if isinstance(disposition_obj, (dict,)) or hasattr(disposition_obj, "recommendation"):
        recommendation = _get(disposition_obj, "recommendation")
        disposition_rationale = _get(disposition_obj, "rationale")
    else:
        recommendation = disposition_obj
        disposition_rationale = None
    disposition = map_disposition(recommendation, esi)

    # --- Rationale: synthesis + rule outputs + disposition reasoning.
    bits: list[str] = []
    synthesis = _get(reasoning, "synthesis")
    if synthesis:
        bits.append(str(synthesis))
    if scored:
        bits.append("rules: " + ", ".join(f"{n}={r}" for n, r in scored))
    if disposition_rationale:
        bits.append(f"disposition: {disposition_rationale}")
    complaint = _get(plan_like, "chief_complaint")
    if complaint:
        bits.append(f"chief complaint: {complaint}")

    return ProposedTriage(
        esi_level=esi,
        orders=tuple(orders),
        disposition=disposition,
        rationale=" | ".join(bits) or None,
    )


# ---------------------------------------------------------------------------
# Encounter -> FHIR Bundle (pure; what the TriageAgent ingests)
# ---------------------------------------------------------------------------

_VITAL_OBSERVATIONS: tuple[tuple[str, str, str], ...] = (
    ("hr", "Heart rate", "/min"),
    ("rr", "Respiratory rate", "/min"),
    ("spo2", "Oxygen saturation", "%"),
    ("sbp", "Systolic blood pressure", "mmHg"),
    ("dbp", "Diastolic blood pressure", "mmHg"),
    ("temp_c", "Body temperature", "Cel"),
    ("pain", "Pain severity", "score"),
    ("gcs", "Glasgow Coma Scale", "score"),
)


def fhir_bundle_from_encounter(enc: Encounter) -> dict[str, Any]:
    """Render an Attending ``Encounter`` as the minimal FHIR Bundle the
    HealthCraft TriageAgent reads (Patient, Encounter.reasonCode, vitals
    Observations, optional history Condition)."""
    patient_id = f"{enc.encounter_id}-patient"
    patient: dict[str, Any] = {"resourceType": "Patient", "id": patient_id}
    if enc.sex:
        patient["gender"] = str(enc.sex).lower()

    fhir_encounter: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": enc.encounter_id,
        "status": "in-progress",
        "subject": {"reference": f"Patient/{patient_id}"},
        "reasonCode": [{"text": enc.chief_complaint}] if enc.chief_complaint else [],
    }

    entries: list[dict[str, Any]] = [
        {"resource": patient},
        {"resource": fhir_encounter},
    ]

    if enc.history:
        entries.append(
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": f"{enc.encounter_id}-history",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"text": enc.history},
                }
            }
        )

    for field_name, display, unit in _VITAL_OBSERVATIONS:
        value = getattr(enc.vitals, field_name, None)
        if value is None:
            continue
        entries.append(
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": f"{enc.encounter_id}-obs-{field_name}",
                    "status": "final",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "code": {"text": display},
                    "valueQuantity": {"value": value, "unit": unit},
                }
            }
        )

    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


# ---------------------------------------------------------------------------
# FakeReasonerProposer — a pure-Python stand-in proposer (no healthcraft)
# ---------------------------------------------------------------------------


class FakeReasonerProposer:
    """A tiny deterministic proposer that emits HealthCraft-shaped plan-likes.

    Exists so the *mapping* path (plan-like -> ProposedTriage -> supervise)
    can be exercised end-to-end with zero external dependencies. It is NOT a
    clinical tool; the vocabulary intentionally mirrors HeuristicReasoner's
    output shape (rule runs with risk levels + a disposition recommendation).
    """

    # (substring of encounter text, rule name, risk_level, disposition rec)
    _TABLE: tuple[tuple[str, str, str, str], ...] = (
        ("chest pain", "HEART Score", "moderate", "observation"),
        ("shortness of breath", "Wells Criteria for PE", "moderate", "observation"),
        ("fever", "qSOFA", "high", "admit"),
        ("headache", "Ottawa SAH Rule", "moderate", "observation"),
        ("ankle", "Ottawa Ankle Rules", "low", "discharge"),
    )

    def plan(self, encounter: Encounter) -> dict[str, Any]:
        """Produce a HealthCraft-TriagePlan-shaped dict for the encounter."""
        blob = encounter.text_blob
        runs: list[dict[str, Any]] = []
        recommendation = "physician_review"
        for needle, rule, risk, rec in self._TABLE:
            if needle in blob:
                runs.append({"rule_name": rule, "risk_level": risk})
                recommendation = rec
                break
        return {
            "chief_complaint": encounter.chief_complaint,
            "rule_result": None,
            "reasoning": {
                "runs": runs,
                "has_conflict": False,
                "synthesis": "fake reasoner (deterministic stand-in)",
            },
            "disposition": {
                "recommendation": recommendation,
                "rationale": "FakeReasonerProposer table lookup",
            },
        }

    def propose(self, encounter: Encounter) -> ProposedTriage:
        return propose_from_plan(self.plan(encounter))


# ---------------------------------------------------------------------------
# Live adapter — lazy healthcraft import; the ONLY impure section
# ---------------------------------------------------------------------------

_WORLD_CACHE: dict[tuple[int, str], Any] = {}


def _import_healthcraft() -> Any:
    """Import healthcraft, appending the source checkout to sys.path if
    needed. Raises HealthcraftUnavailable (never ImportError) on failure."""
    try:
        import healthcraft  # noqa: PLC0415 — lazy by design

        return healthcraft
    except ImportError:
        pass

    src = str(HEALTHCRAFT_SRC)
    if HEALTHCRAFT_SRC.is_dir() and src not in sys.path:
        sys.path.append(src)
        try:
            import healthcraft  # noqa: PLC0415

            return healthcraft
        except ImportError as exc:
            raise HealthcraftUnavailable(
                f"healthcraft found at {src} but failed to import: {exc}"
            ) from exc

    raise HealthcraftUnavailable(
        "healthcraft is not installed and no source checkout was found at "
        f"{src}. `pip install -e <healthcraft checkout>` or set HEALTHCRAFT_HOME "
        "checkout at that path."
    )


def healthcraft_importable() -> bool:
    """True when the live adapter can run (used by tests to skip cleanly)."""
    try:
        _import_healthcraft()
    except HealthcraftUnavailable:
        return False
    return True


def _get_world(seed: int = WORLD_SEED, config_path: Path = WORLD_CONFIG) -> Any:
    """Seed (once, then cache) the deterministic Mercy Point world."""
    key = (seed, str(config_path))
    world = _WORLD_CACHE.get(key)
    if world is None:
        if not config_path.exists():
            raise HealthcraftUnavailable(
                f"healthcraft world config not found: {config_path}"
            )
        try:
            from healthcraft.world.seed import WorldSeeder  # noqa: PLC0415

            world = WorldSeeder(seed=seed).seed_world(config_path)
        except ImportError as exc:
            # healthcraft imports, but a runtime dependency it needs to seed
            # (e.g. PyYAML) is absent — treat as "unavailable", not a crash.
            raise HealthcraftUnavailable(
                f"healthcraft is importable but a runtime dependency is "
                f"missing: {exc}"
            ) from exc
        _WORLD_CACHE[key] = world
    return world


def propose_with_healthcraft(
    encounter: Encounter,
    *,
    reasoner: Any = None,
) -> ProposedTriage:
    """Run HealthCraft's TriageAgent on an Attending Encounter and map its
    TriagePlan into a ProposedTriage.

    ``reasoner`` (optional) is passed through to ``TriageAgent`` — e.g. a
    HealthCraft ``LlmReasoner`` or ``HeuristicReasoner`` (the default).

    Raises:
        HealthcraftUnavailable: healthcraft cannot be imported (or its world
            config is missing). Importing *this module* never fails.
    """
    _import_healthcraft()
    try:
        from healthcraft.agents_assemble.agent_triage.agent import (  # noqa: PLC0415
            TriageAgent,
        )
    except ImportError as exc:
        raise HealthcraftUnavailable(
            f"healthcraft TriageAgent import failed (missing runtime "
            f"dependency): {exc}"
        ) from exc

    world = _get_world()
    agent = TriageAgent(world, reasoner=reasoner)
    plan = agent.run(fhir_bundle_from_encounter(encounter))
    return propose_from_plan(plan)
