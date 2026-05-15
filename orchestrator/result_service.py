"""
Result service — read-only experiment queries.
"""
from database.db import get_experiment, list_experiments, list_experiments_by_status
from utils.artifact_saver import load_metrics, load_metadata


def list_all_experiments() -> list[dict]:
    """Return all experiments ordered by created_at DESC."""
    return list_experiments()


def list_experiments_page(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """
    Return a page of experiments and the total count.

    Returns:
        (experiments, total_count)
    """
    from database.db import list_experiments_paginated
    return list_experiments_paginated(limit=limit, offset=offset)


def list_by_status(status: str) -> list[dict]:
    """Return experiments filtered by status."""
    return list_experiments_by_status(status)


def get_experiment_detail(experiment_id: str) -> dict | None:
    """Return single experiment row, or None."""
    return get_experiment(experiment_id)


def get_experiment_metrics(experiment_id: str) -> dict | None:
    """Load metrics JSON for an experiment. Returns None if not found."""
    return load_metrics(experiment_id)


def get_experiment_metadata(experiment_id: str) -> dict | None:
    """Load metadata JSON for an experiment. Returns None if not found."""
    return load_metadata(experiment_id)


def get_full_experiment(experiment_id: str) -> dict | None:
    """Return experiment row + metrics + metadata. Returns None if experiment not found."""
    experiment = get_experiment(experiment_id)
    if experiment is None:
        return None
    return {
        "experiment": experiment,
        "metrics": load_metrics(experiment_id),
        "metadata": load_metadata(experiment_id),
    }
