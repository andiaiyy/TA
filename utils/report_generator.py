"""
PDF report generator for experiment results — 9-section thesis-grade layout.

Sections (numbered, in order):
  1. Tujuan Model            (static, dataset-aware)
  2. Dataset dan Karakteristik (auto + static)
  3. Pipeline ML              (auto from get_info + flow diagram)
  4. Environment dan Reproducibility (auto from metadata.environment)
  5. Metode Evaluasi          (static template)
  6. Hasil Model              (auto from metrics; reuses existing PNG renderers)
  7. Analisis Hasil           (placeholder, NOT auto-generated)
  8. Integrasi ke Platform    (honest description of actual capabilities)
  9. Limitasi                 (static + audit findings)

Signature, return type (bytes), and ReportLab mechanism are preserved exactly
so the call site in ui/views/view_results.py keeps working.

Rules: No database access. No UI imports.
"""
import io
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable,
)

# ── Shared color palette (single source) ──────────────────────────────────
_PRIMARY = HexColor('#1a1a2e')
_ACCENT = HexColor('#2563eb')
_MUTED = HexColor('#666666')
_GRID = HexColor('#cccccc')
_PLACEHOLDER_FILL = HexColor('#fff8e1')   # light yellow for "needs human fill"
_PLACEHOLDER_BORDER = HexColor('#b08800')
_NOTE_FILL = HexColor('#f0f4ff')          # light blue for honest-limitation notes


# ─── Entry point (signature preserved) ────────────────────────────────────

