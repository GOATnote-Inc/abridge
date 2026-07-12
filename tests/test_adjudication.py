"""The clinician-agreement machinery must itself be trustworthy: packet
generation is deterministic and blind (no labels leak), kappa math is right,
and the scorer refuses partial packets (fail-closed grading of the grader).
"""

import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "adjudication_packet.py"


def _run(*args, tmp=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        cwd=str(tmp or REPO),
    )


def test_packet_is_deterministic_and_blind(tmp_path):
    p = _run("generate")
    assert p.returncode == 0, p.stderr
    packet = (REPO / "evaluation" / "adjudication" / "PACKET.md").read_text()
    again = _run("generate")
    assert again.returncode == 0
    assert packet == (REPO / "evaluation" / "adjudication"
                      / "PACKET.md").read_text()
    # Blind: no expected labels, criteria ids, or gold-set ids leak.
    for token in ("expect", "BLOCK\n", "criterion", "GS-", "RF-", "ATT-"):
        assert token not in packet, f"label leak: {token!r}"
    assert packet.count("## Case") == 23


def test_scorer_refuses_partial_or_junk_rulings(tmp_path):
    bad = tmp_path / "rulings.jsonl"
    bad.write_text(json.dumps({"case": 1, "decision": "ALLOW"}) + "\n")
    p = _run("score", str(bad))
    assert p.returncode == 1
    junk = tmp_path / "rulings2.jsonl"
    junk.write_text("\n".join(
        json.dumps({"case": i, "decision": "MAYBE" if i == 5 else "ALLOW"})
        for i in range(1, 24)) + "\n")
    p2 = _run("score", str(junk))
    assert p2.returncode == 1 and "MAYBE" in p2.stdout


def test_scoring_agrees_with_engine_when_rulings_are_engine_verdicts(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    import adjudication_packet as ap
    cases = ap._cases()
    rulings = tmp_path / "rulings.jsonl"
    with open(rulings, "w") as fh:
        for i, rec in enumerate(cases, 1):
            fh.write(json.dumps(
                {"case": i, "decision": ap._engine_decision(rec)}) + "\n")
    p = _run("score", str(rulings))
    assert p.returncode == 0, p.stderr
    assert "raw agreement 23/23 = 100.0%" in p.stdout
    assert "kappa = 1.000" in p.stdout


def test_kappa_math_on_known_matrix():
    sys.path.insert(0, str(REPO / "scripts"))
    import adjudication_packet as ap
    # Perfect disagreement between two evenly-split raters -> kappa <= 0.
    pairs = [("ALLOW", "BLOCK")] * 5 + [("BLOCK", "ALLOW")] * 5
    assert ap._kappa(pairs) <= 0
    # Textbook 2x2: po=0.7, pe=0.5 -> kappa 0.4.
    pairs = ([("ALLOW", "ALLOW")] * 35 + [("BLOCK", "BLOCK")] * 35
             + [("ALLOW", "BLOCK")] * 15 + [("BLOCK", "ALLOW")] * 15)
    assert abs(ap._kappa(pairs) - 0.4) < 1e-9
