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
from html import escape

import streamlit as st
from ui.i18n import t

from ui.components.dashboard import (
    elapsed_seconds, format_elapsed, progress_view, select_running,
)
from ui.components.sidebar_chrome import render_line, render_progress_bar

logger = logging.getLogger(__name__)

# Interval pembaruan fragmen. Cukup sering untuk terasa hidup, cukup jarang
# untuk tidak membebani broker/DB.
REFRESH_INTERVAL = "15s"

# Kartu yang ditampilkan sebelum diringkas jadi "…+N lainnya". Dinaikkan dari
# tiga: bagian ini menggulir sendiri sekarang, jadi jumlah kartu tidak lagi
# menentukan seberapa jauh navigasi terdorong ke bawah. Batasnya tetap ada
# supaya pembacaan progres per eksperimen tidak tumbuh tanpa batas.
MAX_ROWS = 6

# Jumlah kartu yang muat TANPA menggulir. Lebih dari ini, bagiannya menjadi
# wadah bergulir setinggi tetap.
VISIBLE_CARDS = 2

# Tinggi wadah bergulir, kira-kira dua kartu penuh plus potongan kartu ketiga
# — potongan itulah yang memberi tahu bahwa masih ada yang di bawah.
SCROLL_HEIGHT = 210

# Umur cache pembacaan DB & kesehatan infrastruktur. Lebih pendek dari interval
# fragmen, jadi setiap siklus tetap mendapat data segar — gunanya menahan
# pembacaan beruntun saat pengguna mengklik-klik (tiap rerun halaman ikut
# menggambar ulang blok ini).
CACHE_TTL = 10

# Sidebar sempit: nama pipeline dipotong dengan ellipsis, bukan dibiarkan
# membungkus dan mendorong isi lain.
TITLE_CHARS = 24
SUBTITLE_CHARS = 20

#: Panjang maksimum nama fase pada kartu. Lebih panjang dari itu ia mendorong
#: persentase di kanannya keluar baris.
PHASE_CHARS = 22

# Judul blok — gaya seragam dengan judul blok lain di sidebar.
# Teks bahasa BAWAAN. Konstanta modul dievaluasi sekali saat impor, jadi ia
# tidak boleh menjadi hasil `t()` — nilainya akan terkunci pada bahasa yang
# kebetulan aktif saat modul pertama diimpor. Perenderannya memanggil `t()`;
# konstanta ini tetap ada sebagai nilai bahasa Indonesia dan sebagai kunci
# terjemahannya.
TITLE_TEXT = "Sedang berjalan"
TITLE_KEY = "sidebar.progress_title"
EMPTY_TEXT = "Tidak ada eksperimen berjalan"
EMPTY_KEY = "sidebar.progress_empty"
UNAVAILABLE_TEXT = "Status tidak tersedia"

#: Label tombol yang MENUMPANG kartu. Tidak pernah terlihat — CSS membuatnya
#: tembus pandang — tetapi pembaca layar membacanya, jadi ia menyebut tujuannya.
OPEN_KEY = "sidebar.progress_open"

#: Halaman yang dituju saat kartunya ditekan. Nilainya pengenal halaman di
#: `ui/app.py`, bukan labelnya: label berubah mengikuti bahasa.
RUN_PAGE = "Run Experiment"


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
            # Nama fase TELANJANG untuk kartu sidebar: "Preprocessing", bukan
            # "Fase 1/4 · Preprocessing". Yang dicari mata di sidebar adalah
            # "sedang di mana", dan nomor fase tidak menjawabnya lebih baik —
            # ia hanya memanjangkan barisnya sampai membungkus.
            "phase": shorten(pv.get("stage_name"), PHASE_CHARS) or None,
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
    return f"{lead} · {elapsed}" if elapsed and elapsed != "-" else str(lead)


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


