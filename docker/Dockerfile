# ============================================================
# Main application image — Streamlit UI + Orchestrator
# ============================================================
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pengguna non-root. Kontainer ini menjalankan KODE KONTRIBUSI orang lain:
# sudah dijalankan sebagai proses terpisah dengan validasi statis dan
# verifikasi hash, tetapi sampai di sini ia berjalan sebagai root, sehingga
# satu celah pada pemuatnya berarti root di dalam kontainer. UID-nya TETAP
# (10001), bukan hasil undian: bind-mount `./storage` harus dapat ditulis,
# dan UID yang berubah antar build membuat izin folder host tidak cocok.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

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
# Kepemilikan diserahkan SEBELUM beralih pengguna: `pip install -e .` menulis
# metadata paket ke /app, dan folder storage dibuat di sini.
RUN mkdir -p storage/datasets storage/artifacts && chown -R app:app /app
# Streamlit config — disable telemetry, set server port.
# maxUploadSize (MB) harus sejalan dengan MAX_DATASET_UPLOAD_BYTES di
# ui/views/contribute.py; .streamlit/config.toml milik proyek (ikut ter-COPY di
# atas) menimpa berkas ini, keduanya sengaja disetel sama.
#
# Ditulis SELAGI ROOT dan ke SATU rumah yang dipakai kedua kemungkinan
# pengguna. Menulisnya sesudah `USER` dengan HOME dipatok /root membuat build
# non-root gagal pada `mkdir` — dan kegagalan itu baru terlihat saat
# `--build-arg RUN_AS=app` benar-benar dicoba.
ENV HOME=/home/app
RUN mkdir -p "$HOME/.streamlit" \
    && echo '[server]\nheadless = true\nport = 8501\nenableCORS = false\nenableXsrfProtection = false\nmaxUploadSize = 5120\n\n[browser]\ngatherUsageStats = false' > "$HOME/.streamlit/config.toml" \
    && chown -R app:app "$HOME"

# Pengguna yang menjalankan aplikasi. BAWAANNYA `root`, dan itu keputusan
# yang disengaja untuk host ini, bukan kelalaian:
#
# Docker Desktop di Windows memasang bind-mount lewat 9p dengan opsi
# `uid=0;gid=0`, sehingga SELURUH isi `/app/storage` tampil milik root. Folder
# tampil 0777 (membuat berkas baru berhasil), tetapi `experiments.db` tampil
# 0644 milik root — dan pengguna non-root gagal menulisnya dengan
# "attempt to write a readonly database". Opsi mount itu milik integrasi WSL
# Docker Desktop; compose maupun Dockerfile tidak dapat mengubahnya.
#
# Pada host Linux (deployment sungguhan) jalankan sebagai non-root:
#
#     docker compose build --build-arg RUN_AS=app
#     sudo chown -R 10001:10001 ./storage
#
# UID-nya TETAP 10001 supaya `chown` di host tetap cocok setelah build ulang.
ARG RUN_AS=root
USER ${RUN_AS}

EXPOSE 8501

# Initialize DB and start Streamlit
CMD python -m database.migration && streamlit run ui/app.py
