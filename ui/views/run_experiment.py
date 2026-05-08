"""
Run Experiment page — supports both sync and async execution.
"""
import time
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

from orchestrator.experiment_service import (
    validate_dataset_for_ui, create_and_run_experiment, get_experiment_status,
)
from orchestrator.execution_service import get_pipeline_info
from orchestrator.validation_service import get_available_datasets
from orchestrator.result_service import get_experiment_metrics, get_full_experiment, get_experiment_metadata


def render():
    st.title("🧪 Run Experiment")

    # === SECTION 1: Dataset Selection ===
    st.header("1. Dataset Selection")
    col1, col2 = st.columns(2)
    with col1:
        dataset_type = st.selectbox("Dataset Type", options=get_available_datasets())
        st.session_state["dataset_type"] = dataset_type
    with col2:
        dataset_path = st.text_input("Dataset File Path", placeholder="storage/datasets/your_file.csv")
        st.session_state["dataset_path"] = dataset_path

    if st.button("🔍 Validate Dataset", type="primary", disabled=not dataset_path):
        with st.spinner("Validating..."):
            st.session_state["validation"] = validate_dataset_for_ui(dataset_type, dataset_path)
            st.session_state.pop("last_result", None)
            st.session_state.pop("polling_experiment_id", None)

    if "validation" not in st.session_state:
        return

    v = st.session_state["validation"]
    if not v["success"]:
        st.error(f"❌ {v['error']}")
        return

    st.success("✅ Dataset is valid!")
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", f"{v['row_count']:,}")
    c2.metric("Columns", v["column_count"])
    c3.metric("Classes", len(v["unique_labels"]))
    if v.get("dataset_hash"):
        st.code(f"SHA-256: {v['dataset_hash']}", language=None)
    st.markdown(f"**Labels:** {', '.join(str(lbl) for lbl in v['unique_labels'])}")

    # === SECTION 2: Pipeline Selection ===
    st.header("2. Pipeline Selection")
    pipelines = v.get("compatible_pipelines", {})
    if not pipelines:
        st.warning("No compatible pipelines.")
        return

    pipeline_opts = {pid: info["name"] for pid, info in pipelines.items()}
    selected = st.selectbox("Select Pipeline", list(pipeline_opts.keys()), format_func=lambda x: pipeline_opts[x])
    st.session_state["selected_pipeline"] = selected

    if selected:
        info = get_pipeline_info(selected)
        if info:
            with st.expander("📄 Pipeline Detail (Read-Only)"):
                st.markdown(f"**Paper:** {info.get('paper')}")
                st.markdown(f"**Algorithm:** {info.get('algorithm')}")
                if info.get("preprocessing_steps"):
                    st.markdown("**Preprocessing:**")
                    for i, s in enumerate(info["preprocessing_steps"], 1):
                        st.markdown(f"  {i}. {s}")
                if info.get("feature_selection"):
                    st.markdown(f"**Feature Selection:** {info['feature_selection']}")
                if info.get("fixed_params"):
                    st.markdown("**Fixed Params:**")
                    st.json(info["fixed_params"])
                if info.get("runtime_warning"):
                    st.warning(info["runtime_warning"])
                st.info("⚠️ All parameters locked per paper.")

    # === SECTION 3: Execute ===
    st.header("3. Execute")

    # If currently polling an async experiment, handle that and skip Run button
    if "polling_experiment_id" in st.session_state:
        _poll_experiment(st.session_state["polling_experiment_id"])
        return

    if st.button("🚀 Run Experiment", type="primary"):
        result = create_and_run_experiment(dataset_type, dataset_path, selected)

        if not result["success"]:
            st.error(f"❌ {result['error']}")
            return

        if result.get("async_mode"):
            st.session_state["polling_experiment_id"] = result["experiment_id"]
            st.info(f"⏳ Experiment queued: `{result['experiment_id'][:8]}...`")
            st.rerun()
        else:
            st.session_state["last_result"] = result
            st.rerun()

    # === SECTION 4: Results (sync path) ===
    if "last_result" in st.session_state and st.session_state["last_result"].get("success"):
        _display_results(st.session_state["last_result"])


def _poll_experiment(experiment_id: str):
    """Poll experiment status until FINISHED or FAILED, then trigger rerun."""
    status_data = get_experiment_status(experiment_id)

    if status_data is None:
        st.error("Experiment not found.")
        st.session_state.pop("polling_experiment_id", None)
        return

    status = status_data["status"]

    if status in ("QUEUED", "RUNNING"):
        with st.status(f"Experiment {status.lower()}...", expanded=True):
            st.write(f"**Experiment ID:** `{experiment_id[:8]}...`")
            st.write(f"**Status:** {status}")
            if status == "QUEUED":
                st.write("Waiting for worker to pick up the task...")
            else:
                st.write("Pipeline is executing. This may take several minutes...")
            st.write("This page auto-refreshes every 5 seconds.")
        time.sleep(5)
        st.rerun()

    elif status == "FINISHED":
        st.session_state.pop("polling_experiment_id", None)
        full = get_full_experiment(experiment_id)
        if full:
            st.session_state["last_result"] = {
                "success": True,
                "experiment_id": experiment_id,
                "metrics": full.get("metrics", {}),
                "feature_names": (full.get("metadata") or {}).get("feature_names"),
                "label_mapping": (full.get("metadata") or {}).get("label_mapping"),
            }
        st.rerun()

    elif status == "FAILED":
        st.session_state.pop("polling_experiment_id", None)
        st.error(f"❌ Experiment failed: {status_data.get('error_message', 'Unknown error')}")


