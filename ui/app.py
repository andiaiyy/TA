"""
Streamlit entrypoint.
Run: streamlit run ui/app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.logging_config import setup_logging
setup_logging()

import logging
logger = logging.getLogger(__name__)

import streamlit as st
from database.db import init_db

init_db()


@st.cache_resource
def _seed_admin_once():
    """Buat admin pertama dari environment (idempoten, sekali per server).

    Tidak pernah menimpa akun yang sudah ada, dan tidak membuat apa pun bila
    ADMIN_PASSWORD tidak diset — lihat orchestrator/auth_service.py.
    """
    try:
        from orchestrator.auth_service import ensure_admin_seed
        return bool(ensure_admin_seed())
    except Exception:
        logger.warning("Seed admin gagal dijalankan", exc_info=True)
        return False


_seed_admin_once()


@st.cache_resource
def _startup_cleanup():
    """Run once per server lifetime — not on every Streamlit rerun."""
    from orchestrator.experiment_service import cleanup_stale_experiments
    cleaned = cleanup_stale_experiments()
    if cleaned > 0:
        logger.info("Startup cleanup: removed %d stale experiment(s)", cleaned)


_startup_cleanup()

st.set_page_config(page_title="IDS Research Pipeline System", page_icon="", layout="wide")

# ── Small-screen CSS (media query gated; desktop untouched) ──────────────
# All rules are scoped to viewport widths <= 768px (tablet portrait & phone).
# Desktop layout (layout="wide", >768px) is the primary target and is NOT
# affected by any rule below. Rules only:
#   1. Trim the wide page padding so content does not waste edges.
#   2. Shrink h1/h2 so headings do not dominate the small viewport.
#   3. Shrink metric value font so 3-4 metric cards fit without overflow.
#   4. Allow horizontal scroll on dataframes, AgGrid, and column rows that
#      overflow — safer than restacking, which depends on Streamlit DOM
#      internals that can shift between versions.
# Add !important only where needed to defeat Streamlit's default inline styles.
st.markdown(
    """
<style>
@media (max-width: 768px) {
    .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1rem !important;
    }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.25rem !important; }
    h3 { font-size: 1.1rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.25rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
    [data-testid="stDataFrame"], .stDataFrame, .ag-theme-streamlit, .ag-root-wrapper {
        overflow-x: auto !important;
    }
    [data-testid="stHorizontalBlock"] {
        overflow-x: auto !important;
    }
}
</style>
""",
    unsafe_allow_html=True,
)

# ── Identitas (TANPA gerbang) ─────────────────────────────────────────────
# Aplikasi terbuka langsung dalam mode pengunjung: tidak ada login yang
# memblokir halaman mana pun. Melihat riwayat dan menjalankan eksperimen bebas
# dilakukan siapa saja; yang dibatasi hanyalah aksi berisiko (unggah/setujui/
# kelola pengguna), diperiksa di titik aksinya masing-masing lewat
# orchestrator.auth_service. Switch mode dirender setelah menu halaman.
from ui.views.login import maybe_render_auth_dialog, render_mode_switch

# ── Sidebar navigation ────────────────────────────────────────────────────
# Centralised routing: option_menu returns the selected label, and a single
# dispatch table below routes to each page's render() function. The two
# pages are independent modules in ui/views/. No ui/pages/ folder is used,
# so there is no conflict with Streamlit's built-in multipage navigation.
#
# Defensive: if streamlit-option-menu is not installed (e.g. an older clone
# of the repo without the dep installed), fall back to a plain radio so the
# app stays usable and the user gets a clear hint to install it.

_PAGES = ("Progress & Status", "Run Experiment", "Add Pipeline & Dataset")
_PAGE_ICONS = ("speedometer2", "play-circle", "plus-square")
# Landing page shown when the app first opens. "Progress & Status" is the main
# dashboard (all experiments + live progress); index is resolved by name so menu
# order can change freely without breaking the default.
_DEFAULT_PAGE = "Progress & Status"

try:
    from streamlit_option_menu import option_menu
    _OPTION_MENU_AVAILABLE = True
except Exception as _e:
    option_menu = None
    _OPTION_MENU_AVAILABLE = False
    logger.warning("streamlit-option-menu not available, falling back to radio: %s", _e)


_ACCENT = "#2563eb"  # consistent with the accent already used in other UI


_CURRENT_PAGE_KEY = "_current_page"


def _remembered_index() -> int:
    """Indeks halaman yang sedang dibuka, supaya rerun (mis. setelah masuk
    lewat switch mode di sidebar) mengembalikan pengguna ke halaman yang SAMA —
    bukan melempar ke halaman default."""
    current = st.session_state.get(_CURRENT_PAGE_KEY, _DEFAULT_PAGE)
    if current not in _PAGES:
        current = _DEFAULT_PAGE
    return _PAGES.index(current)


def _select_page() -> str:
    if _OPTION_MENU_AVAILABLE:
        with st.sidebar:
            return option_menu(
                menu_title="Main Menu",
                options=list(_PAGES),
                icons=list(_PAGE_ICONS),
                menu_icon="list",
                default_index=_remembered_index(),
                styles={
                    "container": {"padding": "4px 0", "background-color": "transparent"},
                    "icon": {"font-size": "16px"},
                    "nav-link": {
                        "font-size": "14px",
                        "text-align": "left",
                        "margin": "2px 0",
                        "padding": "8px 12px",
                        "border-radius": "6px",
                        "--hover-color": "#eef2ff",
                    },
                    "nav-link-selected": {
                        "background-color": _ACCENT,
                        "color": "white",
                        "font-weight": "600",
                    },
                    "menu-title": {
                        "font-size": "13px",
                        "font-weight": "600",
                        "color": "#444",
                        "padding": "4px 0 8px 0",
                    },
                },
            )
    # Fallback path
    st.sidebar.caption(
        "Catatan: streamlit-option-menu belum terpasang. Jalankan "
        "`pip install streamlit-option-menu` untuk tampilan menu yang lengkap."
    )
    return st.sidebar.radio("Navigation", _PAGES, index=_remembered_index())


page = _select_page()
# Ingat halaman aktif supaya rerun apa pun (login/logout, aksi di sidebar)
# tidak memindahkan pengguna dari konteks yang sedang ia kerjakan.
st.session_state[_CURRENT_PAGE_KEY] = page

# Switch mode: di BAWAH menu halaman, dipisahkan garis. Pengunjung melihat
# status + tombol Masuk; pengguna yang sudah masuk melihat nama, peran, dan
# tombol Keluar. Berpindah identitas tidak menyentuh data maupun state
# eksperimen yang sedang berjalan.
render_mode_switch()

# Modal masuk/daftar dipanggil dari ALUR UTAMA — di luar blok `with st.sidebar`
# dan bukan dari callback, sesuai pola dialog yang sudah bekerja di halaman
# lain. Tombol mana pun (sidebar atau ajakan masuk di halaman) hanya menulis
# flag; di sinilah flag itu dibaca.
#
# `page` ikut dikirim supaya modal tidak terbawa saat pengguna berpindah
# halaman: bila halaman berbeda dari run sebelumnya, flag dibuang sebelum
# diperiksa. Tanpa ini modal akan terbuka lagi di halaman mana pun yang dibuka
# berikutnya.
maybe_render_auth_dialog(page)

# ── Page routing ──────────────────────────────────────────────────────────
if page == "Progress & Status":
    from ui.views.view_results import render
    render()
elif page == "Run Experiment":
    from ui.views.run_experiment import render
    render()
elif page == "Add Pipeline & Dataset":
    from ui.views.contribute import render
    render()
