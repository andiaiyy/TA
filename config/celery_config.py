"""
Celery configuration.

Centralized config so both the worker and experiment_service
use the same broker/backend settings.

CONCURRENCY NOTE:
  CELERY_CONCURRENCY defaults to 1 — one experiment at a time.
  This is intentional: ML pipelines are CPU/RAM intensive and concurrent
  runs will OOM on most research machines (e.g. 3 × SVC on 500K rows).
  To allow more concurrent runs, set CELERY_CONCURRENCY in the environment,
  but monitor RAM usage carefully.
"""
import os

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Set to True to use async (Celery), False to use sync (local_worker)
USE_ASYNC = os.environ.get("USE_ASYNC", "false").lower() == "true"

# One experiment at a time — prevents OOM on large datasets (see note above)
CELERY_CONCURRENCY = int(os.environ.get("CELERY_CONCURRENCY", "1"))
