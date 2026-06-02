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
def _startup_cleanup():
    """Run once per server lifetime — not on every Streamlit rerun."""
    from orchestrator.experiment_service import cleanup_stale_experiments
    cleaned = cleanup_stale_experiments()
    if cleaned > 0:
        logger.info("Startup cleanup: removed %d stale experiment(s)", cleaned)


_startup_cleanup()

st.set_page_config(page_title="IDS Research Pipeline System", page_icon="", layout="wide")

# ── Sidebar navigation ────────────────────────────────────────────────────
# Centralised routing: option_menu returns the selected label, and a single
# dispatch table below routes to each page's render() function. The four
# pages are independent modules in ui/views/. No ui/pages/ folder is used,
# so there is no conflict with Streamlit's built-in multipage navigation.
#
# Defensive: if streamlit-option-menu is not installed (e.g. an older clone
# of the repo without the dep installed), fall back to a plain radio so the
# app stays usable and the user gets a clear hint to install it.

_PAGES = ("Tutorial", "Run Experiment", "History", "Environment Info")
_PAGE_ICONS = ("book", "play-circle", "clock-history", "info-circle")

try:
    from streamlit_option_menu import option_menu
    _OPTION_MENU_AVAILABLE = True
except Exception as _e:
    option_menu = None
    _OPTION_MENU_AVAILABLE = False
    logger.warning("streamlit-option-menu not available, falling back to radio: %s", _e)


_ACCENT = "#2563eb"  # consistent with the accent already used in other UI


def _select_page() -> str:
    if _OPTION_MENU_AVAILABLE:
        with st.sidebar:
            return option_menu(
                menu_title="Main Menu",
                options=list(_PAGES),
                icons=list(_PAGE_ICONS),
                menu_icon="list",
                default_index=0,
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
    return st.sidebar.radio("Navigation", _PAGES, index=0)


page = _select_page()

# ── About section ────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("**About**")
st.sidebar.markdown(
    "**IDS Research Pipeline System**  \n"
    "Versi 1.0.0  \n"
    "Platform eksperimen IDS berbasis web on-premise dengan pipeline ML "
    "terstandarisasi dan reproduksibilitas bit-per-bit."
)
st.sidebar.caption("Repositori: [ISI: link repositori]")
st.sidebar.caption("© 2026 Andi Siti Aisyah Amin (D1212221043)")

# ── Page routing ──────────────────────────────────────────────────────────
if page == "Tutorial":
    from ui.views.tutorial import render
    render()
elif page == "Run Experiment":
    from ui.views.run_experiment import render
    render()
elif page == "History":
    from ui.views.view_results import render
    render()
elif page == "Environment Info":
    from ui.views.environment_info import render
    render()
