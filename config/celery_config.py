"""
Celery configuration.

Centralized config so both the worker and experiment_service
use the same broker/backend settings.
"""
import os

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Set to True to use async (Celery), False to use sync (local_worker)
USE_ASYNC = os.environ.get("USE_ASYNC", "false").lower() == "true"
