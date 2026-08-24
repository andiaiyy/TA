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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logging_config import setup_logging
setup_logging()

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from config.celery_config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_CONCURRENCY
from database.db import get_experiment, set_running, set_finished, set_failed

logger = logging.getLogger(__name__)
from orchestrator.dataset_parser import parse_dataset
from orchestrator.execution_service import execute_pipeline
from utils.hashing import sha256_file
from utils.timestamps import now_iso
from utils.artifact_saver import save_all_artifacts
from utils.error_sanitizer import sanitize_error

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
    # Complements task_acks_late: if the worker process dies mid-task (OOM kill,
    # SIGKILL, container restart), the broker marks the task as failed instead
    # of redelivering it. Prevents OOM-loop when a task systematically kills its
    # worker (e.g. learning_curve memory blowup on large datasets).
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=CELERY_CONCURRENCY,  # default 1 — prevents OOM on large datasets
)


def _safe_update_state(task, stage: str, meta_extra: dict | None = None) -> None:
    """
    Best-effort progress reporter.

    Emits a custom Celery state "PROGRESS". ``meta`` always carries a ``stage``
    string (backward compatible with the previous coarse reporter and with
    tests/UI that read ``meta["stage"]``); ``meta_extra`` layers the granular
    fields (stage_index, stage_total, stage_percent, overall_percent, message)
    on top when a pipeline stage is being reported. Failures (broker down,
    serialization errors, etc.) are logged and swallowed — progress reporting
    must NEVER cause an experiment to fail.

    Progress is emitted to the Celery result backend (Redis), NOT to SQLite,
    so there is no DB-write amplification to throttle.

    The state name "PROGRESS" is deliberately distinct from Celery's
    built-in states (PENDING/STARTED/SUCCESS/FAILURE/REVOKED/RETRY/REJECTED)
    so we don't shadow them.
    """
    logger.info("[DIAG] _safe_update_state entry stage=%s", stage)
    meta = {"stage": stage}
    if meta_extra:
        meta.update(meta_extra)
        # keep the raw stage string authoritative even if meta_extra overrode it
        meta["stage"] = stage
    try:
        task.update_state(state="PROGRESS", meta=meta)
    except Exception:
        logger.exception("[DIAG] _safe_update_state swallowed exception")
        logger.exception("Progress update failed for stage=%r — continuing", stage)


