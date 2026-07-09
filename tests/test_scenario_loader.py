"""Scenario loader contract (TDD red phase for INV-J + INV-G full-run hash).

Scenario files are the only data that enters the demo. Two rules:
1. Every file must ATTEST synthetic provenance ("synthetic": true). Absence
   of real PHI is not a vibe — it is a validated, machine-checked property.
2. Patient payloads must not carry identifier-shaped keys at all. A synthetic
   MRN still teaches the pipeline to pass MRNs around.
"""

import hashlib
import json

import pytest

from sitrep.replay import Replayer, load_scenario

GOOD = {
    "synthetic": True,
    "events": [
        {"t": 0, "kind": "adt_arrival",
         "patient": {"age": 52, "sex": "M", "chief_complaint": "chest pain"}},
        {"t": 4, "kind": "order_placed",
         "order": {"id": "ord-ecg", "name": "ECG 12-lead", "status": "completed"}},
    ],
}


def write(tmp_path, payload):
    p = tmp_path / "scenario.json"
    p.write_text(json.dumps(payload))
    return p


# ---------------------------------------------------------------- INV-J
class TestSyntheticAttestation:
    def test_valid_scenario_loads(self, tmp_path):
        events = load_scenario(write(tmp_path, GOOD))
        assert len(events) == 2

    def test_missing_attestation_rejected(self, tmp_path):
        bad = {"events": GOOD["events"]}
        with pytest.raises(ValueError, match="synthetic"):
            load_scenario(write(tmp_path, bad))

    def test_false_attestation_rejected(self, tmp_path):
        bad = {"synthetic": False, "events": GOOD["events"]}
        with pytest.raises(ValueError, match="synthetic"):
            load_scenario(write(tmp_path, bad))

    @pytest.mark.parametrize("key", ["name", "mrn", "dob", "ssn", "phone", "address"])
    def test_identifier_shaped_keys_rejected(self, tmp_path, key):
        bad = json.loads(json.dumps(GOOD))
        bad["events"][0]["patient"][key] = "anything"
        with pytest.raises(ValueError, match=key):
            load_scenario(write(tmp_path, bad))

    def test_bare_event_list_rejected(self, tmp_path):
        """The old format — a naked list — must no longer load. Attestation
        cannot be optional or every legacy file silently bypasses INV-J."""
        with pytest.raises(ValueError):
            load_scenario(write(tmp_path, GOOD["events"]))


# ---------------------------------------------------------------- INV-G
class TestFullRunDeterminism:
    def test_two_full_replays_hash_identically(self, tmp_path):
        path = write(tmp_path, GOOD)

        def run() -> str:
            rp = Replayer(load_scenario(path))
            rp.advance_to_end()
            blob = json.dumps(rp.state.snapshot(), sort_keys=True)
            return hashlib.sha256(blob.encode()).hexdigest()

        assert run() == run()

    def test_shuffled_event_file_yields_same_state(self, tmp_path):
        """On-disk ordering is presentation; `t` is truth."""
        shuffled = json.loads(json.dumps(GOOD))
        shuffled["events"] = list(reversed(shuffled["events"]))
        a = Replayer(load_scenario(write(tmp_path, GOOD)))
        b = Replayer(load_scenario(write(tmp_path, shuffled)))
        a.advance_to_end()
        b.advance_to_end()
        assert (json.dumps(a.state.snapshot(), sort_keys=True)
                == json.dumps(b.state.snapshot(), sort_keys=True))