def _display_results(result: dict):
    """Render all metrics and charts."""
    st.header("4. Results")
    m = result["metrics"]
    eid = result["experiment_id"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accuracy", f"{m.get('accuracy', 0):.4f}")
    c2.metric("Precision", f"{m.get('precision', 0):.4f}")
    c3.metric("Recall", f"{m.get('recall', 0):.4f}")
    c4.metric("F1-Score", f"{m.get('f1_score', 0):.4f}")

    full = get_experiment_metrics(eid) or m

    # Confusion Matrix
    if "confusion_matrix" in m:
        st.subheader("Confusion Matrix")
        cm = np.array(m["confusion_matrix"])
        lm = result.get("label_mapping", {})
        labels = sorted(lm.keys(), key=lambda k: lm[k]) if lm else []
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(cm, cmap='Blues')
        plt.colorbar(im, ax=ax)
        if labels:
            ax.set_xticks(range(len(labels)))
            ax.set_yticks(range(len(labels)))
            ax.set_xticklabels([str(l) for l in labels], rotation=45, ha='right')
            ax.set_yticklabels([str(l) for l in labels])
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, format(cm[i, j], 'd'), ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
        ax.set_ylabel("Actual")
        ax.set_xlabel("Predicted")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # ROC Curve
    if "roc_auc" in full:
        st.subheader("ROC Curve")
        col1, col2 = st.columns([3, 1])
        with col1:
            fig, ax = plt.subplots(figsize=(6, 5))
            if "roc_curve" in full:
                fpr = full["roc_curve"]["fpr"]
                tpr = full["roc_curve"]["tpr"]
                if isinstance(fpr, list):
                    ax.plot(fpr, tpr, label=f"AUC = {full['roc_auc']:.4f}", linewidth=2)
                elif isinstance(fpr, dict):
                    for cls in fpr:
                        ax.plot(fpr[cls], tpr[cls], label=cls, linewidth=1.5)
            elif "roc_curves_per_class" in full:
                for cls, curve in full["roc_curves_per_class"].items():
                    ax.plot(curve["fpr"], curve["tpr"], label=str(cls), linewidth=1.5)
            ax.plot([0, 1], [0, 1], 'k--', alpha=0.5)
            ax.set_xlabel("FPR")
            ax.set_ylabel("TPR")
            ax.legend(loc="lower right")
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        with col2:
            st.metric("ROC-AUC", f"{full['roc_auc']:.4f}")

    # Feature Importance
    if "feature_importance" in full and full["feature_importance"]:
        st.subheader("Feature Importance")
        fi = full["feature_importance"]
        fig, ax = plt.subplots(figsize=(8, max(3, len(fi) * 0.3)))
        ax.barh([x["feature"] for x in reversed(fi[:20])],
                [x["importance"] for x in reversed(fi[:20])], color="#2563EB")
        ax.set_xlabel("Importance")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # Per-Class Report
    if "classification_report" in full:
        st.subheader("Per-Class Report")
        report = full["classification_report"]
        class_rows = {k: v for k, v in report.items() if isinstance(v, dict)}
        if class_rows:
            df = pd.DataFrame(class_rows).T.round(4)
            if "support" in df.columns:
                df["support"] = df["support"].astype(int)
            st.dataframe(df, use_container_width=True)

    # Learning Curve
    if "learning_curve" in full and "error" not in full.get("learning_curve", {}):
        st.subheader("Learning Curve")
        lc = full["learning_curve"]
        tr_std = lc.get("train_scores_std", [0] * len(lc["train_sizes"]))
        val_mean = lc.get("val_scores_mean", [])
        val_std = lc.get("val_scores_std", [0] * len(lc["train_sizes"]))
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.fill_between(
            lc["train_sizes"],
            [m - s for m, s in zip(lc["train_scores_mean"], tr_std)],
            [m + s for m, s in zip(lc["train_scores_mean"], tr_std)],
            alpha=0.1, color="blue",
        )
        if val_mean:
            ax.fill_between(
                lc["train_sizes"],
                [mv - s for mv, s in zip(val_mean, val_std)],
                [mv + s for mv, s in zip(val_mean, val_std)],
                alpha=0.1, color="orange",
            )
        ax.plot(lc["train_sizes"], lc["train_scores_mean"], 'o-', color="blue", label="Train", linewidth=2)
        if val_mean:
            ax.plot(lc["train_sizes"], val_mean, 'o-', color="orange", label="Validation", linewidth=2)
        ax.set_xlabel("Training Size")
        ax.set_ylabel("F1 (Weighted)")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # PDF Download
    st.markdown("---")
    st.subheader("📥 Download Report")
    try:
        from utils.report_generator import generate_report
        pipe_info = get_pipeline_info(st.session_state.get("selected_pipeline", "")) or {}
        exp_metadata = get_experiment_metadata(eid) or {}

        pdf_bytes = generate_report(
            experiment_id=eid,
            dataset_type=st.session_state.get("dataset_type", "Unknown"),
            dataset_path=st.session_state.get("dataset_path", "Unknown"),
            dataset_hash=exp_metadata.get("dataset_hash", full.get("dataset_hash", "N/A")),
            pipeline_id=st.session_state.get("selected_pipeline", "Unknown"),
            pipeline_info=pipe_info,
            metrics=full,
            metadata=exp_metadata,
            label_mapping=result.get("label_mapping"),
            feature_names=result.get("feature_names"),
        )
        st.download_button(
            label="📄 Download PDF Report",
            data=pdf_bytes,
            file_name=f"experiment_report_{eid[:8]}.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        st.warning(f"PDF generation failed: {e}")

    st.caption(f"Experiment ID: `{eid}`")
