"""Tests for execution_service — no DB needed."""
import pytest
import numpy as np
import pandas as pd
from contracts.dataset_schemas import CICIDS2017_SCHEMA
from orchestrator.execution_service import execute_pipeline, get_pipeline_info


@pytest.fixture
def valid_cicids_df():
    np.random.seed(42)
    n = 100
    feature_cols = [c for c in CICIDS2017_SCHEMA["expected_columns"] if c != "Label"]
    data = {col: np.random.randn(n) for col in feature_cols}
    data["Label"] = ["BENIGN"] * 50 + ["DDoS"] * 50
    return pd.DataFrame(data)


def test_execute_success(valid_cicids_df):
    result = execute_pipeline("cicids2017.rf_paper_a", valid_cicids_df, "CICIDS2017")
    assert result.accuracy >= 0.0
    assert result.model is not None


def test_execute_unknown_pipeline(valid_cicids_df):
    with pytest.raises(ValueError):
        execute_pipeline("fake.pipeline", valid_cicids_df, "CICIDS2017")


def test_get_pipeline_info():
    info = get_pipeline_info("cicids2017.rf_paper_a")
    assert info is not None and "paper" in info


def test_get_pipeline_info_not_found():
    assert get_pipeline_info("fake") is None
