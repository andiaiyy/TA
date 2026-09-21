# ============================================================
# Celery worker image — executes ML pipelines
# ============================================================
FROM python:3.11-slim

# System deps (some sklearn/numpy operations need build tools)
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

# Install Python deps
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
ENV HOME=/home/app
ARG RUN_AS=root
USER ${RUN_AS}

# Default command — solo pool for compatibility (prefork doesn't work on all platforms)
CMD ["celery", "-A", "workers.celery_worker", "worker", "--loglevel=info", "--pool=solo", "--concurrency=1"]
