"""Failure-mode detectors.

Brandon's four named weaknesses -- incomplete audio, transcription error,
anchoring bias, hallucination -- each get a deterministic, program-aided
detector here (no API key required to run). The two that benefit from language
understanding (anchoring re-read, free-text hallucination) expose an
`llm_augment` hook that a screener-model pass can call to sharpen recall; the
deterministic layer is the always-on floor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..encounter import Encounter, ProposedTriage
from ..esi import EsiAssessment
from ..verdict import Detection, Severity
from .anchoring_bias import detect_anchoring
from .hallucination import detect_hallucination
from .incomplete_audio import detect_incomplete_audio
from .transcription_error import detect_transcription_error

logger = logging.getLogger(__name__)

_Hook = Callable[[Encounter, ProposedTriage], "tuple[bool, str, str]"]


def run_all(
    enc: Encounter, proposed: ProposedTriage, assessment: EsiAssessment
) -> list[Detection]:
    # LLM augmentation is opt-in and additive; hooks are None unless
    # ATTENDING_LLM_AUGMENT is set and a key/SDK is available (see llm.py).
    from .. import llm

    failures: list[Detection] = []

    def _guard(name: str, hook: _Hook | None) -> _Hook | None:
        """Record a failing augmentation hook as an INFO detection.

        The deterministic floor still stands (the detectors also catch), but
        an operator who enabled augmentation can now SEE that it stopped —
        the outage is a finding, never a silent no-op.
        """
        if hook is None:
            return None

        def wrapped(e: Encounter, p: ProposedTriage) -> tuple[bool, str, str]:
            try:
                return hook(e, p)
            except Exception as exc:
                failures.append(Detection(
                    "llm_augment", False, Severity.INFO,
                    f"{name} augmentation unavailable "
                    f"({type(exc).__name__}); deterministic floor stands",
                    evidence=str(exc),
                ))
                raise

        return wrapped

    anchor_hook = _guard("anchoring", llm.anchoring_hook())
    halluc_hook = _guard("hallucination", llm.hallucination_hook())
    return [
        detect_incomplete_audio(enc),
        detect_transcription_error(enc),
        detect_anchoring(enc, proposed, assessment, llm_augment=anchor_hook),
        detect_hallucination(enc, proposed, llm_augment=halluc_hook),
        *failures,
    ]
