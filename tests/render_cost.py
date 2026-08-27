"""Penghitung PEKERJAAN BERAT pada satu render halaman.

Kesan "lambat" pada Streamlit hampir selalu berasal dari pekerjaan yang diulang
pada setiap interaksi, bukan dari gayanya. Modul ini membuat pekerjaan itu
TERUKUR: satu definisi yang dipakai laporan maupun test, sehingga angka yang
dilaporkan tidak mungkin berbeda dari yang diuji.

**Yang dihitung**

``db``      — setiap sambungan basis data dibuka (``database.db.get_connection``
              adalah satu-satunya pintu; seluruh kueri melewatinya).
``listdir`` — setiap penelusuran isi folder (``Path.glob`` / ``Path.iterdir``).
``stat``    — setiap pembacaan metadata berkas (``Path.stat``).
``open``    — setiap berkas DATA dibuka (hanya di bawah ``storage/``). Impor
              modul Python juga memakai ``open``; ikut menghitungnya akan
              menenggelamkan angka yang kita pedulikan di bawah puluhan
              pembacaan yang hanya terjadi sekali seumur proses.

**Cara memakainya**::

    with RenderCost() as cost:
        render_page(...)
    print(cost.counts)

Penghitung dipasang lewat ``monkeypatch``-style penggantian atribut, lalu
dikembalikan lagi saat keluar — tidak ada modul yang berubah permanen.
"""
from __future__ import annotations

import builtins
from pathlib import Path

#: Hanya pembacaan DI BAWAH folder ini yang dihitung sebagai pembacaan berkas.
DATA_ROOT = (Path(__file__).resolve().parents[1] / "storage").resolve()


def _is_data_path(value) -> bool:
    """True bila `value` menunjuk ke sesuatu di dalam ``storage/``."""
    try:
        return DATA_ROOT in Path(str(value)).resolve().parents
    except Exception:                       # pragma: no cover - defensif
        return False


class RenderCost:
    """Penghitung pekerjaan berat, dipakai sebagai context manager."""

    KINDS = ("db", "listdir", "stat", "open")

    def __init__(self) -> None:
        self.counts: dict[str, int] = {kind: 0 for kind in self.KINDS}
        self._restore: list[tuple] = []

    # ── pemasangan ────────────────────────────────────────────────────────

    def _wrap(self, owner, name: str, kind: str, *, data_only: bool = False) -> None:
        original = getattr(owner, name)

        def counted(*args, **kwargs):
            if not data_only or (args and _is_data_path(args[0])):
                self.counts[kind] += 1
            return original(*args, **kwargs)

        setattr(owner, name, counted)
        self._restore.append((owner, name, original))

    def __enter__(self) -> "RenderCost":
        import database.db as db

        self._wrap(db, "get_connection", "db")
        self._wrap(Path, "glob", "listdir")
        self._wrap(Path, "iterdir", "listdir")
        self._wrap(Path, "stat", "stat", data_only=True)
        self._wrap(builtins, "open", "open", data_only=True)
        return self

    def __exit__(self, *_exc) -> bool:
        for owner, name, original in reversed(self._restore):
            setattr(owner, name, original)
        self._restore.clear()
        return False

    # ── pembacaan ─────────────────────────────────────────────────────────

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def __str__(self) -> str:                # pragma: no cover - alat laporan
        parts = " · ".join(f"{k}={self.counts[k]}" for k in self.KINDS)
        return f"{parts} (total {self.total})"


def clear_streamlit_caches() -> None:
    """Kosongkan cache Streamlit supaya pengukuran tidak dibantu run sebelumnya.

    Pengukuran yang jujur harus mengukur render PERTAMA — render kedua tentu
    lebih murah karena cache-nya sudah panas, dan itu bukan yang membuat
    pengguna menunggu.
    """
    import streamlit as st

    try:
        st.cache_data.clear()
    except Exception:                       # pragma: no cover - defensif
        pass
    try:
        st.cache_resource.clear()
    except Exception:                       # pragma: no cover - defensif
        pass
