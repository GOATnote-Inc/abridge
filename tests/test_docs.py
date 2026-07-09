"""Docs/artifacts must track the code — the drift class an external reviewer
caught twice (stale transcript, then stale report) is now structurally guarded."""

import re
from pathlib import Path

from attending import knowledge as K

REPO = Path(__file__).parent.parent
_VERSION_RE = re.compile(r"esi-v4-attending-[\d.]+\d")


def test_evaluation_report_matches_code_ruleset():
    text = (REPO / "evaluation" / "REPORT.md").read_text()
    found = set(_VERSION_RE.findall(text))
    assert found == {K.RULESET_VERSION}, (
        f"evaluation/REPORT.md cites {found}, code is {K.RULESET_VERSION} — "
        "update the report alongside the ruleset")


def test_knowledge_export_matches_code_ruleset():
    import json
    cfg = json.loads((REPO / "configs" / "knowledge.json").read_text())
    assert cfg["ruleset_version"] == K.RULESET_VERSION


def test_review_packet_is_labeled_as_template():
    text = (REPO / "docs" / "CLINICAL_REVIEW_PACKET.md").read_text()
    assert "BLANK TEMPLATE" in text and "docs/reviews/" in text


def test_completed_review_record_exists_when_status_reviewed():
    if "physician-reviewed" in K.APPROVAL_STATUS:
        assert list((REPO / "docs" / "reviews").glob("*.md")), (
            "approval_status claims physician-reviewed but docs/reviews/ is empty")
