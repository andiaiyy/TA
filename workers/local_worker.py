"""
Local synchronous worker. Phase 1 executor (Weeks 1-6).
No database access. No UI imports.
"""
from contracts.pipeline_contracts import PipelineInput, PipelineResult


def run_pipeline(pipeline, pipeline_input: PipelineInput) -> PipelineResult:
    """Execute a pipeline and return its result."""
    return pipeline.run(pipeline_input)
