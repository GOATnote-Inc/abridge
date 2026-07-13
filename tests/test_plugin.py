"""The plugin/marketplace packaging must not drift: manifests parse, the
skill's frontmatter obeys the agentskills.io constraints, the bundled MCP
config points at the real server module, and the skill's tool allowlist
matches the tools the server actually registers."""

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "attending"


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must open with YAML frontmatter"
    fm: dict = {}
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^\S", line) and ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()
    return fm


def test_marketplace_and_plugin_manifests_parse_and_agree():
    mkt = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    assert mkt["name"] == "attending"
    entry = mkt["plugins"][0]
    assert entry["name"] == "attending"
    src = (REPO / entry["source"]).resolve()
    assert src == PLUGIN and src.is_dir()
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "attending"
    assert manifest["version"] == mkt["metadata"]["version"]


def test_skill_frontmatter_obeys_spec_constraints():
    text = (PLUGIN / "skills" / "clinical-safety-supervisor"
            / "SKILL.md").read_text()
    fm = _frontmatter(text)
    assert fm["name"] == "clinical-safety-supervisor"      # matches dir
    assert len(fm["name"]) <= 64
    assert re.fullmatch(r"[a-z0-9-]+", fm["name"])
    assert 0 < len(fm["description"]) <= 1024
    assert "supervise" in fm["description"].lower()
    assert len(text.splitlines()) < 500                     # progressive disclosure
    # the body must teach the two verdict responses
    assert "BLOCK" in text and "ESCALATE" in text
    assert "no override parameter" in text


def test_plugin_mcp_config_points_at_the_real_server():
    cfg = json.loads((PLUGIN / ".mcp.json").read_text())
    server = cfg["mcpServers"]["attending"]
    assert server["args"] == ["-m", "attending.mcp_server"]
    assert "CLAUDE_PLUGIN_ROOT" in server["env"]["PYTHONPATH"]
    assert (REPO / "src" / "attending" / "mcp_server.py").is_file()


def test_skill_allowlist_matches_registered_tools():
    import pytest
    pytest.importorskip("mcp")
    import anyio

    from attending import mcp_server
    registered = {f"mcp__attending__{t.name}"
                  for t in anyio.run(mcp_server.mcp.list_tools)}
    fm = _frontmatter((PLUGIN / "skills" / "clinical-safety-supervisor"
                       / "SKILL.md").read_text())
    allowed = set(fm["allowed-tools"].split())
    assert allowed == registered, (
        "skill allowlist and server tools drifted")
