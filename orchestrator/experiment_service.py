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
    cancel_experiment as db_cancel_experiment,
    get_experiment, init_db, set_task_id,
)
from utils.hashing import sha256_file
from utils.timestamps import now_iso
from utils.artifact_saver import save_all_artifacts
from utils.error_sanitizer import sanitize_error

# [DIAG] In-process diagnostic stash for UI consumption.
# Keyed by experiment_id, stores resolved USE_ASYNC, chosen branch,
# task_id, and dispatch timestamp. Lives for the life of the Streamlit
# process. Keeps orchestrator free of any Streamlit import (layer rule).
_DIAG_DISPATCH: dict[str, dict] = {}


def get_diag(experiment_id: str) -> dict:
    """[DIAG] Return the dispatch diagnostic for an experiment, or {} if absent."""
    return _DIAG_DISPATCH.get(experiment_id, {})


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

    # [DIAG-PATH] Unsanitized entry log — prints what the orchestrator received
    # from the UI BEFORE any sanitizer touches it. Lets us correlate the
    # experiment_id with the raw dataset_path and existence check.
    import os
    logger.error(
        "[DIAG-PATH] create_and_run_experiment received: "
        "dataset_type=%r dataset_path=%r exists=%s USE_ASYNC=%s pipeline_id=%r",
        dataset_type, dataset_path, os.path.exists(dataset_path), USE_ASYNC, pipeline_id,
    )

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
            # Warn if queue is already deep — concurrent heavy pipelines can OOM
            from database.db import list_experiments_by_status
            from database.models import STATUS_QUEUED, STATUS_RUNNING
            running = list_experiments_by_status(STATUS_RUNNING)
            queued = list_experiments_by_status(STATUS_QUEUED)
            active_count = len(running) + len(queued)
            if active_count >= 3:
                logger.warning(
                    "Queue depth is %d (running=%d, queued=%d). "
                    "Consider waiting for existing experiments to finish.",
                    active_count, len(running), len(queued),
                )

            from workers.celery_worker import run_pipeline_task
            logger.info("[DIAG] USE_ASYNC=%s branch=async", USE_ASYNC)
            async_result = run_pipeline_task.delay(
                experiment_id=experiment_id,
                dataset_type=dataset_type,
                dataset_path=dataset_path,
                pipeline_id=pipeline_id,
            )
            # [DIAG] Stash dispatch facts for the UI diagnostic block.
            _DIAG_DISPATCH[experiment_id] = {
                "USE_ASYNC": USE_ASYNC,
                "branch": "async",
                "task_id": async_result.id,
                "timestamp": now_iso(),
            }
            # Persist Celery task id so cancel_experiment can revoke the
            # right task later. revoke() targets by Celery task id, NOT by
            # our experiment uuid.
            try:
                set_task_id(experiment_id, async_result.id)
            except Exception:
                logger.exception(
                    "Failed to persist Celery task_id for %s — cancellation "
                    "of this experiment will be a no-op on the worker side",
                    experiment_id,
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
        # Sync path has no progress reporter — UI shows static text.
        # Async path supplies a Celery-backed callback (see celery_worker.py).
        logger.info("[DIAG] USE_ASYNC=%s branch=sync", USE_ASYNC)
        # [DIAG] Stash dispatch facts for the UI diagnostic block.
        _DIAG_DISPATCH[experiment_id] = {
            "USE_ASYNC": USE_ASYNC,
            "branch": "sync",
            "task_id": None,
            "timestamp": now_iso(),
        }
        result = execute_pipeline(pipeline_id, df, dataset_type, dataset_path=dataset_path, progress=None)

        # [DIAG-PATH] Sync-path post-pipeline state snapshot — mirrors the worker
        # snapshot in celery_worker.py so the failure-point trail is identical
        # whichever execution mode the user is running.
        try:
            import os as _os
            from config.settings import ARTIFACTS_DIR as _ART_DIR
            logger.error(
                "[DIAG-PATH] sync save-section entry: experiment_id=%r "
                "dataset_path=%r ds_exists=%s ARTIFACTS_DIR=%r art_exists=%s "
                "cwd=%r model_type=%r extra_info_keys=%r",
                experiment_id, dataset_path, _os.path.exists(dataset_path),
                str(_ART_DIR), _os.path.exists(str(_ART_DIR)),
                _os.getcwd(), type(result.model).__name__,
                list(result.extra_info.keys()) if result.extra_info else [],
            )
        except Exception:
            logger.exception("[DIAG-PATH] sync pre-save snapshot itself raised")

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
        # Save artifacts — if this fails, nothing is on disk yet
        try:
            paths = save_all_artifacts(experiment_id, result.model, metrics_dict, metadata_dict)
            logger.error(
                "[DIAG-PATH] sync save_all_artifacts returned: model_path=%r metrics_path=%r metadata_path=%r",
                paths.get("model_path"), paths.get("metrics_path"), paths.get("metadata_path"),
            )
        except Exception as artifact_error:
            logger.exception(
                "[DIAG-PATH] sync save_all_artifacts raised — UNSANITIZED: type=%r repr=%r",
                type(artifact_error).__name__, repr(artifact_error),
            )
            logger.exception("Artifact saving failed for %s", experiment_id)
            set_failed(experiment_id, completed_at=now_iso(),
                       error_message=sanitize_error(f"Artifact save failed: {artifact_error}"))
            return {
                "success": False,
                "experiment_id": experiment_id,
                "async_mode": False,
                "error": f"Artifact save failed: {artifact_error}",
                "metrics": None,
                "feature_names": None,
                "label_mapping": None,
            }

        # Update DB — if this fails after artifacts are saved, clean up to avoid orphans
        try:
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
        except Exception as db_error:
            logger.exception(
                "[DIAG-PATH] sync set_finished raised — UNSANITIZED: type=%r repr=%r",
                type(db_error).__name__, repr(db_error),
            )
            logger.exception(
                "set_finished failed for %s after artifacts were saved — cleaning up", experiment_id
            )
            try:
                import shutil
                from config.settings import ARTIFACTS_DIR
                artifact_dir = ARTIFACTS_DIR / experiment_id
                if artifact_dir.exists():
                    shutil.rmtree(artifact_dir)
                    logger.info("Cleaned up orphaned artifacts for %s", experiment_id)
            except Exception as cleanup_error:
                logger.error(
                    "Artifact cleanup also failed for %s: %s — manual cleanup required: "
                    "storage/artifacts/%s/", experiment_id, cleanup_error, experiment_id
                )
            raise db_error

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
            set_failed(experiment_id, completed_at=now_iso(), error_message=sanitize_error(str(e)))
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

    When USE_ASYNC is True, the experiment is RUNNING, and a task_id is
    stored, also attempt a best-effort read of the Celery task's
    PROGRESS meta from Redis and attach it as ``celery_stage`` for the
    UI to display. Failures are silent (debug-logged) — the DB row is
    still the authoritative status.
    """
    exp = get_experiment(experiment_id)
    if exp is None:
        return None

    if USE_ASYNC and exp.get("status") == "RUNNING" and exp.get("task_id"):
        try:
            from workers.celery_worker import app as celery_app
            async_result = celery_app.AsyncResult(exp["task_id"])
            info = async_result.info
            if isinstance(info, dict):
                stage = info.get("stage")
                if stage:
                    exp["celery_stage"] = stage
                # Pass through the granular progress payload (stage_index,
                # stage_total, stage_percent, overall_percent, stage_name,
                # message) so the UI can render the Jenkins-style stage view.
                # Backward compatible: absent for old/coarse emitters.
                exp["celery_progress"] = {
                    k: info[k] for k in (
                        "stage_name", "stage_index", "stage_total",
                        "stage_percent", "overall_percent", "message",
                    ) if k in info
                }
        except Exception:
            logger.debug(
                "Could not read Celery PROGRESS meta for %s — omitting celery_stage",
                experiment_id,
                exc_info=True,
            )

    return exp


def cancel_experiment(experiment_id: str) -> dict:
    """
    Cancel a QUEUED or RUNNING experiment.

    Async mode: best-effort Celery task revoke (SIGTERM) using the stored
    Celery task id, then DB -> FAILED.
    Sync mode: DB -> FAILED only (in-process pipeline cannot be interrupted mid-run).

    Note on Celery revocation: revoke() targets by Celery task id, which differs
    from experiment_id. We persist the AsyncResult.id at dispatch time
    (see create_and_run_experiment) and look it up here. If task_id is NULL
    (sync experiment, or async experiment whose set_task_id call failed)
    the revoke is skipped — the idempotency guard in the worker will still
    drop any late result after the DB is marked FAILED.

    Returns dict with: success, experiment_id, message
    """
    exp = get_experiment(experiment_id)
    if exp is None:
        return {
            "success": False,
            "experiment_id": experiment_id,
            "message": f"Experiment {experiment_id} not found",
        }

    if exp["status"] not in ("QUEUED", "RUNNING"):
        return {
            "success": False,
            "experiment_id": experiment_id,
            "message": f"Cannot cancel experiment in status '{exp['status']}'",
        }

    if USE_ASYNC:
        task_id = exp.get("task_id")
        if task_id:
            try:
                from workers.celery_worker import app as celery_app
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception as e:
                logger.warning("Could not revoke Celery task %s for %s: %s", task_id, experiment_id, e)
        else:
            logger.debug(
                "cancel_experiment: no task_id stored for %s — skipping Celery revoke",
                experiment_id,
            )

    updated = db_cancel_experiment(experiment_id, completed_at=now_iso())
    if updated:
        return {
            "success": True,
            "experiment_id": experiment_id,
            "message": "Experiment cancelled successfully",
        }
    return {
        "success": False,
        "experiment_id": experiment_id,
        "message": "Experiment could not be cancelled (may have just completed)",
    }


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
