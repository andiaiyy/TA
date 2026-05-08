---
name: SQLite + Docker bind mount + multi-container = correctness hazard
description: WAL mode does not magically make SQLite safe across container processes sharing a host bind-mount; document the failure modes during reviews.
type: feedback
---

When SQLite (especially with WAL) is shared across multiple containers via a bind mount, flag these specific risks:
- WAL/SHM files (`-wal`, `-shm`) are mmap'd; bind mounts on Docker Desktop (Windows/macOS via gRPC-FUSE / virtiofs) historically have broken POSIX file locking and mmap coherence. WAL relies on shared-memory coordination via `-shm`.
- `fsync` on overlay/bind mounts is not always honored. Power loss / `docker kill` can leave a half-written WAL the other container can't recover.
- A worker crash mid-write does not corrupt the main DB *file*, but a stuck `-shm` file with a dead process still listed as a connection can block recovery on next open.
- WAL checkpoint requires writer access from *some* connection; readers alone cannot checkpoint, and an unbounded WAL grows without bound.

**Why:** This is a class of bug that "works on my laptop, fails in CI/prod." Repeatedly seen.

**How to apply:** When the architecture has SQLite + multi-container shared volume, push hard for either (a) a real DB (Postgres in compose), or (b) all DB writes funneled through a single process (e.g., the worker), with the UI reading via API/IPC, never opening sqlite directly.
