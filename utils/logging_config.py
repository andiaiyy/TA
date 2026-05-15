"""
Logging configuration.

Call setup_logging() once at application startup (ui/app.py and celery_worker.py).

Format:
  - Local dev: human-readable with timestamp
  - Docker (JSON_LOGS=true): structured JSON for log aggregation
"""
import logging
import os
import sys


def setup_logging(level: int | None = None) -> None:
    """
    Configure root logger.

    Reads LOG_LEVEL from environment (DEBUG, INFO, WARNING, ERROR).
    Reads JSON_LOGS from environment — set to "true" for Docker JSON format.
    """
    if level is None:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    use_json = os.environ.get("JSON_LOGS", "false").lower() == "true"

    if use_json:
        fmt = '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("streamlit").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)
