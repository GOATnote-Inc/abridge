#!/usr/bin/env python3
"""Evidence-count drift guard: counts derive from reality, or the build fails.

Reality sources:
  tests_collected       pytest --collect-only (environment-invariant by
                        construction — gateway tests collect everywhere and
                        skip without the extra)
  mutation_mechanisms   len(GATES) in scripts/mutation_check.py
  goldset_cases         line count of evaluation/goldset.jsonl
  adversarial_attacks   pytest --collect-only tests/test_adversarial.py

Modes:
  (default)  write evaluation/COUNTS.json
  --check    also scan the evidence documents for count-shaped claims and
             exit 1 on any number that does not match reality. Lines with a
             transition arrow ("->" / "→") are historical (changelog) and
             exempt; docs/reviews/ is never scanned (dated records).

Wired into `make check` and CI: prose cannot drift from the suite again.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COUNTS = REPO / "evaluation" / "COUNTS.json"

CHECKED_DOCS = [
    "README.md",
    "docs/SYSTEM_CARD.md",
    "evaluation/REPORT.md",
    "DEMO_FRIDAY.md",
    "DEMO_SATURDAY.md",
]


def _collected(*pytest_args: str) -> int:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *pytest_args],
        cwd=REPO, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    ).stdout
    m = re.search(r"(\d+) tests? collected", out)
    if not m:
        raise SystemExit(f"could not parse collection output:\n{out[-400:]}")
    return int(m.group(1))


def _mutation_mechanisms() -> int:
    text = (REPO / "scripts" / "mutation_check.py").read_text()
    m = re.search(r"GATES = \[(.*?)\]", text, re.S)
    assert m, "GATES list not found"
    return len(re.findall(r'"[a-z_]+"', m.group(1)))


def actuals() -> dict:
    return {
        "tests_collected": _collected("tests"),
        "mutation_mechanisms": _mutation_mechanisms(),
        "goldset_cases": len([
            x for x in (REPO / "evaluation" / "goldset.jsonl")
            .read_text().splitlines() if x.strip()]),
        "adversarial_attacks": _collected("tests/test_adversarial.py"),
    }


# Claim-shaped patterns -> which actual they must equal.
def _claims(line: str) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for m in re.finditer(r"\b(\d+)\s+tests\b", line):
        found.append(("tests_collected", int(m.group(1))))
    for m in re.finditer(r"\b(\d+)/(\d+)\b", line):
        a, b = int(m.group(1)), int(m.group(2))
        if a == b and b > 5:          # 22/22, 23/23 style totals
            key = ("mutation_mechanisms" if b != 23 else "goldset_cases")
            found.append((key, b))
        elif b == 23:                  # 0/23, x/23 goldset fractions
            found.append(("goldset_cases", b))
    for m in re.finditer(r"\b(\d+)\s+mutation (?:targets|mechanisms)\b", line):
        found.append(("mutation_mechanisms", int(m.group(1))))
    for m in re.finditer(r"\ball (\d+) safety mechanisms\b", line):
        found.append(("mutation_mechanisms", int(m.group(1))))
    for m in re.finditer(r"\b(\d+) automated attacks\b", line):
        found.append(("adversarial_attacks", int(m.group(1))))
    return found


def check(act: dict) -> list[str]:
    errors: list[str] = []
    for rel in CHECKED_DOCS:
        for n, line in enumerate((REPO / rel).read_text().splitlines(), 1):
            if "->" in line or "→" in line:      # historical transitions
                continue
            for key, claimed in _claims(line):
                if claimed != act[key]:
                    errors.append(
                        f"{rel}:{n}: claims {key}={claimed}, actual {act[key]}"
                        f" | {line.strip()[:80]}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    act = actuals()
    COUNTS.write_text(json.dumps(act, indent=2) + "\n")
    print(json.dumps(act))
    if args.check:
        errors = check(act)
        for e in errors:
            print("DRIFT:", e, file=sys.stderr)
        if errors:
            return 1
        print(f"counts check: {len(CHECKED_DOCS)} docs consistent with reality")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
