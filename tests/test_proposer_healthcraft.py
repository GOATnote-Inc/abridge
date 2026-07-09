"""Tests for the HealthCraft TriageAgent -> Attending proposer adapter.

Two tiers:

1. Pure mapping tests (always run) — fabricated plan-like dicts/objects,
   no healthcraft import anywhere.
2. Integration test (runs only when healthcraft is importable, otherwise
   pytest.skip) — seeds a real Mercy Point world, runs the real
   TriageAgent, maps its TriagePlan, and supervises the result.
"""

from __future__ import annotations

from enum import IntEnum
from types import SimpleNamespace

import pytest

from attending import Decision, supervise
from attending.encounter import Encounter, Vitals
from attending.proposers.healthcraft import (
    FakeReasonerProposer,
    HealthcraftUnavailable,
    esi_from_risk,
    esi_to_int,
    fhir_bundle_from_encounter,
    healthcraft_importable,
    map_disposition,
    orders_for_rules,
    propose_from_plan,
    propose_with_healthcraft,
)


class _FakeESILevel(IntEnum):
    """Stand-in for healthcraft.entities.encounters.ESILevel (also IntEnum)."""

    RESUSCITATION = 1
    EMERGENT = 2
    URGENT = 3
    LESS_URGENT = 4
    NON_URGENT = 5


# ---------------------------------------------------------------------------
# esi_to_int / esi_from_risk
# ---------------------------------------------------------------------------


def test_esi_to_int_accepts_intenum_int_and_numeric_string():
    assert esi_to_int(_FakeESILevel.EMERGENT) == 2
    assert esi_to_int(3) == 3
    assert esi_to_int("4") == 4


def test_esi_to_int_rejects_garbage():
    assert esi_to_int(None) is None
    assert esi_to_int("urgent") is None
    assert esi_to_int(0) is None
    assert esi_to_int(6) is None
    assert esi_to_int(True) is None  # bools are not acuities


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        ("high", 2),
        ("HIGH", 2),
        ("moderate", 3),
        ("intermediate", 3),
        ("low", 4),
        ("very_low", 4),
        (None, None),
        ("banana", None),
        (2, None),
    ],
)
def test_esi_from_risk(risk, expected):
    assert esi_from_risk(risk) == expected


# ---------------------------------------------------------------------------
# map_disposition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rec", "esi", "expected"),
    [
        ("admit", 2, "main_ed"),
        ("admitted", 3, "main_ed"),
        ("observation", 3, "main_ed"),
        ("physician_review", None, "main_ed"),
        ("transfer", 2, "main_ed"),
        ("admit", 1, "resus"),  # ESI 1 upgrades in-department dispo to resus
        ("discharge", 4, "discharge"),
        ("discharged", 5, "discharge"),
        ("home", 4, "discharge"),
        ("fast-track", 4, "fast_track"),
        (None, 3, None),
        ("", 3, None),
    ],
)
def test_map_disposition(rec, esi, expected):
    assert map_disposition(rec, esi) == expected


def test_map_disposition_passes_unknown_through_for_supervisor_scrutiny():
    # Unknown release-ish words must NOT be laundered into a safe bucket:
    # the supervisor's own discharge-word list still needs to see them.
    assert map_disposition("Waiting_Room", 4) == "waiting_room"
    assert map_disposition("lobby", 3) == "lobby"


# ---------------------------------------------------------------------------
# orders_for_rules
# ---------------------------------------------------------------------------


def test_orders_for_rules_maps_and_dedupes():
    orders = orders_for_rules(
        ["HEART Score", "TIMI Risk Score for UA/NSTEMI", "Wells Criteria for PE"]
    )
    # HEART + TIMI both imply ecg/troponin (deduped); Wells adds d_dimer.
    assert orders == ("ecg", "troponin", "d_dimer")


def test_orders_for_rules_sepsis_and_unknown():
    assert orders_for_rules(["qSOFA"]) == ("lactate", "blood_cultures")
    assert orders_for_rules(["Ottawa SAH Rule"]) == ("ct_head",)
    assert orders_for_rules(["Totally Novel Rule"]) == ()
    assert orders_for_rules(None) == ()


# ---------------------------------------------------------------------------
# propose_from_plan — fabricated plan-likes (dict AND object shaped)
# ---------------------------------------------------------------------------


