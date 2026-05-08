"""
PDF report generator for experiment results.

Generates a professional, thesis-grade PDF containing:
  - Title + experiment metadata
  - Summary metrics table
  - Confusion matrix chart
  - ROC curve chart
  - Feature importance chart
  - Per-class classification report table
  - Learning curve chart

Uses reportlab for PDF generation and matplotlib for chart rendering.

Rules:
  - No database access
  - No UI imports
  - Returns bytes (PDF content) — caller decides what to do with it
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
from reportlab.lib.enums import TA_CENTER, TA_LEFT


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
    """
    Generate a PDF report and return it as bytes.

    Args:
        experiment_id: UUID string
        dataset_type: e.g. "CICIDS2017"
        dataset_path: path to CSV
        dataset_hash: SHA-256
        pipeline_id: e.g. "cicids2017.rf_paper_a"
        pipeline_info: from pipeline.get_info() — paper, algorithm, steps, params
        metrics: full metrics dict (including extra_info like roc_auc, feature_importance, etc.)
        metadata: experiment metadata dict (optional)
        label_mapping: e.g. {"BENIGN": 0, "DDoS": 1}
        feature_names: list of feature names used

    Returns:
        PDF file contents as bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=18, spaceAfter=6*mm,
    )
    heading_style = ParagraphStyle(
        'CustomHeading', parent=styles['Heading2'],
        fontSize=14, spaceBefore=8*mm, spaceAfter=4*mm,
        textColor=HexColor('#1a1a2e'),
    )
    normal_style = styles['Normal']
    small_style = ParagraphStyle(
        'Small', parent=styles['Normal'],
        fontSize=8, textColor=HexColor('#666666'),
    )

    story = []

    # ── Title ──────────────────────────────────────────────────
    story.append(Paragraph("Experiment Report", title_style))
    story.append(Paragraph("IDS Research Pipeline Execution System", styles['Heading4']))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#cccccc')))
    story.append(Spacer(1, 4*mm))

    # ── Metadata table ─────────────────────────────────────────
    story.append(Paragraph("Experiment Metadata", heading_style))

    created_at = metadata.get("created_at", "N/A") if metadata else "N/A"
    completed_at = metadata.get("completed_at", "N/A") if metadata else "N/A"

    hash_display = (dataset_hash[:32] + "...") if len(dataset_hash) > 32 else dataset_hash
    meta_data = [
        ["Experiment ID", experiment_id],
        ["Dataset Type", dataset_type],
        ["Dataset Path", dataset_path],
        ["Dataset Hash (SHA-256)", hash_display],
        ["Pipeline ID", pipeline_id],
        ["Paper", pipeline_info.get("paper", "N/A")],
        ["Algorithm", pipeline_info.get("algorithm", "N/A")],
        ["Created At", created_at],
        ["Completed At", completed_at],
    ]
    if feature_names:
        meta_data.append(["Features Used", ", ".join(feature_names)])

    meta_table = Table(meta_data, colWidths=[5*cm, 11*cm])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#f0f0f0')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 4*mm))

    # ── Pipeline configuration ─────────────────────────────────
    if pipeline_info.get("preprocessing_steps"):
        story.append(Paragraph("Pipeline Configuration", heading_style))
        steps_text = "<br/>".join(
            f"<b>{i+1}.</b> {s}"
            for i, s in enumerate(pipeline_info["preprocessing_steps"])
        )
        story.append(Paragraph(f"<b>Preprocessing:</b><br/>{steps_text}", normal_style))
        story.append(Spacer(1, 2*mm))

        if pipeline_info.get("feature_selection"):
            story.append(Paragraph(
                f"<b>Feature Selection:</b> {pipeline_info['feature_selection']}", normal_style,
            ))
            story.append(Spacer(1, 2*mm))

        if pipeline_info.get("fixed_params"):
            params_str = ", ".join(f"{k}={v}" for k, v in pipeline_info["fixed_params"].items())
            story.append(Paragraph(f"<b>Fixed Parameters:</b> {params_str}", normal_style))
            story.append(Spacer(1, 2*mm))

        if pipeline_info.get("train_test_split"):
            split_str = ", ".join(f"{k}={v}" for k, v in pipeline_info["train_test_split"].items())
            story.append(Paragraph(f"<b>Train/Test Split:</b> {split_str}", normal_style))

    # ── Summary metrics ────────────────────────────────────────
    story.append(Paragraph("Summary Metrics", heading_style))

    metrics_data = [
        ["Metric", "Value"],
        ["Accuracy", f"{metrics.get('accuracy', 0):.6f}"],
        ["Precision (weighted)", f"{metrics.get('precision', 0):.6f}"],
        ["Recall (weighted)", f"{metrics.get('recall', 0):.6f}"],
        ["F1-Score (weighted)", f"{metrics.get('f1_score', 0):.6f}"],
    ]
    if "roc_auc" in metrics:
        metrics_data.append(["ROC-AUC", f"{metrics['roc_auc']:.6f}"])

    metrics_table = Table(metrics_data, colWidths=[6*cm, 5*cm])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(metrics_table)

    # ── Confusion matrix ───────────────────────────────────────
    if "confusion_matrix" in metrics:
        story.append(Paragraph("Confusion Matrix", heading_style))
        cm_img = _render_confusion_matrix(
            np.array(metrics["confusion_matrix"]),
            label_mapping=label_mapping,
        )
        story.append(Image(cm_img, width=12*cm, height=10*cm))

    # ── ROC curve ─────────────────────────────────────────────
    if "roc_auc" in metrics:
        story.append(Paragraph("ROC Curve", heading_style))
        roc_img = _render_roc_curve(metrics)
        story.append(Image(roc_img, width=12*cm, height=10*cm))

    # ── Feature importance ─────────────────────────────────────
    if "feature_importance" in metrics:
        story.append(PageBreak())
        story.append(Paragraph("Feature Importance", heading_style))
        fi_img = _render_feature_importance(metrics["feature_importance"])
        story.append(Image(fi_img, width=14*cm, height=8*cm))

    # ── Per-class report ───────────────────────────────────────
    if "classification_report" in metrics:
        story.append(Paragraph("Per-Class Classification Report", heading_style))
        report = metrics["classification_report"]
        class_rows = {k: v for k, v in report.items() if isinstance(v, dict)}

        if class_rows:
            header = ["Class", "Precision", "Recall", "F1-Score", "Support"]
            table_data = [header]
            for cls_name, cls_metrics in class_rows.items():
                table_data.append([
                    cls_name,
                    f"{cls_metrics.get('precision', 0):.4f}",
                    f"{cls_metrics.get('recall', 0):.4f}",
                    f"{cls_metrics.get('f1-score', 0):.4f}",
                    str(int(cls_metrics.get('support', 0))),
                ])

            report_table = Table(table_data, colWidths=[4*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
            report_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a1a2e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(report_table)

    # ── Learning curve ─────────────────────────────────────────
    if "learning_curve" in metrics and "error" not in metrics["learning_curve"]:
        story.append(Paragraph("Learning Curve", heading_style))
        lc_img = _render_learning_curve(metrics["learning_curve"])
        story.append(Image(lc_img, width=14*cm, height=9*cm))

    # ── Footer ─────────────────────────────────────────────────
    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#cccccc')))
    story.append(Paragraph(
        f"Generated by IDS Research Pipeline System  --  "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        small_style,
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ── Chart rendering helpers ────────────────────────────────────────────────────

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
            # Binary classification — single curve
            ax.plot(fpr, tpr, label=f"ROC (AUC = {metrics['roc_auc']:.4f})", linewidth=2)
        elif isinstance(fpr, dict):
            # Multiclass — one curve per class
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
    ax.set_title("Feature Importance (Random Forest)")
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
