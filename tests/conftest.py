"""Test infrastructure.

Mutation hook: when ATTENDING_MUTATE_GATE is set (by scripts/mutation_check.py,
never by hand), the named communication gate is no-opped for the whole test
session. The harness then asserts the suite FAILS — proving every gate is
load-bearing ("disable a gate and its tests fail" as a command, not a claim).
"""

from __future__ import annotations

import os


def _mutate_gate(name: str) -> None:
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


_target = os.environ.get("ATTENDING_MUTATE_GATE")
if _target:
    _mutate_gate(_target)
