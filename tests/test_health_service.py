"""Tests for orchestrator.health_service — the execution-infrastructure health
check that guards async submit. Fully mocked: never requires a real Redis or a
live Celery worker. The contract under test:

  - Never raises; always returns a plain dict with the documented keys.
  - Sync mode reports healthy WITHOUT probing broker/worker (can_run True).
  - Async mode: can_run True only when broker AND >=1 worker are reachable.
  - Broker/worker probes swallow every exception and return a failure status.
"""
import orchestrator.health_service as hs


_KEYS = {"mode", "broker_ok", "worker_ok", "worker_count", "queue_depth", "message", "can_run"}


def test_sync_mode_healthy_without_probing(monkeypatch):
    monkeypatch.setattr("config.celery_config.USE_ASYNC", False, raising=False)
    # If a probe were called in sync mode this would blow up the test:
    monkeypatch.setattr(hs, "_probe_broker", lambda *a, **k: (_ for _ in ()).throw(AssertionError("probed in sync")))
    monkeypatch.setattr(hs, "_probe_workers", lambda *a, **k: (_ for _ in ()).throw(AssertionError("probed in sync")))

    out = hs.check_execution_health()
    assert set(out.keys()) == _KEYS
    assert out["mode"] == "sync"
    assert out["can_run"] is True
    assert out["broker_ok"] is True and out["worker_ok"] is True


def test_async_broker_down_disables_run(monkeypatch):
    monkeypatch.setattr("config.celery_config.USE_ASYNC", True, raising=False)
    monkeypatch.setattr(hs, "_probe_broker", lambda url, t: (False, "Broker (Redis) tidak dapat dihubungi: ConnectionError", None))
    # workers must NOT be probed once the broker is down
    monkeypatch.setattr(hs, "_probe_workers", lambda t: (_ for _ in ()).throw(AssertionError("worker probed while broker down")))

    out = hs.check_execution_health()
    assert out["mode"] == "async"
    assert out["broker_ok"] is False
    assert out["worker_ok"] is False
    assert out["can_run"] is False
    assert "Broker" in out["message"]


def test_async_worker_down_disables_run(monkeypatch):
    monkeypatch.setattr("config.celery_config.USE_ASYNC", True, raising=False)
    monkeypatch.setattr(hs, "_probe_broker", lambda url, t: (True, "", 0))
    monkeypatch.setattr(hs, "_probe_workers", lambda t: (False, 0, "Tidak ada worker Celery yang aktif."))

    out = hs.check_execution_health()
    assert out["broker_ok"] is True
    assert out["worker_ok"] is False
    assert out["can_run"] is False
    assert "worker" in out["message"].lower()


def test_async_all_ok_enables_run(monkeypatch):
    monkeypatch.setattr("config.celery_config.USE_ASYNC", True, raising=False)
    monkeypatch.setattr(hs, "_probe_broker", lambda url, t: (True, "", 3))
    monkeypatch.setattr(hs, "_probe_workers", lambda t: (True, 2, ""))

    out = hs.check_execution_health()
    assert out["broker_ok"] is True
    assert out["worker_ok"] is True
    assert out["worker_count"] == 2
    assert out["queue_depth"] == 3
    assert out["can_run"] is True


def test_probe_broker_swallows_exception(monkeypatch):
    import redis

    def _boom(*a, **k):
        raise ConnectionError("no redis")

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(_boom), raising=True)
    ok, msg, depth = hs._probe_broker("redis://localhost:6379/0", 1.0)
    assert ok is False
    assert depth is None
    assert "Broker" in msg


def test_probe_workers_swallows_exception(monkeypatch):
    import workers.celery_worker as cw

    class _BrokenControl:
        def ping(self, timeout=None):
            raise RuntimeError("broker unreachable")

    class _BrokenApp:
        control = _BrokenControl()

    monkeypatch.setattr(cw, "app", _BrokenApp(), raising=False)
    ok, count, msg = hs._probe_workers(1.0)
    assert ok is False
    assert count == 0
    assert msg


def test_check_execution_health_never_raises(monkeypatch):
    """Even if a probe itself misbehaves by raising, the top-level function is
    only exposed to the probe RESULTS; but guard the sync-config read path too."""
    monkeypatch.setattr("config.celery_config.USE_ASYNC", True, raising=False)
    monkeypatch.setattr(hs, "_probe_broker", lambda url, t: (True, "", None))
    monkeypatch.setattr(hs, "_probe_workers", lambda t: (True, 1, ""))
    out = hs.check_execution_health()
    assert out["can_run"] is True