def generate_report(
    experiment_id: str,
    dataset_type: str,
    dataset_path: str,
    dataset_hash: str,
    pipeline_id: str,
    pipeline_info: dict,
    metrics: dict,
    metadata: dict | None = None,
    label_mapping: dict | None = None,
    feature_names: list[str] | None = None,
) -> bytes:
    """Generate the 9-section PDF and return it as bytes."""
    ctx = _build_context(
        experiment_id=experiment_id, dataset_type=dataset_type,
        dataset_path=dataset_path, dataset_hash=dataset_hash,
        pipeline_id=pipeline_id, pipeline_info=pipeline_info or {},
        metrics=metrics or {}, metadata=metadata or {},
        label_mapping=label_mapping, feature_names=feature_names,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    styles = _build_styles()
    story: list = []

    _cover(story, styles, ctx)

    for section_fn in (
        _section_1_tujuan,
        _section_2_dataset,
        _section_3_pipeline,
        _section_4_environment,
        _section_5_metode,
        _section_6_hasil,
        _section_7_analisis,
        _section_8_integrasi,
        _section_9_limitasi,
    ):
        try:
            section_fn(story, styles, ctx)
        except Exception as e:
            # Defensive: if one section raises, embed the error and keep going
            # so the reader still gets the rest of the report.
            story.append(Paragraph(
                f"<i>(Bagian gagal di-render: {type(e).__name__}: {e})</i>",
                styles["small_muted"],
            ))

    _footer(story, styles, ctx)
    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ─── Context builder (single read of all inputs) ──────────────────────────

def _build_context(**kw) -> dict:
    """Collect every piece of data the sections may need into one dict.

    Defensive: missing fields become None / [] / {}; sections decide how to
    render absence. No defaults that lie about values (e.g. accuracy=0).
    """
    md = kw.get("metadata") or {}
    env = md.get("environment") if isinstance(md.get("environment"), dict) else {}
    metrics = kw.get("metrics") or {}
    pinfo = kw.get("pipeline_info") or {}

    created_at = md.get("created_at")
    completed_at = md.get("completed_at")
    wall_clock = _wall_clock(created_at, completed_at)

    return {
        # IDs and paths
        "experiment_id": kw.get("experiment_id"),
        "dataset_type": kw.get("dataset_type"),
        "dataset_path": kw.get("dataset_path"),
        "dataset_hash": kw.get("dataset_hash") or "N/A",
        "pipeline_id": kw.get("pipeline_id"),
        "label_mapping": kw.get("label_mapping"),
        "feature_names": kw.get("feature_names") or md.get("feature_names"),
        # Pipeline metadata (from get_info)
        "paper": pinfo.get("paper"),
        "algorithm": pinfo.get("algorithm"),
        "preprocessing_steps": pinfo.get("preprocessing_steps") or [],
        "feature_selection": pinfo.get("feature_selection"),
        "fixed_params": pinfo.get("fixed_params") or {},
        "train_test_split": pinfo.get("train_test_split") or {},
        "runtime_warning": pinfo.get("runtime_warning"),
        # Metrics
        "metrics": metrics,
        "accuracy": metrics.get("accuracy"),
        "precision": metrics.get("precision"),
        "recall": metrics.get("recall"),
        "f1_score": metrics.get("f1_score"),
        "roc_auc": metrics.get("roc_auc"),
        "confusion_matrix": metrics.get("confusion_matrix"),
        "feature_importance": metrics.get("feature_importance") or [],
        "classification_report": metrics.get("classification_report") or {},
        "learning_curve": metrics.get("learning_curve") if isinstance(
            metrics.get("learning_curve"), dict
        ) and "error" not in (metrics.get("learning_curve") or {}) else None,
        # Timing
        "created_at": created_at or "N/A",
        "completed_at": completed_at or "N/A",
        "wall_clock": wall_clock,   # str or None
        # Environment
        "env": env,
        "python_version": env.get("python_version"),
        "sklearn_version": env.get("sklearn_version"),
        "pandas_version": env.get("pandas_version"),
        "numpy_version": env.get("numpy_version"),
        "is_docker": env.get("is_docker"),
        "docker_image_version": env.get("docker_image_version"),
        "platform_str": env.get("platform"),
    }


def _wall_clock(created_at, completed_at) -> str | None:
    if not created_at or not completed_at:
        return None
    try:
        s = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        e = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
        secs = (e - s).total_seconds()
        if secs < 0:
            return None
        if secs < 60:
            return f"{secs:.1f} s"
        if secs < 3600:
            return f"{secs/60:.2f} min"
        return f"{secs/3600:.2f} h"
    except Exception:
        return None


# ─── Style sheet ──────────────────────────────────────────────────────────

def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontSize=20, spaceAfter=4*mm),
        "subtitle": ParagraphStyle("Sub", parent=base["Heading4"], fontSize=11,
                                    textColor=_MUTED, spaceAfter=4*mm),
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontSize=14,
                                   spaceBefore=8*mm, spaceAfter=3*mm, textColor=_PRIMARY),
        "subsection": ParagraphStyle("Subsec", parent=base["Heading3"], fontSize=11,
                                      spaceBefore=4*mm, spaceAfter=2*mm, textColor=_PRIMARY),
        "normal": base["Normal"],
        "italic": ParagraphStyle("Italic", parent=base["Normal"], fontName="Helvetica-Oblique"),
        "small_muted": ParagraphStyle("SmallMuted", parent=base["Normal"],
                                       fontSize=8, textColor=_MUTED),
        "placeholder": ParagraphStyle("Placeholder", parent=base["Normal"],
                                       fontName="Helvetica-Oblique", textColor=HexColor('#705500')),
        "note": ParagraphStyle("Note", parent=base["Normal"],
                                fontName="Helvetica-Oblique", fontSize=9, textColor=_MUTED),
    }


# ─── Reusable mini-blocks ─────────────────────────────────────────────────

