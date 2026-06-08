"""Tests for validator.py."""
import pytest
import pandas as pd

from contracts.dataset_schemas import HIKARI2021_SCHEMA
from orchestrator.validator import validate_dataset


def _make_df(columns, n_rows=10):
    """Helper: create DataFrame with given columns."""
    import numpy as np
    np.random.seed(42)
    data = {col: np.random.randn(n_rows) for col in columns if col != "Label"}
    if "Label" in columns:
        # HIKARI2021 labels are integer 0/1 (Benign / Malicious)
        data["Label"] = [0] * (n_rows // 2) + [1] * (n_rows - n_rows // 2)
    return pd.DataFrame(data)


def test_validate_valid_hikari2021():
    df = _make_df(HIKARI2021_SCHEMA["expected_columns"])
    result = validate_dataset(df, "HIKARI2021")
    assert result.is_valid is True
    assert result.missing_columns == []
    assert 0 in result.unique_labels


def test_validate_missing_columns():
    cols = [c for c in HIKARI2021_SCHEMA["expected_columns"] if c not in ["flow_duration", "Label"]]
    df = _make_df(cols)
    result = validate_dataset(df, "HIKARI2021")
    assert result.is_valid is False
    assert "flow_duration" in result.missing_columns


def test_validate_extra_columns_allowed():
    cols = HIKARI2021_SCHEMA["expected_columns"] + ["bonus_col"]
    df = _make_df(cols)
    result = validate_dataset(df, "HIKARI2021")
    assert result.is_valid is True
    assert "bonus_col" in result.extra_columns


def test_validate_unknown_dataset_type():
    df = _make_df(["A", "B"])
    result = validate_dataset(df, "FAKE_DATASET")
    assert result.is_valid is False
    assert any("Unknown" in e or "unknown" in e for e in result.errors)


def test_validate_empty_dataframe():
    cols = HIKARI2021_SCHEMA["expected_columns"]
    df = pd.DataFrame(columns=cols)
    result = validate_dataset(df, "HIKARI2021")
    assert result.is_valid is False
    assert any("empty" in e.lower() for e in result.errors)
