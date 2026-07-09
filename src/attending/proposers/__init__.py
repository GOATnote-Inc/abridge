"""Proposing agents that Attending can supervise.

Attending is the screener, never the performer: modules in this package
adapt *external* proposing agents (e.g. HealthCraft's TriageAgent) into
the ``ProposedTriage`` shape that ``attending.supervise`` grades.

Import discipline: nothing here may hard-depend on an external agent at
import time. Heavy/optional dependencies (healthcraft) are imported
lazily inside functions, so ``import attending.proposers.healthcraft``
always succeeds and raises a clear error only when the external agent
is actually invoked.
"""

from .healthcraft import (
    FakeReasonerProposer,
    HealthcraftUnavailable,
    propose_from_plan,
    propose_with_healthcraft,
)

__all__ = [
    "FakeReasonerProposer",
    "HealthcraftUnavailable",
    "propose_from_plan",
    "propose_with_healthcraft",
]
