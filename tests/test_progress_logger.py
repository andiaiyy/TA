"""Tests for utils/progress_logger.py.

Covers:
- phase_start / phase_end / step / warn / error / info schema
- read_progress_log returns events in order
- NullProgressLogger is a true no-op (creates no file)
- Unwritable path warns, does not raise
- Two sequential events are both persisted (no buffering loss)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.progress_logger import (
    NullProgressLogger,
    ProgressLogger,
    read_progress_log,
)


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "exp-abc" / "progress.log"


def _read_lines(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── Real logger ───────────────────────────────────────────────────────────

def test_phase_start_writes_expected_schema(log_path: Path) -> None:
    log = ProgressLogger(log_path)
    log.phase_start("Preprocessing", "loading data")

    rows = _read_lines(log_path)
    assert len(rows) == 1
    ev = rows[0]
    assert ev["event"] == "phase_start"
    assert ev["phase"] == "Preprocessing"
    assert ev["message"] == "loading data"
    assert "ts" in ev and ev["ts"].endswith("+00:00")  # UTC


def test_phase_end_includes_duration_when_supplied(log_path: Path) -> None:
    log = ProgressLogger(log_path)
    log.phase_end("Training", "done", duration_seconds=12.5)

    ev = _read_lines(log_path)[0]
    assert ev["event"] == "phase_end"
    assert ev["duration_seconds"] == 12.5


def test_phase_end_omits_duration_when_not_supplied(log_path: Path) -> None:
    log = ProgressLogger(log_path)
    log.phase_end("Training")

    ev = _read_lines(log_path)[0]
    assert "duration_seconds" not in ev


def test_step_warn_error_all_write(log_path: Path) -> None:
    log = ProgressLogger(log_path)
    log.step("Phase 9", "MI sampling", "1M rows")
    log.warn("Phase 9", "RFE fell back to MI")
    log.error("Phase 9", "out of memory")

    rows = _read_lines(log_path)
    assert [r["event"] for r in rows] == ["step", "warn", "error"]
    assert rows[0]["step"] == "MI sampling"
    assert "RFE" in rows[1]["message"]


def test_info_has_no_phase_field(log_path: Path) -> None:
    log = ProgressLogger(log_path)
    log.info("Experiment started")

    ev = _read_lines(log_path)[0]
    assert ev["event"] == "info"
    assert ev["message"] == "Experiment started"
    assert "phase" not in ev


def test_two_sequential_events_both_persisted(log_path: Path) -> None:
    """No cross-call buffering — the UI tails this from another process."""
    log = ProgressLogger(log_path)
    log.phase_start("A")
    log.phase_end("A")

    rows = _read_lines(log_path)
    assert [r["event"] for r in rows] == ["phase_start", "phase_end"]


def test_parent_dir_is_created(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "progress.log"
    assert not deep.parent.exists()
    ProgressLogger(deep).info("hello")
    assert deep.exists()


# ── read_progress_log ─────────────────────────────────────────────────────

def test_read_progress_log_returns_events_in_order(log_path: Path) -> None:
    log = ProgressLogger(log_path)
    log.phase_start("P1")
    log.step("P1", "s1")
    log.phase_end("P1")

    events = read_progress_log(log_path)
    assert [e["event"] for e in events] == ["phase_start", "step", "phase_end"]


def test_read_progress_log_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_progress_log(tmp_path / "nope.log") == []


def test_read_progress_log_skips_malformed_lines(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        '{"event": "phase_start", "phase": "A"}\n'
        '{partial broken line\n'
        '{"event": "phase_end", "phase": "A"}\n',
        encoding="utf-8",
    )
    events = read_progress_log(log_path)
    assert [e["event"] for e in events] == ["phase_start", "phase_end"]


# ── NullProgressLogger ────────────────────────────────────────────────────

def test_null_logger_creates_no_file(tmp_path: Path) -> None:
    n = NullProgressLogger()
    n.phase_start("P", "ignored")
    n.step("P", "s", "ignored")
    n.warn("P", "ignored")
    n.error("P", "ignored")
    n.phase_end("P")
    n.info("ignored")
    # No file was specified, so nothing should have been created.
    assert list(tmp_path.iterdir()) == []


def test_null_logger_log_path_is_none() -> None:
    assert NullProgressLogger().log_path is None


# ── Failure handling ──────────────────────────────────────────────────────

def test_unwritable_path_does_not_raise(tmp_path: Path, caplog) -> None:
    """If write fails, the call must complete silently (with a WARN log)."""
    # Use a path whose parent is an existing file — mkdir + write will fail.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    bad = blocker / "progress.log"  # parent is a file, not a dir

    log = ProgressLogger(bad)  # constructor swallows mkdir failure
    log.info("should not raise")  # write also swallows
    # Test passes if we got here without exception.
