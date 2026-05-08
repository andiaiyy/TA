"""Tests for RF Paper A pipeline."""
import pytest
import json
import numpy as np
import pandas as pd
from contracts.pipeline_contracts import PipelineInput
from contracts.dataset_schemas import CICIDS2017_SCHEMA
from pipelines.cicids2017.rf_paper_a import RFPaperAPipeline


@pytest.fixture
def synthetic_cicids_df():
    np.random.seed(42)
    n = 200
    feature_cols = [c for c in CICIDS2017_SCHEMA["expected_columns"] if c != "Label"]
    data = {col: np.random.randn(n) for col in feature_cols}
    data["Flow Bytes/s"][0] = np.inf
    data["Flow Bytes/s"][1] = -np.inf
    data["Flow Packets/s"][2] = np.inf
    data["Flow Bytes/s"][3] = np.nan
    data["Label"] = ["BENIGN"] * 100 + ["DDoS"] * 100
    return pd.DataFrame(data)


@pytest.fixture
def pipeline_result(synthetic_cicids_df):
    pipeline = RFPaperAPipeline()
    inp = PipelineInput(df=synthetic_cicids_df, label_column="Label", dataset_type="CICIDS2017")
    return pipeline.run(inp)


def test_returns_result(pipeline_result):
    assert pipeline_result.accuracy >= 0.0
    assert pipeline_result.precision >= 0.0


def test_confusion_matrix_shape(pipeline_result):
    assert len(pipeline_result.confusion_matrix) == 2
    assert len(pipeline_result.confusion_matrix[0]) == 2


def test_feature_selection_count(pipeline_result):
    assert len(pipeline_result.feature_names) == 8


def test_label_mapping(pipeline_result):
    assert "BENIGN" in pipeline_result.label_mapping
    assert "DDoS" in pipeline_result.label_mapping


def test_model_not_none(pipeline_result):
    assert pipeline_result.model is not None


def test_get_info():
    info = RFPaperAPipeline().get_info()
    for key in ["paper", "algorithm", "preprocessing_steps", "feature_selection", "fixed_params", "train_test_split"]:
        assert key in info


def test_reproducibility(synthetic_cicids_df):
    pipeline = RFPaperAPipeline()
    r1 = pipeline.run(PipelineInput(df=synthetic_cicids_df.copy(), label_column="Label", dataset_type="CICIDS2017"))
    r2 = pipeline.run(PipelineInput(df=synthetic_cicids_df.copy(), label_column="Label", dataset_type="CICIDS2017"))
    assert r1.accuracy == r2.accuracy
    assert r1.f1_score == r2.f1_score
    assert r1.feature_names == r2.feature_names


def test_extra_info_keys(pipeline_result):
    for key in ["roc_auc", "roc_curve", "feature_importance", "classification_report", "learning_curve"]:
        assert key in pipeline_result.extra_info


def test_roc_auc_valid(pipeline_result):
    assert 0.0 <= pipeline_result.extra_info["roc_auc"] <= 1.0


def test_roc_curve_shape(pipeline_result):
    roc = pipeline_result.extra_info["roc_curve"]
    assert len(roc["fpr"]) == len(roc["tpr"])


def test_feature_importance_count(pipeline_result):
    fi = pipeline_result.extra_info["feature_importance"]
    assert len(fi) == 8
    assert all("feature" in item and "importance" in item for item in fi)


def test_feature_importance_sorted(pipeline_result):
    importances = [item["importance"] for item in pipeline_result.extra_info["feature_importance"]]
    assert importances == sorted(importances, reverse=True)


def test_classification_report(pipeline_result):
    report = pipeline_result.extra_info["classification_report"]
    assert "BENIGN" in report
    assert "DDoS" in report
    assert "weighted avg" in report


def test_learning_curve(pipeline_result):
    lc = pipeline_result.extra_info["learning_curve"]
    if "error" not in lc:
        assert len(lc["train_sizes"]) == 5


def test_extra_info_json_serializable(pipeline_result):
    json.dumps(pipeline_result.extra_info, default=str)
