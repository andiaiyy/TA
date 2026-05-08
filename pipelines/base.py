"""
Abstract base class for all research pipelines.

Rules: No database imports. No UI imports. No side effects beyond computation.
Must be fully deterministic given same input + random_state.
"""
from abc import ABC, abstractmethod
from contracts.pipeline_contracts import PipelineInput, PipelineResult


class BasePipeline(ABC):

    @abstractmethod
    def run(self, pipeline_input: PipelineInput) -> PipelineResult:
        """Execute full pipeline: preprocess → train → evaluate → return."""
        pass

    @abstractmethod
    def get_info(self) -> dict:
        """Return static metadata: paper, algorithm, preprocessing_steps, feature_selection, fixed_params, train_test_split."""
        pass
