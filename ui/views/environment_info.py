"""Environment Info page — read-only system diagnostics."""
import streamlit as st
from pathlib import Path

from config.settings import BASE_DIR, STORAGE_DIR, ARTIFACTS_DIR, DATASETS_DIR, DB_PATH, get_environment_info
from config.pipeline_registry import list_all_pipelines
from orchestrator.validation_service import get_available_datasets
from orchestrator.execution_service import get_pipeline_info
from orchestrator.result_service import list_all_experiments


def render():
    st.title("⚙️ Environment Info")

    env = get_environment_info()

    # --- System Info ---
    with st.expander("🖥️ System", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Python:** {env.get('python_version', 'N/A')}")
            st.markdown(f"**Platform:** {env.get('platform', 'N/A')}")
            st.markdown(f"**Machine:** {env.get('machine', 'N/A')}")
        with c2:
            st.markdown(f"**scikit-learn:** {env.get('sklearn_version', 'N/A')}")
            st.markdown(f"**pandas:** {env.get('pandas_version', 'N/A')}")
            st.markdown(f"**numpy:** {env.get('numpy_version', 'N/A')}")

    # --- Docker Status ---
    with st.expander("🐳 Docker", expanded=True):
        if env.get("is_docker"):
            st.success("✅ Running inside Docker container")
            if env.get("docker_image_version"):
                st.markdown(f"**Image Version:** `{env['docker_image_version']}`")
            st.markdown("Environment is isolated and reproducible.")
        else:
            st.info("ℹ️ Running locally (not in Docker)")
            st.markdown("For environment-level reproducibility, deploy with `docker-compose up`.")

    # --- Execution Mode ---
    with st.expander("⚡ Execution Mode", expanded=True):
        from config.celery_config import USE_ASYNC, CELERY_BROKER_URL
        if USE_ASYNC:
            st.success("✅ Async mode (Celery + Redis)")
            st.markdown("Experiments are queued and executed by a background worker.")
            try:
                import redis as _redis
                r = _redis.Redis.from_url(CELERY_BROKER_URL)
                r.ping()
                st.markdown("**Redis:** 🟢 Connected")
            except Exception:
                st.markdown("**Redis:** 🔴 Not reachable")
        else:
            st.info("ℹ️ Sync mode (local worker)")
            st.markdown("Experiments run in the UI process. Set `USE_ASYNC=true` for background execution.")

    # --- Storage Paths ---
    with st.expander("📁 Storage", expanded=True):
        st.markdown(f"**Base:** `{BASE_DIR}`")
        st.markdown(f"**Datasets:** `{DATASETS_DIR}`")
        st.markdown(f"**Artifacts:** `{ARTIFACTS_DIR}`")
        st.markdown(f"**Database:** `{DB_PATH}`")
        dp = Path(DATASETS_DIR)
        if dp.exists():
            csvs = list(dp.glob("*.csv"))
            st.markdown(f"**CSV files:** {len(csvs)}")
            for f in csvs:
                st.markdown(f"  - `{f.name}` ({f.stat().st_size / 1024 / 1024:.1f} MB)")
        ap = Path(ARTIFACTS_DIR)
        if ap.exists():
            st.markdown(f"**Experiments:** {len([d for d in ap.iterdir() if d.is_dir()])}")

    # --- Registered Pipelines ---
    with st.expander("🔧 Pipelines", expanded=True):
        pipelines = list_all_pipelines()
        datasets = get_available_datasets()
        st.markdown(f"**Total pipelines:** {len(pipelines)}")
        st.markdown(f"**Supported datasets:** {', '.join(datasets)}")
        for pid, info in pipelines.items():
            st.markdown(f"### `{pid}`")
            st.markdown(f"**{info['name']}** — {info['paper']}")
            detail = get_pipeline_info(pid)
            if detail and detail.get("fixed_params"):
                st.json(detail["fixed_params"])

    # --- Database Stats ---
    with st.expander("🗄️ Database", expanded=False):
        exps = list_all_experiments()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(exps))
        c2.metric("Finished", sum(1 for e in exps if e.get("status") == "FINISHED"))
        c3.metric("Failed", sum(1 for e in exps if e.get("status") == "FAILED"))
