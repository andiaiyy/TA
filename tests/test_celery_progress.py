"""Tests for coarse Celery PROGRESS state emission from run_pipeline_task.

The worker emits a custom "PROGRESS" state at two boundaries via the
``_safe_update_state`` helper:
  - just before execute_pipeline (stage mentions "execut")
  - just after execute_pipeline, before artifact save (stage mentions "sav")

Failures of update_state must never propagate — the task must still
complete and call set_finished.

Implementation note: the task is decorated with ``bind=True``, so we
invoke it through ``run_pipeline_task.run(...)`` which is the original
function bound to the task instance. ``self`` inside the task body is
the (singleton) registered task object, so to intercept update_state we
patch the method on that instance for the duration of the test.
"""
from unittest.mock import patch, MagicMock

import pandas as pd

from workers import celery_worker


def _fake_result():
    """Minimal PipelineResult-shaped object for the task body to consume."""
    r = MagicMock()
    r.accuracy = 0.9
    r.precision = 0.9
    r.recall = 0.9
    r.f1_score = 0.9
    r.confusion_matrix = [[1, 0], [0, 1]]
    r.extra_info = {}
    r.label_mapping = {"benign": 0, "attack": 1}
    r.feature_names = ["f1", "f2"]
    r.model = MagicMock()
    return r


def _run_task_with_patched_update_state(update_state_mock):
    """Invoke the task body with all I/O patched out. ``update_state_mock``
    replaces the bound task's ``update_state`` method so we can observe
    or fail progress reports without touching a real broker."""
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    task = celery_worker.run_pipeline_task
    with patch.object(celery_worker, "get_experiment", return_value=None), \
         patch.object(celery_worker, "set_running"), \
         patch.object(celery_worker, "sha256_file", return_value="deadbeef"), \
         patch.object(celery_worker, "parse_dataset", return_value=df), \
         patch.object(celery_worker, "execute_pipeline", return_value=_fake_result()), \
         patch.object(celery_worker, "save_all_artifacts",
                      return_value={"metrics_path": "/tmp/m.json", "model_path": "/tmp/m.pkl"}), \
         patch.object(celery_worker, "set_finished") as mock_set_finished, \
         patch.object(celery_worker, "now_iso", return_value="2026-01-01T00:00:00Z"), \
         patch.object(task, "update_state", new=update_state_mock):
        result = task.run(
            experiment_id="exp-progress",
            dataset_type="HIKARI2021",
            dataset_path="/fake/path.csv",
            pipeline_id="hikari2021.nbgc_pipeline",
        )
    return result, mock_set_finished


def test_progress_emitted_at_both_boundaries():
    """update_state must be called with state='PROGRESS' and non-empty
    meta['stage'] at least twice — one referencing execution, one
    referencing saving."""
    update_state = MagicMock()
    result, _ = _run_task_with_patched_update_state(update_state)

    assert result["success"] is True

    progress_calls = [
        call for call in update_state.call_args_list
        if call.kwargs.get("state") == "PROGRESS"
    ]
    assert len(progress_calls) >= 2, (
        f"Expected at least 2 PROGRESS updates, got {len(progress_calls)}: "
        f"{update_state.call_args_list}"
    )

    stages = [call.kwargs["meta"]["stage"].lower() for call in progress_calls]
    assert all(s for s in stages), f"Empty stage string in {stages}"
    assert any("execut" in s for s in stages), f"No execution stage in {stages}"
    assert any("sav" in s for s in stages), f"No save stage in {stages}"


def test_progress_failure_does_not_break_task():
    """If update_state raises (e.g. broker down), _safe_update_state must
    swallow it: the task still completes and set_finished is still called."""
    update_state = MagicMock(side_effect=RuntimeError("broker unreachable"))
    result, mock_set_finished = _run_task_with_patched_update_state(update_state)

    # update_state was attempted at least once and raised every time…
    assert update_state.called
    # …but the task still finished successfully.
    assert result["success"] is True
    mock_set_finished.assert_called_once()
