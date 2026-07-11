"""Attending -- a fail-closed supervising layer for clinical triage agents.

Reviews every action a triage agent proposes, blocks the unsafe ones, and cites
the exact ED safety criterion tripped. Built on top of HealthCraft
(Apache 2.0, arXiv:2605.21496).
"""

from .encounter import Encounter, ProposedTriage, Vitals
from .supervisor import supervise
from .verdict import Decision, Verdict

__version__ = "0.2.1"
__all__ = ["Encounter", "ProposedTriage", "Vitals", "supervise", "Decision",
           "Verdict"]
