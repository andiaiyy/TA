"""Tests for the granular progress payload enrichment (workers/progress_util).

Contract verified here:
  - build_progress_meta() returns all PROGRESS_FIELDS.
  - stage_index / stage_total resolve against the registry stage list.
  - overall_percent is MONOTONIC (never decreases) across the ordered stages,
    and only reaches 100 when the current stage is fully complete.
  - Backward compatible: the raw ``stage`` string key is always present, and an
    unknown/wrapper stage does not crash or move the bar backwards.
"""
import pytest

from workers.progress_util import (
    build_progress_meta, PROGRESS_FIELDS, build_stage_view, format_duration,
)
from config.pipeline_registry import get_pipeline


HIKARI = "hikari2021.rfc_pipeline"
EVE = "eve_cbr.rfc"


def _stages(pid):
    return list((get_pipeline(pid) or {}).get("stages") or [])


def test_all_fields_present():
    meta = build_progress_meta(HIKARI, _stages(HIKARI)[0])
    for f in PROGRESS_FIELDS:
        assert f in meta, f"missing field {f} in {meta}"


def test_stage_key_is_raw_string():
    meta = build_progress_meta(HIKARI, "Training")
    assert meta["stage"] == "Training"
    assert meta["stage_name"] == "Training"


def test_index_and_total_resolve_hikari():
    stages = _stages(HIKARI)
    assert len(stages) >= 3
    mid = stages[1]
    meta = build_progress_meta(HIKARI, mid)
    assert meta["stage_total"] == len(stages)
    assert meta["stage_index"] == 2
    assert 0 <= meta["overall_percent"] <= 100


def test_eve_stages_resolve():
    stages = _stages(EVE)
    # grouped 14-phase stages: split + 7 groups + collect = 9
    assert len(stages) == 9
    meta = build_progress_meta(EVE, "Export & train/test split (fase 8)")
    assert meta["stage_index"] == stages.index("Export & train/test split (fase 8)") + 1
    assert meta["stage_total"] == 9


@pytest.mark.parametrize("pid", [HIKARI, EVE])
def test_overall_monotonic_across_stages(pid):
    """Feeding the ordered stages forward must never decrease overall_percent."""
    stages = _stages(pid)
    last_index, last_overall = 0, 0
    seen = []
    for name in stages:
        meta = build_progress_meta(pid, name, last_index=last_index, last_overall=last_overall)
        assert meta["overall_percent"] >= last_overall, (
            f"overall decreased at {name}: {meta['overall_percent']} < {last_overall}"
        )
        last_overall = meta["overall_percent"]
        last_index = meta["stage_index"] or last_index
        seen.append(last_overall)
    # sequence is non-decreasing and makes real progress
    assert seen == sorted(seen)
    assert seen[-1] > seen[0]


def test_entering_last_stage_is_below_100():
    """At the entry of the final stage (stage_percent=0) the bar is < 100 —
    100 is reserved for the FINISHED state (handled by the UI)."""
    stages = _stages(HIKARI)
    meta = build_progress_meta(HIKARI, stages[-1])  # stage_percent defaults 0
    assert meta["overall_percent"] < 100


def test_full_last_stage_reaches_100():
    stages = _stages(HIKARI)
    meta = build_progress_meta(HIKARI, stages[-1], stage_percent=100.0)
    assert meta["overall_percent"] == 100


def test_unknown_stage_is_graceful_and_monotonic():
    """A wrapper/unknown stage must not crash, must keep the 'stage' key, and
    must not move the bar backwards."""
    meta = build_progress_meta(HIKARI, "Saving results...", last_index=3, last_overall=90)
    assert meta["stage"] == "Saving results..."
    assert meta["overall_percent"] >= 90  # clamped, never regresses


def test_unknown_pipeline_does_not_crash():
    meta = build_progress_meta("does.not.exist", "Whatever")
    assert meta["stage"] == "Whatever"
    assert 0 <= meta["overall_percent"] <= 100
    assert meta["stage_total"] is None


# ── build_stage_view (horizontal Jenkins-style columns) ───────────────────

def test_stage_view_states_running():
    view = build_stage_view(5, 3, "RUNNING", {}, now_ts=100.0)
    states = [v["state"] for v in view]
    assert states == ["done", "done", "running", "waiting", "waiting"]
    assert [v["index"] for v in view] == [1, 2, 3, 4, 5]


def test_stage_view_finished_all_done():
    view = build_stage_view(4, None, "FINISHED", {}, now_ts=100.0)
    assert all(v["state"] == "done" for v in view)


def test_stage_view_durations():
    # stage1: 0..10 (10s), stage2: 10..25 (15s), stage3 running since 25, now=40 (15s)
    starts = {1: 0.0, 2: 10.0, 3: 25.0}
    view = build_stage_view(5, 3, "RUNNING", starts, now_ts=40.0)
    assert view[0]["duration_sec"] == 10.0   # stage 1 completed
    assert view[1]["duration_sec"] == 15.0   # stage 2 completed
    assert view[2]["duration_sec"] == 15.0   # stage 3 running elapsed
    assert view[3]["duration_sec"] is None   # waiting
    assert view[4]["duration_sec"] is None


def test_stage_view_unknown_start_is_none():
    # completed stage whose start was never observed -> duration unknown
    view = build_stage_view(3, 3, "RUNNING", {3: 50.0}, now_ts=60.0)
    assert view[0]["duration_sec"] is None
    assert view[0]["state"] == "done"
    assert view[2]["duration_sec"] == 10.0


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(130) == "2m 10s"
    assert format_duration(3661) == "1h 01m 01s"
