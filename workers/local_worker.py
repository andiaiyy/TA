"""
Local synchronous worker.

Executes a pipeline synchronously in the current process. Captures all
stdout printed by the pipeline (phase headers, progress lines) into a
single string and attaches it to ``PipelineResult.extra_info["process_log"]``
so the UI can show it in a "Process Log" expander after completion.

Rules: no database access, no UI imports.
"""
import io
import sys
from contextlib import redirect_stdout
from typing import Callable, Optional

from contracts.pipeline_contracts import PipelineInput, PipelineResult


class _TeeStream:
    """Forward writes to both an in-memory buffer and the real stdout.

    Keeping the real stdout alive means phase prints still appear in the
    worker terminal exactly as before — the capture is purely additive.
    """

    def __init__(self, buffer: io.StringIO, real_stdout) -> None:
        self._buffer = buffer
        self._real = real_stdout

    def write(self, text: str) -> int:
        self._buffer.write(text)
        try:
            return self._real.write(text)
        except Exception:
            # Some sinks (pytest capture, Streamlit) may raise mid-write;
            # we never want the capture itself to break a pipeline run.
            return len(text)

    def flush(self) -> None:
        self._buffer.flush()
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


def run_pipeline(
    pipeline,
    pipeline_input: PipelineInput,
    progress: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """Execute a pipeline and return its result with captured stdout.

    ``progress`` is forwarded verbatim to ``pipeline.run``. When None
    (default — sync/test path) the pipeline runs identically to before.
    """
    log_buffer = io.StringIO()
    tee = _TeeStream(log_buffer, sys.stdout)

    with redirect_stdout(tee):
        result = pipeline.run(pipeline_input, progress=progress)

    captured = log_buffer.getvalue()
    if captured:
        # extra_info is a dict on PipelineResult; safe to mutate in place.
        result.extra_info["process_log"] = captured

    return result
