"""Test infrastructure.

Mutation hook: when ATTENDING_MUTATE_GATE is set (by scripts/mutation_check.py,
never by hand), the named safety mechanism — a communication gate OR a
decision-side rule/detector — is no-opped for the whole test session. The
harness then asserts the suite FAILS, proving every mechanism is load-bearing
("disable it and its tests fail" as a command, not a claim).
"""

from __future__ import annotations

import os


def _noop_detection(detector: str):
    from attending.verdict import Detection, Severity

    def stub(*args, **kwargs):
        return Detection(detector, False, Severity.INFO, "MUTATED OFF")

    return stub


def _mutate_comms_gate(name: str) -> None:
    from sitrep import gates

    if name == "check_disclosure_gap":
        # State-level gate: called directly by attending.comms, not via ALL_GATES.
        import attending.comms as comms

        gates.check_disclosure_gap = lambda s: []  # type: ignore[assignment]
        comms.check_disclosure_gap = lambda s: []  # type: ignore[assignment]
        return
    before = len(gates.ALL_GATES)
    gates.ALL_GATES = [g for g in gates.ALL_GATES if g.__name__ != name]
    if len(gates.ALL_GATES) == before:
        raise RuntimeError(f"mutation target not found: {name}")


def _mutate_decision(name: str) -> None:
    """Decision-surface mutants — each disables one safety mechanism."""
    import attending.detectors as det
    import attending.esi as esi
    import attending.knowledge as K
    import attending.supervisor as sup

    if name == "esi_independent_assessment":
        # Supervisor trusts the proposal instead of re-deriving acuity.
        def lazy(enc):
            return esi.EsiAssessment(5, "C", reasons=("MUTATED",),
                                     resource_estimate=(0, 0))
        sup.compute_esi = lazy  # type: ignore[assignment]
    elif name == "red_flag_matching":
        esi.match_red_flags = lambda enc: []  # type: ignore[assignment]
    elif name == "requirement_group_and":
        # Collapse conjunction-of-groups back to the pre-fix ANY semantics.
        def flat(seq):
            union = tuple(x for item in (seq or ()) for x in
                          ((item,) if isinstance(item, str) else tuple(item)))
            return (union,) if union else ()
        K.normalize_requires = flat  # type: ignore[assignment]
    elif name in ("hallucination", "anchoring_bias",
                  "incomplete_audio", "transcription_error"):
        stub = _noop_detection(name)
        fn = f"detect_{name}" if name != "anchoring_bias" else "detect_anchoring"
        import importlib
        mod = importlib.import_module(f"attending.detectors.{name}")
        setattr(mod, fn, stub)
        setattr(det, fn, stub)  # the binding run_all actually calls
    else:
        raise RuntimeError(f"unknown decision mutant: {name}")


DECISION_MUTANTS = {
    "esi_independent_assessment", "red_flag_matching", "requirement_group_and",
    "hallucination", "anchoring_bias", "incomplete_audio", "transcription_error",
}

_target = os.environ.get("ATTENDING_MUTATE_GATE")
if _target:
    if _target in DECISION_MUTANTS:
        _mutate_decision(_target)
    else:
        _mutate_comms_gate(_target)