def phase_text(row: dict) -> str:
    """Yang ditulis besar di kartu: FASE, bukan status mentah.

    Fase menjawab "sedang mengerjakan apa"; status hanya menjawab "hidup atau
    tidak", dan kartu ini sudah menjawabnya lewat titik berdenyutnya. Fase
    dipakai bila diketahui; bila belum ada (job masih QUEUED, atau broker tidak
    terbaca) barulah statusnya — sebab mengarang nama fase lebih buruk daripada
    menyebut keadaan apa adanya.
    """
    return str(row.get("phase") or row.get("status") or "-")


def run_card_html(row: dict, *, aktif: bool = False) -> str:
    """Kartu satu eksperimen berjalan. MURNI: string, tanpa Streamlit.

    Empat baris, semuanya pendek: penanda hidup, nama pipeline, nama dataset,
    lalu fase berdampingan dengan persentasenya di atas bar tipis.

    Yang SENGAJA tidak ada di sini: waktu berjalan, nomor fase, status mentah
    di samping fase, dan keterangan broker. Sidebar bukan tempat melaporkan —
    ia tempat memberi tahu sekilas bahwa ada yang berjalan dan sampai mana.

    Persentase hanya ditulis bila memang ada. Progres granular tidak selalu
    tersedia, dan "0%" untuk yang tidak diketahui adalah angka karangan.
    """
    pct = row.get("percent")
    ada_pct = isinstance(pct, (int, float))
    lebar = max(0, min(100, int(pct))) if ada_pct else 0

    kanan = (f'<span class="ids-run-pct">{lebar}%</span>' if ada_pct else "")
    # Pipeline DAN dataset pada SATU baris, dipisah titik tengah. Keduanya
    # bersama-sama adalah identitas run ini — "pipeline mana atas data mana" —
    # dan memecahnya menjadi dua baris membuat mata membacanya sebagai dua
    # fakta terpisah, sekaligus menambah tinggi tiap kartu.
    nama = escape(str(row.get("title") or "?"))
    if row.get("dataset"):
        nama += (f'<span class="ids-run-dot-sep">·</span>'
                 f'<span class="ids-run-ds">{escape(str(row["dataset"]))}</span>')
    # Bar hanya digambar bila persentasenya diketahui: jalur kosong yang tidak
    # pernah terisi terbaca seperti progres yang macet di nol.
    bar = (f'<div class="ids-run-track">'
           f'<div class="ids-run-fill" style="width:{lebar}%"></div></div>'
           if ada_pct else "")

    # Kartu yang SEDANG dipantau ditandai, supaya pengguna yang kembali ke
    # sidebar mengenali mana yang barusan ia buka di antara beberapa yang
    # berjalan. Penandanya tepi tipis, bukan latar pekat: ia menjawab "yang
    # ini", bukan "yang ini penting".
    kelas = "ids-run ids-run--active" if aktif else "ids-run"
    return (
        f'<div class="{kelas}">'
        '<div class="ids-run-live"><span class="ids-run-dot"></span>'
        f'{escape(t(TITLE_KEY))}</div>'
        f'<div class="ids-run-name">{nama}</div>'
        f'<div class="ids-run-foot">'
        f'<span class="ids-run-phase">{escape(phase_text(row))}</span>{kanan}'
        f'</div>{bar}'
        '</div>'
    )


def _open_running(experiment_id) -> None:
    """Buka halaman Jalankan Eksperimen pada eksperimen yang sedang berjalan.

    Tiga hal disetel sekaligus, dan ketiganya memang diperlukan: halaman yang
    dituju, tampilan eksekusi di dalam halaman itu, dan eksperimen mana yang
    dipantau. Menyetel halamannya saja akan mendarat di katalog pipeline —
    bukan di layar progres yang sedang dicari pengguna.

    Kuncinya kunci yang SUDAH dipakai aplikasi ini, bukan mekanisme kedua:
    `polling_experiment_id` adalah kunci yang sama yang dipakai halaman itu
    sendiri saat ia menjalankan eksperimen.
    """
    from ui.components import page_flags
    from ui.views import run_experiment as rx

    if experiment_id:
        st.session_state["polling_experiment_id"] = experiment_id
    rx.go_to_execute()
    page_flags.request_page(RUN_PAGE)


