"""Tests for execution_service — no DB needed."""
import pytest
import numpy as np
import pandas as pd
from contracts.dataset_schemas import HIKARI2021_SCHEMA
from orchestrator.execution_service import execute_pipeline, get_pipeline_info


@pytest.fixture
def valid_hikari_df():
    np.random.seed(42)
    n = 100
    feature_cols = [c for c in HIKARI2021_SCHEMA["expected_columns"] if c != "Label"]
    # All features as random numerics; non-numeric / artifact columns named in
    # _common._DROP_COLS will be dropped by the pipeline regardless of dtype.
    data = {col: np.random.randn(n) for col in feature_cols}
    data["Label"] = [0] * 50 + [1] * 50
    return pd.DataFrame(data)


def test_execute_success(valid_hikari_df):
    result = execute_pipeline("hikari2021.nbgc_pipeline", valid_hikari_df, "HIKARI2021")
    assert result.accuracy >= 0.0
    assert result.model is not None


def test_execute_unknown_pipeline(valid_hikari_df):
    with pytest.raises(ValueError):
        execute_pipeline("fake.pipeline", valid_hikari_df, "HIKARI2021")


def test_get_pipeline_info():
    info = get_pipeline_info("hikari2021.nbgc_pipeline")
    assert info is not None and "paper" in info


def test_get_pipeline_info_not_found():
    assert get_pipeline_info("fake") is None
