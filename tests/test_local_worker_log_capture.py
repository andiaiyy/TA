"""Tests for stdout capture in local_worker.run_pipeline.

The worker wraps pipeline.run() with redirect_stdout so anything the
pipeline prints during execution lands in extra_info["process_log"]
for the UI to display.
"""
from contracts.pipeline_contracts import PipelineInput, PipelineResult
from workers.local_worker import run_pipeline


class _PrintingPipeline:
    """A minimal pipeline stub that prints during run()."""

    def run(self, pipeline_input, progress=None):
        print("PHASE 1: HELLO")
        print("PHASE 2: WORLD")
        if progress is not None:
            progress("test stage")
        return PipelineResult(
            accuracy=0.9, precision=0.9, recall=0.9, f1_score=0.9,
            confusion_matrix=[[1, 0], [0, 1]],
            model=object(),
            feature_names=["a", "b"],
            label_mapping={"X": 0, "Y": 1},
            extra_info={},
        )


def _input():
    import pandas as pd
    return PipelineInput(
        df=pd.DataFrame({"a": [1], "b": [2]}),
        label_column="label",
        dataset_type="TEST",
        dataset_path="",
    )


def test_process_log_captured_into_extra_info():
    result = run_pipeline(_PrintingPipeline(), _input())
    assert "process_log" in result.extra_info
    log = result.extra_info["process_log"]
    assert "PHASE 1: HELLO" in log
    assert "PHASE 2: WORLD" in log


def test_progress_callback_still_forwarded():
    calls = []
    run_pipeline(_PrintingPipeline(), _input(), progress=calls.append)
    assert calls == ["test stage"]


def test_no_log_no_key():
    """A silent pipeline shouldn't pollute extra_info with empty process_log."""

    class _SilentPipeline:
        def run(self, pipeline_input, progress=None):
            return PipelineResult(
                accuracy=0.9, precision=0.9, recall=0.9, f1_score=0.9,
                confusion_matrix=[[1, 0], [0, 1]],
                model=object(),
                feature_names=[],
                label_mapping={},
                extra_info={},
            )

    result = run_pipeline(_SilentPipeline(), _input())
    assert "process_log" not in result.extra_info
