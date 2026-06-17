"""
Tests for the EVE/Suricata pipeline family.

The EVE family is now the **cbr 14-phase anti-leakage** pipeline (`eve_cbr.*`).
The legacy 7-phase pipelines (`eve_suricata.*`) were archived (recoverable)
under ``pipelines/_archive/eve_suricata_7phase/`` and are no longer registered.

Schema / parser / validator tests are dataset-format tests and remain.
Full cbr pipeline execution (split TLS → 14 phases → natural-holdout metrics)
needs the full 1M EVE dataset and ~80s; it is covered by the Docker integration
checkpoint (STAGE 4a/4b), not by this fast unit-test module.
"""
import json as _json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts.pipeline_contracts import PipelineInput

# eve_100k.json is a JSON array (not NDJSON); use the line-delimited .ndjson.
_EVE_PATH = Path("storage/datasets/eve_100k.ndjson")
_MIN_RECORDS = 500   # minimum viable record count for both classes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def small_eve_ndjson(tmp_path_factory):
    """First 2000 valid NDJSON records to a temp file; skip if dataset absent."""
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


# ---------------------------------------------------------------------------
# Schema test (fast)
# ---------------------------------------------------------------------------

def test_eve_schema_registered():
    from contracts.dataset_schemas import get_schema
    schema = get_schema("EVE_SURICATA")
    assert schema is not None
    assert schema["label_column"] == "Target"
    assert schema["file_format"] == "json_or_csv"
    assert "expected_top_level_keys" in schema


# ---------------------------------------------------------------------------
# Registry — EVE family is now cbr; 7-phase is archived/unregistered
# ---------------------------------------------------------------------------

def test_eve_cbr_pipelines_in_registry():
    from config.pipeline_registry import PIPELINE_REGISTRY
    for pid in ("eve_cbr.rfc", "eve_cbr.dt", "eve_cbr.lsvc", "eve_cbr.xgb"):
        assert pid in PIPELINE_REGISTRY
        assert PIPELINE_REGISTRY[pid]["dataset_type"] == "EVE_SURICATA"


def test_legacy_7phase_unregistered():
    from config.pipeline_registry import PIPELINE_REGISTRY
    for pid in ("eve_suricata.rfc", "eve_suricata.dt", "eve_suricata.knn", "eve_suricata.xgb"):
        assert pid not in PIPELINE_REGISTRY


def test_registry_composition():
    """Registry is exactly 6 HIKARI + 4 eve_cbr = 10 pipelines."""
    from config.pipeline_registry import PIPELINE_REGISTRY as R
    hikari = [k for k in R if k.startswith("hikari2021.")]
    cbr = [k for k in R if k.startswith("eve_cbr.")]
    suricata = [k for k in R if k.startswith("eve_suricata.")]
    assert len(hikari) == 6
    assert len(cbr) == 4
    assert len(suricata) == 0
    assert len(R) == 10


# ---------------------------------------------------------------------------
# cbr get_info() — metadata honesty
# ---------------------------------------------------------------------------

def test_cbr_rfc_get_info():
    from pipelines.eve_cbr.rfc_pipeline import EveCbrRFCPipeline
    info = EveCbrRFCPipeline().get_info()
    assert info["algorithm"] == "Random Forest"
    assert info["app"] == "TLS"
    assert "anti_leakage" in info
    assert info["fixed_params"]["enforce_row_level_conversion_cap"] is True
    assert info["fixed_params"]["models"] == ["RFC"]


def test_cbr_dt_get_info():
    from pipelines.eve_cbr.dt_pipeline import EveCbrDTPipeline
    assert EveCbrDTPipeline().get_info()["algorithm"] == "Decision Tree"


def test_cbr_lsvc_get_info():
    from pipelines.eve_cbr.lsvc_pipeline import EveCbrLSVCPipeline
    assert EveCbrLSVCPipeline().get_info()["algorithm"] == "Linear SVC"


def test_cbr_xgb_get_info():
    from pipelines.eve_cbr.xgb_pipeline import EveCbrXGBPipeline
    assert EveCbrXGBPipeline().get_info()["algorithm"] == "XGBoost"


def test_cbr_requires_dataset_path():
    """cbr pipelines must reject input without a dataset_path."""
    from pipelines.eve_cbr.rfc_pipeline import EveCbrRFCPipeline
    inp = PipelineInput(
        df=pd.DataFrame({"_placeholder": [1]}),
        label_column="Target",
        dataset_type="EVE_SURICATA",
        dataset_path="",
    )
    with pytest.raises(ValueError):
        EveCbrRFCPipeline().run(inp)


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
