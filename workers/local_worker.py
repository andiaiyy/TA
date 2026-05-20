"""
Local synchronous worker. Phase 1 executor (Weeks 1-6).
No database access. No UI imports.
"""
from typing import Callable, Optional

from contracts.pipeline_contracts import PipelineInput, PipelineResult


def run_pipeline(
    pipeline,
    pipeline_input: PipelineInput,
    progress: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """Execute a pipeline and return its result.

    ``progress`` is forwarded verbatim to ``pipeline.run``. When None
    (default — sync/test path) the pipeline runs identically to before.
    """
    return pipeline.run(pipeline_input, progress=progress)
