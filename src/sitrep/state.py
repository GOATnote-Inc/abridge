"""Encounter state: the single source of truth all four panes render from.

Design constraints (see INVERSION.md):
- Escalations are MONOTONIC. There is deliberately no method to clear them (F6).
- Results carry the full disclosure lifecycle: released -> viewed -> discussed.
  The gap between `viewed` and `discussed` on a critical result is the
  patient-safety hole this system instruments (F3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Order:
    id: str
    name: str
    status: str = "in-progress"  # in-progress | completed | cancelled


@dataclass
class Result:
    id: str
    order_id: str
    name: str
    value: str = ""
    flag: str = "pending"        # pending | normal | abnormal | critical
    status: str = "preliminary"  # preliminary | final | amended
    released: bool = False
    viewed: bool = False
    discussed: bool = False


@dataclass
class Consult:
    id: str
    service: str
    status: str = "pending"      # pending | responded


@dataclass
class Escalation:
    reason: str


class EncounterState:
    def __init__(self, patient: dict[str, Any] | None = None) -> None:
        self.patient: dict[str, Any] = patient or {}
        self.orders: dict[str, Order] = {}
        self.results: dict[str, Result] = {}
        self.consults: dict[str, Consult] = {}
        self.escalations: list[Escalation] = []
        self.alerts: list[str] = []
        self.disposition: str | None = None

    # -- mutations ---------------------------------------------------------
    def add_order(self, order: Order) -> None:
        self.orders[order.id] = order

    def add_result(self, result: Result) -> None:
        if result.order_id not in self.orders:
            raise ValueError(
                f"Orphan result '{result.id}' references unknown order "
                f"'{result.order_id}' — rejecting at ingestion (INV-H). "
                f"A result without an order is corruption, not data."
            )
        self.results[result.id] = result
        if result.status == "final":
            self.orders[result.order_id].status = "completed"

    def add_consult(self, consult: Consult) -> None:
        self.consults[consult.id] = consult

    def mark_released(self, result_id: str) -> None:
        self.results[result_id].released = True

    def mark_viewed(self, result_id: str) -> None:
        self.results[result_id].viewed = True

    def mark_discussed(self, result_id: str) -> None:
        self.results[result_id].discussed = True

    def escalate(self, reason: str) -> None:
        """Monotonic by construction: append-only, no clear method exists."""
        self.escalations.append(Escalation(reason=reason))

    # -- introspection ------------------------------------------------------
    def known_ids(self) -> set[str]:
        return set(self.orders) | set(self.results) | set(self.consults)

    def entity_names(self) -> dict[str, str]:
        """Map of chart entity id -> display name, for grounding checks."""
        names: dict[str, str] = {}
        for o in self.orders.values():
            names[o.id] = o.name
        for r in self.results.values():
            names[r.id] = r.name
        for c in self.consults.values():
            names[c.id] = c.service
        return names

    def refs_for_name(self, name: str) -> set[str]:
        """All ids whose entity carries this display name (order + its result)."""
        ids = {i for i, n in self.entity_names().items() if n.lower() == name.lower()}
        for r in self.results.values():
            if r.name.lower() == name.lower():
                ids.add(r.order_id)
        return ids

    def snapshot(self) -> dict[str, Any]:
        """Pure, order-stable serialization — determinism contract for F11."""
        return {
            "patient": dict(sorted(self.patient.items())),
            "orders": {k: vars(v) for k, v in sorted(self.orders.items())},
            "results": {k: vars(v) for k, v in sorted(self.results.items())},
            "consults": {k: vars(v) for k, v in sorted(self.consults.items())},
            "escalations": [vars(e) for e in self.escalations],
            "alerts": list(self.alerts),
            "disposition": self.disposition,
        }
