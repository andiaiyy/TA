"""Parameterized tests for all 5 new HIKARI2021 pipelines (DT, KNN, SVC, NBGC, LR)."""
import pytest
import json
import numpy as np
import pandas as pd
from contracts.pipeline_contracts import PipelineInput
from contracts.dataset_schemas import HIKARI2021_SCHEMA
from pipelines.hikari2021.dt_pipeline import HikariDTPipeline
from pipelines.hikari2021.knn_pipeline import HikariKNNPipeline
from pipelines.hikari2021.svc_pipeline import HikariSVCPipeline
from pipelines.hikari2021.nbgc_pipeline import HikariNBGCPipeline
from pipelines.hikari2021.lr_pipeline import HikariLRPipeline


PIPELINE_CLASSES = [
    pytest.param(HikariDTPipeline, id="dt"),
    pytest.param(HikariKNNPipeline, id="knn"),
    pytest.param(HikariSVCPipeline, id="svc"),
    pytest.param(HikariNBGCPipeline, id="nbgc"),
    pytest.param(HikariLRPipeline, id="lr"),
]


@pytest.fixture(scope="session")
def synthetic_hikari_df():
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


@pytest.fixture(scope="session", params=PIPELINE_CLASSES)
def pipeline_result(request, synthetic_hikari_df):
    pipeline = request.param()
    inp = PipelineInput(df=synthetic_hikari_df.copy(), label_column="Label", dataset_type="HIKARI2021")
    return pipeline.run(inp)


# --- Tests using pipeline_result fixture (5 pipelines × 8 functions = 40 tests) ---

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
    dropped = ["Unnamed: 0.1", "Unnamed: 0", "uid", "originh", "responh", "traffic_category"]
    for col in dropped:
        assert col not in pipeline_result.feature_names


def test_extra_info_keys(pipeline_result):
    for key in ["roc_auc", "roc_curve", "feature_importance", "classification_report"]:
        assert key in pipeline_result.extra_info


def test_roc_auc_valid(pipeline_result):
    assert 0.0 <= pipeline_result.extra_info["roc_auc"] <= 1.0


def test_classification_report_classes(pipeline_result):
    report = pipeline_result.extra_info["classification_report"]
    assert "Benign" in report
    assert "Malicious" in report


# --- Tests using @pytest.mark.parametrize (5 pipelines × 2 functions = 10 tests) ---

@pytest.mark.parametrize("pipeline_cls", PIPELINE_CLASSES)
def test_get_info(pipeline_cls):
    info = pipeline_cls().get_info()
    for key in ["paper", "algorithm", "preprocessing_steps", "feature_selection", "fixed_params"]:
        assert key in info


@pytest.mark.parametrize("pipeline_cls", PIPELINE_CLASSES)
def test_reproducibility(pipeline_cls, synthetic_hikari_df):
    r1 = pipeline_cls().run(
        PipelineInput(df=synthetic_hikari_df.copy(), label_column="Label", dataset_type="HIKARI2021")
    )
    r2 = pipeline_cls().run(
        PipelineInput(df=synthetic_hikari_df.copy(), label_column="Label", dataset_type="HIKARI2021")
    )
    assert r1.accuracy == r2.accuracy
    assert r1.f1_score == r2.f1_score
