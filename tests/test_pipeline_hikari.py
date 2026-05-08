"""Tests for HIKARI2021 RFC pipeline."""
import pytest
import json
import numpy as np
import pandas as pd
from contracts.pipeline_contracts import PipelineInput
from contracts.dataset_schemas import HIKARI2021_SCHEMA
from pipelines.hikari2021.rfc_pipeline import HikariRFCPipeline


@pytest.fixture
def synthetic_hikari_df():
    """
    Synthetic DataFrame mimicking HIKARI2021 structure.
    400 rows: 300 benign (0), 100 malicious (1) — imbalanced like real data.
    Includes the artifact/identifier columns that should be dropped.
    """
    np.random.seed(42)
    n = 400
    all_cols = HIKARI2021_SCHEMA["expected_columns"]

    data = {}
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


@pytest.fixture
def pipeline_result(synthetic_hikari_df):
    pipeline = HikariRFCPipeline()
    inp = PipelineInput(df=synthetic_hikari_df, label_column="Label", dataset_type="HIKARI2021")
    return pipeline.run(inp)


def test_returns_result(pipeline_result):
    assert pipeline_result.accuracy >= 0.0
    assert pipeline_result.precision >= 0.0


def test_confusion_matrix_shape(pipeline_result):
    assert len(pipeline_result.confusion_matrix) == 2
    assert len(pipeline_result.confusion_matrix[0]) == 2


def test_label_mapping(pipeline_result):
    assert 0 in pipeline_result.label_mapping
    assert 1 in pipeline_result.label_mapping


def test_model_not_none(pipeline_result):
    assert pipeline_result.model is not None


def test_feature_names_no_dropped_cols(pipeline_result):
    """Dropped columns should not appear in feature_names."""
    dropped = ["Unnamed: 0.1", "Unnamed: 0", "uid", "originh", "responh", "traffic_category"]
    for col in dropped:
        assert col not in pipeline_result.feature_names


def test_get_info():
    info = HikariRFCPipeline().get_info()
    for key in ["paper", "algorithm", "preprocessing_steps", "feature_selection", "fixed_params"]:
        assert key in info


def test_reproducibility(synthetic_hikari_df):
    pipeline = HikariRFCPipeline()
    r1 = pipeline.run(PipelineInput(df=synthetic_hikari_df.copy(), label_column="Label", dataset_type="HIKARI2021"))
    r2 = pipeline.run(PipelineInput(df=synthetic_hikari_df.copy(), label_column="Label", dataset_type="HIKARI2021"))
    assert r1.accuracy == r2.accuracy
    assert r1.f1_score == r2.f1_score


def test_extra_info_keys(pipeline_result):
    for key in ["roc_auc", "roc_curve", "feature_importance", "classification_report"]:
        assert key in pipeline_result.extra_info


def test_roc_auc_valid(pipeline_result):
    assert 0.0 <= pipeline_result.extra_info["roc_auc"] <= 1.0


def test_classification_report_classes(pipeline_result):
    report = pipeline_result.extra_info["classification_report"]
    assert "Benign" in report
    assert "Malicious" in report


def test_feature_importance_sorted(pipeline_result):
    fi = pipeline_result.extra_info["feature_importance"]
    importances = [item["importance"] for item in fi]
    assert importances == sorted(importances, reverse=True)


def test_json_serializable(pipeline_result):
    json.dumps(pipeline_result.extra_info, default=str)
