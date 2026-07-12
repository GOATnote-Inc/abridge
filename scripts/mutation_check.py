#!/usr/bin/env python3
"""Mutation harness: prove every communication gate is load-bearing.

For each gate, run the test suite with that gate no-opped (via the
ATTENDING_MUTATE_GATE hook in tests/conftest.py) and demand FAILURES — a gate
whose removal changes nothing is dead weight or, worse, untested safety
theater. Finishes with a clean run that must be green.

    make mutation          # or: python3 scripts/mutation_check.py

Exit 0 only if every mutant is caught AND the clean suite passes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Communication gates + decision-surface mechanisms: EVERY one must be
# load-bearing (its removal must fail tests).
GATES = [
    # comms surface
    "gate_result_context_labels",
    "gate_no_interpretation",
    "gate_info_blocking",
    "gate_no_advice",
    "gate_compliance",
    "gate_grounding",
    "gate_escalation",
    "gate_readability",
    "check_disclosure_gap",
    # decision surface
    "esi_independent_assessment",
    "red_flag_matching",
    "requirement_group_and",
    "hallucination",
    "anchoring_bias",
    "incomplete_audio",
    "transcription_error",
    # coverage surface (F14-F19)
    "coverage_grounding",
    "coverage_frankenfacts",
    "fabricated_authority",
    "coverage_provenance",
    "coverage_outcome",
    "denial_signoff",
    "denial_justification",
]

_SUMMARY = re.compile(r"(\d+) failed")


def run_suite(mutate: str | None) -> tuple[int, int]:
    """Return (exit_code, failed_count)."""
    env = dict(os.environ, PYTHONPATH="src")
    if mutate:
        env["ATTENDING_MUTATE_GATE"] = mutate
    else:
        env.pop("ATTENDING_MUTATE_GATE", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    m = _SUMMARY.search(proc.stdout)
    return proc.returncode, int(m.group(1)) if m else 0


def main() -> int:
    ok = True
    for gate in GATES:
        code, failed = run_suite(gate)
        caught = code != 0 and failed > 0
        ok &= caught
        print(f"  {'CAUGHT' if caught else 'MISSED'}  -{gate}: "
              f"{failed} test(s) fail with the gate disabled")
    code, failed = run_suite(None)
    clean = code == 0
    ok &= clean
    print(f"  {'GREEN' if clean else 'BROKEN'}  clean run: "
          f"{'all tests pass' if clean else f'{failed} failed'}")
    if not ok:
        print("\nMUTATION CHECK FAILED — a gate is not load-bearing "
              "(or the clean suite is red).", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
