"""
Streamlit entrypoint.
Run: streamlit run ui/app.py  (requires: pip install -e . first)
"""
import streamlit as st
from database.db import init_db

init_db()


@st.cache_resource
def _startup_cleanup():
    """Run once per server lifetime — not on every Streamlit rerun."""
    from orchestrator.experiment_service import cleanup_stale_experiments
    cleaned = cleanup_stale_experiments()
    if cleaned > 0:
        print(f"[startup] Cleaned up {cleaned} stale experiment(s)")


_startup_cleanup()

st.set_page_config(page_title="IDS Research Pipeline System", page_icon="🔬", layout="wide")

st.sidebar.title("🔬 IDS Research Platform")
st.sidebar.markdown("---")

page = st.sidebar.radio("Navigation", ["Run Experiment", "Experiment History", "Environment Info"])

if page == "Run Experiment":
    from ui.views.run_experiment import render
    render()
elif page == "Experiment History":
    from ui.views.view_results import render
    render()
elif page == "Environment Info":
    from ui.views.environment_info import render
    render()
