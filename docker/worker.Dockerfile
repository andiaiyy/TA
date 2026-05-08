# ============================================================
# Celery worker image — executes ML pipelines
# ============================================================
FROM python:3.11-slim

# System deps (some sklearn/numpy operations need build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN pip install -e .

# Create storage directories (will be overridden by volume mounts)
RUN mkdir -p storage/datasets storage/artifacts

# Default command — solo pool for compatibility (prefork doesn't work on all platforms)
CMD ["celery", "-A", "workers.celery_worker", "worker", "--loglevel=info", "--pool=solo", "--concurrency=1"]
