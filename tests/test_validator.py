"""Tests for validator.py."""
import pytest
import pandas as pd

from contracts.dataset_schemas import CICIDS2017_SCHEMA
from orchestrator.validator import validate_dataset


def _make_df(columns, n_rows=10):
    """Helper: create DataFrame with given columns."""
    import numpy as np
    np.random.seed(42)
    data = {col: np.random.randn(n_rows) for col in columns if col != "Label"}
    if "Label" in columns:
        data["Label"] = ["BENIGN"] * (n_rows // 2) + ["DDoS"] * (n_rows - n_rows // 2)
    return pd.DataFrame(data)


def test_validate_valid_cicids2017():
    df = _make_df(CICIDS2017_SCHEMA["expected_columns"])
    result = validate_dataset(df, "CICIDS2017")
    assert result.is_valid is True
    assert result.missing_columns == []
    assert "BENIGN" in result.unique_labels


def test_validate_missing_columns():
    cols = [c for c in CICIDS2017_SCHEMA["expected_columns"] if c not in ["Flow Duration", "Label"]]
    df = _make_df(cols)
    result = validate_dataset(df, "CICIDS2017")
    assert result.is_valid is False
    assert "Flow Duration" in result.missing_columns


def test_validate_extra_columns_allowed():
    cols = CICIDS2017_SCHEMA["expected_columns"] + ["bonus_col"]
    df = _make_df(cols)
    result = validate_dataset(df, "CICIDS2017")
    assert result.is_valid is True
    assert "bonus_col" in result.extra_columns


def test_validate_unknown_dataset_type():
    df = _make_df(["A", "B"])
    result = validate_dataset(df, "FAKE_DATASET")
    assert result.is_valid is False
    assert any("Unknown" in e or "unknown" in e for e in result.errors)


def test_validate_empty_dataframe():
    cols = CICIDS2017_SCHEMA["expected_columns"]
    df = pd.DataFrame(columns=cols)
    result = validate_dataset(df, "CICIDS2017")
    assert result.is_valid is False
    assert any("empty" in e.lower() for e in result.errors)
