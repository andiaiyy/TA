"""
Structured progress logger for pipeline execution.

Writes one JSON event per line to a per-experiment log file at
``storage/artifacts/{experiment_id}/progress.log``. The UI tails this
file across process boundaries (Streamlit + Celery worker share the
storage volume), so each write is opened fresh, written, flushed, and
closed — no cross-call buffering.

A logging failure must NEVER crash a pipeline. All I/O is wrapped in
try/except; failures are reported via Python ``logging`` at WARNING.

Two implementations live in this module:

* ``ProgressLogger`` — writes events to disk.
* ``NullProgressLogger`` — same surface, every method a no-op. Used as
  the default for CLI runs and tests so pipelines can call the logger
  unconditionally.

Event schema (one JSON object per line):

    {"ts": "<ISO-8601 UTC ms>", "event": "phase_start" | "phase_end"
        | "step" | "warn" | "error" | "info",
     "phase": "<phase name>"     (optional for "info"),
     "step":  "<step name>"      (only for "step"),
     "message": "<free text>",
     "duration_seconds": <float> (only for "phase_end" when supplied)}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """ISO-8601 UTC with millisecond precision, e.g. 2026-05-22T10:34:18.412+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ProgressLogger:
    """Append-mode JSONL progress logger. One file per experiment."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = Path(log_path)
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            # Don't raise — pipelines must run even if the log path is bad.
            logger.warning(
                "ProgressLogger: could not create parent dir for %s: %s",
                self._log_path, e,
            )

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ─── Public API ──────────────────────────────────────────────────────

    def phase_start(self, phase: str, message: str = "") -> None:
        self._write({"event": "phase_start", "phase": phase, "message": message})

    def phase_end(
        self,
        phase: str,
        message: str = "",
        duration_seconds: Optional[float] = None,
    ) -> None:
        payload = {"event": "phase_end", "phase": phase, "message": message}
        if duration_seconds is not None:
            payload["duration_seconds"] = float(duration_seconds)
        self._write(payload)

    def step(self, phase: str, step: str, message: str = "") -> None:
        self._write({"event": "step", "phase": phase, "step": step, "message": message})

    def warn(self, phase: str, message: str) -> None:
        self._write({"event": "warn", "phase": phase, "message": message})

    def error(self, phase: str, message: str) -> None:
        self._write({"event": "error", "phase": phase, "message": message})

    def info(self, message: str) -> None:
        # No phase context — used at experiment-level boundaries
        # ("Experiment started", "Experiment finished", etc.).
        self._write({"event": "info", "message": message})

    # ─── Internal ────────────────────────────────────────────────────────

    def _write(self, payload: dict) -> None:
        payload = {"ts": _now_iso(), **payload}
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False))
                f.write("\n")
                f.flush()
        except Exception as e:
            # Logging the failure but never raising — a pipeline must keep
            # running even if the disk is full or read-only.
            logger.warning(
                "ProgressLogger: write to %s failed (%s) — event dropped: %r",
                self._log_path, e, payload,
            )


class NullProgressLogger:
    """No-op logger. Used when no log path is supplied (CLI, tests)."""

    log_path: Optional[Path] = None

    def phase_start(self, phase: str, message: str = "") -> None: pass
    def phase_end(self, phase: str, message: str = "",
                  duration_seconds: Optional[float] = None) -> None: pass
    def step(self, phase: str, step: str, message: str = "") -> None: pass
    def warn(self, phase: str, message: str) -> None: pass
    def error(self, phase: str, message: str) -> None: pass
    def info(self, message: str) -> None: pass


def read_progress_log(log_path: Path) -> list[dict]:
    """Read all events from a progress log file in order.

    Returns ``[]`` if the file is missing, empty, or unreadable. Malformed
    lines (partial writes seen mid-tail) are skipped silently — callers
    re-read on poll, so eventual consistency is fine.
    """
    p = Path(log_path)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Partial line during a concurrent write — skip it.
                    continue
    except Exception as e:
        logger.warning("read_progress_log: failed to read %s: %s", p, e)
        return []
    return out
