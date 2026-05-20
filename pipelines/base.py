"""
Abstract base class for all research pipelines.

Rules: No database imports. No UI imports. No side effects beyond computation.
Must be fully deterministic given same input + random_state.
"""
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

from contracts.pipeline_contracts import PipelineInput, PipelineResult

logger = logging.getLogger(__name__)

# Type alias for the optional progress callback. The callback receives a
# short human-readable stage label (e.g. "Training"). Pipelines invoke it
# at coarse boundaries between existing steps; it is purely informational.
ProgressCallback = Callable[[str], None]


class BasePipeline(ABC):

    @abstractmethod
    def run(
        self,
        pipeline_input: PipelineInput,
        progress: Optional[ProgressCallback] = None,
    ) -> PipelineResult:
        """Execute full pipeline: preprocess → train → evaluate → return.

        ``progress`` is an optional callback. When provided, pipelines may
        invoke it with a short stage label between existing steps. It must
        have NO effect on results — pipelines run identically with
        ``progress=None`` (default) and ``progress=<callable>``. Failures
        inside the callback must never propagate; use ``_emit_progress``.
        """

    @abstractmethod
    def get_info(self) -> dict:
        """Return static metadata: paper, algorithm, preprocessing_steps, feature_selection, fixed_params, train_test_split."""
        pass

    @staticmethod
    def _emit_progress(progress: Optional[ProgressCallback], stage: str) -> None:
        """Best-effort progress emission. Swallows all exceptions.

        Progress reporting is purely informational; a broken callback must
        never crash a running pipeline or change its result.
        """
        logger.info("[DIAG] pipeline _emit_progress stage=%s callback_is_none=%s", stage, progress is None)
        if progress is None:
            return
        try:
            progress(stage)
        except Exception:
            logger.exception("Progress callback failed for stage=%r — continuing", stage)