def _placeholder_block(text: str, styles: dict):
    """Visually distinct [ISI ANALISIS ...] block (light-yellow with border)."""
    p = Paragraph(text, styles["placeholder"])
    t = Table([[p]], colWidths=[16*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PLACEHOLDER_FILL),
        ("BOX", (0, 0), (-1, -1), 0.75, _PLACEHOLDER_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _kv_table(rows: list[list[str]], col_widths=(5*cm, 11*cm)):
    t = Table(rows, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor('#f0f0f0')),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _section_heading(story, styles, number: int, title: str) -> None:
    story.append(Paragraph(f"{number}. {title}", styles["section"]))


def _none_or(v, fallback="[tidak tersedia]"):
    """Render value or honest placeholder. Avoids printing 'None' or fake 0."""
    if v is None or v == "":
        return fallback
    return str(v)


# ─── Cover ────────────────────────────────────────────────────────────────

def _cover(story, styles, ctx):
    story.append(Paragraph("Experiment Report", styles["title"]))
    story.append(Paragraph("IDS Research Pipeline Execution System", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_GRID))
    story.append(Spacer(1, 4*mm))
    story.append(_kv_table([
        ["Experiment ID", _none_or(ctx["experiment_id"])],
        ["Dataset", _none_or(ctx["dataset_type"])],
        ["Pipeline", _none_or(ctx["pipeline_id"])],
        ["Algorithm", _none_or(ctx["algorithm"])],
        ["Created", _none_or(ctx["created_at"])],
        ["Completed", _none_or(ctx["completed_at"])],
    ]))


# ─── 1. Tujuan Model ──────────────────────────────────────────────────────

_TUJUAN_BY_DATASET = {
    "HIKARI2021": (
        "Model machine learning pada eksperimen ini berfungsi sebagai detection engine untuk "
        "klasifikasi trafik terenkripsi pada dataset HIKARI2021 (varian ALLFLOWMETER), dengan "
        "label biner benign versus malicious. Klasifikasi dilakukan pada fitur flow yang sudah "
        "diekstraksi; eksperimen tidak melakukan dekripsi maupun analisis payload."
    ),
    "EVE_SURICATA": (
        "Model machine learning pada eksperimen ini berfungsi sebagai detection engine untuk "
        "klasifikasi catatan EVE Suricata dengan label biner yang diturunkan dari kehadiran "
        "alert berisi severity. Eksperimen berorientasi batch pada berkas NDJSON yang sudah "
        "tersedia, bukan pada stream alert real-time dari Suricata yang sedang berjalan."
    ),
}


def _section_1_tujuan(story, styles, ctx):
    _section_heading(story, styles, 1, "Tujuan Model")
    text = _TUJUAN_BY_DATASET.get(
        ctx["dataset_type"],
        "Model machine learning pada eksperimen ini berfungsi sebagai detection engine "
        "yang melakukan klasifikasi pada dataset terpilih. Eksperimen berorientasi batch "
        "dan tidak melakukan alert generation real-time."
    )
    story.append(Paragraph(text, styles["normal"]))


# ─── 2. Dataset dan Karakteristik ─────────────────────────────────────────

def _section_2_dataset(story, styles, ctx):
    _section_heading(story, styles, 2, "Dataset dan Karakteristik")

    full_hash = ctx["dataset_hash"]
    rows = [
        ["Nama dataset", _none_or(ctx["dataset_type"])],
        ["Berkas sumber", _none_or(ctx["dataset_path"])],
        ["SHA-256 (lengkap)", full_hash],
        ["Jumlah baris (total)", "[ISI: tidak tersimpan di metadata.json]"],
        ["Baris training", "[ISI: tidak tersimpan di metadata.json]"],
        ["Baris testing", "[ISI: tidak tersimpan di metadata.json]"],
        ["Distribusi label (benign vs malicious)", "[ISI: tidak tersimpan; lihat confusion matrix di Bagian 6]"],
    ]
    story.append(_kv_table(rows))
    story.append(Spacer(1, 3*mm))

    story.append(Paragraph("Karakteristik dan preprocessing yang dipakai pipeline:",
                            styles["subsection"]))

    char_map = {
        "HIKARI2021": "Fitur numerik berbasis flow varian ALLFLOWMETER, mencakup payload statistics dan window/header counts.",
        "EVE_SURICATA": "Hasil parsing NDJSON EVE Suricata; tujuh fase preprocessing menurunkan label dari alert.severity.",
    }
    story.append(Paragraph(
        f"<b>Jenis fitur:</b> {char_map.get(ctx['dataset_type'], '[ISI: jelaskan jenis fitur]')}",
        styles["normal"],
    ))

    steps = ctx["preprocessing_steps"]
    if steps:
        steps_html = "<br/>".join(f"<b>{i+1}.</b> {s}" for i, s in enumerate(steps))
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(f"<b>Langkah preprocessing (dari get_info):</b><br/>{steps_html}",
                                styles["normal"]))
    else:
        story.append(Paragraph(
            "<b>Langkah preprocessing:</b> tidak tersedia dari pipeline_info.",
            styles["italic"],
        ))


# ─── 3. Pipeline ML ───────────────────────────────────────────────────────

_FLOW_DEFAULT = [
    "Dataset Ingestion (CSV / NDJSON)",
    "Preprocessing (cleaning, encoding)",
    "Feature Selection",
    "Train-Test Split (stratified, random_state tetap)",
    "Model Training (hyperparameter terkunci)",
    "Evaluation (metrik utama + extra_info)",
    "Artifact Serialization (joblib model.pkl + metrics.json + metadata.json)",
]


def _section_3_pipeline(story, styles, ctx):
    _section_heading(story, styles, 3, "Pipeline ML")

    # Use feature_selection text from get_info if available
    fs = ctx["feature_selection"] or "(detail di pipeline_info.feature_selection)"

    flow = list(_FLOW_DEFAULT)
    flow[2] = f"Feature Selection: {fs}"

    if ctx["dataset_type"] == "EVE_SURICATA":
        flow.insert(1, "EVE preprocessing tujuh fase (load+label, feature engineering, computed features, cleaning, correlation analysis, train-test split, feature selection)")

    # Render as a numbered flow (text-based, no ASCII art)
    flow_html = "<br/>".join(
        f"<b>{i+1}.</b> {step} &nbsp;&nbsp;&#8595;" if i < len(flow) - 1 else f"<b>{i+1}.</b> {step}"
        for i, step in enumerate(flow)
    )
    story.append(Paragraph(flow_html, styles["normal"]))

    story.append(Spacer(1, 3*mm))
    note = (
        "Alur berhenti pada serialisasi artefak. Platform ini tidak menyediakan "
        "deployment ke endpoint API inference atau alert storage; model dipakai "
        "kembali untuk evaluasi atau rerun, bukan untuk serving real-time."
    )
    story.append(Paragraph(f"<i>Catatan kejujuran:</i> {note}", styles["note"]))

    # Fixed parameters + train-test split from get_info
    if ctx["fixed_params"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Hyperparameter terkunci (dari get_info):", styles["subsection"]))
        rows = [[k, str(v)] for k, v in ctx["fixed_params"].items()]
        story.append(_kv_table(rows, col_widths=(6*cm, 10*cm)))

    if ctx["train_test_split"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Konfigurasi train-test split:", styles["subsection"]))
        rows = [[k, str(v)] for k, v in ctx["train_test_split"].items()]
        story.append(_kv_table(rows, col_widths=(6*cm, 10*cm)))


# ─── 4. Environment dan Reproducibility ───────────────────────────────────

def _section_4_environment(story, styles, ctx):
    _section_heading(story, styles, 4, "Environment dan Reproducibility")

    rows = [
        ["Python version", _none_or(ctx["python_version"])],
        ["scikit-learn", _none_or(ctx["sklearn_version"])],
        ["pandas", _none_or(ctx["pandas_version"])],
        ["numpy", _none_or(ctx["numpy_version"])],
        ["Platform", _none_or(ctx["platform_str"])],
        ["Docker", "Ya" if ctx["is_docker"] else ("Tidak" if ctx["is_docker"] is False else "[tidak tercatat]")],
        ["Docker image version", _none_or(ctx["docker_image_version"])],
        ["random_state (invariant platform)", "42 (terkunci untuk seluruh operasi stokastik per CLAUDE.md)"],
        ["Dataset SHA-256", ctx["dataset_hash"]],
    ]
    story.append(_kv_table(rows))

    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "Kombinasi random_state yang dikunci, dataset hash yang tercatat, dan lingkungan "
        "yang dikontainerisasi memungkinkan eksperimen direproduksi bit-per-bit pada mesin "
        "lain. Selama hash dataset sama, kode pipeline sama, dan environment image sama, "
        "metrik yang dihasilkan akan identik antar eksekusi. Sifat ini adalah nilai jual "
        "utama platform dan menjadi dasar klaim reproducibility tugas akhir.",
        styles["normal"],
    ))


# ─── 5. Metode Evaluasi ───────────────────────────────────────────────────

_METRIC_EXPLAIN = [
    ("Accuracy",
     "Proporsi prediksi yang benar dari total prediksi. Pada dataset IDS dengan kelas "
     "tidak seimbang, accuracy bisa menyesatkan karena dominansi kelas benign."),
    ("Precision",
     "Dari semua trafik yang ditandai malicious oleh model, berapa proporsi yang benar-benar "
     "malicious. Precision rendah berarti banyak false positive, yang menghasilkan alert "
     "lelah (alert fatigue) pada operator IDS."),
    ("Recall",
     "Dari semua trafik malicious yang sebenarnya, berapa proporsi yang berhasil "
     "ditemukan model. Recall rendah berarti banyak false negative, yaitu serangan lolos "
     "tidak terdeteksi. Pada konteks keamanan, recall sering lebih kritis daripada precision."),
    ("F1-score",
     "Harmonic mean dari precision dan recall, memberi satu angka ringkasan ketika kedua "
     "sisi diberi bobot sama. Digunakan sebagai metrik utama bila tidak ada preferensi "
     "operasional spesifik antara false positive dan false negative."),
    ("ROC-AUC",
     "Area di bawah kurva ROC, mengukur kemampuan model membedakan kelas pada berbagai "
     "threshold. Nilai mendekati 1 menandakan separabilitas yang baik; 0,5 setara tebak acak."),
    ("Confusion Matrix",
     "Tabel jumlah prediksi per pasangan (actual, predicted). Sumber data mentah untuk "
     "menghitung precision, recall, false positive rate, dan menelusuri kelas mana yang "
     "saling tertukar."),
]


def _section_5_metode(story, styles, ctx):
    _section_heading(story, styles, 5, "Metode Evaluasi")
    story.append(Paragraph(
        "Pada konteks Intrusion Detection System, false negative (serangan lolos) dan "
        "false positive (alarm palsu) memiliki konsekuensi operasional yang berbeda. "
        "Karenanya, evaluasi tidak bergantung pada accuracy tunggal, melainkan pada "
        "kombinasi metrik berikut yang masing-masing menyoroti aspek berbeda dari performa.",
        styles["normal"],
    ))
    story.append(Spacer(1, 2*mm))
    for name, desc in _METRIC_EXPLAIN:
        story.append(Paragraph(f"<b>{name}.</b> {desc}", styles["normal"]))
        story.append(Spacer(1, 1*mm))


# ─── 6. Hasil Model ───────────────────────────────────────────────────────

def _section_6_hasil(story, styles, ctx):
    _section_heading(story, styles, 6, "Hasil Model")

    metrics = ctx["metrics"]
    rows = [["Metrik", "Nilai"]]
    def _fmt(v):
        return f"{v:.6f}" if isinstance(v, (int, float)) else "[tidak tersedia]"
    rows += [
        ["Accuracy", _fmt(ctx["accuracy"])],
        ["Precision (weighted)", _fmt(ctx["precision"])],
        ["Recall (weighted)", _fmt(ctx["recall"])],
        ["F1-score (weighted)", _fmt(ctx["f1_score"])],
    ]
    if ctx["roc_auc"] is not None:
        rows.append(["ROC-AUC", _fmt(ctx["roc_auc"])])
    wc_label = "Wall-clock elapsed (created → completed)"
    rows.append([wc_label, ctx["wall_clock"] or "[tidak dapat dihitung]"])

    t = Table(rows, colWidths=[7*cm, 6*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Catatan: wall-clock di atas dihitung dari created_at hingga completed_at; ini "
        "termasuk waktu antrian (queue) untuk mode asinkron. Platform tidak menyimpan "
        "waktu mulai eksekusi terpisah dan tidak mengukur inference latency.",
        styles["note"],
    ))

    # Confusion matrix
    if ctx["confusion_matrix"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Confusion Matrix", styles["subsection"]))
        try:
            cm_img = _render_confusion_matrix(
                np.array(ctx["confusion_matrix"]),
                label_mapping=ctx["label_mapping"],
            )
            story.append(Image(cm_img, width=12*cm, height=10*cm))
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender confusion matrix: {e}</i>", styles["italic"]))

    # ROC curve
    if ctx["roc_auc"] is not None or "roc_curve" in metrics:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("ROC Curve", styles["subsection"]))
        try:
            roc_img = _render_roc_curve(metrics)
            story.append(Image(roc_img, width=12*cm, height=10*cm))
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender ROC curve: {e}</i>", styles["italic"]))

    # Feature importance
    if ctx["feature_importance"]:
        story.append(PageBreak())
        story.append(Paragraph("Feature Importance", styles["subsection"]))
        try:
            fi_img = _render_feature_importance(ctx["feature_importance"])
            story.append(Image(fi_img, width=14*cm, height=8*cm))
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender feature importance: {e}</i>", styles["italic"]))
    elif ctx["algorithm"] and any(k in (ctx["algorithm"] or "").lower() for k in ("knn", "naive", "logistic")):
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            "<i>Feature importance tidak tersedia untuk algoritma ini.</i>",
            styles["italic"],
        ))

    # Per-class classification report
    if ctx["classification_report"]:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("Per-Class Classification Report", styles["subsection"]))
        rep = ctx["classification_report"]
        class_rows = {k: v for k, v in rep.items() if isinstance(v, dict)}
        if class_rows:
            header = ["Class", "Precision", "Recall", "F1-Score", "Support"]
            data = [header]
            for cls, m in class_rows.items():
                data.append([
                    cls,
                    f"{m.get('precision', 0):.4f}",
                    f"{m.get('recall', 0):.4f}",
                    f"{m.get('f1-score', 0):.4f}",
                    str(int(m.get('support', 0))),
                ])
            rt = Table(data, colWidths=[4*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
            rt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(rt)

    # Learning curve
    if ctx["learning_curve"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Learning Curve", styles["subsection"]))
        try:
            lc_img = _render_learning_curve(ctx["learning_curve"])
            story.append(Image(lc_img, width=14*cm, height=9*cm))
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender learning curve: {e}</i>", styles["italic"]))


# ─── 7. Analisis Hasil (placeholders) ─────────────────────────────────────

_ANALYSIS_PROMPTS = [
    "[ISI ANALISIS: Apakah performa model sesuai ekspektasi untuk dataset ini? Bandingkan "
    "dengan klaim paper rujukan bila ada. Sebutkan apakah accuracy/F1 berada dalam rentang "
    "yang dilaporkan paper aslinya, dan jelaskan penyebab bila terdapat selisih signifikan.]",

    "[ISI ANALISIS: Apakah imbalance kelas memengaruhi hasil? Bandingkan precision dan "
    "recall pada metrik weighted dan pada per-class classification report di Bagian 6. "
    "Bila terdapat selisih besar antara kelas mayoritas dan minoritas, jelaskan implikasinya "
    "untuk operasional IDS.]",

    "[ISI ANALISIS: Kategori serangan atau pola trafik mana yang paling sulit diklasifikasi? "
    "Rujuk confusion matrix. Identifikasi kelas yang banyak salah-prediksi menjadi kelas lain "
    "dan diskusikan kemungkinan penyebab dari sudut pandang karakteristik fitur.]",

    "[ISI ANALISIS: Bagaimana trade-off precision versus recall pada konteks operasional IDS "
    "untuk skenario penggunaan model ini? Pada SOC dengan kapasitas analyst terbatas, "
    "precision rendah berarti alert fatigue; pada lingkungan kritis, recall rendah berarti "
    "serangan lolos. Sebutkan mana yang lebih relevan dan mengapa.]",

    "[ISI ANALISIS: Apakah ada indikasi overfitting? Bandingkan training score dan validation "
    "score pada learning curve di Bagian 6 (bila tersedia). Selisih besar antara keduanya "
    "atau plateau validation score yang dini menandakan overfitting; jelaskan mitigasi yang "
    "telah diterapkan pipeline.]",
]


def _section_7_analisis(story, styles, ctx):
    _section_heading(story, styles, 7, "Analisis Hasil")
    story.append(Paragraph(
        "<i>Bagian ini sengaja diisi peneliti setelah meninjau hasil. Placeholder di "
        "bawah memandu pertanyaan-pertanyaan kunci yang perlu dijawab; jangan dihapus "
        "tanpa pengisian.</i>",
        styles["note"],
    ))
    story.append(Spacer(1, 2*mm))
    for prompt in _ANALYSIS_PROMPTS:
        story.append(_placeholder_block(prompt, styles))
        story.append(Spacer(1, 2*mm))


# ─── 8. Integrasi ke Platform ─────────────────────────────────────────────

def _section_8_integrasi(story, styles, ctx):
    _section_heading(story, styles, 8, "Integrasi ke Platform")

    story.append(Paragraph(
        "Platform mengintegrasikan model ke dalam alur eksperimen yang terkontrol, bukan "
        "ke dalam jalur produksi serving. Berikut detail kapabilitas aktual saat laporan "
        "ini dibuat, ditulis apa adanya tanpa fitur yang dilebih-lebihkan.",
        styles["normal"],
    ))
    story.append(Spacer(1, 2*mm))

    rows = [
        ["Penyimpanan model",
         "joblib di storage/artifacts/{experiment_id}/model.pkl"],
        ["Penyimpanan metrik",
         "metrics.json (metrik utama + extra_info) di direktori artefak yang sama"],
        ["Penyimpanan metadata",
         "metadata.json (dataset_hash SHA-256, pipeline_id, timestamp, environment)"],
        ["Antarmuka pengguna",
         "Streamlit (ui/views/). Tidak terdapat endpoint API inference (FastAPI/Flask)."],
        ["Mode eksekusi sinkron",
         "workers/local_worker.py — pipeline.run() langsung di proses pemanggil"],
        ["Mode eksekusi asinkron",
         "workers/celery_worker.py via Celery + Redis (aktif bila USE_ASYNC=true)"],
        ["Orkestrasi",
         "orchestrator/ (validation, execution dispatch, experiment lifecycle, result read)"],
        ["Containerization",
         "docker-compose dengan tiga service: ids_redis, ids_worker, ids_ui"],
        ["Inference real-time / API serving",
         "Tidak tersedia. Platform berorientasi eksperimen batch."],
        ["Pengukuran inference latency / throughput",
         "Tidak diukur. Yang tersedia hanya wall-clock total eksperimen."],
    ]
    story.append(_kv_table(rows, col_widths=(5.5*cm, 10.5*cm)))


# ─── 9. Limitasi ──────────────────────────────────────────────────────────

_LIMITATIONS = [
    "Dataset publik (HIKARI2021, EVE Suricata) tidak selalu merepresentasikan "
    "trafik jaringan dunia nyata terkini; profil serangan dan distribusi fitur dapat berbeda "
    "dengan kondisi operasional pengguna platform.",

    "Platform tidak melakukan packet capture real-time. Masukan adalah dataset yang sudah "
    "diekstraksi menjadi fitur flow (CSV) atau catatan alert NDJSON. Integrasi dengan "
    "Suricata yang sedang berjalan, NetFlow live, atau sumber lain di luar lingkup platform.",

    "Tidak terdapat online learning atau adaptive retraining. Setiap eksperimen melatih "
    "model dari nol dengan random_state tetap; model tidak diperbarui secara inkremental "
    "ketika tersedia data baru.",

    "Tidak terdapat penanganan khusus untuk encrypted traffic di luar fitur yang sudah "
    "tersedia di dataset (misalnya HIKARI2021 ALLFLOWMETER). Platform tidak melakukan "
    "decryption, fingerprinting TLS lanjutan, atau analisis payload terenkripsi.",

    "Tidak terdapat endpoint API inference. Model tidak dapat dipanggil sebagai service "
    "untuk klasifikasi real-time; konsumsi model dilakukan dalam konteks evaluasi pada "
    "antarmuka platform atau melalui rerun eksperimen.",

    "Tidak terdapat pengukuran inference latency atau throughput. Wall-clock yang tercatat "
    "hanya mencakup durasi total eksperimen (queue + execution); membandingkan model untuk "
    "skenario produksi memerlukan instrumentasi tambahan.",

    "Pipeline tertentu memiliki keterbatasan algoritmik yang melekat. Sebagai contoh, "
    "Support Vector Classifier pada dataset HIKARI2021 berjalan sangat lambat pada data "
    "berukuran ratusan ribu baris karena kompleksitas O(n²) — platform menampilkan "
    "runtime warning di antarmuka sebelum eksekusi dimulai.",
]


def _section_9_limitasi(story, styles, ctx):
    _section_heading(story, styles, 9, "Limitasi")
    story.append(Paragraph(
        "Keterbatasan berikut dilaporkan secara terbuka. Pengungkapan ini bukan untuk "
        "mengurangi nilai platform, melainkan untuk memberikan panduan jujur bagi peneliti "
        "lain yang ingin memakai atau memperluas hasil eksperimen.",
        styles["normal"],
    ))
    story.append(Spacer(1, 2*mm))
    for i, lim in enumerate(_LIMITATIONS, 1):
        story.append(Paragraph(f"<b>{i}.</b> {lim}", styles["normal"]))
        story.append(Spacer(1, 1*mm))

    # Append per-experiment runtime warning if get_info had one
    if ctx["runtime_warning"]:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"<b>Catatan khusus pipeline ini:</b> {ctx['runtime_warning']}",
            styles["note"],
        ))


# ─── Footer ───────────────────────────────────────────────────────────────

def _footer(story, styles, ctx):
    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRID))
    story.append(Paragraph(
        f"Generated by IDS Research Pipeline System  -  "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}  -  "
        f"experiment {ctx['experiment_id']}",
        styles["small_muted"],
    ))