def _plan_dict(**overrides):
    plan = {
        "chief_complaint": "chest pain radiating to left arm",
        "rule_result": {
            "rule": "HEART Score",
            "result": {"score": 6.0, "risk_level": "high", "recommendation": "admit"},
        },
        "reasoning": {
            "runs": [
                {"rule_name": "HEART Score", "risk_level": "high"},
                {"rule_name": "TIMI Risk Score for UA/NSTEMI", "risk_level": "moderate"},
            ],
            "has_conflict": False,
            "synthesis": "Highest-risk verdict: high.",
        },
        "disposition": {"recommendation": "admit", "rationale": "risk_level=high"},
    }
    plan.update(overrides)
    return plan


def test_propose_from_plan_high_risk_admit():
    proposed = propose_from_plan(_plan_dict())
    assert proposed.esi_level == 2  # worst risk = high -> ESI 2
    assert proposed.disposition == "main_ed"
    assert set(("ecg", "troponin")) <= set(proposed.orders)
    assert "HEART Score=high" in proposed.rationale
    assert "chest pain" in proposed.rationale


def test_propose_from_plan_explicit_esi_level_wins():
    proposed = propose_from_plan(_plan_dict(esi_level=_FakeESILevel.RESUSCITATION))
    assert proposed.esi_level == 1
    assert proposed.disposition == "resus"  # admit + ESI 1 -> resus


def test_propose_from_plan_low_risk_discharge():
    plan = _plan_dict(
        rule_result={
            "rule": "Ottawa Ankle Rules",
            "result": {"score": 0.0, "risk_level": "low", "recommendation": "discharge"},
        },
        reasoning={
            "runs": [{"rule_name": "Ottawa Ankle Rules", "risk_level": "low"}],
            "has_conflict": False,
            "synthesis": "low",
        },
        disposition={"recommendation": "discharge", "rationale": "risk_level=low"},
    )
    proposed = propose_from_plan(plan)
    assert proposed.esi_level == 4
    assert proposed.disposition == "discharge"
    assert proposed.orders == ("xr_ankle",)


def test_propose_from_plan_conflict_caps_esi_at_3():
    plan = _plan_dict(
        reasoning={
            "runs": [
                {"rule_name": "HEART Score", "risk_level": "low"},
                {"rule_name": "sPESI", "risk_level": "high"},
            ],
            "has_conflict": True,
            "synthesis": "CONFLICT: rules disagree.",
        },
        rule_result=None,
        disposition={"recommendation": "physician_review", "rationale": "conflict"},
    )
    proposed = propose_from_plan(plan)
    assert proposed.esi_level == 2  # high already beats the conflict cap
    assert proposed.disposition == "main_ed"

    # And with no scored risk at all, a conflict alone commits ESI 3.
    plan["reasoning"]["runs"] = []
    proposed = propose_from_plan(plan)
    assert proposed.esi_level == 3


def test_propose_from_plan_no_rule_no_esi_fails_closed_downstream():
    plan = _plan_dict(
        rule_result=None,
        reasoning={"runs": [], "has_conflict": False, "synthesis": "no rule fired"},
        disposition={"recommendation": "physician_review", "rationale": "no rule"},
    )
    proposed = propose_from_plan(plan)
    assert proposed.esi_level is None  # supervisor Rule 1 escalates this
    assert proposed.orders == ()

    enc = Encounter(encounter_id="e-norule", chief_complaint="feeling odd")
    verdict = supervise(enc, proposed)
    assert verdict.decision is not Decision.ALLOW  # "not evaluated" != "safe"


def test_propose_from_plan_unscored_rule_is_not_an_order():
    plan = _plan_dict(
        rule_result=None,
        reasoning={
            "runs": [
                {"rule_name": "HEART Score", "risk_level": None},  # unscoreable
                {"rule_name": "Ottawa SAH Rule", "risk_level": "moderate"},
            ],
            "has_conflict": False,
            "synthesis": "partial",
        },
        disposition={"recommendation": "observation", "rationale": "x"},
    )
    proposed = propose_from_plan(plan)
    assert proposed.orders == ("ct_head",)  # no ecg/troponin from unscored HEART
    assert proposed.esi_level == 3


def test_propose_from_plan_accepts_attribute_objects():
    """TriagePlan is a dataclass, not a dict — the mapper must read attrs."""
    plan = SimpleNamespace(
        chief_complaint="fever and confusion",
        rule_result={
            "rule": "qSOFA",
            "result": {"score": 2.0, "risk_level": "high", "recommendation": "admit"},
        },
        reasoning=SimpleNamespace(
            runs=[SimpleNamespace(rule_name="qSOFA", risk_level="high")],
            has_conflict=False,
            synthesis="sepsis risk",
        ),
        disposition={"recommendation": "admit", "rationale": "risk_level=high"},
    )
    proposed = propose_from_plan(plan)
    assert proposed.esi_level == 2
    assert proposed.disposition == "main_ed"
    assert proposed.orders == ("lactate", "blood_cultures")


def test_propose_from_plan_explicit_orders_appended():
    proposed = propose_from_plan(_plan_dict(orders=["cxr", "ecg"]))
    assert "cxr" in proposed.orders
    assert proposed.orders.count("ecg") == 1  # deduped against rule-implied


# ---------------------------------------------------------------------------
# fhir_bundle_from_encounter
# ---------------------------------------------------------------------------


def test_fhir_bundle_from_encounter_roundtrips_complaint_and_vitals():
    enc = Encounter(
        encounter_id="ENC-42",
        chief_complaint="chest pain",
        sex="male",
        vitals=Vitals(hr=110, spo2=93),
        history="prior MI",
    )
    bundle = fhir_bundle_from_encounter(enc)
    types = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert types.count("Patient") == 1
    assert types.count("Encounter") == 1
    assert types.count("Condition") == 1
    assert types.count("Observation") == 2  # hr + spo2 only (None omitted)
    fhir_enc = next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Encounter"
    )
    assert fhir_enc["reasonCode"] == [{"text": "chest pain"}]


# ---------------------------------------------------------------------------
# FakeReasonerProposer end-to-end (pure Python, no healthcraft)
# ---------------------------------------------------------------------------


def test_fake_reasoner_proposer_supervised_end_to_end():
    enc = Encounter(
        encounter_id="e-fake-1",
        chief_complaint="chest pain for two hours",
        age_years=61,
        vitals=Vitals(hr=98, sbp=142, spo2=97),
    )
    proposed = FakeReasonerProposer().propose(enc)
    assert proposed.esi_level == 3  # moderate HEART
    assert proposed.disposition == "main_ed"
    assert "ecg" in proposed.orders and "troponin" in proposed.orders

    verdict = supervise(enc, proposed)
    assert verdict.decision in {Decision.ALLOW, Decision.BLOCK, Decision.ESCALATE}


def test_module_imports_without_healthcraft():
    """The adapter module itself must never hard-depend on healthcraft."""
    import attending.proposers.healthcraft  # noqa: F401, PLC0415

    assert callable(propose_with_healthcraft)
    assert issubclass(HealthcraftUnavailable, RuntimeError)


# ---------------------------------------------------------------------------
# Integration — REAL HealthCraft TriageAgent (skip when not installed)
# ---------------------------------------------------------------------------


def test_integration_real_triage_agent_supervised():
    if not healthcraft_importable():
        pytest.skip("healthcraft not installed")
    try:
        import healthcraft  # noqa: F401, PLC0415
    except ImportError:
        pytest.skip("healthcraft not installed")

    enc = Encounter(
        encounter_id="ENC-INT-1",
        chief_complaint="chest pain radiating to left arm",
        age_years=58,
        sex="male",
        vitals=Vitals(hr=104, rr=20, spo2=96, sbp=148, dbp=92, pain=7),
        history="hypertension, smoker",
    )
    try:
        proposed = propose_with_healthcraft(enc)
    except HealthcraftUnavailable as exc:
        pytest.skip(f"healthcraft unavailable at runtime: {exc}")

    # The real TriageAgent produced a plan; the mapping must yield our types.
    assert proposed.disposition is None or isinstance(proposed.disposition, str)
    assert isinstance(proposed.orders, tuple)
    assert proposed.esi_level is None or 1 <= proposed.esi_level <= 5
    assert proposed.rationale  # a real plan always carries some reasoning

    verdict = supervise(enc, proposed)
    assert verdict.decision in {Decision.ALLOW, Decision.BLOCK, Decision.ESCALATE}
    assert verdict.encounter_id == "ENC-INT-1"
    # Fail-closed sanity: if the agent proposed no acuity, we must not ALLOW.
    if proposed.esi_level is None:
        assert verdict.decision is not Decision.ALLOW
