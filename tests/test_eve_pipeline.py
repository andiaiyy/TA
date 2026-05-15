"""
Integration tests for EVE/Suricata pipeline wrappers.

These tests run the FULL 9-phase preprocessing chain — expect several minutes
per test, not seconds. All tests are skipped when the EVE dataset is absent.

Expected dataset: storage/datasets/eve_100k.json  (NDJSON, one object per line)
"""
import json as _json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts.pipeline_contracts import PipelineInput

_EVE_PATH = Path("storage/datasets/eve_100k.json")
_MIN_RECORDS = 500   # minimum viable record count for Phase 1 to produce both classes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def small_eve_ndjson(tmp_path_factory):
    """
    Write the first 2000 valid NDJSON records to a temp file.
    Scoped to session so all tests share one preprocessing run.
    Skips if the dataset is not present.
    """
    if not _EVE_PATH.exists():
        pytest.skip(f"EVE dataset not found at {_EVE_PATH}")

    records = []
    with open(_EVE_PATH, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except Exception:
                continue
            if len(records) >= 2000:
                break

    if len(records) < _MIN_RECORDS:
        pytest.skip(f"EVE dataset has fewer than {_MIN_RECORDS} valid records")

    out = tmp_path_factory.mktemp("eve") / "eve_small.json"
    with open(out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(_json.dumps(rec) + "\n")

    return str(out)


@pytest.fixture(scope="session")
def eve_input(small_eve_ndjson, tmp_path_factory):
    """PipelineInput with dataset_path pointing to small NDJSON fixture."""
    import config.settings as _s
    _s.BASE_DIR = str(tmp_path_factory.getbasetemp().parent)
    return PipelineInput(
        df=pd.DataFrame({"_placeholder": [1]}),
        label_column="Target",
        dataset_type="EVE_SURICATA",
        dataset_path=small_eve_ndjson,
    )


# ---------------------------------------------------------------------------
# Schema / validator tests (fast)
# ---------------------------------------------------------------------------

def test_eve_schema_registered():
    from contracts.dataset_schemas import get_schema
    schema = get_schema("EVE_SURICATA")
    assert schema is not None
    assert schema["label_column"] == "Target"
    assert schema["file_format"] == "json_or_csv"
    assert "expected_top_level_keys" in schema


def test_eve_pipelines_in_registry():
    from config.pipeline_registry import PIPELINE_REGISTRY
    for pid in ("eve_suricata.rfc", "eve_suricata.dt", "eve_suricata.knn", "eve_suricata.xgb"):
        assert pid in PIPELINE_REGISTRY
        assert PIPELINE_REGISTRY[pid]["dataset_type"] == "EVE_SURICATA"


def test_rfc_get_info():
    from pipelines.eve_suricata.rfc_pipeline import EveRFCPipeline
    info = EveRFCPipeline().get_info()
    assert "paper" in info
    assert "algorithm" in info
    assert "preprocessing_steps" in info
    assert len(info["preprocessing_steps"]) >= 5


def test_dt_get_info():
    from pipelines.eve_suricata.dt_pipeline import EveDTPipeline
    info = EveDTPipeline().get_info()
    assert info["algorithm"] == "Decision Tree"


def test_knn_get_info():
    from pipelines.eve_suricata.knn_pipeline import EveKNNPipeline
    info = EveKNNPipeline().get_info()
    assert info["algorithm"] == "K-Nearest Neighbors"
    assert "scaler" in info.get("fixed_params", {})


def test_xgb_get_info():
    pytest.importorskip("xgboost", reason="xgboost not installed")
    from pipelines.eve_suricata.xgb_pipeline import EveXGBPipeline
    info = EveXGBPipeline().get_info()
    assert info["algorithm"] == "XGBoost"


# ---------------------------------------------------------------------------
# parse_dataset + validator tests (need fixture file)
# ---------------------------------------------------------------------------

def test_parse_ndjson(small_eve_ndjson, tmp_path, monkeypatch):
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(Path(small_eve_ndjson).parent.parent))
    from orchestrator.dataset_parser import parse_dataset
    df = parse_dataset(small_eve_ndjson)
    assert len(df) > 0
    assert any(c.startswith("src_ip") or c == "src_ip" for c in df.columns)


def test_validate_eve_dataset(small_eve_ndjson, tmp_path, monkeypatch):
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", str(Path(small_eve_ndjson).parent.parent))
    from orchestrator.dataset_parser import parse_dataset
    from orchestrator.validator import validate_dataset
    df = parse_dataset(small_eve_ndjson)
    result = validate_dataset(df, "EVE_SURICATA")
    assert result.is_valid, f"Validation failed: {result.errors}"
    assert result.label_column == "Target"


# ---------------------------------------------------------------------------
# Pipeline integration tests (slow — full phase chain)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_rfc_pipeline_runs(eve_input):
    from pipelines.eve_suricata.rfc_pipeline import EveRFCPipeline
    result = EveRFCPipeline().run(eve_input)
    assert 0.0 <= result.accuracy <= 1.0
    assert result.model is not None
    assert result.feature_names
    assert "phase_summaries" in result.extra_info
    assert result.confusion_matrix


@pytest.mark.slow
def test_dt_pipeline_runs(eve_input):
    from pipelines.eve_suricata.dt_pipeline import EveDTPipeline
    result = EveDTPipeline().run(eve_input)
    assert 0.0 <= result.accuracy <= 1.0
    assert result.model is not None


@pytest.mark.slow
def test_knn_pipeline_runs(eve_input):
    from pipelines.eve_suricata.knn_pipeline import EveKNNPipeline
    result = EveKNNPipeline().run(eve_input)
    assert 0.0 <= result.accuracy <= 1.0
    assert result.model is not None


@pytest.mark.slow
def test_xgb_pipeline_runs(eve_input):
    pytest.importorskip("xgboost", reason="xgboost not installed")
    from pipelines.eve_suricata.xgb_pipeline import EveXGBPipeline
    result = EveXGBPipeline().run(eve_input)
    assert 0.0 <= result.accuracy <= 1.0


@pytest.mark.slow
def test_rfc_reproducibility(small_eve_ndjson, tmp_path_factory):
    """Same seed + same file → same accuracy."""
    import config.settings as _s
    _s.BASE_DIR = str(tmp_path_factory.getbasetemp().parent)
    inp = PipelineInput(
        df=pd.DataFrame({"_placeholder": [1]}),
        label_column="Target",
        dataset_type="EVE_SURICATA",
        dataset_path=small_eve_ndjson,
    )
    from pipelines.eve_suricata.rfc_pipeline import EveRFCPipeline
    r1 = EveRFCPipeline().run(inp)
    r2 = EveRFCPipeline().run(inp)
    assert r1.accuracy == r2.accuracy