def render_progress_block() -> None:
    """Kartu status eksperimen berjalan, TANPA memasuki sidebar.

    Satu kartu, satu eksperimen — yang paling depan di antrean. Bila ada lebih
    dari satu, sisanya dihitung sebagai satu baris pendek alih-alih digambar
    sebagai tumpukan kartu: sidebar bukan tabel.

    SELURUH kartu dapat diklik. Tombolnya ditumpangkan tepat di atas kartu dan
    dibuat tembus pandang lewat CSS, jadi yang terlihat kartunya sementara yang
    ditekan sebuah tombol Streamlit sungguhan — dengan fokus papan ketik dan
    pembacaan layar yang ikut bekerja. Tautan HTML akan lebih sederhana, tetapi
    ia memuat ulang halaman dan membuang keadaan sesi, termasuk eksperimen yang
    sedang dipantau.
    """
    view = load_progress_view()

    # Keadaan kosong TIDAK memakai kartu: kotak berbatas untuk mengatakan
    # "tidak ada apa-apa" justru membuat ketiadaan itu menonjol.
    if view.get("error"):
        render_line(UNAVAILABLE_TEXT, muted=True, small=True)
        return
    if not view["rows"]:
        render_line(t(EMPTY_KEY), muted=True, small=True)
        return

    # SATU kartu per eksperimen. Menggabungkan beberapa run ke dalam satu
    # kartu "sedang berjalan" akan menyembunyikan justru yang perlu dibedakan:
    # run mana yang sedang di fase mana, dan mana yang hendak dibuka.
    dipantau = st.session_state.get("polling_experiment_id")
    rows = view["rows"]

    # Menggulir SENDIRI begitu kartunya lebih dari dua. Tanpa itu, empat run
    # mendorong pengalih bahasa dan pemilih peran keluar dari pandangan —
    # navigasi kalah oleh sesuatu yang hanya berlangsung beberapa menit.
    wadah = (st.container(height=SCROLL_HEIGHT, border=False)
             if len(rows) > VISIBLE_CARDS else st.container())
    with wadah:
        for row in rows:
            eid = row.get("experiment_id")
            with st.container():
                st.markdown('<span class="ids-run-card"></span>',
                            unsafe_allow_html=True)
                st.markdown(run_card_html(row, aktif=bool(eid) and eid == dipantau),
                            unsafe_allow_html=True)
                # Kunci tombol memuat id eksperimennya: dua kartu dengan kunci
                # yang sama akan menjadi satu widget, dan menekan yang kedua
                # membuka yang pertama.
                if st.button(t(OPEN_KEY), key=f"run_card_open_{eid}",
                             use_container_width=True):
                    _open_running(eid)
                    # Fragmen: tanpa `scope="app"` yang tergambar ulang hanya
                    # blok ini, dan halamannya tidak pernah berpindah.
                    st.rerun(scope="app")

    if view["extra"]:
        render_line(overflow_text(view["extra"]), muted=True, small=True)



@st.fragment(run_every=REFRESH_INTERVAL)
def render_sidebar_progress() -> None:
    """Blok progres di sidebar, memperbarui diri sendiri tiap 15 detik.

    Sidebar dimasuki DI DALAM fragmen: itu yang membuat pembaruan menggambar
    ulang di tempat yang sama alih-alih menumpuk. Hanya fungsi ini yang
    dijalankan ulang — halaman di sebelahnya tidak.
    """
    with st.sidebar:
        # TANPA garis pemisah: kartunya sendiri yang memisahkan blok ini dari
        # navigasi di atasnya. Garis DAN kotak sekaligus berarti dua pembatas
        # untuk satu batas.
        try:
            render_progress_block()
        except Exception:                   # pragma: no cover - defensif
            # Sidebar tidak boleh error/menggantung karena worker atau broker.
            logger.debug("Blok progres sidebar gagal dirender", exc_info=True)
            st.caption(UNAVAILABLE_TEXT)
