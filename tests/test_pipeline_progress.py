"""Tests for the optional progress callback on pipeline.run().

The callback contract:
  - Default ``progress=None`` means no progress reporting and a byte-identical
    result to the pre-callback behavior.
  - When supplied, the callback is invoked with short stage labels at
    coarse boundaries between existing steps.
  - Exceptions raised inside the callback MUST be swallowed by
    ``_emit_progress`` so a broken reporter cannot fail the pipeline.
  - Progress reporting MUST NOT change the result (reproducibility).

These tests use the HIKARI DT pipeline as the canonical exemplar because
it is fast, deterministic, and exercises the four-stage labeling pattern.
"""
import numpy as np
import pandas as pd
import pytest

from contracts.dataset_schemas import HIKARI2021_SCHEMA
from contracts.pipeline_contracts import PipelineInput
from pipelines.hikari2021.dt_pipeline import HikariDTPipeline


@pytest.fixture(scope="module")
def synthetic_hikari_df():
    np.random.seed(42)
    n = 400
    all_cols = HIKARI2021_SCHEMA["expected_columns"]
    data: dict = {}
    for col in all_cols:
        if col == "Label":
            data[col] = [0] * 300 + [1] * 100
        elif col == "traffic_category":
            data[col] = ["Benign"] * 300 + ["Bruteforce"] * 100
        elif col in ("uid", "originh", "responh"):
            data[col] = [f"val_{i}" for i in range(n)]
        elif col in ("Unnamed: 0", "Unnamed: 0.1"):
            data[col] = list(range(n))
        else:
            data[col] = np.random.randn(n)
    return pd.DataFrame(data)


def _make_input(df: pd.DataFrame) -> PipelineInput:
    return PipelineInput(df=df.copy(), label_column="Label", dataset_type="HIKARI2021")


def test_default_progress_none_runs(synthetic_hikari_df):
    """progress defaults to None — pipeline must run cleanly."""
    result = HikariDTPipeline().run(_make_input(synthetic_hikari_df))
    assert result.accuracy >= 0.0
    assert result.model is not None


def test_callback_invoked_with_stage_labels(synthetic_hikari_df):
    """When supplied, the callback receives non-empty stage labels at
    least once. Exact stage count and wording are an implementation
    detail of the pipeline, but the contract is: it gets called."""
    stages: list[str] = []
    HikariDTPipeline().run(_make_input(synthetic_hikari_df), progress=stages.append)

    assert len(stages) >= 1, f"Expected at least 1 stage, got {stages}"
    assert all(isinstance(s, str) and s for s in stages), (
        f"All stages must be non-empty strings, got {stages}"
    )


def test_callback_failure_does_not_break_pipeline(synthetic_hikari_df):
    """A callback that raises every time must NOT propagate. The pipeline
    must complete and return a valid PipelineResult."""
    def boom(stage: str) -> None:
        raise RuntimeError(f"reporter broken on stage={stage!r}")

    result = HikariDTPipeline().run(_make_input(synthetic_hikari_df), progress=boom)
    assert result.accuracy >= 0.0
    assert result.model is not None


def test_progress_does_not_change_result(synthetic_hikari_df):
    """Reproducibility invariant: the result with progress=None must
    match the result with a working callback exactly. The callback is
    purely informational and must not influence any computation."""
    base = HikariDTPipeline().run(_make_input(synthetic_hikari_df))
    with_progress = HikariDTPipeline().run(
        _make_input(synthetic_hikari_df), progress=lambda _s: None,
    )

    assert base.accuracy == with_progress.accuracy
    assert base.precision == with_progress.precision
    assert base.recall == with_progress.recall
    assert base.f1_score == with_progress.f1_score
    assert base.confusion_matrix == with_progress.confusion_matrix
    assert base.feature_names == with_progress.feature_names
    assert base.label_mapping == with_progress.label_mapping


def test_progress_with_failing_callback_matches_baseline(synthetic_hikari_df):
    """Even when the callback raises on every call, the result must be
    identical to the no-callback baseline. Errors inside the reporter
    cannot perturb the ML computation."""
    base = HikariDTPipeline().run(_make_input(synthetic_hikari_df))

    def boom(_s: str) -> None:
        raise RuntimeError("nope")

    broken = HikariDTPipeline().run(_make_input(synthetic_hikari_df), progress=boom)

    assert base.accuracy == broken.accuracy
    assert base.confusion_matrix == broken.confusion_matrix
