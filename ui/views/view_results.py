"""Experiment History page — AgGrid table with grouped columns, metric
highlighting, status badges, relative timestamps, and row-click detail."""
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from orchestrator.result_service import (
    list_all_experiments, get_full_experiment, get_experiment_metrics,
)
from orchestrator.experiment_service import rerun_experiment, cancel_experiment
from ui.views._artifact_browser import (
    render_file_browser, make_json_loader, make_text_loader, make_bytes_reader,
)


# ─── Time helpers ──────────────────────────────────────────────────────────

def _parse_iso(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _relative_time(iso_str):
    dt = _parse_iso(iso_str)
    if dt is None:
        return "-"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    days = secs / 86400
    if days < 30:
        return f"{int(days)}d ago"
    if days < 365:
        return f"{int(days // 30)}mo ago"
    return f"{int(days // 365)}y ago"


def _epoch(iso_str):
    dt = _parse_iso(iso_str)
    return dt.timestamp() if dt else 0.0


def _duration(start, end):
    s, e = _parse_iso(start), _parse_iso(end)
    if s is None or e is None:
        return "-"
    secs = (e - s).total_seconds()
    if secs < 0:
        return "-"
    if secs < 60:
        return f"{secs:.0f}s"
    return f"{secs / 60:.1f}min"


def _build_artifact_files(experiment_id: str) -> dict:
    """Read storage/artifacts/{experiment_id}/ dynamically and map each file
    to a viewer spec. Path-guarded to the experiment's artifact directory."""
    from pathlib import Path
    from config.settings import ARTIFACTS_DIR

    base = Path(ARTIFACTS_DIR).resolve()
    art_dir = (base / experiment_id).resolve()
    files: dict = {}
    if not art_dir.is_relative_to(base) or not art_dir.exists():
        return files

    for entry in sorted(art_dir.iterdir()):
        if not entry.is_file():
            continue
        rp = entry.resolve()
        if not rp.is_relative_to(art_dir):
            continue  # defensive: skip anything resolving outside the dir
        name = entry.name
        rel = f"storage/artifacts/{experiment_id}/{name}"
        ext = entry.suffix.lower()
        if ext == ".json":
            files[name] = {"icon": "", "language": "json", "full_path": rel,
                           "download_name": name, "loader": make_json_loader(rp)}
        elif ext in (".log", ".txt"):
            files[name] = {"icon": "", "language": "text", "full_path": rel,
                           "download_name": name, "tail": ext == ".log",
                           "loader": make_text_loader(rp)}
        elif ext in (".pkl", ".joblib", ".bin"):
            files[name] = {"icon": "", "binary": True, "full_path": rel,
                           "size": rp.stat().st_size, "download_name": name,
                           "read_bytes": make_bytes_reader(rp)}
        else:
            files[name] = {"icon": "", "binary": True, "full_path": rel,
                           "size": rp.stat().st_size, "download_name": name,
                           "read_bytes": make_bytes_reader(rp)}
    return files


@st.cache_data(show_spinner=False)
def _roc_auc(experiment_id, completed_at):
    """Load roc_auc from metrics.json. Cache key includes completed_at so it
    invalidates only when the experiment actually finishes/changes."""
    metrics = get_experiment_metrics(experiment_id)
    if metrics and isinstance(metrics.get("roc_auc"), (int, float)):
        return float(metrics["roc_auc"])
    return None


# ─── Grid data ─────────────────────────────────────────────────────────────

def _dataset_basename(path) -> str:
    """Extract basename from a path that may use either '/' or '\\' separator.

    Robust to mixed-environment history: rows written from Docker store
    '/app/storage/datasets/foo.csv'; rows written from Windows host store
    'D:\\Program\\TA\\storage\\datasets\\foo.csv'. ``Path(...).name`` on Linux
    fails for the Windows form because backslash is not a separator there, so
    we split on both. Returns "-" for empty/None.
    """
    if not path:
        return "-"
    import re
    parts = re.split(r"[\\/]", str(path))
    return parts[-1] or "-"


def _build_grid_df(experiments: list[dict]) -> pd.DataFrame:
    rows = []
    for e in experiments:
        finished = e.get("status") == "FINISHED"
        roc = _roc_auc(e["id"], e.get("completed_at")) if finished else None
        rows.append({
            "ID": e["id"][:8],
            "_full_id": e["id"],
            "Start Time": _relative_time(e.get("created_at")),
            "_created_epoch": _epoch(e.get("created_at")),
            "_created_abs": (e.get("created_at") or "-")[:19],
            "Duration": _duration(e.get("started_at"), e.get("completed_at")),
            "Pipeline": e.get("pipeline_id", "-"),
            "Dataset": e.get("dataset_type", "-"),
            "File": _dataset_basename(e.get("dataset_path")),
            "Status": e.get("status", "-"),
            "Accuracy": e.get("accuracy"),
            "Precision": e.get("precision_score"),
            "Recall": e.get("recall"),
            "F1-score": e.get("f1_score"),
            "ROC-AUC": roc,
            "random_state": "42",
            "test_split": "0.20",
            "Hash": (e.get("dataset_hash") or "-")[:8],
        })
    df = pd.DataFrame(rows)

    # Per-column max flags for highlighting (ignores None/NaN robustly).
    for col, flag in [
        ("Accuracy", "_hi_accuracy"), ("Precision", "_hi_precision"),
        ("Recall", "_hi_recall"), ("F1-score", "_hi_f1"), ("ROC-AUC", "_hi_roc"),
    ]:
        numeric = pd.to_numeric(df[col], errors="coerce")
        col_max = numeric.max()
        if pd.notna(col_max):
            df[flag] = [bool(pd.notna(v) and v == col_max) for v in numeric]
        else:
            df[flag] = False
    return df


_METRIC_FORMATTER = JsCode(
    "function(p){ if(p.value===null||p.value===undefined||isNaN(p.value)){return '-';} "
    "return Number(p.value).toFixed(4); }"
)

_START_COMPARATOR = JsCode(
    "function(a,b,nodeA,nodeB){ const x=(nodeA.data&&nodeA.data._created_epoch)||0; "
    "const y=(nodeB.data&&nodeB.data._created_epoch)||0; return x-y; }"
)

_STATUS_STYLE = JsCode("""
function(params){
    const colors = {
        'FINISHED':'#d4edda','RUNNING':'#cce5ff','FAILED':'#f8d7da',
        'CANCELLED':'#e2e3e5','QUEUED':'#fff3cd','PENDING':'#fff3cd'
    };
    const bg = colors[params.value];
    if (bg) { return {'backgroundColor': bg, 'fontWeight': '600'}; }
    return null;
}
""")


def _hi_style(flag_field: str) -> JsCode:
    return JsCode(
        f"function(params){{ if(params.data && params.data.{flag_field}){{ "
        f"return {{'backgroundColor':'#cce5ff','fontWeight':'600'}}; }} return null; }}"
    )


def _metric_col(header, field, hi_flag, group_open):
    col = {
        "headerName": header, "field": field, "width": 110,
        "type": "numericColumn",
        "valueFormatter": _METRIC_FORMATTER,
        "cellStyle": _hi_style(hi_flag),
    }
    if group_open:
        col["columnGroupShow"] = "open"
    return col


def _build_grid_options(df: pd.DataFrame) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, resizable=True, filterable=False)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    options = gb.build()

    options["columnDefs"] = [
        {"headerName": "Info", "children": [
            {"headerName": "ID", "field": "ID", "width": 110, "pinned": "left"},
            {"headerName": "Start Time", "field": "Start Time", "width": 120,
             "tooltipField": "_created_abs", "comparator": _START_COMPARATOR,
             "sort": "desc"},
            {"headerName": "Duration", "field": "Duration", "width": 100},
            {"headerName": "Pipeline", "field": "Pipeline", "width": 210},
            {"headerName": "Dataset", "field": "Dataset", "width": 130},
            {"headerName": "File", "field": "File", "width": 200,
             "tooltipField": "File"},
            {"headerName": "Status", "field": "Status", "width": 120,
             "cellStyle": _STATUS_STYLE},
        ]},
        {"headerName": "Metrics", "children": [
            # F1-score has no columnGroupShow → always visible (the column that
            # survives when the Metrics group is collapsed). The rest are "open".
            _metric_col("F1-score", "F1-score", "_hi_f1", group_open=False),
            _metric_col("Accuracy", "Accuracy", "_hi_accuracy", group_open=True),
            _metric_col("Precision", "Precision", "_hi_precision", group_open=True),
            _metric_col("Recall", "Recall", "_hi_recall", group_open=True),
            _metric_col("ROC-AUC", "ROC-AUC", "_hi_roc", group_open=True),
        ]},
        {"headerName": "Config", "children": [
            # Hash stays visible when Config collapses; the rest are "open".
            {"headerName": "Hash", "field": "Hash", "width": 110},
            {"headerName": "random_state", "field": "random_state", "width": 120,
             "columnGroupShow": "open"},
            {"headerName": "test_split", "field": "test_split", "width": 110,
             "columnGroupShow": "open"},
        ]},
    ]

    options["suppressHorizontalScroll"] = False
    options["enableBrowserTooltips"] = True
    if len(df) > 20:
        options["pagination"] = True
        options["paginationPageSize"] = 20
    return options


