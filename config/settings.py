"""
Central configuration — all paths and settings.

Supports both local development and Docker deployment.
Docker containers override paths via environment variables.
"""
import os
import platform
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
ARTIFACTS_DIR = STORAGE_DIR / "artifacts"
DATASETS_DIR = STORAGE_DIR / "datasets"
DB_PATH = os.environ.get("DB_PATH", str(STORAGE_DIR / "experiments.db"))


def get_environment_info() -> dict:
    """
    Collect environment information for experiment metadata.
    Captures Python version, platform, key library versions,
    and Docker image version if running in container.
    """
    import sys

    info = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
    }

    try:
        import sklearn
        info["sklearn_version"] = sklearn.__version__
    except ImportError:
        pass

    try:
        import pandas
        info["pandas_version"] = pandas.__version__
    except ImportError:
        pass

    try:
        import numpy
        info["numpy_version"] = numpy.__version__
    except ImportError:
        pass

    info["is_docker"] = _is_running_in_docker()

    docker_image = os.environ.get("DOCKER_IMAGE_VERSION", None)
    if docker_image:
        info["docker_image_version"] = docker_image
    elif info["is_docker"]:
        info["docker_image_version"] = "unknown (set DOCKER_IMAGE_VERSION env)"

    return info


def _is_running_in_docker() -> bool:
    """Detect if running inside a Docker container."""
    if Path("/.dockerenv").exists():
        return True
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read()
    except (FileNotFoundError, PermissionError):
        return False
