"""The web replay is venue-critical: a JS syntax slip or a render-time throw
blanks the demo. These tests pin the two failure modes machine-checkably;
deeper behavior lives in scripts/web_smoke.js (node), skipped where node is
absent (CI runners have it).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGES = [REPO / "web" / "index.html", REPO / "web" / "playground.html"]


def _script_body(page: Path) -> str:
    m = re.search(r"<script>(.*)</script>", page.read_text(), re.S)
    assert m, f"{page.name}: no script block"
    js = m.group(1)
    js = re.sub(r'"(?:[^"\\]|\\.)*"', '""', js)
    js = re.sub(r"'(?:[^'\\]|\\.)*'", "''", js)
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    js = re.sub(r"//[^\n]*", "", js)
    return js


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_js_brackets_balanced(page: Path) -> None:
    js = _script_body(page)
    close = {")": "(", "}": "{", "]": "["}
    depth = {c: 0 for c in "({["}
    for ch in js:
        if ch in depth:
            depth[ch] += 1
        elif ch in close:
            depth[close[ch]] -= 1
            assert depth[close[ch]] >= 0, f"{page.name}: extra {ch}"
    assert all(v == 0 for v in depth.values()), f"{page.name}: unbalanced {depth}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_revision_diffs_render_from_golden_transcript() -> None:
    proc = subprocess.run(
        ["node", str(REPO / "scripts" / "web_smoke.js")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_recorded_playground_verdicts_are_fresh() -> None:
    """The hosted playground replays committed verdicts; they must match a
    live regeneration through the current engine byte-for-byte, and cover
    every preset the page defines (keys derive from the page's own arrays)."""
    pytest.importorskip("fastapi")
    import json
    import sys
    committed = (REPO / "web" / "playground_recorded.json").read_text()
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "playground_recorded.py"),
         "--stdout"],
        capture_output=True, text=True, timeout=180,
        env={"PYTHONPATH": str(REPO / "src"),
             "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == committed, "recordings stale — regenerate"
    rec = json.loads(committed)["recorded"]
    assert len(rec) == 15
    dump = subprocess.run(
        ["node", str(REPO / "scripts" / "playground_presets_dump.js")],
        capture_output=True, text=True, timeout=60,
    )
    assert dump.returncode == 0, dump.stderr
    presets = json.loads(dump.stdout)
    for p in presets:
        key = p["path"] + "|" + json.dumps(
            p["body"], sort_keys=True, separators=(",", ":"),
            ensure_ascii=False)
        # three-way parity: python canonical == the page's own stableStr
        # (extracted and executed by the dump script) == a recorded key
        assert key == p["page_key"], f"canonicalizer drift: {p['label']}"
        assert key in rec, f"preset not recorded: {p['label']}"
        assert rec[key]["status"] < 500