# ─── Page ──────────────────────────────────────────────────────────────────

def render():
    st.title("Experiment History")

    experiments = list_all_experiments()
    if not experiments:
        st.info("Belum ada eksperimen. Buka halaman 'Run Experiment' untuk membuat satu.")
        st.session_state.pop("selected_experiment_id", None)
        return

    st.caption(
        f"{len(experiments)} eksperimen. Klik satu baris untuk membuka detail. "
        "Grup Metrics dan Config dapat di-collapse lewat ikon di header grup."
    )

    df = _build_grid_df(experiments)
    grid_options = _build_grid_options(df)

    grid_response = AgGrid(
        df,
        gridOptions=grid_options,
        allow_unsafe_jscode=True,
        theme="streamlit",
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        fit_columns_on_grid_load=False,
        height=440,
        key="experiment_history_grid",
    )

    # Resolve selection. AgGrid may return a DataFrame or a list depending on
    # version; handle both. Persist in session_state so the detail panel stays
    # visible across reruns triggered by detail-panel buttons.
    selected_id = None
    sel = grid_response.get("selected_rows")
    if isinstance(sel, pd.DataFrame):
        if not sel.empty and "_full_id" in sel.columns:
            selected_id = sel.iloc[0]["_full_id"]
    elif isinstance(sel, list) and sel:
        selected_id = sel[0].get("_full_id")

    if selected_id:
        st.session_state["selected_experiment_id"] = selected_id
    selected_id = st.session_state.get("selected_experiment_id")

    if not selected_id:
        st.info("Pilih satu eksperimen pada tabel di atas untuk melihat detailnya.")
        return

    st.markdown("---")
    _render_detail(selected_id)


