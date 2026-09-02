"""
Shared, interactive result views — used by BOTH the Run Experiment page and the
Experiment History page so the two render identically with zero duplication.

Two data sources are unified by ``normalize_result_payload`` into one payload:
  - Run Experiment: an in-memory PipelineResult-derived dict (+ metrics.json).
  - History:        metrics.json + metadata.json (+ the DB experiment row).

All defensive behaviour is preserved:
  - feature_importance empty (KNN / Gaussian NB) → informative message.
  - learning_curve absent (EVE-cbr) → natural- vs balanced-holdout fallback.
  - label_mapping keys may be int or str; positive class is derived from the
    label NAME (never hardcoded 0/1) via the shared _confusion_breakdown.

Pure helpers (``normalize_result_payload``, ``confusion_breakdown``) do not
touch Streamlit and are unit-tested. Rendering helpers use only Streamlit-native
components. The UI shows charts interactively only; the equivalent static images
live solely in the PDF report (report_generator builds those independently from
metrics.json). This module never changes computation or metrics.json.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ui.i18n import t

# Reuse the tested confusion-matrix breakdown (positive class from label name,
# int/str label keys handled) — the same helper the PDF report uses.
from utils.report_generator import _confusion_breakdown as confusion_breakdown


# ─── Pure payload normalization (no Streamlit) ────────────────────────────

def normalize_result_payload(
    *,
    experiment_id,
    metrics,
    metadata=None,
    label_mapping=None,
    feature_names=None,
    pipeline_id=None,
    dataset_type=None,
) -> dict:
    """Unify the two result data sources into one uniform payload.

    Explicit arguments win; anything not given falls back to ``metadata``
    (metrics.json's sibling). Returns a dict with stable keys so both pages can
    render through the same code path. Pure — safe to unit-test.
    """
    metadata = metadata or {}
    metrics = metrics or {}

    def _pick(explicit, meta_key):
        return explicit if explicit is not None else metadata.get(meta_key)

    return {
        "experiment_id": experiment_id,
        "metrics": metrics,
        "label_mapping": _pick(label_mapping, "label_mapping") or {},
        "feature_names": _pick(feature_names, "feature_names") or [],
        "pipeline_id": _pick(pipeline_id, "pipeline_id") or "",
        "dataset_type": _pick(dataset_type, "dataset_type") or "",
    }


def _roc_quality(auc: float) -> str:
    """Qualitative band for an AUC value (references the actual number)."""
    # AMBANGNYA TIDAK BERUBAH — hanya kalimatnya yang kini dari katalog.
    from ui.i18n import t

    if auc >= 0.9:
        return t("ps.rv_auc_excellent")
    if auc >= 0.8:
        return t("ps.rv_auc_good")
    if auc >= 0.7:
        return t("ps.rv_auc_fair")
    if auc > 0.55:
        return t("ps.rv_auc_weak")
    return t("ps.rv_auc_chance")


# ─── Interactive renderers (Streamlit-native) ─────────────────────────────

def _render_interactive_cm(cm, label_mapping, eid: str) -> None:
    """Interactive confusion matrix: semantic colored cells + cell picker +
    dynamically-computed security interpretation. Binary [[TN,FP],[FN,TP]] for
    both HIKARI (weighted headline) and EVE cbr (natural-holdout)."""
    b = confusion_breakdown(cm, label_mapping)
    if not b:
        st.info(t("ps.rv_no_cm"))
        return

    an, nn = b["attack_name"], b["normal_name"]
    tp, fn, fp, tn, total = b["tp"], b["fn"], b["fp"], b["tn"], b["total"]

    def _pct(x):
        return f"{(x / total * 100):.1f}%" if total else "—"

    palette = {
        "tn": ("#dcfce7", "#166534"), "tp": ("#dcfce7", "#166534"),
        "fp": ("#fef3c7", "#92400e"), "fn": ("#fee2e2", "#991b1b"),
    }

    def _cell(count, title, key):
        bg, fg = palette[key]
        st.markdown(
            f"<div style='background:{bg}; color:{fg}; border:1px solid {fg}33; "
            f"border-radius:8px; padding:10px; text-align:center;'>"
            f"<div style='font-size:0.95rem; font-weight:600;'>{title}</div>"
            f"<div style='font-size:1.5rem; font-weight:700; line-height:1.3;'>{count:,}</div>"
            f"<div style='font-size:0.95rem; opacity:0.85;'>"
            f"{t('ps.rv_of_total', pct=_pct(count))}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    hdr = st.columns([1.1, 1, 1])
    _head = "text-align:center; font-size:0.95rem; font-weight:600;"
    hdr[1].markdown(f"<div style='{_head}'>"
                    f"{t('ps.rv_predicted', name=nn)}</div>",
                    unsafe_allow_html=True)
    hdr[2].markdown(f"<div style='{_head}'>"
                    f"{t('ps.rv_predicted', name=an)}</div>",
                    unsafe_allow_html=True)
    r1 = st.columns([1.1, 1, 1])
    _side = "font-size:0.95rem; font-weight:600; padding-top:24px;"
    r1[0].markdown(f"<div style='{_side}'>{t('ps.rv_actual', name=nn)}</div>",
                   unsafe_allow_html=True)
    with r1[1]:
        _cell(tn, t("ps.rv_cell_tn", name=nn), "tn")
    with r1[2]:
        _cell(fp, t("ps.rv_cell_fp"), "fp")
    r2 = st.columns([1.1, 1, 1])
    r2[0].markdown(f"<div style='{_side}'>{t('ps.rv_actual', name=an)}</div>",
                   unsafe_allow_html=True)
    with r2[1]:
        _cell(fn, t("ps.rv_cell_fn", name=an), "fn")
    with r2[2]:
        _cell(tp, t("ps.rv_cell_tp", name=an), "tp")

    st.markdown(t("ps.rv_security_reading"))
    mcols = st.columns(3)
    _rec = b["attack_recall"]
    mcols[0].metric(
        t("ps.rv_attacks_caught"), _pct(tp) if total else "—",
        help=t("ps.rv_help_caught", tp=f"{tp:,}",
               total=f"{b['attack_total']:,}",
               recall=(t("ps.rv_help_recall_suffix",
                         pct=f"{(_rec * 100):.1f}%")
                       if _rec is not None else "")))
    mcols[1].metric(
        t("ps.rv_attacks_missed"), f"{fn:,}",
        help=(t("ps.rv_help_missed_pct",
                pct=f"{(fn / b['attack_total'] * 100):.1f}%")
              if b["attack_total"] else t("ps.rv_help_missed_unknown")))
    mcols[2].metric(
        t("ps.rv_false_alarms"), f"{fp:,}",
        help=(t("ps.rv_help_fp_pct", pct=f"{(b['fp_rate'] * 100):.1f}%")
              if b.get("fp_rate") is not None
              else t("ps.rv_help_fp_unknown")))

    # Kunci dict = label pilihan yang TAMPIL, jadi ia ikut bahasa; keduanya
    # berasal dari katalog yang sama sehingga tidak dapat bercampur.
    explain = {
        t("ps.rv_cell_tp", name=an): t("ps.rv_explain_tp", count=f"{tp:,}",
                                       attack=an),
        t("ps.rv_cell_fn", name=an): t("ps.rv_explain_fn", count=f"{fn:,}",
                                       attack=an, normal=nn),
        t("ps.rv_cell_fp"): t("ps.rv_explain_fp", count=f"{fp:,}", normal=nn),
        t("ps.rv_cell_tn", name=nn): t("ps.rv_explain_tn", count=f"{tn:,}",
                                       normal=nn),
    }
    sel = st.radio(t("ps.rv_cell_detail"), list(explain.keys()), horizontal=True, key=f"cmsel_{eid}")
    st.info(explain[sel])


def _render_interactive_fi(fi_list, pipeline_id: str, note, eid: str) -> None:
    """Interactive feature importance: Top-N slider + sortable ProgressColumn
    table. Defensive for pipelines that provide none (KNN, NBGC)."""
    if not fi_list:
        st.info(t("rv.no_feature_importance"))
        return

    n_total = len(fi_list)
    if n_total > 5:
        top_n = st.slider(
            t("ps.rv_top_features"), min_value=5, max_value=min(30, n_total),
            value=min(20, n_total), key=f"fislider_{eid}",
        )
    else:
        top_n = n_total

    rows = fi_list[:top_n]
    df = pd.DataFrame(rows)
    # Asal bobot menempel pada KOLOM yang dijelaskannya, bukan sebagai baris
    # keterangan di bawah tabel.
    if note:
        bobot_help = str(note)
    elif pipeline_id and "lr" in pipeline_id.lower():
        bobot_help = t("ps.rv_weights_logreg")
    else:
        bobot_help = t("ps.rv_weights_relative")

    if "importance" in df.columns and "feature" in df.columns:
        _max = max((float(r.get("importance", 0)) for r in rows), default=1.0) or 1.0
        st.dataframe(
            df[["feature", "importance"]],
            column_config={
                "feature": st.column_config.TextColumn(
                    t("ps.rv_col_feature")),
                "importance": st.column_config.ProgressColumn(
                    t("ps.rv_col_weight"), format="%.4f",
                    min_value=0.0, max_value=_max,
                    help=bobot_help,
                ),
            },
            hide_index=True, use_container_width=True,
        )
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def _render_interactive_roc(metrics: dict, eid: str) -> None:
    """Interactive ROC (line chart {FPR,TPR} + diagonal reference + AUC metric
    + dynamic interpretation). roc_curve has only fpr/tpr (no thresholds), so no
    threshold value is fabricated; an operating-point explorer picks a REAL
    point on the curve."""
    auc = metrics.get("roc_auc")
    roc = metrics.get("roc_curve")
    if auc is None and not isinstance(roc, dict):
        st.info(t("ps.rv_no_roc"))
        return

    col_chart, col_auc = st.columns([3, 1])
    fpr = roc.get("fpr") if isinstance(roc, dict) else None
    tpr = roc.get("tpr") if isinstance(roc, dict) else None
    with col_auc:
        if auc is not None:
            st.metric(
                "ROC-AUC", f"{auc:.4f}",
                help=t("ps.rv_roc_reading", quality=_roc_quality(auc)))

    if isinstance(fpr, list) and isinstance(tpr, list) and fpr and tpr:
        n = len(fpr)
        if n > 600:
            idx = np.linspace(0, n - 1, 600).astype(int)
            c_fpr = [fpr[i] for i in idx]
            c_tpr = [tpr[i] for i in idx]
        else:
            c_fpr, c_tpr = fpr, tpr
        _tpr_label, _ref_label = t("ps.rv_tpr_model"), t("ps.rv_chart_random")
        df = pd.DataFrame({"FPR": c_fpr, _tpr_label: c_tpr,
                           _ref_label: c_fpr})
        with col_chart:
            st.line_chart(df, x="FPR", y=[_tpr_label, _ref_label],
                          height=320)

        if n >= 2:
            # (a) Kejujuran "ini titik kurva, BUKAN threshold" menempel pada
            #     penggeser yang menghasilkannya.
            k = st.slider(
                t("ps.rv_roc_point"), 0, n - 1, n // 2,
                key=f"roc_op_{eid}",
                help=t("ps.rv_roc_point_note"))
            oc = st.columns(2)
            oc[0].metric(t("ps.rv_tpr"), f"{tpr[k] * 100:.1f}%")
            oc[1].metric(t("ps.rv_fpr"), f"{fpr[k] * 100:.1f}%")
    elif auc is not None:
        with col_chart:
            st.info(t("rv.no_roc_points"))


def _render_interactive_lc_or_holdout(metrics: dict, eid: str) -> None:
    """Learning curve interactive for HIKARI; for EVE-cbr (no learning curve),
    fall back to a natural- vs balanced-holdout comparison. Numbers come only
    from metrics.json — nothing is fabricated."""
    lc = metrics.get("learning_curve")
    has_lc = isinstance(lc, dict) and "error" not in lc and lc.get("train_sizes")

    if has_lc:
        st.subheader("Learning Curve")
        ts = lc["train_sizes"]
        tm = lc.get("train_scores_mean", [])
        vm = lc.get("val_scores_mean", [])
        tstd = lc.get("train_scores_std", [0] * len(ts))
        vstd = lc.get("val_scores_std", [0] * len(ts))

        data = {"Train": tm}
        if vm:
            data["Validation"] = vm
        show_std = st.checkbox(t("ps.rv_show_std"), key=f"lc_std_{eid}")
        if show_std:
            data["Train +σ"] = [a + b for a, b in zip(tm, tstd)]
            data["Train −σ"] = [a - b for a, b in zip(tm, tstd)]
            if vm:
                data["Val +σ"] = [a + b for a, b in zip(vm, vstd)]
                data["Val −σ"] = [a - b for a, b in zip(vm, vstd)]
        st.line_chart(pd.DataFrame(data, index=ts), height=320)

        tbl = pd.DataFrame({
            "train_size": ts, "train_mean": tm, "train_std": tstd,
            "val_mean": vm if vm else [None] * len(ts),
            "val_std": vstd,
        }).round(4)
        st.dataframe(tbl, hide_index=True, use_container_width=True)

        if vm and tm:
            # AMBANGNYA TIDAK BERUBAH; hanya kalimatnya dari katalog.
            gap = tm[-1] - vm[-1]
            if gap > 0.10:
                verdict = t("ps.rv_lc_overfitting", gap=f"{gap:.3f}")
            elif vm[-1] < 0.70 and abs(gap) < 0.05:
                verdict = t("ps.rv_lc_underfitting", score=f"{vm[-1]:.3f}")
            elif vm[-1] >= 0.80 and abs(gap) < 0.05:
                verdict = t("ps.rv_lc_learns_well", score=f"{vm[-1]:.3f}",
                            gap=f"{gap:.3f}")
            else:
                verdict = t("ps.rv_lc_plain", gap=f"{gap:.3f}",
                            score=f"{vm[-1]:.3f}")
            st.markdown(verdict)
        return

    nat = metrics.get("natural_holdout")
    bal = metrics.get("balanced_holdout")
    if isinstance(nat, dict) and isinstance(bal, dict) and (nat or bal):
        st.subheader(t("ps.rv_dual_holdout"))
        st.info(t("ps.rv_dual_holdout_note"))
        labels = [
            ("precision_attack", "Precision (attack)"),
            ("recall_attack", "Recall (attack)"),
            ("f1_attack", "F1 (attack)"),
            ("auc", "AUC"),
            ("accuracy", "Accuracy"),
        ]
        rows = [
            {t("ps.rv_col_metric"): lab, "Natural-holdout": nat.get(k),
             "Balanced-holdout": bal.get(k)}
            for k, lab in labels if (k in nat or k in bal)
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            chart = {
                lab: {"Natural": nat.get(k), "Balanced": bal.get(k)}
                for k, lab in labels if k in ("precision_attack", "recall_attack", "f1_attack")
                and (nat.get(k) is not None or bal.get(k) is not None)
            }
            if chart:
                st.bar_chart(pd.DataFrame(chart).T)



def _render_per_class(metrics: dict) -> None:
    report = metrics.get("classification_report") or {}
    rows = {k: v for k, v in report.items() if isinstance(v, dict)}
    if rows:
        st.subheader("Per-Class Report")
        df = pd.DataFrame(rows).T.round(4)
        if "support" in df.columns:
            df["support"] = df["support"].astype(int)
        st.dataframe(df, use_container_width=True)


# ─── Top-level orchestrator used by BOTH pages ────────────────────────────

def render_results(payload: dict, *, key: str, pipeline_id: str = "") -> None:
    """Render the full interactive result view from a normalized payload.

    Renders (all top-level — never nested inside a caller's expander):
    metric row → confusion matrix → feature importance → ROC → per-class →
    learning curve / dual-holdout → process log. All charts are interactive;
    static images exist only in the PDF report (built independently).

    ``key`` scopes widget keys (pass the experiment_id). Page-specific extras
    (PDF download, artifact viewer, re-run, delete) stay in the caller.
    """
    m = payload.get("metrics") or {}
    lm = payload.get("label_mapping") or {}
    pid = pipeline_id or payload.get("pipeline_id") or ""
    eid = str(key)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accuracy", f"{m.get('accuracy', 0):.4f}")
    c2.metric("Precision", f"{m.get('precision', 0):.4f}")
    c3.metric("Recall", f"{m.get('recall', 0):.4f}")
    c4.metric("F1-Score", f"{m.get('f1_score', 0):.4f}")

    if "confusion_matrix" in m:
        st.subheader("Confusion Matrix")
        _render_interactive_cm(m["confusion_matrix"], lm, eid)

    st.subheader("Feature Importance")
    _render_interactive_fi(m.get("feature_importance") or [], pid, m.get("feature_importance_note"), eid)

    if ("roc_auc" in m) or ("roc_curve" in m):
        st.subheader("ROC Curve")
        _render_interactive_roc(m, eid)

    _render_per_class(m)

    _render_interactive_lc_or_holdout(m, eid)

    if m.get("process_log"):
        with st.expander("Process Log", expanded=False):
            st.code(m["process_log"], language=None)
