"""Tests for the pure 'Progress & Status' dashboard helpers
(ui/components/dashboard). No DB / Celery / Redis / Streamlit runtime needed —
all inputs are plain dicts, so 0, 1, and >1 running experiments and the
cross-session progress payload are exercised with mocked data only.
"""
from ui.components.dashboard import (
    select_running, progress_view, elapsed_seconds, format_elapsed,
)


# ── select_running ────────────────────────────────────────────────────────

def test_select_running_empty():
    assert select_running([]) == []
    assert select_running(None) == []


def test_select_running_filters_and_orders():
    exps = [
        {"id": "a", "status": "FINISHED", "created_at": "2026-07-10T10:00:00+00:00"},
        {"id": "b", "status": "RUNNING", "created_at": "2026-07-10T10:05:00+00:00"},
        {"id": "c", "status": "QUEUED", "created_at": "2026-07-10T10:06:00+00:00"},
        {"id": "d", "status": "RUNNING", "created_at": "2026-07-10T10:07:00+00:00"},
        {"id": "e", "status": "FAILED", "created_at": "2026-07-10T10:01:00+00:00"},
    ]
    out = select_running(exps)
    ids = [e["id"] for e in out]
    # RUNNING first (newest→oldest): d, b ; then QUEUED: c
    assert ids == ["d", "b", "c"]


def test_select_running_multiple_all_returned():
    exps = [{"id": str(i), "status": "RUNNING", "created_at": f"2026-07-10T10:0{i}:00+00:00"}
            for i in range(3)]
    assert len(select_running(exps)) == 3


# ── progress_view (never fabricates) ──────────────────────────────────────

def test_progress_view_full_granular():
    status = {"status": "RUNNING", "celery_progress": {
        "overall_percent": 50, "stage_index": 3, "stage_total": 4, "stage_name": "Training"}}
    pv = progress_view(status)
    assert pv["overall_percent"] == 50
    assert pv["stage_index"] == 3 and pv["stage_total"] == 4
    assert pv["stage_label"] == "Fase 3/4 — Training"


def test_progress_view_absent_is_all_none():
    # QUEUED / cross-session / broker-down → no fabricated percentage
    pv = progress_view({"status": "QUEUED"})
    assert pv == {"overall_percent": None, "stage_label": None,
                  "stage_index": None, "stage_total": None}


def test_progress_view_partial_stage_name_only():
    pv = progress_view({"celery_stage": "Menyiapkan eksekusi…"})
    assert pv["overall_percent"] is None
    assert pv["stage_label"] == "Menyiapkan eksekusi…"
    assert pv["stage_index"] is None


def test_progress_view_suppresses_diag():
    pv = progress_view({"celery_stage": "[DIAG] worker task entered"})
    assert pv["stage_label"] is None


def test_progress_view_non_dict():
    assert progress_view(None)["overall_percent"] is None


# ── elapsed_seconds / format_elapsed ──────────────────────────────────────

def test_elapsed_seconds_deterministic():
    from ui.components.dashboard import _epoch
    start = "2026-07-10T10:00:00+00:00"
    now_epoch = _epoch("2026-07-10T10:02:30+00:00")
    assert elapsed_seconds(start, now_epoch=now_epoch) == 150.0


def test_elapsed_seconds_unknown():
    assert elapsed_seconds(None) is None
    assert elapsed_seconds("") is None


def test_format_elapsed():
    assert format_elapsed(None) == "—"
    assert format_elapsed(0) == "0m 00s"
    assert format_elapsed(65) == "1m 05s"
    assert format_elapsed(3661) == "1h 01m 01s"
