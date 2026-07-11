"""
Execution-infrastructure health check for the async (Celery + Redis) mode.

Safe to call from the UI: short timeouts, ALL exceptions swallowed, returns a
plain dict (never raises). The UI caches the result briefly so the broker is
not probed on every Streamlit rerun.

Read-only w.r.t. execution — it never dispatches, revokes, or mutates anything.
Sync mode (USE_ASYNC=false) needs no broker/worker, so it reports healthy
without probing (broker/worker checks are only relevant in async mode).

This module does NOT change the USE_ASYNC value or the sync execution path; it
only observes infrastructure so the UI can inform the user and guard submit.
"""
import logging

logger = logging.getLogger(__name__)

DEFAULT_BROKER_TIMEOUT = 1.0   # seconds — keep short so the UI never hangs
DEFAULT_WORKER_TIMEOUT = 1.5   # seconds — control.ping round-trip


def _probe_broker(broker_url: str, timeout: float):
    """Probe the Redis broker. Returns (ok: bool, message: str, queue_depth).

    Never raises. ``queue_depth`` is the default Celery queue length when the
    broker is Redis and readable, else None (optional/best-effort).
    """
    try:
        import redis
        client = redis.Redis.from_url(
            broker_url, socket_connect_timeout=timeout, socket_timeout=timeout,
        )
        client.ping()
    except Exception as e:  # noqa: BLE001 — the UI must never see an exception
        logger.debug("broker probe failed", exc_info=True)
        return False, f"Broker (Redis) tidak dapat dihubungi: {type(e).__name__}", None

    depth = None
    try:
        depth = int(client.llen("celery"))  # default Celery queue name
    except Exception:
        depth = None
    return True, "", depth


def _probe_workers(timeout: float):
    """Probe for live Celery workers via control.ping. Returns
    (ok: bool, count: int, message: str). Never raises."""
    try:
        from workers.celery_worker import app as celery_app
        pong = celery_app.control.ping(timeout=timeout) or []
        count = len(pong)
        if count > 0:
            return True, count, ""
        return False, 0, "Tidak ada worker Celery yang aktif."
    except Exception as e:  # noqa: BLE001
        logger.debug("worker probe failed", exc_info=True)
        return False, 0, f"Gagal memeriksa worker: {type(e).__name__}"


def check_execution_health(
    *,
    broker_timeout: float = DEFAULT_BROKER_TIMEOUT,
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
) -> dict:
    """Return the current execution-infrastructure health as a plain dict.

    Keys:
      mode          "async" | "sync" (from the effective USE_ASYNC config)
      broker_ok     bool | None
      worker_ok     bool | None
      worker_count  int (active workers; 0 when unknown/none)
      queue_depth   int | None (optional; None when unavailable)
      message       short human-readable status/error (may be "")
      can_run       bool — whether Run Experiment should be allowed

    In sync mode broker/worker are not required, so ``can_run`` is True and no
    probing happens. In async mode ``can_run`` is True only when both the broker
    and at least one worker are reachable. Never raises.
    """
    # Import at call time so tests can monkeypatch config.celery_config.USE_ASYNC.
    from config.celery_config import USE_ASYNC, CELERY_BROKER_URL

    out = {
        "mode": "async" if USE_ASYNC else "sync",
        "broker_ok": None, "worker_ok": None,
        "worker_count": 0, "queue_depth": None,
        "message": "", "can_run": True,
    }

    if not USE_ASYNC:
        out.update(
            broker_ok=True, worker_ok=True, can_run=True,
            message=("Mode sinkron — eksekusi berjalan di proses UI; "
                     "broker/worker tidak diperlukan."),
        )
        return out

    broker_ok, bmsg, depth = _probe_broker(CELERY_BROKER_URL, broker_timeout)
    out["broker_ok"] = broker_ok
    out["queue_depth"] = depth
    if not broker_ok:
        # Broker down → no point pinging workers; guard submit.
        out.update(worker_ok=False, worker_count=0, can_run=False, message=bmsg)
        return out

    worker_ok, count, wmsg = _probe_workers(worker_timeout)
    out.update(worker_ok=worker_ok, worker_count=count, can_run=bool(worker_ok))
    if not worker_ok:
        out["message"] = wmsg or "Tidak ada worker Celery yang aktif."
    return out
