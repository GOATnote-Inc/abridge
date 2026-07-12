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
