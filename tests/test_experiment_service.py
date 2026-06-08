"""Integration tests for experiment lifecycle."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch
from contracts.dataset_schemas import HIKARI2021_SCHEMA
from database.db import init_db, get_experiment
from orchestrator.experiment_service import (
    validate_dataset_for_ui, create_and_run_experiment, rerun_experiment,
)
from orchestrator.result_service import list_all_experiments, get_full_experiment


@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # Create minimal valid CSV
    np.random.seed(42)
    n = 100
    feature_cols = [c for c in HIKARI2021_SCHEMA["expected_columns"] if c != "Label"]
    # All features as random numerics; non-numeric / artifact columns named in
    # _common._DROP_COLS will be dropped by the pipeline regardless of dtype.
    data = {col: np.random.randn(n) for col in feature_cols}
    data["Label"] = [0] * 50 + [1] * 50
    df = pd.DataFrame(data)
    csv_path = str(tmp_path / "test.csv")
    df.to_csv(csv_path, index=False)

    import sqlite3
    def _get_conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    with patch("database.db.get_connection", side_effect=_get_conn), \
         patch("utils.artifact_saver.ARTIFACTS_DIR", artifacts_dir), \
         patch("orchestrator.experiment_service.sha256_file", return_value="abc123"), \
         patch("config.settings.BASE_DIR", str(tmp_path)):
        init_db(db_path)
        yield {"db_path": db_path, "artifacts_dir": artifacts_dir, "csv_path": csv_path}


def test_validate_valid(test_env):
    r = validate_dataset_for_ui("HIKARI2021", test_env["csv_path"])
    assert r["success"] is True


def test_validate_missing_file(test_env):
    r = validate_dataset_for_ui("HIKARI2021", "/nonexistent.csv")
    assert r["success"] is False


def test_validate_unknown_type(test_env):
    r = validate_dataset_for_ui("FAKE", test_env["csv_path"])
    assert r["success"] is False


def test_create_and_run(test_env):
    r = create_and_run_experiment("HIKARI2021", test_env["csv_path"], "hikari2021.nbgc_pipeline")
    assert r["success"] is True
    assert r["metrics"]["accuracy"] >= 0.0


def test_experiment_in_db(test_env):
    r = create_and_run_experiment("HIKARI2021", test_env["csv_path"], "hikari2021.nbgc_pipeline")
    exp = get_experiment(r["experiment_id"], test_env["db_path"])
    assert exp["status"] == "FINISHED"


def test_artifacts_saved(test_env):
    r = create_and_run_experiment("HIKARI2021", test_env["csv_path"], "hikari2021.nbgc_pipeline")
    d = test_env["artifacts_dir"] / r["experiment_id"]
    assert (d / "model.pkl").exists()
    assert (d / "metrics.json").exists()


def test_invalid_pipeline(test_env):
    r = create_and_run_experiment("HIKARI2021", test_env["csv_path"], "fake.pipeline")
    assert r["success"] is False


def test_rerun(test_env):
    orig = create_and_run_experiment("HIKARI2021", test_env["csv_path"], "hikari2021.nbgc_pipeline")
    rerun = rerun_experiment(orig["experiment_id"])
    assert rerun["success"] is True
    assert rerun["experiment_id"] != orig["experiment_id"]


def test_rerun_nonexistent(test_env):
    r = rerun_experiment("nonexistent-id")
    assert r["success"] is False
