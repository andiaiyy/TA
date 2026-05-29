"""Tests for artifact saving."""
import pytest
import json
from pathlib import Path
from unittest.mock import patch
from utils.artifact_saver import (
    get_artifact_dir, save_model, save_metrics, save_metadata,
    save_all_artifacts, load_metrics, load_metadata,
)


@pytest.fixture
def mock_artifacts_dir(tmp_path):
    with patch("utils.artifact_saver.ARTIFACTS_DIR", tmp_path):
        yield tmp_path


def test_get_artifact_dir_creates(mock_artifacts_dir):
    d = get_artifact_dir("test-001")
    assert d.exists() and d.is_dir()


def test_save_model(mock_artifacts_dir):
    from sklearn.ensemble import RandomForestClassifier
    m = RandomForestClassifier(n_estimators=10, random_state=42)
    m.fit([[1, 2], [3, 4]], [0, 1])
    path = save_model("test-001", m)
    assert "model.pkl" in path
    assert (mock_artifacts_dir / "test-001" / "model.pkl").exists()


def test_save_metrics(mock_artifacts_dir):
    save_metrics("test-001", {"accuracy": 0.95, "confusion_matrix": [[1, 0], [0, 1]]})
    saved = json.loads((mock_artifacts_dir / "test-001" / "metrics.json").read_text())
    assert saved["accuracy"] == 0.95


def test_save_metadata(mock_artifacts_dir):
    save_metadata("test-001", {"pipeline_id": "rf"})
    saved = json.loads((mock_artifacts_dir / "test-001" / "metadata.json").read_text())
    assert saved["pipeline_id"] == "rf"


def test_save_all_artifacts(mock_artifacts_dir):
    from sklearn.ensemble import RandomForestClassifier
    m = RandomForestClassifier(n_estimators=10, random_state=42)
    m.fit([[1, 2], [3, 4]], [0, 1])
    paths = save_all_artifacts("test-001", m, {"accuracy": 0.9}, {"id": "test-001"})
    assert all(k in paths for k in ["model_path", "metrics_path", "metadata_path"])


def test_load_metrics(mock_artifacts_dir):
    save_metrics("test-001", {"accuracy": 0.95})
    assert load_metrics("test-001")["accuracy"] == 0.95


def test_load_metrics_not_found(mock_artifacts_dir):
    assert load_metrics("nonexistent") is None


def test_returns_absolute_path(mock_artifacts_dir):
    """Saved paths must be absolute so consumers in any CWD can open the file.

    Previously returned a relative path, which broke when UI process and
    Celery worker had different working directories.
    """
    from sklearn.ensemble import RandomForestClassifier
    m = RandomForestClassifier(n_estimators=10, random_state=42)
    m.fit([[1, 2], [3, 4]], [0, 1])
    path = save_model("test-001", m)
    assert Path(path).is_absolute()