@app.task(
    bind=True,
    name='workers.run_pipeline_task',
    soft_time_limit=3600,   # 1 hour soft limit — raises SoftTimeLimitExceeded
    time_limit=3900,        # 1 hour 5 min hard kill
    acks_late=True,
)
def run_pipeline_task(self, experiment_id: str, dataset_type: str,
                      dataset_path: str, pipeline_id: str,
                      param_overrides: dict | None = None):
    """
    Async pipeline execution task.

    Called by experiment_service.create_and_run_experiment() when USE_ASYNC=true.
    The experiment record already exists in DB with status=QUEUED — beserta
    kolom run_mode/params_used yang sudah terisi di sana.

    ``param_overrides`` OPSIONAL dan default None. Isinya sudah divalidasi
    orchestrator sebelum tugas ini dikirim, dan pada run RESMI selalu kosong,
    jadi tugas lama tanpa argumen ini (mis. yang sudah antre saat pembaruan)
    tetap berjalan sebagai run dengan parameter terkunci.

    Steps:
      1. Idempotency check (skip if already FINISHED/FAILED)
      2. Set status RUNNING
      3. Hash dataset file
      4. Parse dataset
      5. Execute pipeline
      6. Save artifacts (with orphan cleanup on DB failure)
      7. Set status FINISHED (or FAILED on error)
    """
    # First statement in the task body — proves the worker actually picked up
    # the task AND that update_state itself works, in one shot. The diagnostic
    # intent is kept in the log; the user-facing meta stage is a clean message
    # (no "[DIAG]" scaffolding leaking into the UI). The UI reads
    # AsyncResult(task_id).info back through get_experiment_status().
    logger.info("[DIAG] worker task entered experiment_id=%s", experiment_id)
    try:
        self.update_state(state="PROGRESS", meta={"stage": "Menyiapkan eksekusi…"})
    except Exception:
        logger.exception("[DIAG] worker-entered update_state failed")
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

        # Hash the dataset file (was missing in the async path previously)
        try:
            dataset_hash = sha256_file(dataset_path)
        except Exception as hash_error:
            logger.warning("Could not hash dataset in worker for %s: %s", experiment_id, hash_error)
            dataset_hash = "unknown"

        df = parse_dataset(dataset_path)

        _safe_update_state(self, "Executing pipeline...")
        # Forward fine-grained pipeline stages to Celery PROGRESS state, enriched
        # with granular stage_index/stage_total/overall_percent computed from the
        # registry stage list. _safe_update_state already swallows exceptions
        # internally; the pipeline-side _emit_progress wrapper does so as well —
        # a doubly safe path that cannot fail the experiment. The enrichment is
        # pure observation (workers/progress_util) and never touches computation.
        from workers.progress_util import build_progress_meta
        _prog_state = {"last_index": 0, "last_overall": 0}

        def _progress(stage: str) -> None:
            logger.info("[DIAG] celery callback invoked stage=%s", stage)
            try:
                meta = build_progress_meta(
                    pipeline_id, stage,
                    last_index=_prog_state["last_index"],
                    last_overall=_prog_state["last_overall"],
                )
                if meta.get("stage_index"):
                    _prog_state["last_index"] = meta["stage_index"]
                _prog_state["last_overall"] = meta.get("overall_percent", _prog_state["last_overall"])
                _safe_update_state(self, stage, meta_extra=meta)
            except Exception:
                # Never let enrichment break progress reporting; fall back to
                # the plain stage string.
                _safe_update_state(self, stage)
        result = execute_pipeline(
            pipeline_id, df, dataset_type, dataset_path=dataset_path, progress=_progress,
            param_overrides=param_overrides,
        )
        _safe_update_state(self, "Saving results...")
        logger.error("[DIAG] SAVE ENTRY REACHED")

        # [DIAG-PATH] Post-pipeline state snapshot — fires BEFORE artifact save.
        # If a FileNotFoundError occurs between here and set_finished, the line
        # below will be the last [DIAG-PATH] entry in the worker log, giving us
        # the exact path values active at that moment.
        try:
            import os as _os
            from config.settings import ARTIFACTS_DIR as _ART_DIR
            logger.error(
                "[DIAG-PATH] worker save-section entry: experiment_id=%r "
                "dataset_path=%r ds_exists=%s ARTIFACTS_DIR=%r art_exists=%s "
                "cwd=%r model_type=%r extra_info_keys=%r",
                experiment_id, dataset_path, _os.path.exists(dataset_path),
                str(_ART_DIR), _os.path.exists(str(_ART_DIR)),
                _os.getcwd(), type(result.model).__name__,
                list(result.extra_info.keys()) if result.extra_info else [],
            )
        except Exception:
            logger.exception("[DIAG-PATH] pre-save snapshot itself raised")

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
            "dataset_hash": dataset_hash,       # Fix 4: was missing in async path
            "pipeline_id": pipeline_id,
            "label_mapping": result.label_mapping,
            "feature_names": result.feature_names,
            "created_at": now_iso(),
            "completed_at": now_iso(),
        }
        # Mode + parameter yang dipakai, dibaca dari record yang sudah dibuat
        # orchestrator — SATU sumber untuk kedua jalur eksekusi, jadi artefak
        # jalur async membawa keterangan yang persis sama dengan jalur sync.
        try:
            from orchestrator.run_mode import mode_of, params_of, changed_keys, locked_params
            _row = get_experiment(experiment_id) or {}
            _used = params_of(_row)
            _locked = locked_params(pipeline_id)
            metadata_dict.update({
                "run_mode": mode_of(_row),
                "params_used": _used,
                "params_locked": _locked,
                "params_changed": changed_keys(_used, _locked),
            })
        except Exception:
            logger.exception("Mode/parameter tidak dapat ditambahkan ke metadata %s",
                             experiment_id)

        # Save artifacts — if this fails, nothing is on disk yet
        try:
            paths = save_all_artifacts(experiment_id, result.model, metrics_dict, metadata_dict)
            # [DIAG-PATH] Confirm save returned and log the exact paths it produced.
            logger.error(
                "[DIAG-PATH] save_all_artifacts returned: model_path=%r metrics_path=%r metadata_path=%r",
                paths.get("model_path"), paths.get("metrics_path"), paths.get("metadata_path"),
            )
        except Exception as artifact_error:
            # [DIAG-PATH] Log the UNSANITIZED traceback so we can see the real path.
            logger.exception(
                "[DIAG-PATH] save_all_artifacts raised — UNSANITIZED: type=%r repr=%r",
                type(artifact_error).__name__, repr(artifact_error),
            )
            logger.exception("Artifact saving failed for %s", experiment_id)
            set_failed(experiment_id, completed_at=now_iso(),
                       error_message=sanitize_error(f"Artifact save failed: {artifact_error}"))
            return {"success": False, "experiment_id": experiment_id}

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
            # [DIAG-PATH] Log the UNSANITIZED error before cleanup re-raises it.
            logger.exception(
                "[DIAG-PATH] set_finished raised — UNSANITIZED: type=%r repr=%r",
                type(db_error).__name__, repr(db_error),
            )
            logger.exception(
                "set_finished failed for %s after artifacts saved — cleaning up", experiment_id
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
        # [DIAG-PATH] Log the UNSANITIZED error and full traceback before sanitization
        # strips the absolute path. This is the last-line catch-all so any FileNotFoundError
        # that bypassed the inner save/set_finished try blocks will surface here.
        logger.exception(
            "[DIAG-PATH] outer except: type=%r repr=%r str=%r",
            type(e).__name__, repr(e), str(e),
        )
        try:
            set_failed(experiment_id, completed_at=now_iso(), error_message=sanitize_error(str(e)))
        except Exception:
            logger.exception("set_failed itself raised during error handling for %s", experiment_id)
        raise
