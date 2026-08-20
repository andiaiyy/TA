# ============================================================
# Main application image — Streamlit UI + Orchestrator
# ============================================================
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
# --no-build-isolation: reuse the setuptools already installed in the image
# instead of fetching an isolated build env from PyPI (resilient to offline/
# flaky-network builds).
RUN pip install -e . --no-build-isolation

# Create storage directories (will be overridden by volume mounts)
RUN mkdir -p storage/datasets storage/artifacts

# Streamlit config — disable telemetry, set server port.
# maxUploadSize (MB) harus sejalan dengan MAX_DATASET_UPLOAD_BYTES di
# ui/views/contribute.py; .streamlit/config.toml milik proyek (ikut ter-COPY di
# atas) menimpa berkas ini, keduanya sengaja disetel sama.
RUN mkdir -p /root/.streamlit
RUN echo '[server]\nheadless = true\nport = 8501\nenableCORS = false\nenableXsrfProtection = false\nmaxUploadSize = 5120\n\n[browser]\ngatherUsageStats = false' > /root/.streamlit/config.toml

EXPOSE 8501

# Initialize DB and start Streamlit
CMD python -m database.migration && streamlit run ui/app.py