def _render_detail(selected_id: str):
    """Render full detail for one experiment. Logic preserved from the prior
    selectbox-based version; only the selection source changed."""
    full = get_full_experiment(selected_id)
    if not full:
        st.error("Eksperimen tidak ditemukan.")
        st.session_state.pop("selected_experiment_id", None)
        return

    exp = full["experiment"]
    metrics = full.get("metrics")
    metadata = full.get("metadata")

    st.subheader(f"Experiment Detail — {exp['id'][:8]}")

    with st.expander("Metadata", expanded=True):
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
        with st.expander("Metrics", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Accuracy", f"{metrics.get('accuracy', 0):.4f}")
            c2.metric("Precision", f"{metrics.get('precision', 0):.4f}")
            c3.metric("Recall", f"{metrics.get('recall', 0):.4f}")
            c4.metric("F1", f"{metrics.get('f1_score', 0):.4f}")
            if "roc_auc" in metrics:
                st.metric("ROC-AUC", f"{metrics['roc_auc']:.4f}")

            # Confusion Matrix + Feature Importance side by side to save
            # vertical space. Pipelines without feature importance (e.g. KNN)
            # get a caption in the right column instead of an empty plot.
            has_cm = "confusion_matrix" in metrics
            has_fi = bool(metrics.get("feature_importance"))
            if has_cm or has_fi:
                col_left, col_right = st.columns(2)
                if has_cm:
                    with col_left:
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
                if has_fi:
                    with col_right:
                        fi_full = metrics["feature_importance"]
                        n_total = len(fi_full)
                        top_n = 20
                        fi = fi_full[:top_n]
                        fig, ax = plt.subplots(figsize=(5, max(4, len(fi) * 0.3)))
                        ax.barh(
                            [x["feature"] for x in reversed(fi)],
                            [x["importance"] for x in reversed(fi)],
                            color="#2563EB",
                        )
                        ax.set_xlabel("Importance")
                        title = f"Top {len(fi)} Feature Importance"
                        if n_total > len(fi):
                            title += f" (of {n_total} total)"
                        ax.set_title(title, fontsize=11)
                        fig.tight_layout()
                        st.pyplot(fig)
                        plt.close(fig)
                elif has_cm:
                    with col_right:
                        st.caption("Feature importance tidak tersedia untuk algoritma ini.")

            if "classification_report" in metrics:
                report = metrics["classification_report"]
                rows = {k: v for k, v in report.items() if isinstance(v, dict)}
                if rows:
                    st.dataframe(pd.DataFrame(rows).T.round(4), use_container_width=True)

        # Process Log — captured pipeline stdout, persisted in metrics.json
        if "process_log" in metrics and metrics["process_log"]:
            with st.expander("Process Log", expanded=False):
                st.code(metrics["process_log"], language=None)

    elif exp["status"] in ("QUEUED", "RUNNING"):
        st.info(f"Experiment is {exp['status'].lower()}. Refresh to see updates.")
        if st.button("Cancel Experiment", key=f"cancel_{selected_id}"):
            r = cancel_experiment(selected_id)
            if r["success"]:
                st.warning("Experiment cancelled.")
                st.rerun()
            else:
                st.error(r["message"])

    elif exp["status"] == "FAILED":
        error_msg = exp.get("error_message", "Unknown")
        if error_msg == "Cancelled by user":
            st.warning("Experiment was cancelled by user.")
        else:
            st.error(f"Failed: {error_msg}")

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
            label="Download PDF Report",
            data=pdf_bytes,
            file_name=f"experiment_report_{exp['id'][:8]}.pdf",
            mime="application/pdf",
            key=f"pdf_{selected_id}",
        )

    # === Artifact Viewer ===
    st.markdown("---")
    st.subheader("Artifact Viewer")
    if exp["status"] == "FINISHED":
        artifact_files = _build_artifact_files(exp["id"])
        if artifact_files:
            render_file_browser(artifact_files, state_key="selected_file_artifact_view")
        else:
            st.info("Artefak belum tersedia atau direktori artefak kosong.")
    else:
        st.info(f"Artefak belum tersedia. Eksperimen berstatus {exp['status']}.")

    st.markdown("---")
    if st.button("Re-run", key=f"rerun_{selected_id}"):
        with st.spinner("Re-running..."):
            r = rerun_experiment(selected_id)
            if r["success"]:
                st.success(f"New: `{r['experiment_id'][:8]}...` — refresh to see.")
            else:
                st.error(r["error"])
