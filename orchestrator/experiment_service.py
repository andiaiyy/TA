"""
Experiment service — main facade for UI.

Supports both synchronous and asynchronous execution.
Set USE_ASYNC=true in environment to use Celery; default is sync (no Redis needed).

ONLY orchestrator file that accesses database/.
"""
import logging
import uuid
from pathlib import Path

from config.celery_config import USE_ASYNC

logger = logging.getLogger(__name__)
from orchestrator.validation_service import validate_for_experiment
from orchestrator.execution_service import execute_pipeline
from orchestrator.dataset_parser import parse_dataset
from orchestrator.dynamic_registry import traceability_for
from database.db import (
    create_experiment, set_running, set_finished, set_failed,
    cancel_experiment as db_cancel_experiment,
    get_connection, get_experiment, init_db, set_task_id,
)
from orchestrator.user_errors import UserFacingMixin


class ExperimentServiceError(UserFacingMixin, RuntimeError):
    """Tindakan atas sebuah eksperimen ditolak pengamannya."""
from utils.hashing import sha256_file
from utils.timestamps import now_iso
from utils.artifact_saver import save_all_artifacts
from utils.error_sanitizer import sanitize_error
from orchestrator.run_mode import ParamError, dump_params, resolve_params

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


# ── Pembatas beban ────────────────────────────────────────────────────────
#
# Dua pembatas, dan keduanya menjawab pertanyaan yang BERBEDA:
#
#   * KUOTA menjawab "berapa banyak yang boleh berjalan sekaligus". Worker
#     berjalan dengan `concurrency=1`, jadi run kelima seorang pengguna hanya
#     mengantre di belakang run keempatnya sendiri — sementara orang lain
#     menunggu di belakang kelimanya.
#   * LAJU menjawab "berapa sering boleh memulai". Kuota saja tidak cukup:
#     seseorang yang membatalkan lalu memulai lagi berulang-ulang tetap
#     menguasai antrean tanpa pernah melewati kuotanya.
#
# Keduanya dihitung dari BASIS DATA, bukan dari penghitung dalam memori:
# penghitung dalam memori hilang saat aplikasi dimulai ulang, dan menjadi nol
# justru pada saat yang paling mungkin disalahgunakan.
#
# Nilai bawaannya longgar dengan sengaja. Pada pemakaian lab, tak seorang pun
# akan menyentuhnya; pembatas yang menghalangi pemakaian wajar akan dimatikan
# orang, dan pembatas yang dimatikan tidak membatasi apa pun.

MAX_ACTIVE_RUNS_ENV = "MAX_ACTIVE_RUNS_PER_OWNER"
MAX_RUNS_WINDOW_ENV = "MAX_RUNS_PER_WINDOW"
RUN_WINDOW_MINUTES_ENV = "RUN_WINDOW_MINUTES"

DEFAULT_MAX_ACTIVE_RUNS = 3
DEFAULT_MAX_RUNS_PER_WINDOW = 20
DEFAULT_RUN_WINDOW_MINUTES = 10

#: Nilai 0 atau negatif berarti "tanpa batas" — ditulis eksplisit supaya
#: mematikan pembatas menjadi keputusan yang terbaca, bukan efek samping.
def _limit(env_name: str, default: int) -> int:
    import os

    try:
        nilai = int(os.environ.get(env_name, "").strip() or default)
    except ValueError:
        logger.warning("%s bukan angka; memakai bawaan %s", env_name, default)
        return default
    return nilai


def active_runs_for(owner: str | None, db_path: str | None = None) -> int:
    """Berapa run milik `owner` yang sedang mengantre atau berjalan.

    Pengunjung tanpa akun berbagi SATU ember. Itu disengaja: tanpa identitas,
    tidak ada cara membedakan sepuluh orang dari satu orang yang menekan
    sepuluh kali, dan yang kedua justru yang perlu dibatasi.
    """
    from database.models import STATUS_QUEUED, STATUS_RUNNING

    conn = get_connection(db_path)
    try:
        if owner:
            baris = conn.execute(
                "SELECT COUNT(*) FROM experiments WHERE owner = ? "
                "AND status IN (?, ?)",
                (owner, STATUS_QUEUED, STATUS_RUNNING)).fetchone()
        else:
            baris = conn.execute(
                "SELECT COUNT(*) FROM experiments "
                "WHERE (owner IS NULL OR owner = '') AND status IN (?, ?)",
                (STATUS_QUEUED, STATUS_RUNNING)).fetchone()
    finally:
        conn.close()
    return int(baris[0] if baris else 0)


