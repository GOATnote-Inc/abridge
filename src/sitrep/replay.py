"""Deterministic encounter replayer (F11).

Feeds scripted timelines through the same state machine the live agent will
subscribe to. Pure function of its event list: two replays of the same
fixture produce byte-identical snapshots, which is what makes the demo
rehearsable and the eval reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sitrep.state import Consult, EncounterState, Order, Result

# Keys that identifier-shaped data rides in on. Even synthetic values are
# banned: a fake MRN still teaches the pipeline to pass MRNs around (INV-J).
FORBIDDEN_PATIENT_KEYS = {"name", "mrn", "dob", "ssn", "phone", "address"}


def load_scenario(path: str | Path) -> list[dict[str, Any]]:
    """Load a scenario file, enforcing the INV-J contract:
    top-level object with `"synthetic": true` and an `events` list, and no
    identifier-shaped keys in any patient payload. Bare event lists (the
    legacy format) are rejected so attestation can never be skipped."""
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError(
            "Scenario must be an object with a 'synthetic' attestation, "
            "not a bare event list."
        )
    if payload.get("synthetic") is not True:
        raise ValueError("Scenario missing 'synthetic': true attestation (INV-J).")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("Scenario 'events' must be a list.")
    for event in events:
        patient = event.get("patient")
        if isinstance(patient, dict):
            bad = FORBIDDEN_PATIENT_KEYS & set(patient)
            if bad:
                raise ValueError(
                    f"Identifier-shaped patient key(s) {sorted(bad)} forbidden "
                    f"in scenario files (INV-J)."
                )
    return events


class Replayer:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = sorted(events, key=lambda e: e["t"])
        self.state = EncounterState()
        self.applied: list[dict[str, Any]] = []
        self._cursor = 0

    # -- event application --------------------------------------------------
    def _apply(self, event: dict[str, Any]) -> None:
        kind = event["kind"]
        if kind == "adt_arrival":
            self.state.patient = dict(event["patient"])
        elif kind == "order_placed":
            self.state.add_order(Order(**event["order"]))
        elif kind in ("result_prelim", "result_final"):
            self.state.add_result(Result(**event["result"]))
        elif kind == "result_released":
            self.state.mark_released(event["result_id"])
        elif kind == "patient_viewed_result":
            self.state.mark_viewed(event["result_id"])
        elif kind == "result_discussed":
            self.state.mark_discussed(event["result_id"])
        elif kind == "consult_placed":
            self.state.add_consult(Consult(**event["consult"]))
        elif kind == "consult_response":
            self.state.consults[event["consult_id"]].status = "responded"
        elif kind == "red_flag_utterance":
            self.state.escalate(event["detail"])
        elif kind == "disposition":
            self.state.disposition = event["disposition"]
        else:
            raise ValueError(f"Unknown event kind: {kind}")
        self.applied.append(event)

    # -- advancement ---------------------------------------------------------
    def advance_until(self, kind: str) -> None:
        """Apply events up to and INCLUDING the first event of `kind`."""
        while self._cursor < len(self.events):
            event = self.events[self._cursor]
            self._apply(event)
            self._cursor += 1
            if event["kind"] == kind:
                return
        raise ValueError(f"No event of kind '{kind}' in timeline.")

    def advance_to_end(self) -> None:
        while self._cursor < len(self.events):
            self._apply(self.events[self._cursor])
            self._cursor += 1
