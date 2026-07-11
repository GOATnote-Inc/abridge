"""Failure-mode detectors.

Brandon's four named weaknesses -- incomplete audio, transcription error,
anchoring bias, hallucination -- each get a deterministic, program-aided
detector here (no API key required to run). The two that benefit from language
understanding (anchoring re-read, free-text hallucination) expose an
`llm_augment` hook that a screener-model pass can call to sharpen recall; the
deterministic layer is the always-on floor.
"""

from __future__ import annotations

from ..encounter import Encounter, ProposedTriage
from ..esi import EsiAssessment
from ..verdict import Detection
from .anchoring_bias import detect_anchoring
from .hallucination import detect_hallucination
from .incomplete_audio import detect_incomplete_audio
from .transcription_error import detect_transcription_error


def run_all(
    enc: Encounter, proposed: ProposedTriage, assessment: EsiAssessment
) -> list[Detection]:
    # LLM augmentation is opt-in and additive; hooks are None unless
    # ATTENDING_LLM_AUGMENT is set and a key/SDK is available (see llm.py).
    from .. import llm
    anchor_hook = llm.anchoring_hook()
    halluc_hook = llm.hallucination_hook()
    return [
        detect_incomplete_audio(enc),
        detect_transcription_error(enc),
        detect_anchoring(enc, proposed, assessment, llm_augment=anchor_hook),
        detect_hallucination(enc, proposed, llm_augment=halluc_hook),
    ]