def recent_runs_for(owner: str | None, minutes: int,
                    db_path: str | None = None) -> int:
    """Berapa run milik `owner` yang DIMULAI dalam `minutes` terakhir.

    Dihitung dari `created_at`, bukan dari statusnya: run yang sudah selesai
    atau dibatalkan tetap memakai giliran worker, dan justru pembatalan
    berulang yang hendak dicegah pembatas ini.
    """
    from datetime import datetime, timedelta

    from utils.timestamps import now_iso

    batas = (datetime.fromisoformat(now_iso().replace("Z", "+00:00"))
             - timedelta(minutes=max(1, int(minutes)))).isoformat()
    conn = get_connection(db_path)
    try:
        if owner:
            baris = conn.execute(
                "SELECT COUNT(*) FROM experiments WHERE owner = ? "
                "AND created_at >= ?", (owner, batas)).fetchone()
        else:
            baris = conn.execute(
                "SELECT COUNT(*) FROM experiments "
                "WHERE (owner IS NULL OR owner = '') AND created_at >= ?",
                (batas,)).fetchone()
    finally:
        conn.close()
    return int(baris[0] if baris else 0)


def run_limit_blocker(owner: str | None, db_path: str | None = None) -> str:
    """Kunci pesan bila pembatas beban menolak run ini; "" bila boleh."""
    kuota = _limit(MAX_ACTIVE_RUNS_ENV, DEFAULT_MAX_ACTIVE_RUNS)
    if kuota > 0 and active_runs_for(owner, db_path) >= kuota:
        return "err.run_too_many_active"

    laju = _limit(MAX_RUNS_WINDOW_ENV, DEFAULT_MAX_RUNS_PER_WINDOW)
    jendela = _limit(RUN_WINDOW_MINUTES_ENV, DEFAULT_RUN_WINDOW_MINUTES)
    if laju > 0 and recent_runs_for(owner, jendela, db_path) >= laju:
        return "err.run_rate_limited"
    return ""


def create_and_run_experiment(
    dataset_type: str,
    dataset_path: str,
    pipeline_id: str,
    owner: str | None = None,
    run_mode: str | None = None,
    param_overrides: dict | None = None,
) -> dict:
    """
    Create and execute an experiment.

    ``run_mode`` (opsional, default None) memilih mode eksekusi. None dan nilai
    tak dikenal berarti **run RESMI** — bawaan platform tidak pernah eksplorasi.
    Pada run resmi ``param_overrides`` DIBUANG sepenuhnya oleh
    ``resolve_params`` sebelum apa pun dijalankan, jadi tidak ada jalur yang
    membuat run resmi memakai nilai yang diubah. Parameter yang benar-benar
    dipakai dicatat di basis data (``run_mode``/``params_used``) dan di
    metadata artefak, untuk kedua mode.

    ``owner`` (opsional, default None) hanyalah METADATA pencatatan: username
    pengguna yang sedang masuk, atau None bila dijalankan tanpa login. Nilainya
    TIDAK diteruskan ke worker maupun ke pipeline — jalur komputasi tidak
    mengetahuinya — dan tidak pernah dipakai untuk menyaring tampilan.

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

    # Izin DI SINI, bukan di tombol. Bawaannya terbuka untuk siapa saja —
    # itu kebijakan platform ini dan tidak berubah. `REQUIRE_LOGIN_TO_RUN=true`
    # menutupnya bagi pengunjung tanpa akun, untuk pemasangan yang dapat
    # dijangkau di luar jaringan tepercaya.
    #
    # Sebelumnya `can_run_experiment` ada, berdokumentasi, dan TIDAK PERNAH
    # dipanggil dari mana pun: kebijakannya tertulis tetapi tidak ditegakkan.
    from orchestrator.auth_service import can_run_experiment, get_user

    if not can_run_experiment(get_user(owner) if owner else None):
        logger.warning("Run ditolak: %s tidak berwenang menjalankan eksperimen",
                       owner or "(pengunjung)")
        return {
            "success": False,
            "experiment_id": None,
            "async_mode": USE_ASYNC,
            "error": "err.run_requires_login",
            "metrics": None,
            "feature_names": None,
            "label_mapping": None,
        }

    ditolak = run_limit_blocker(owner)
    if ditolak:
        logger.warning("Run ditolak pembatas beban (%s): %s",
                       owner or "(pengunjung)", ditolak)
        return {
            "success": False,
            "experiment_id": None,
            "async_mode": USE_ASYNC,
            "error": ditolak,
            "metrics": None,
            "feature_names": None,
            "label_mapping": None,
        }

    # Mode + parameter diselesaikan SEBELUM record dibuat, supaya baris basis
    # data sudah membawa modenya sejak QUEUED — tidak ada jendela waktu di mana
    # sebuah run eksplorasi terlihat seperti run resmi.
    try:
        resolved = resolve_params(pipeline_id, run_mode, param_overrides)
    except ParamError as e:
        logger.warning("Parameter ditolak untuk %s: %s", pipeline_id, e)
        return {
            "success": False,
            "experiment_id": None,
            "async_mode": USE_ASYNC,
            "error": str(e),
            "metrics": None,
            "feature_names": None,
            "label_mapping": None,
        }
    effective_params = resolved["params"]
    applied_overrides = resolved["overrides"]
    resolved_mode = resolved["run_mode"]

    # [DIAG-PATH] Unsanitized entry log — prints what the orchestrator received
    # from the UI BEFORE any sanitizer touches it. Lets us correlate the
    # experiment_id with the raw dataset_path and existence check.
    import os
    logger.debug(
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
            owner=owner,
            run_mode=resolved_mode,
            params_used=dump_params(effective_params),
            params_changed=1 if resolved["changed"] else 0,
            # Ketertelusuran pipeline terunggah: versi + SHA-256 berkasnya.
            # Pipeline bawaan menghasilkan None/None (definisinya ada di git).
            **traceability_for(pipeline_id),
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
                param_overrides=applied_overrides,
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
        result = execute_pipeline(pipeline_id, df, dataset_type, dataset_path=dataset_path,
                                  progress=None, param_overrides=applied_overrides)

        # [DIAG-PATH] Sync-path post-pipeline state snapshot — mirrors the worker
        # snapshot in celery_worker.py so the failure-point trail is identical
        # whichever execution mode the user is running.
        try:
            import os as _os
            from config.settings import ARTIFACTS_DIR as _ART_DIR
            logger.debug(
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
            # Mode + parameter ikut ke metadata.json supaya artefak dapat
            # berdiri sendiri: dibaca terpisah dari basis data pun, terlihat
            # apakah ia run resmi dan dengan parameter apa. Struktur
            # metrics.json TIDAK disentuh — tidak ada field metrik yang berubah.
            "run_mode": resolved_mode,
            "params_used": effective_params,
            "params_locked": resolved["locked"],
            "params_changed": resolved["changed"],
        }
        # Save artifacts — if this fails, nothing is on disk yet
        try:
            paths = save_all_artifacts(experiment_id, result.model, metrics_dict, metadata_dict)
            logger.debug(
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
                            f"Experiment stale: stuck in {status} for over "
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
    # Mengulang harus mengulang HAL YANG SAMA: run eksplorasi diulang sebagai
    # eksplorasi dengan parameter yang sama, run resmi tetap resmi. Tanpa ini,
    # "Re-run" diam-diam mengubah eksplorasi menjadi resmi.
    from orchestrator.run_mode import (
        RUN_MODE_EXPLORATION, changed_keys, mode_of, params_of,
    )
    mode = mode_of(original)
    overrides = {}
    if mode == RUN_MODE_EXPLORATION:
        used = params_of(original)
        locked = _locked_params_for(original["pipeline_id"])
        overrides = {k: used[k] for k in changed_keys(used, locked)}

    return create_and_run_experiment(
        dataset_type=original["dataset_type"],
        dataset_path=original["dataset_path"],
        pipeline_id=original["pipeline_id"],
        run_mode=mode,
        param_overrides=overrides,
    )


def _locked_params_for(pipeline_id: str) -> dict:
    """Nilai terkunci pipeline; {} bila pipeline-nya tidak dapat dimuat."""
    from orchestrator.run_mode import locked_params
    try:
        return locked_params(pipeline_id)
    except Exception:                       # pragma: no cover - defensif
        logger.debug("fixed_params tidak terbaca untuk %s", pipeline_id, exc_info=True)
        return {}


# ── Penghapusan eksperimen ────────────────────────────────────────────────

#: Keadaan yang TIDAK boleh dihapus: eksperimennya masih hidup. Menghapus
#: barisnya sementara worker masih menulis artefaknya meninggalkan folder yatim
#: dan task yang menulis ke baris yang sudah tidak ada.
_DELETE_BLOCKED_STATUSES = ("QUEUED", "RUNNING")


def delete_blocker(experiment: dict | None) -> str:
    """Alasan eksperimen ini TIDAK dapat dihapus; "" bila boleh.

    Alasannya selalu dinyatakan: tombol mati tanpa keterangan membuat orang
    menebak apa yang salah.
    """
    if not experiment:
        return "err.experiment_not_found"
    if (experiment.get("status") or "") in _DELETE_BLOCKED_STATUSES:
        return "err.experiment_still_running"
    return ""


def delete_experiment(experiment_id: str, *, actor: dict | None,
                      db_path: str | None = None) -> dict:
    """Hapus satu eksperimen beserta artefaknya. Hanya Research Admin.

    Sebelumnya tidak ada jalur ini sama sekali: membersihkan satu eksperimen
    berarti SQL mentah, dan folder artefaknya tertinggal karena tidak ada yang
    ikut membuangnya. Audit celah menemukannya justru saat membersihkan
    dirinya sendiri.

    Urutannya disengaja, dan tiap langkah adalah pengaman:

    1. **izin** — ditegakkan di FUNGSI, bukan di tombol;
    2. **keadaan** — eksperimen yang masih mengantre atau berjalan ditolak;
    3. **baris dihapus lebih dulu** — bila penghapusan gagal, artefaknya masih
       utuh dan keadaannya tetap konsisten. Urutan sebaliknya meninggalkan
       baris yang menunjuk artefak yang sudah tidak ada;
    4. **artefak dibuang per berkas**, di dalam foldernya sendiri, dan hanya
       bila foldernya benar-benar berada di bawah ``ARTIFACTS_DIR`` dan
       bernama seperti id eksperimen. TIDAK ada penghapusan rekursif atas
       jalur hasil turunan.

    Mengembalikan keterangan apa yang terhapus, supaya pemanggil dapat
    mengatakannya apa adanya alih-alih "berhasil".
    """
    from orchestrator.auth_service import require_approve
    from database.db import get_experiment

    require_approve(actor, db_path)

    row = get_experiment(experiment_id, db_path)
    blocked = delete_blocker(row)
    if blocked:
        raise ExperimentServiceError(
            f"Eksperimen {experiment_id} tidak dapat dihapus.", key=blocked,
            values={"id": experiment_id})

    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))
        conn.commit()
    finally:
        conn.close()

    dibuang = _remove_artifacts(experiment_id)
    logger.info("Eksperimen %s dihapus oleh %s (%d berkas artefak)",
                experiment_id, (actor or {}).get("username"), len(dibuang))
    return {"experiment_id": experiment_id,
            "status": row.get("status"),
            "pipeline_id": row.get("pipeline_id"),
            "files": dibuang}


def _remove_artifacts(experiment_id: str) -> list[str]:
    """Buang folder artefak satu eksperimen. Kembalikan nama berkas terbuang.

    PENGAMAN BERLAPIS, dan tiap lapis pernah menjadi sebab nyata: folder harus
    berada TEPAT di bawah `ARTIFACTS_DIR`, namanya harus sama persis dengan id
    eksperimennya, dan berkas dibuang satu per satu — bukan `rmtree` atas
    jalur yang dirakit dari untaian, yang pernah menghapus 514 berkas di luar
    sasarannya karena satu jalur teruraikan terlalu tinggi.
    """
    from config.settings import ARTIFACTS_DIR

    nama = Path(str(experiment_id)).name
    if not nama or nama != str(experiment_id):
        logger.warning("Id eksperimen tidak layak dijadikan nama folder: %r",
                       experiment_id)
        return []

    akar = Path(ARTIFACTS_DIR).resolve()
    folder = (akar / nama).resolve()
    if folder.parent != akar or not folder.is_dir():
        return []

    dibuang = []
    try:
        for berkas in folder.iterdir():
            if berkas.is_file():
                berkas.unlink()
                dibuang.append(berkas.name)
        if not any(folder.iterdir()):
            folder.rmdir()
    except OSError:                          # pragma: no cover - defensif
        logger.warning("Artefak %s tidak dapat dibuang seluruhnya",
                       experiment_id, exc_info=True)
    return dibuang
