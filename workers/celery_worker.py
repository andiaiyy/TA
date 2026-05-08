"""
Celery async worker.

Executes pipeline tasks in a separate process via Redis message broker.
The worker does the FULL lifecycle: parse → run → save artifacts → update DB.

Start with:
    celery -A workers.celery_worker worker --loglevel=info --pool=solo

Rules:
    - Worker accesses DB directly (needed for status updates from worker process)
    - Worker accesses filesystem (artifact saving)
    - Worker does NOT import from ui/
"""
import logging

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from config.celery_config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND
from database.db import get_experiment, set_running, set_finished, set_failed

logger = logging.getLogger(__name__)
from orchestrator.dataset_parser import parse_dataset
from orchestrator.execution_service import execute_pipeline
from utils.timestamps import now_iso
from utils.artifact_saver import save_all_artifacts

# --- Celery App ---
app = Celery(
    'worker',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@app.task(
    bind=True,
    name='workers.run_pipeline_task',
    soft_time_limit=3600,   # 1 hour soft limit — raises SoftTimeLimitExceeded
    time_limit=3900,        # 1 hour 5 min hard kill
    acks_late=True,
)
def run_pipeline_task(self, experiment_id: str, dataset_type: str,
                      dataset_path: str, pipeline_id: str):
    """
    Async pipeline execution task.

    Called by experiment_service.create_and_run_experiment() when USE_ASYNC=true.
    The experiment record already exists in DB with status=QUEUED.

    Steps:
      1. Set status RUNNING
      2. Parse dataset
      3. Execute pipeline
      4. Save artifacts
      5. Set status FINISHED (or FAILED on error)
    """
    try:
        # Idempotency guard: skip if already completed (handles Celery acks_late redelivery)
        exp = get_experiment(experiment_id)
        if exp and exp["status"] in ("FINISHED", "FAILED"):
            logger.warning(
                "run_pipeline_task: experiment %s already in %s — skipping redelivered task",
                experiment_id, exp["status"],
            )
            return {"success": True, "experiment_id": experiment_id, "skipped": True}

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

        return {"success": True, "experiment_id": experiment_id}

    except SoftTimeLimitExceeded:
        error_msg = (
            "Pipeline execution timed out after 1 hour (soft_time_limit=3600s). "
            "This typically happens with SVC on large datasets."
        )
        try:
            set_failed(experiment_id, completed_at=now_iso(), error_message=error_msg)
        except Exception:
            logger.exception("set_failed itself raised during timeout handling for %s", experiment_id)
        raise

    except Exception as e:
        try:
            set_failed(experiment_id, completed_at=now_iso(), error_message=str(e))
        except Exception:
            logger.exception("set_failed itself raised during error handling for %s", experiment_id)
        raise
