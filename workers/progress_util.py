"""
Progress payload enrichment — turns a plain stage-name string emitted by a
pipeline into the granular, Jenkins-style progress payload consumed by the UI.

Design constraints (see tests/test_progress_schema.py):
  - Pure and side-effect free — no Celery, no DB, no I/O. Easy to unit-test.
  - The pipeline callback contract stays ``progress(stage: str)`` (a string), so
    this enrichment happens DOWNSTREAM in the worker, never inside pipelines.
  - ``overall_percent`` is MONOTONIC: callers pass the previous value and it is
    clamped so the global bar never moves backwards, even for unknown/wrapper
    stages ("Executing pipeline...", "Saving results...").
  - Backward compatible: the returned dict always contains a ``"stage"`` key
    (the raw string) so older consumers keep working.

Progress is pure observation. It is emitted via the Celery task state (Redis),
never written to SQLite, so there is no DB-write amplification to throttle.
"""
from __future__ import annotations

from typing import Optional


PROGRESS_FIELDS = (
    "stage", "stage_name", "stage_index", "stage_total",
    "stage_percent", "overall_percent", "message",
)


def _stages_for(pipeline_id: str) -> list[str]:
    """Ordered stage labels for a pipeline, from the registry. [] if unknown."""
    try:
        from config.pipeline_registry import get_pipeline
        entry = get_pipeline(pipeline_id) or {}
        stages = entry.get("stages") or []
        return list(stages) if isinstance(stages, (list, tuple)) else []
    except Exception:
        return []


def build_progress_meta(
    pipeline_id: str,
    stage_name: str,
    *,
    stage_percent: float = 0.0,
    last_index: int = 0,
    last_overall: int = 0,
    message: Optional[str] = None,
) -> dict:
    """Enrich a stage-name string into a granular progress payload.

    Args:
        pipeline_id:  registry key (used to resolve the ordered stage list).
        stage_name:   the raw stage label the pipeline emitted.
        stage_percent: 0..100 progress WITHIN the current stage (usually 0 at a
                       boundary; the UI animates within-stage on top of this).
        last_index:   previously reported 1-based stage index (for monotonicity
                      when the current stage is unknown, e.g. wrapper stages).
        last_overall: previously reported overall_percent (clamp floor).
        message:      optional short status text (defaults to stage_name).

    Returns:
        dict with keys PROGRESS_FIELDS. ``overall_percent`` is >= last_overall.
    """
    stages = _stages_for(pipeline_id)
    total = len(stages)

    index: Optional[int] = None
    for i, s in enumerate(stages, start=1):
        if s == stage_name:
            index = i
            break

    # Unknown stage (wrapper stage, or a label not in the registry list):
    # keep the last known index so the bar does not jump around.
    effective_index = index if index is not None else max(int(last_index), 0)

    # clamp within-stage percent to [0, 100]
    try:
        sp = float(stage_percent)
    except (TypeError, ValueError):
        sp = 0.0
    sp = max(0.0, min(100.0, sp))

    if total > 0 and effective_index > 0:
        # Overall = completed-stage floor + within-current-stage contribution.
        # A stage entry (sp=0) reports the floor of the stage just started, so
        # the bar reaches 100 only when the run is FINISHED (handled by the UI),
        # never merely on entering the last stage.
        completed = effective_index - 1
        overall = (completed + sp / 100.0) / total * 100.0
        overall_int = int(round(overall))
    else:
        # Unknown pipeline/stage — small non-zero so the bar shows life.
        overall_int = 5

    # Monotonic: never below the previously reported overall.
    overall_int = max(overall_int, int(last_overall), 0)
    overall_int = min(overall_int, 100)

    return {
        "stage": stage_name,                 # backward-compat key (kept as str)
        "stage_name": stage_name,
        "stage_index": index if index is not None else (effective_index or None),
        "stage_total": total or None,
        "stage_percent": round(sp, 1),
        "overall_percent": overall_int,
        "message": message if message is not None else stage_name,
    }


def build_stage_view(
    stage_total: int,
    current_index: Optional[int],
    status: str,
    starts: dict,
    now_ts: float,
) -> list[dict]:
    """Per-stage status + duration for the horizontal Jenkins-style view.

    Pure and side-effect free (no Streamlit) so it is unit-testable. Durations
    are derived from observed stage-entry timestamps (``starts``: {1-based index
    -> first-seen epoch seconds}); a duration is None ("—") when it cannot be
    computed from what was actually observed during polling.

    Args:
        stage_total:   number of stages.
        current_index: 1-based index of the running stage (or None).
        status:        DB status string (RUNNING / QUEUED / FINISHED / ...).
        starts:        {stage_index: first-seen epoch seconds} accumulated by UI.
        now_ts:        current epoch seconds (for the running stage's elapsed).

    Returns:
        list of {index, state ('done'|'running'|'waiting'), duration_sec|None},
        one entry per stage, in order.
    """
    total = int(stage_total or 0)
    finished = str(status).upper() == "FINISHED"
    cur = current_index if isinstance(current_index, int) else None

    view: list[dict] = []
    for i in range(1, total + 1):
        if finished or (cur is not None and i < cur):
            state = "done"
        elif cur is not None and i == cur:
            state = "running"
        else:
            state = "waiting"

        # Duration: a completed stage lasts from its start until the next stage
        # started; the running stage lasts from its start until now. Unknown
        # (None) when the relevant timestamps were not observed during polling.
        dur = None
        s_i = starts.get(i)
        if state == "done":
            s_next = starts.get(i + 1)
            if s_i is not None and s_next is not None and s_next >= s_i:
                dur = s_next - s_i
        elif state == "running":
            if s_i is not None:
                dur = max(0.0, now_ts - s_i)
        view.append({"index": i, "state": state, "duration_sec": dur})
    return view


def format_duration(seconds: Optional[float]) -> str:
    """Compact human duration ('—' when unknown)."""
    if seconds is None:
        return "—"
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"
