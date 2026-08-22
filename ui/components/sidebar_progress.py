"""
Blok "Sedang berjalan" di sidebar — pemantauan eksperimen dari halaman mana pun.

Tujuannya satu: pengguna yang sedang mengisi formulir di halaman lain tetap
dapat melihat eksperimennya berjalan tanpa harus kembali ke Progress & Status.

**Pembaruan otomatis memakai fragmen, bukan rerun global.** ``st.fragment`` hanya
menjalankan ulang blok ini setiap 15 detik; sisa halaman tidak tersentuh.
Rerun global berkala (``time.sleep`` + ``st.rerun``) akan mengganggu pengguna
yang sedang mengisi metadata pipeline, memilih berkas unggahan, atau membuka
modal masuk/daftar — isian bisa hilang dan dialog tertutup.

**Logika pembacaan TIDAK ditulis ulang.** Pemilihan & pengurutan eksperimen
berjalan memakai ``select_running``; progres granular lintas-sesi dibaca lewat
``get_experiment_status`` (task_id → hasil task) lalu diterjemahkan oleh
``progress_view``; elapsed lewat ``elapsed_seconds``/``format_elapsed``;
kesehatan infrastruktur lewat ``check_execution_health``. Seluruhnya fungsi yang
sudah dipakai halaman Progress & Status.

**Tidak pernah mengarang angka.** ``progress_view`` mengembalikan None bila
progres granular tidak tersedia (tugas masih QUEUED, broker/worker mati, atau
sesi lain yang mengirim tugasnya) — baris itu menampilkan status + elapsed saja.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.components.dashboard import (
    elapsed_seconds, format_elapsed, progress_view, select_running,
)
from ui.components.sidebar_chrome import render_line, render_progress_bar

logger = logging.getLogger(__name__)

# Interval pembaruan fragmen. Cukup sering untuk terasa hidup, cukup jarang
# untuk tidak membebani broker/DB.
REFRESH_INTERVAL = "15s"

# Baris yang ditampilkan sebelum diringkas jadi "…+N lainnya". Sidebar sempit;
# lebih dari ini akan mendorong blok identitas keluar dari pandangan.
MAX_ROWS = 3

# Umur cache pembacaan DB & kesehatan infrastruktur. Lebih pendek dari interval
# fragmen, jadi setiap siklus tetap mendapat data segar — gunanya menahan
# pembacaan beruntun saat pengguna mengklik-klik (tiap rerun halaman ikut
# menggambar ulang blok ini).
CACHE_TTL = 10

# Sidebar sempit: nama pipeline dipotong dengan ellipsis, bukan dibiarkan
# membungkus dan mendorong isi lain.
TITLE_CHARS = 24
SUBTITLE_CHARS = 20

# Judul blok — gaya seragam dengan judul blok lain di sidebar.
TITLE_TEXT = "Sedang berjalan"
EMPTY_TEXT = "Tidak ada eksperimen berjalan"
UNAVAILABLE_TEXT = "Status tidak tersedia"


def shorten(text, limit: int) -> str:
    """Potong dengan ellipsis supaya muat di sidebar. Aman untuk None."""
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[: max(1, limit - 1)].rstrip() + "…"


# ── Lapis MURNI: bentuk tampilan, tanpa Streamlit & tanpa I/O ─────────────

def build_progress_view(experiments, *, status_reader=None, can_read_progress=True,
                        limit: int = MAX_ROWS, now_epoch=None) -> dict:
    """Susun isi blok sidebar dari daftar eksperimen. MURNI & dapat diuji.

    ``experiments``       daftar baris eksperimen (dict) apa adanya dari DB.
    ``status_reader``     fungsi ``id -> status_data`` (biasanya
                          ``get_experiment_status``); None berarti tidak ada
                          pembacaan lintas-sesi dan baris memakai datanya sendiri.
    ``can_read_progress`` False saat broker mati — pembacaan progres dilewati.

    Mengembalikan::

        {"rows": [...], "extra": int, "total": int, "degraded": bool}

    ``rows[i]["percent"]`` bernilai None bila progres granular tidak tersedia —
    tidak pernah diisi angka karangan.
    """
    running = select_running(experiments)
    shown, rows = running[:max(0, limit)], []

    for e in shown:
        status_data = None
        if can_read_progress and status_reader is not None:
            try:
                status_data = status_reader(e.get("id"))
            except Exception:               # pembacaan progres tidak pernah
                status_data = None          # menjatuhkan sidebar
        status_data = status_data or e

        pv = progress_view(status_data)
        seconds = elapsed_seconds(e.get("started_at") or e.get("created_at"),
                                  now_epoch)
        status = status_data.get("status") or e.get("status") or "-"
        rows.append({
            "experiment_id": e.get("id"),
            "title": shorten(e.get("pipeline_id"), TITLE_CHARS) or "?",
            "dataset": shorten(e.get("dataset_type"), SUBTITLE_CHARS),
            "status": status,
            "percent": pv["overall_percent"],
            "stage": shorten(pv["stage_label"], TITLE_CHARS + 8) or None,
            "elapsed": format_elapsed(seconds),
        })

    return {
        "rows": rows,
        "extra": max(0, len(running) - len(rows)),
        "total": len(running),
        "degraded": not can_read_progress,
    }


def row_caption(row: dict) -> str:
    """Satu baris keterangan — yang PALING informatif untuk ruang sempit.

    Fase berjalan bila diketahui (itu yang benar-benar memberi tahu di mana
    eksperimennya), kalau tidak status + elapsed. Sengaja tidak keduanya:
    gabungan fase + elapsed melebihi lebar sidebar dan membungkus jadi dua
    baris, sehingga blok identitas terdorong turun.

    Dipisah dari perenderan supaya isinya dapat diuji langsung.
    """
    stage = row.get("stage")
    if stage:
        return str(stage)
    lead = row.get("status") or "-"
    elapsed = row.get("elapsed")
    return f"{lead} · {elapsed}" if elapsed and elapsed != "—" else str(lead)


def overflow_text(extra: int) -> str:
    """Ringkasan sisa baris yang tidak ditampilkan."""
    return f"…+{extra} lainnya" if extra > 0 else ""


# ── Pembacaan data (di-cache singkat) ─────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _inflight_rows() -> list[dict]:
    """Baris RUNNING & QUEUED dari DB — dua kueri tersaring status, bukan
    seluruh tabel eksperimen."""
    from database.db import list_experiments_by_status
    return list_experiments_by_status("RUNNING") + list_experiments_by_status("QUEUED")


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _health() -> dict:
    """Kesehatan infrastruktur, memakai pemeriksaan yang sudah ada. Di-cache
    supaya broker tidak diprobe tiap kali blok ini digambar."""
    try:
        from orchestrator.health_service import check_execution_health
        return check_execution_health()
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Pemeriksaan kesehatan gagal", exc_info=True)
        return {"mode": "async", "broker_ok": False}


def _status_reader():
    """``get_experiment_status`` bila dapat diimpor; None bila tidak."""
    try:
        from orchestrator.experiment_service import get_experiment_status
        return get_experiment_status
    except Exception:                       # pragma: no cover - defensif
        return None


def load_progress_view() -> dict:
    """Baca DB + kesehatan, lalu susun tampilannya. Tidak pernah melempar."""
    try:
        rows = _inflight_rows()
    except Exception:
        logger.debug("Daftar eksperimen berjalan tidak terbaca", exc_info=True)
        return {"rows": [], "extra": 0, "total": 0, "degraded": True,
                "error": True}

    health = _health()
    async_mode = health.get("mode") == "async"
    can_read = (not async_mode) or bool(health.get("broker_ok"))

    view = build_progress_view(rows, status_reader=_status_reader(),
                               can_read_progress=can_read)
    view["error"] = False
    return view


# ── Perenderan ────────────────────────────────────────────────────────────

def row_title(row: dict) -> str:
    """Judul baris: nama pipeline, ditambah dataset bila ada. Keduanya sudah
    dipendekkan oleh ``build_progress_view``."""
    return (f"{row['title']} · {row['dataset']}" if row.get("dataset")
            else str(row["title"]))


def render_progress_block() -> None:
    """Isi blok, TANPA memasuki sidebar — pemanggilnya yang menentukan wadah.

    Seluruh baris lewat ``render_line`` supaya sisipan kirinya sama persis
    dengan item navigasi dan blok identitas.
    """
    render_line(TITLE_TEXT, muted=True, small=True)
    view = load_progress_view()

    if view.get("error"):
        render_line(UNAVAILABLE_TEXT, muted=True, small=True)
        return
    if not view["rows"]:
        render_line(EMPTY_TEXT, muted=True, small=True)
        return

    for row in view["rows"]:
        render_line(row_title(row), strong=True)
        percent = row["percent"]
        if percent is not None:
            render_progress_bar(percent)
            render_line(f"{percent}% · {row_caption(row)}", muted=True, small=True)
        else:
            # Tanpa progres granular: status + elapsed saja, tidak mengarang persen.
            render_line(row_caption(row), muted=True, small=True)

    if view["extra"]:
        render_line(overflow_text(view["extra"]), muted=True, small=True)
    if view["degraded"]:
        render_line(f"⚠ {UNAVAILABLE_TEXT} — broker tidak tersambung.",
                    muted=True, small=True)


@st.fragment(run_every=REFRESH_INTERVAL)
def render_sidebar_progress() -> None:
    """Blok progres di sidebar, memperbarui diri sendiri tiap 15 detik.

    Sidebar dimasuki DI DALAM fragmen: itu yang membuat pembaruan menggambar
    ulang di tempat yang sama alih-alih menumpuk. Hanya fungsi ini yang
    dijalankan ulang — halaman di sebelahnya tidak.
    """
    with st.sidebar:
        st.divider()
        try:
            render_progress_block()
        except Exception:                   # pragma: no cover - defensif
            # Sidebar tidak boleh error/menggantung karena worker atau broker.
            logger.debug("Blok progres sidebar gagal dirender", exc_info=True)
            st.caption(UNAVAILABLE_TEXT)
