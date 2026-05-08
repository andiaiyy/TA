"""Experiment History page."""
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

from orchestrator.result_service import list_all_experiments, get_full_experiment
from orchestrator.experiment_service import rerun_experiment

_STATUS_ICON = {"FINISHED": "✅", "FAILED": "❌", "RUNNING": "🔄", "QUEUED": "⏳"}


def render():
    st.title("📊 Experiment History")
    experiments = list_all_experiments()
    if not experiments:
        st.info("No experiments yet.")
        return

    # Summary table
    display = []
    for e in experiments:
        icon = _STATUS_ICON.get(e["status"], "❓")
        display.append({
            "ID": e["id"][:8] + "...",
            "Dataset": e["dataset_type"],
            "Pipeline": e["pipeline_id"],
            "Status": f"{icon} {e['status']}",
            "Accuracy": f"{e['accuracy']:.4f}" if e.get("accuracy") is not None else "—",
            "F1": f"{e['f1_score']:.4f}" if e.get("f1_score") is not None else "—",
            "Created": e["created_at"][:19] if e.get("created_at") else "—",
        })
    st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)

    # Detail view
    st.subheader("Detail")
    exp_map = {
        f"{e['id'][:8]}... | {e['pipeline_id']} | {e['status']}": e["id"]
        for e in experiments
    }
    selected_label = st.selectbox("Select experiment:", list(exp_map.keys()))
    selected_id = exp_map[selected_label]

    full = get_full_experiment(selected_id)
    if not full:
        st.error("Not found.")
        return

    exp = full["experiment"]
    metrics = full.get("metrics")
    metadata = full.get("metadata")

    with st.expander("📋 Metadata", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**ID:** `{exp['id']}`")
            st.markdown(f"**Dataset:** {exp['dataset_type']}")
            st.markdown(f"**Pipeline:** {exp['pipeline_id']}")
            st.markdown(f"**Status:** {exp['status']}")
        with c2:
            st.markdown(f"**Created:** {exp.get('created_at', 'N/A')}")
            st.markdown(f"**Completed:** {exp.get('completed_at', 'N/A')}")
            if exp.get("dataset_hash"):
                st.markdown(f"**Hash:** `{exp['dataset_hash'][:16]}...`")
            if metadata and metadata.get("feature_names"):
                st.markdown(f"**Features:** {', '.join(metadata['feature_names'])}")

    if exp["status"] == "FINISHED" and metrics:
        with st.expander("📈 Metrics", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Accuracy", f"{metrics.get('accuracy', 0):.4f}")
            c2.metric("Precision", f"{metrics.get('precision', 0):.4f}")
            c3.metric("Recall", f"{metrics.get('recall', 0):.4f}")
            c4.metric("F1", f"{metrics.get('f1_score', 0):.4f}")
            if "roc_auc" in metrics:
                st.metric("ROC-AUC", f"{metrics['roc_auc']:.4f}")

            if "confusion_matrix" in metrics:
                cm = np.array(metrics["confusion_matrix"])
                labels = []
                if metadata and metadata.get("label_mapping"):
                    labels = sorted(
                        metadata["label_mapping"].keys(),
                        key=lambda k: metadata["label_mapping"][k],
                    )
                fig, ax = plt.subplots(figsize=(5, 4))
                ax.imshow(cm, cmap='Blues')
                if labels:
                    ax.set_xticks(range(len(labels)))
                    ax.set_yticks(range(len(labels)))
                    ax.set_xticklabels(labels, rotation=45, ha='right')
                    ax.set_yticklabels(labels)
                for i in range(cm.shape[0]):
                    for j in range(cm.shape[1]):
                        ax.text(j, i, format(cm[i, j], 'd'), ha="center", va="center",
                                color="white" if cm[i, j] > cm.max() / 2 else "black")
                ax.set_ylabel("Actual")
                ax.set_xlabel("Predicted")
                fig.tight_layout()
                st.pyplot(fig)
                plt.close(fig)

            if "classification_report" in metrics:
                report = metrics["classification_report"]
                rows = {k: v for k, v in report.items() if isinstance(v, dict)}
                if rows:
                    st.dataframe(pd.DataFrame(rows).T.round(4), use_container_width=True)

            if "feature_importance" in metrics:
                fi = metrics["feature_importance"]
                fig, ax = plt.subplots(figsize=(7, 3))
                ax.barh(
                    [x["feature"] for x in reversed(fi)],
                    [x["importance"] for x in reversed(fi)],
                    color="#2563EB",
                )
                fig.tight_layout()
                st.pyplot(fig)
                plt.close(fig)

    elif exp["status"] == "FAILED":
        st.error(f"Failed: {exp.get('error_message', 'Unknown')}")

    # === PDF Download Button ===
    if exp["status"] == "FINISHED" and metrics:
        from utils.report_generator import generate_report
        from orchestrator.execution_service import get_pipeline_info

        pipe_info = get_pipeline_info(exp["pipeline_id"]) or {}

        pdf_bytes = generate_report(
            experiment_id=exp["id"],
            dataset_type=exp["dataset_type"],
            dataset_path=exp["dataset_path"],
            dataset_hash=exp.get("dataset_hash", "N/A"),
            pipeline_id=exp["pipeline_id"],
            pipeline_info=pipe_info,
            metrics=metrics,
            metadata=metadata,
            label_mapping=metadata.get("label_mapping") if metadata else None,
            feature_names=metadata.get("feature_names") if metadata else None,
        )

        st.download_button(
            label="📄 Download PDF Report",
            data=pdf_bytes,
            file_name=f"experiment_report_{exp['id'][:8]}.pdf",
            mime="application/pdf",
            key=f"pdf_{selected_id}",
        )

    st.markdown("---")
    if st.button("🔁 Re-run", key=f"rerun_{selected_id}"):
        with st.spinner("Re-running..."):
            r = rerun_experiment(selected_id)
            if r["success"]:
                st.success(f"✅ New: `{r['experiment_id'][:8]}...` — refresh to see.")
            else:
                st.error(r["error"])