# ─── Existing chart render helpers (preserved verbatim) ───────────────────

def _render_confusion_matrix(cm: np.ndarray, label_mapping: dict | None = None) -> io.BytesIO:
    """Render confusion matrix as PNG and return as BytesIO."""
    labels = []
    if label_mapping:
        labels = sorted(label_mapping.keys(), key=lambda k: label_mapping[k])

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(cm, interpolation='nearest', cmap='Blues')
    plt.colorbar(im, ax=ax)

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
    ax.set_title("Confusion Matrix")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _render_roc_curve(metrics: dict) -> io.BytesIO:
    """Render ROC curve as PNG and return as BytesIO."""
    fig, ax = plt.subplots(figsize=(6, 5))

    if "roc_curve" in metrics:
        roc = metrics["roc_curve"]
        fpr = roc["fpr"]
        tpr = roc["tpr"]
        if isinstance(fpr, list):
            ax.plot(fpr, tpr, label=f"ROC (AUC = {metrics.get('roc_auc', 0):.4f})", linewidth=2)
        elif isinstance(fpr, dict):
            for cls_name in fpr:
                ax.plot(fpr[cls_name], tpr[cls_name], label=cls_name, linewidth=1.5)
    elif "roc_curves_per_class" in metrics:
        for cls_name, curve in metrics["roc_curves_per_class"].items():
            ax.plot(curve["fpr"], curve["tpr"], label=cls_name, linewidth=1.5)

    ax.plot([0, 1], [0, 1], 'k--', alpha=0.5, label="Random")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title(f"ROC Curve (AUC = {metrics.get('roc_auc', 0):.4f})")
    ax.legend(loc="lower right")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _render_feature_importance(feature_importance: list[dict]) -> io.BytesIO:
    """Render feature importance bar chart as PNG and return as BytesIO."""
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(
        [item["feature"] for item in reversed(feature_importance)],
        [item["importance"] for item in reversed(feature_importance)],
        color="#2563EB",
    )
    ax.set_xlabel("Importance")
    ax.set_title("Feature Importance")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _render_learning_curve(lc: dict) -> io.BytesIO:
    """Render learning curve as PNG and return as BytesIO."""
    train_sizes = lc["train_sizes"]
    train_mean = lc["train_scores_mean"]
    train_std = lc.get("train_scores_std", [0] * len(train_sizes))
    val_mean = lc.get("val_scores_mean", lc.get("test_scores_mean", []))
    val_std = lc.get("val_scores_std", [0] * len(train_sizes))

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.fill_between(train_sizes,
                    [m - s for m, s in zip(train_mean, train_std)],
                    [m + s for m, s in zip(train_mean, train_std)],
                    alpha=0.1, color="blue")
    ax.fill_between(train_sizes,
                    [m - s for m, s in zip(val_mean, val_std)],
                    [m + s for m, s in zip(val_mean, val_std)],
                    alpha=0.1, color="orange")
    ax.plot(train_sizes, train_mean, 'o-', color="blue", label="Training", linewidth=2)
    ax.plot(train_sizes, val_mean, 'o-', color="orange", label="Validation", linewidth=2)

    ax.set_xlabel("Training Set Size")
    ax.set_ylabel("F1 Score (Weighted)")
    ax.set_title("Learning Curve")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf
