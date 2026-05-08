"""
Experiment service — main facade for UI.

Supports both synchronous and asynchronous execution.
Set USE_ASYNC=true in environment to use Celery; default is sync (no Redis needed).

ONLY orchestrator file that accesses database/.
"""
import logging
import uuid

from config.celery_config import USE_ASYNC

logger = logging.getLogger(__name__)
from orchestrator.validation_service import validate_for_experiment
from orchestrator.execution_service import execute_pipeline
from orchestrator.dataset_parser import parse_dataset
from database.db import (
    create_experiment, set_running, set_finished, set_failed,
    get_experiment, init_db,
)
from utils.hashing import sha256_file
from utils.timestamps import now_iso
from utils.artifact_saver import save_all_artifacts


def validate_dataset_for_ui(dataset_type: str, dataset_path: str) -> dict:
    """Called when user clicks 'Validate Dataset'."""
    return validate_for_experiment(dataset_type, dataset_path)


def create_and_run_experiment(
    dataset_type: str,
    dataset_path: str,
    pipeline_id: str,
) -> dict:
    """
    Create and execute an experiment.

    If USE_ASYNC is True:
      - Creates DB record (QUEUED)
      - Dispatches Celery task
      - Returns immediately with async_mode=True, metrics=None
      - UI must poll get_experiment_status() for completion

    If USE_ASYNC is False (default):
      - Runs synchronously (blocks until done)
      - Returns with metrics populated

    Returns dict with:
        success: bool
        experiment_id: str
        async_mode: bool
        error: str | None
        metrics: dict | None  (None if async — poll later)
        feature_names: list | None
        label_mapping: dict | None
    """
    experiment_id = str(uuid.uuid4())

    try:
        dataset_hash = sha256_file(dataset_path)

        create_experiment(
            experiment_id=experiment_id,
            dataset_type=dataset_type,
            dataset_path=dataset_path,
            dataset_hash=dataset_hash,
            pipeline_id=pipeline_id,
            created_at=now_iso(),
        )

        if USE_ASYNC:
            from workers.celery_worker import run_pipeline_task
            run_pipeline_task.delay(
                experiment_id=experiment_id,
                dataset_type=dataset_type,
                dataset_path=dataset_path,
                pipeline_id=pipeline_id,
            )
            return {
                "success": True,
                "experiment_id": experiment_id,
                "async_mode": True,
                "error": None,
                "metrics": None,
                "feature_names": None,
                "label_mapping": None,
            }

        # --- Sync path ---
        set_running(experiment_id, started_at=now_iso())
        df = parse_dataset(dataset_path)
        result = execute_pipeline(pipeline_id, df, dataset_type)

        metrics_dict = {
            "accuracy": result.accuracy,
            "precision": result.precision,
            "recall": result.recall,
            "f1_score": result.f1_score,
            "confusion_matrix": result.confusion_matrix,
            **result.extra_info,
        }
        metadata_dict = {
            "experiment_id": experiment_id,
            "dataset_type": dataset_type,
            "dataset_path": dataset_path,
            "dataset_hash": dataset_hash,
            "pipeline_id": pipeline_id,
            "label_mapping": result.label_mapping,
            "feature_names": result.feature_names,
            "created_at": now_iso(),
            "completed_at": now_iso(),
        }
        paths = save_all_artifacts(experiment_id, result.model, metrics_dict, metadata_dict)

        set_finished(
            experiment_id=experiment_id,
            completed_at=now_iso(),
            accuracy=result.accuracy,
            precision_score=result.precision,
            recall=result.recall,
            f1_score=result.f1_score,
            metrics_path=paths["metrics_path"],
            model_path=paths["model_path"],
        )

        return {
            "success": True,
            "experiment_id": experiment_id,
            "async_mode": False,
            "error": None,
            "metrics": metrics_dict,
            "feature_names": result.feature_names,
            "label_mapping": result.label_mapping,
        }

    except Exception as e:
        try:
            set_failed(experiment_id, completed_at=now_iso(), error_message=str(e))
        except Exception:
            logger.exception("set_failed itself raised during error handling for %s", experiment_id)
        return {
            "success": False,
            "experiment_id": experiment_id,
            "async_mode": USE_ASYNC,
            "error": str(e),
            "metrics": None,
            "feature_names": None,
            "label_mapping": None,
        }


def cleanup_stale_experiments(stale_threshold_minutes: int = 120) -> int:
    """
    Find experiments stuck in RUNNING or QUEUED for too long and mark them FAILED.

    Called at app startup to recover from worker crashes.

    Returns:
        Number of experiments cleaned up.
    """
    from database.db import list_experiments_by_status
    from database.models import STATUS_RUNNING, STATUS_QUEUED
    from datetime import datetime, timezone, timedelta

    count = 0
    threshold = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)

    for status in [STATUS_RUNNING, STATUS_QUEUED]:
        experiments = list_experiments_by_status(status)
        for exp in experiments:
            created = exp.get("created_at", "")
            try:
                created_dt = datetime.fromisoformat(created)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                if created_dt < threshold:
                    set_failed(
                        exp["id"],
                        completed_at=now_iso(),
                        error_message=(
                            f"Experiment stale — stuck in {status} for over "
                            f"{stale_threshold_minutes} minutes. Likely caused by worker crash."
                        ),
                    )
                    count += 1
            except (ValueError, TypeError):
                continue

    return count


def get_experiment_status(experiment_id: str) -> dict | None:
    """
    Get current experiment status. Used for UI polling in async mode.
    Returns the full experiment dict from DB, or None if not found.
    """
    return get_experiment(experiment_id)


def rerun_experiment(experiment_id: str) -> dict:
    """Re-execute with same config. Returns new experiment result."""
    original = get_experiment(experiment_id)
    if original is None:
        return {
            "success": False,
            "experiment_id": None,
            "async_mode": USE_ASYNC,
            "error": f"Experiment {experiment_id} not found",
            "metrics": None,
            "feature_names": None,
            "label_mapping": None,
        }
    return create_and_run_experiment(
        dataset_type=original["dataset_type"],
        dataset_path=original["dataset_path"],
        pipeline_id=original["pipeline_id"],
    )
