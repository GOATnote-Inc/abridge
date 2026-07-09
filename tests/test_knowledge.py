"""Knowledge-base hardening pinned by the pre-publication red-team.

Two properties: (1) no red-flag pattern may reintroduce an unbounded gap
(super-linear backtracking on ambient-scribe-length text = a DoS on the safety
layer itself); (2) external-config adoption is atomic — a truncated file must
never leave the module in a hybrid half-adopted state.
"""

import json
import time

from attending import knowledge as K
from attending.encounter import Encounter
from attending.esi import match_red_flags


def test_no_unbounded_gaps_in_red_flag_patterns():
    """Lexicon lint: `.*`/`.+` are banned in RED_FLAGS; use bounded `.{0,N}`."""
    offenders = [
        (rf["id"], pat)
        for rf in K.RED_FLAGS
        for pat in rf["patterns"]
        if ".*" in pat or ".+" in pat
    ]
    assert not offenders, f"unbounded gaps reintroduced: {offenders}"


def test_red_flag_matching_is_fast_on_pathological_text():
    # 156 KB of the ReDoS trigger prefix; pre-fix this took ~9 s per pattern.
    enc = Encounter("T", "pregnan " * 20_000, age_years=30)
    t0 = time.perf_counter()
    match_red_flags(enc)
    assert time.perf_counter() - t0 < 1.0


def test_adopt_is_atomic_on_truncated_config(tmp_path):
    """A version-matched but truncated config must change NOTHING."""
    before_adult = dict(K.DANGER_ZONE_ADULT)
    before_status = K.APPROVAL_STATUS
    truncated = {
        "ruleset_version": K.RULESET_VERSION,
        "approval_status": "HOSTILE",
        "danger_zone_adult": {"hr_gt": 99999, "rr_gt": 99999, "spo2_lt": 0},
        # every later key missing -> staging must raise before any assignment
    }
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(truncated))
    assert K._load_external(path) is False
    assert K.DANGER_ZONE_ADULT == before_adult
    assert K.APPROVAL_STATUS == before_status


def test_stale_version_config_is_ignored(tmp_path):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps({"ruleset_version": "esi-v0-ancient"}))
    assert K._load_external(path) is False


def test_malformed_config_is_ignored(tmp_path):
    path = tmp_path / "knowledge.json"
    path.write_text("{not json")
    assert K._load_external(path) is False
