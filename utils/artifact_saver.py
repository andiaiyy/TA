"""
Artifact saving utilities.

Saves to storage/artifacts/{experiment_id}/:
  - model.pkl (joblib)
  - metrics.json (accuracy, precision, recall, f1, confusion_matrix, extra_info)
  - metadata.json (dataset_hash, pipeline_id, timestamps, etc.)

Rules: No database access. No UI imports. Returns ABSOLUTE paths so consumers
(UI process, Celery worker, PDF generator) can open the files regardless of CWD.
"""
import json
import joblib
from pathlib import Path
from config.settings import ARTIFACTS_DIR


def get_artifact_dir(experiment_id: str) -> Path:
    """Return artifact dir for an experiment, creating if needed."""
    d = ARTIFACTS_DIR / experiment_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_model(experiment_id: str, model: object) -> str:
    """Save model using joblib serialization as model.pkl. Returns absolute path."""
    d = get_artifact_dir(experiment_id)
    path = d / "model.pkl"
    joblib.dump(model, path)
    return str(path.resolve())


def save_metrics(experiment_id: str, metrics: dict) -> str:
    """Save metrics as JSON. Returns absolute path."""
    d = get_artifact_dir(experiment_id)
    path = d / "metrics.json"
    with open(path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    return str(path.resolve())


def save_metadata(experiment_id: str, metadata: dict) -> str:
    """Save metadata as JSON. Returns absolute path."""
    d = get_artifact_dir(experiment_id)
    path = d / "metadata.json"
    with open(path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    return str(path.resolve())


def save_all_artifacts(experiment_id: str, model: object, metrics: dict, metadata: dict) -> dict:
    """Save all artifacts. Adds environment info to metadata without mutating the caller's dict."""
    from config.settings import get_environment_info

    metadata = {**metadata, "environment": get_environment_info()}

    return {
        "model_path": save_model(experiment_id, model),
        "metrics_path": save_metrics(experiment_id, metrics),
        "metadata_path": save_metadata(experiment_id, metadata),
    }


def load_metrics(experiment_id: str) -> dict | None:
    """Load metrics JSON. Returns None if not found."""
    path = ARTIFACTS_DIR / experiment_id / "metrics.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_metadata(experiment_id: str) -> dict | None:
    """Load metadata JSON. Returns None if not found."""
    path = ARTIFACTS_DIR / experiment_id / "metadata.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)
