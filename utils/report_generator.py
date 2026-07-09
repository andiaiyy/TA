"""
PDF report generator — operational-first layout for network engineers (non-ML).

Design goal: translate ML results into network-security language FIRST, then
provide ML technical detail as supporting appendix. Every interpretive sentence
is assembled from the experiment's ACTUAL numbers at render time (computed from
metrics.json / extra_info / metadata) — never boilerplate, never fabricated.
If a field is absent, its block is hidden cleanly (no empty placeholders).

Section order (easy → technical):
  Cover            identity + one-line detection verdict
  A. Ringkasan Eksekutif          (1 computed paragraph, plain language)
  B. Konteks Eksperimen           (dataset, honest label origin, algorithm, config)
  C. Hasil Deteksi — Interpretasi Jaringan   (confusion matrix → operational terms)
  D. Metrik Performa — Penjelasan Awam       (each metric + plain meaning + verdict)
  E. Fitur Jaringan Paling Berpengaruh       (importance + per-feature network meaning)
  F. Catatan Metodologis (kejujuran)         (metric semantics, holdout, anti-leakage)
  G. Informasi Reproducibility               (dataset_hash, seed, environment)
  Lampiran Teknis                            (full metric table, ROC, per-class, LC)

Narrative is family-aware: HIKARI metrics are weighted-average on ground-truth
labels; EVE-cbr metrics are attack-class on the natural holdout with labels
derived from Suricata alerts. The operational counts (detected / missed / false
alarm) are ALWAYS derived from the confusion matrix (attack = positive class),
so they are correct and attack-focused for both families.

Signature, return type (bytes), and ReportLab mechanism are preserved exactly
so the call site in ui/views/view_results.py keeps working.

Rules: No database access. No UI imports. Reads provided data only — never
mutates pipeline outputs or recomputes model metrics.
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
_GOOD = HexColor('#15803d')        # green — good direction
_WARN = HexColor('#b45309')        # amber — needs attention
_CRIT = HexColor('#b91c1c')        # red — critical (missed attacks)
_GOOD_FILL = HexColor('#ecfdf5')
_WARN_FILL = HexColor('#fffbeb')
_CRIT_FILL = HexColor('#fef2f2')
_NOTE_FILL = HexColor('#f0f4ff')   # light blue for honest-method notes


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
    """Generate the operational-first PDF and return it as bytes."""
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
        _section_a_ringkasan,
        _section_b_konteks,
        _section_c_deteksi,
        _section_d_metrik,
        _section_e_fitur,
        _section_f_metodologi,
        _section_g_reproducibility,
        _section_lampiran,
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

    dataset_type = kw.get("dataset_type")
    label_mapping = kw.get("label_mapping") or md.get("label_mapping")

    # Operational breakdown from the confusion matrix (attack = positive class).
    # This is the single source of truth for "detected / missed / false alarm".
    breakdown = _confusion_breakdown(metrics.get("confusion_matrix"), label_mapping)

    return {
        # IDs and paths
        "experiment_id": kw.get("experiment_id"),
        "dataset_type": dataset_type,
        "is_eve": dataset_type == "EVE_SURICATA",
        "dataset_path": kw.get("dataset_path"),
        "dataset_hash": kw.get("dataset_hash") or "N/A",
        "pipeline_id": kw.get("pipeline_id"),
        "label_mapping": label_mapping,
        "feature_names": kw.get("feature_names") or md.get("feature_names"),
        # Pipeline metadata (from get_info)
        "paper": pinfo.get("paper"),
        "algorithm": pinfo.get("algorithm"),
        "preprocessing_steps": pinfo.get("preprocessing_steps") or [],
        "feature_selection": pinfo.get("feature_selection"),
        "fixed_params": pinfo.get("fixed_params") or {},
        "train_test_split": pinfo.get("train_test_split") or {},
        "anti_leakage_info": pinfo.get("anti_leakage"),
        "metrics_policy": pinfo.get("metrics_policy"),
        "runtime_warning": pinfo.get("runtime_warning"),
        # Metrics
        "metrics": metrics,
        "accuracy": metrics.get("accuracy"),
        "precision": metrics.get("precision"),
        "recall": metrics.get("recall"),
        "f1_score": metrics.get("f1_score"),
        "roc_auc": metrics.get("roc_auc"),
        "confusion_matrix": metrics.get("confusion_matrix"),
        "breakdown": breakdown,
        "feature_importance": metrics.get("feature_importance") or [],
        "classification_report": metrics.get("classification_report") or {},
        "learning_curve": metrics.get("learning_curve") if isinstance(
            metrics.get("learning_curve"), dict
        ) and "error" not in (metrics.get("learning_curve") or {}) else None,
        # EVE-cbr honesty fields (absent for HIKARI)
        "anti_leakage": metrics.get("anti_leakage") if isinstance(metrics.get("anti_leakage"), dict) else {},
        "evaluation": metrics.get("evaluation") if isinstance(metrics.get("evaluation"), dict) else {},
        "selected_combo": metrics.get("selected_combo") if isinstance(metrics.get("selected_combo"), dict) else {},
        # Timing
        "created_at": created_at or "N/A",
        "completed_at": completed_at or "N/A",
        "wall_clock": wall_clock,
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


# ─── Operational helpers (everything derived from real numbers) ───────────

def _norm_label_mapping(label_mapping) -> dict:
    """Return {int_index: name} from a mapping that may have str or int keys."""
    out = {}
    if isinstance(label_mapping, dict):
        for k, v in label_mapping.items():
            try:
                out[int(k)] = str(v)
            except (ValueError, TypeError):
                continue
    return out


_ATTACK_WORDS = ("attack", "malicious", "malign", "intrusion", "anomaly", "serangan")


def _confusion_breakdown(cm, label_mapping) -> dict | None:
    """Translate a binary 2x2 confusion matrix into operational counts.

    Convention (sklearn): rows = actual, cols = predicted, label order ascending
    [0, 1]. Positive class (attack) is detected by name when possible, else
    defaults to index 1. Returns None for non-binary / empty / all-zero matrices
    so callers can hide the operational section cleanly.
    """
    if not cm or not isinstance(cm, (list, tuple)) or len(cm) != 2:
        return None
    try:
        c = [[int(cm[0][0]), int(cm[0][1])], [int(cm[1][0]), int(cm[1][1])]]
    except (ValueError, TypeError, IndexError):
        return None

    total = c[0][0] + c[0][1] + c[1][0] + c[1][1]
    if total <= 0:
        return None

    names = _norm_label_mapping(label_mapping)
    pos = 1
    for idx, name in names.items():
        if any(w in name.lower() for w in _ATTACK_WORDS):
            pos = idx
            break
    neg = 0 if pos == 1 else 1

    attack_name = names.get(pos, "Serangan")
    normal_name = names.get(neg, "Normal")

    tp = c[pos][pos]
    fn = c[pos][neg]
    fp = c[neg][pos]
    tn = c[neg][neg]

    attack_total = tp + fn
    normal_total = tn + fp
    pred_attack = tp + fp

    def _safe(n, d):
        return (n / d) if d else None

    big, small = max(attack_total, normal_total), min(attack_total, normal_total)
    imbalance_ratio = (big / small) if small else None

    a_rec = _safe(tp, attack_total)
    a_prec = _safe(tp, pred_attack)
    a_f1 = None
    if a_rec is not None and a_prec is not None and (a_rec + a_prec) > 0:
        a_f1 = 2 * a_prec * a_rec / (a_prec + a_rec)

    return {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "total": total,
        "attack_total": attack_total, "normal_total": normal_total,
        "pred_attack": pred_attack,
        "attack_recall": a_rec,
        "attack_precision": a_prec,
        "attack_f1": a_f1,
        "fp_rate": _safe(fp, normal_total),
        "specificity": _safe(tn, normal_total),
        "attack_share": _safe(attack_total, total),
        "imbalance_ratio": imbalance_ratio,
        "attack_name": attack_name,
        "normal_name": normal_name,
        "pos_index": pos, "neg_index": neg,
    }


def _pct(x) -> str:
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "[tidak tersedia]"


def _grp(n) -> str:
    """Thousands-grouped integer string (e.g. 135.046) using dot separator."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(n)


def _recall_verdict(r):
    """(color, label, clause) for attack-detection rate. Value-driven, not fixed."""
    if r is None:
        return _MUTED, "tidak tersedia", ""
    if r >= 0.95:
        return _GOOD, "sangat baik", "hampir seluruh serangan berhasil tertangkap"
    if r >= 0.85:
        return _GOOD, "baik", "sebagian besar serangan tertangkap, sebagian kecil lolos"
    if r >= 0.60:
        return _WARN, "perlu perhatian", "cukup banyak serangan lolos tanpa terdeteksi"
    return _CRIT, "lemah", "mayoritas serangan lolos tanpa terdeteksi"


def _precision_verdict(p):
    """(color, label, clause) for how trustworthy an 'attack' alert is."""
    if p is None:
        return _MUTED, "tidak tersedia", ""
    if p >= 0.90:
        return _GOOD, "sangat baik", "hampir setiap alarm benar-benar serangan"
    if p >= 0.75:
        return _GOOD, "baik", "mayoritas alarm benar, sebagian kecil false alarm"
    if p >= 0.50:
        return _WARN, "perlu perhatian", "hampir separuh alarm adalah false alarm"
    return _CRIT, "lemah", "mayoritas alarm ternyata bukan serangan (banyak false alarm)"


def _f1_verdict(f):
    if f is None:
        return _MUTED, "tidak tersedia", ""
    if f >= 0.90:
        return _GOOD, "sangat baik", "keseimbangan deteksi dan ketepatan alarm sangat baik"
    if f >= 0.75:
        return _GOOD, "baik", "keseimbangan deteksi dan ketepatan alarm tergolong baik"
    if f >= 0.55:
        return _WARN, "perlu perhatian", "ada kompromi antara serangan lolos dan false alarm"
    return _CRIT, "lemah", "deteksi dan ketepatan alarm sama-sama belum memadai"


def _auc_verdict(a):
    if a is None:
        return _MUTED, "tidak tersedia", ""
    if a >= 0.90:
        return _GOOD, "sangat baik", "model memisahkan serangan dari trafik normal dengan jelas"
    if a >= 0.80:
        return _GOOD, "baik", "model cukup mampu memisahkan serangan dari trafik normal"
    if a >= 0.70:
        return _WARN, "perlu perhatian", "kemampuan memisahkan serangan dari normal masih terbatas"
    return _CRIT, "lemah", "kemampuan memisahkan serangan dari normal mendekati tebakan acak"


# ─── Network meaning of features (derived from the feature name itself) ────

# Exact, curated meanings for features actually emitted by the pipelines.
_FEATURE_EXACT = {
    "bytes_per_sec": "laju volume data (byte per detik) pada aliran — throughput koneksi",
    "pkts_per_sec": "laju paket per detik — kepadatan pengiriman paket",
    "bytes_per_pkt": "rata-rata ukuran paket (byte/paket) — besar tiap paket",
    "total_bytes": "total byte yang ditransfer dalam aliran",
    "total_pkts": "total paket dalam aliran",
    "duration": "durasi aliran (lama koneksi berlangsung)",
    "bytes_toserver": "volume byte dari klien ke server (arah unggah)",
    "pkts_toserver": "jumlah paket dari klien ke server",
    "pkts_toclient": "jumlah paket dari server ke klien (arah unduh)",
    "bytes_toserver_ratio": "porsi byte yang menuju server dibanding total — arah dominan trafik",
    "pkts_toserver_ratio": "porsi paket yang menuju server dibanding total — arah dominan trafik",
    "src_port": "port sumber koneksi",
    "src_port_class": "kategori port sumber (well-known / registered / ephemeral)",
    "dest_port_class": "kategori port tujuan — menyiratkan jenis layanan yang dihubungi",
    "unique_dest_port_window": "banyak port tujuan unik dalam satu jendela waktu — indikator port scanning",
    "unique_dest_ip_window": "banyak IP tujuan unik dalam satu jendela waktu — indikator sweep/penyebaran",
    "event_count_window": "jumlah event log dalam jendela waktu — intensitas aktivitas",
    "no_alert_count_window": "jumlah event tanpa alert dalam jendela waktu",
    "total_bytes_window": "akumulasi byte dalam jendela waktu — burst volume",
    "total_pkts_window": "akumulasi paket dalam jendela waktu — burst paket",
    "bytes_per_event_window": "rata-rata byte per event dalam jendela waktu",
    "pkts_per_event_window": "rata-rata paket per event dalam jendela waktu",
    "ts_hour": "jam terjadinya aktivitas — pola waktu (temporal) trafik",
    "app_proto_h": "protokol aplikasi (hash) — jenis layanan pada aliran",
    # EVE interaction (product) features — describe both factors honestly.
    "interaction_bytes_rate_packet_rate": "interaksi antara laju byte dan laju paket per detik",
    "interaction_total_bytes_duration": "interaksi antara total byte dan durasi aliran",
    "interaction_total_pkts_duration": "interaksi antara total paket dan durasi aliran",
    # HIKARI ALLFLOWMETER common features.
    "flow_duration": "durasi aliran (lama koneksi berlangsung)",
    "down_up_ratio": "rasio volume unduh terhadap unggah pada aliran",
    "fwd_subflow_bytes": "volume byte pada subflow arah maju (klien→server)",
    "bwd_subflow_bytes": "volume byte pada subflow arah balik (server→klien)",
    "fwd_init_window_size": "ukuran TCP receive window awal arah maju (kontrol aliran)",
    "bwd_init_window_size": "ukuran TCP receive window awal arah balik (kontrol aliran)",
}


def _feature_network_meaning(name: str) -> str | None:
    """Plain-Indonesian network meaning of a feature, derived from its name.

    Returns None when the name carries no recognizable network token, so the
    caller can omit the sentence rather than invent a meaning.
    """
    if not name:
        return None
    raw = str(name)
    key = raw.lower()
    if key in _FEATURE_EXACT:
        return _FEATURE_EXACT[key]

    prefix = ""
    work = key
    if work.startswith("log_"):
        prefix = "skala logaritmik dari "
        work = work[4:]
    if work.startswith("interaction_"):
        prefix = "kombinasi (interaksi) dari " + prefix
        work = work[len("interaction_"):]

    if work in _FEATURE_EXACT:
        return prefix + _FEATURE_EXACT[work]

    # Token-based fallback — each clause is an honest reading of the name token,
    # not an invented statistic. Ordered specific -> general; tokens prone to
    # substring collisions (e.g. "ratio" is inside "du-ratio-n") are placed
    # AFTER the words that legitimately contain them.
    rules = [
        # window size (TCP control) BEFORE the generic "window" time-bucket token
        ("init_window", "ukuran TCP receive window awal (kontrol aliran)"),
        ("window_size", "ukuran TCP receive window (kontrol aliran)"),
        # duration / IAT BEFORE "ratio" (avoids 'du-ratio-n' false match)
        ("duration", "durasi aliran (lama koneksi)"),
        ("iat", "inter-arrival time — jeda waktu antar paket"),
        ("per_sec", "laju per detik (kecepatan) suatu besaran trafik"),
        ("_rate", "laju (kecepatan) suatu besaran trafik"),
        ("down_up_ratio", "rasio volume unduh terhadap unggah"),
        ("ratio", "rasio antar komponen/arah trafik"),
        ("unique_dest_port", "banyak port tujuan unik — indikator port scanning"),
        ("unique_dest_ip", "banyak IP tujuan unik — indikator sweep jaringan"),
        ("port_class", "kategori port (jenis layanan)"),
        ("dest_port", "port tujuan — layanan yang dihubungi"),
        ("src_port", "port sumber koneksi"),
        ("toserver", "volume/arah trafik dari klien ke server"),
        ("toclient", "volume/arah trafik dari server ke klien"),
        ("subflow", "volume/jumlah pada subflow (segmen aliran)"),
        ("payload", "statistik ukuran payload (byte) paket"),
        ("header", "ukuran header paket"),
        ("flag", "jumlah TCP flag (mis. SYN/PSH/URG) pada aliran"),
        ("bulk", "transfer data bulk (burst) pada aliran"),
        ("active", "lama koneksi dalam keadaan aktif"),
        ("idle", "lama koneksi dalam keadaan idle (menganggur)"),
        ("seg_size", "ukuran segmen paket"),
        ("window", "agregasi dalam jendela waktu — perilaku per periode (burst/berulang)"),
        ("bytes", "volume data (byte) yang ditransfer"),
        ("pkts", "jumlah paket"),
        ("packet", "jumlah paket"),
        ("alert", "jumlah alert pada aliran"),
        ("event", "jumlah event log pada aliran"),
        ("proto", "protokol aplikasi yang dipakai"),
        ("hour", "jam aktivitas — pola waktu (temporal)"),
        ("flow", "karakteristik aliran (flow) jaringan"),
    ]
    for token, meaning in rules:
        if token in work:
            return prefix + meaning
    return None


# ─── Style sheet ──────────────────────────────────────────────────────────

def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontSize=20, spaceAfter=4*mm),
        "subtitle": ParagraphStyle("Sub", parent=base["Heading4"], fontSize=11,
                                    textColor=_MUTED, spaceAfter=4*mm),
        "verdict": ParagraphStyle("Verdict", parent=base["Normal"], fontSize=11,
                                   leading=15),
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontSize=14,
                                   spaceBefore=8*mm, spaceAfter=3*mm, textColor=_PRIMARY),
        "subsection": ParagraphStyle("Subsec", parent=base["Heading3"], fontSize=11,
                                      spaceBefore=4*mm, spaceAfter=2*mm, textColor=_PRIMARY),
        "normal": ParagraphStyle("Body", parent=base["Normal"], fontSize=10, leading=14),
        "italic": ParagraphStyle("Italic", parent=base["Normal"], fontName="Helvetica-Oblique"),
        "small_muted": ParagraphStyle("SmallMuted", parent=base["Normal"],
                                       fontSize=8, textColor=_MUTED),
        "note": ParagraphStyle("Note", parent=base["Normal"],
                                fontName="Helvetica-Oblique", fontSize=9, textColor=_MUTED),
        "cell": ParagraphStyle("Cell", parent=base["Normal"], fontSize=9, leading=12),
    }


# ─── Reusable mini-blocks ─────────────────────────────────────────────────

def _kv_table(rows: list[list[str]], col_widths=(5*cm, 11*cm)):
    wrapped = []
    style_cell = ParagraphStyle("kvcell", fontSize=9, leading=12)
    for r in rows:
        wrapped.append([Paragraph(str(r[0]), ParagraphStyle("kvkey", fontSize=9, leading=12,
                                                             fontName="Helvetica-Bold")),
                        Paragraph(str(r[1]), style_cell)])
    t = Table(wrapped, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor('#f0f0f0')),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _callout(text: str, styles, *, fill, border):
    """Colored callout box (used for the critical 'serangan lolos' highlight)."""
    p = Paragraph(text, styles["normal"])
    t = Table([[p]], colWidths=[16*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), 0.9, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _section_heading(story, styles, letter: str, title: str) -> None:
    story.append(Paragraph(f"{letter}. {title}", styles["section"]))


def _none_or(v, fallback="[tidak tersedia]"):
    """Render value or honest placeholder. Avoids printing 'None' or fake 0."""
    if v is None or v == "":
        return fallback
    return str(v)


def _hexcolor_name(c) -> str:
    """ReportLab HexColor → '#rrggbb' for inline <font color=...> tags."""
    return '#%02x%02x%02x' % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))


# ─── Cover (+ one-line detection verdict) ─────────────────────────────────

def _cover(story, styles, ctx):
    story.append(Paragraph("Laporan Eksperimen Deteksi Intrusi", styles["title"]))
    story.append(Paragraph("IDS Research Pipeline Execution System", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=_GRID))
    story.append(Spacer(1, 3*mm))

    b = ctx["breakdown"]
    if b and b["attack_recall"] is not None:
        color, label, _ = _recall_verdict(b["attack_recall"])
        ch = _hexcolor_name(color)
        verdict = (
            f"Pada pengujian ini model mengenali "
            f"<b><font color='{ch}'>{_pct(b['attack_recall'])}</font></b> dari serangan yang ada "
            f"(<b>{_grp(b['tp'])}</b> dari <b>{_grp(b['attack_total'])}</b> serangan), "
            f"dengan <b>{_grp(b['fn'])}</b> serangan lolos dan "
            f"<b>{_grp(b['fp'])}</b> false alarm dari "
            f"<b>{_grp(b['normal_total'])}</b> aliran normal."
        )
        story.append(Paragraph(verdict, styles["verdict"]))
        story.append(Spacer(1, 3*mm))

    story.append(_kv_table([
        ["Experiment ID", _none_or(ctx["experiment_id"])],
        ["Dataset", _none_or(ctx["dataset_type"])],
        ["Pipeline", _none_or(ctx["pipeline_id"])],
        ["Algoritma", _none_or(ctx["algorithm"])],
        ["Dibuat", _none_or(ctx["created_at"])],
        ["Selesai", _none_or(ctx["completed_at"])],
    ]))


# ─── A. Ringkasan Eksekutif (computed paragraph) ──────────────────────────

def _section_a_ringkasan(story, styles, ctx):
    _section_heading(story, styles, "A", "Ringkasan Eksekutif")

    algo = ctx["algorithm"] or "Model machine learning"
    ds = "EVE/Suricata (trafik TLS)" if ctx["is_eve"] else (ctx["dataset_type"] or "dataset terpilih")
    b = ctx["breakdown"]

    if not b:
        story.append(Paragraph(
            f"Eksperimen ini menjalankan algoritma <b>{algo}</b> pada dataset <b>{ds}</b>. "
            "Rincian hasil deteksi tidak dapat diterjemahkan ke bentuk operasional karena "
            "confusion matrix tidak tersedia atau bukan biner; lihat tabel metrik teknis "
            "pada Lampiran.",
            styles["normal"],
        ))
        return

    rec, prec = b["attack_recall"], b["attack_precision"]
    rcolor, rlabel, rclause = _recall_verdict(rec)
    pcolor, plabel, pclause = _precision_verdict(prec)
    rc, pc = _hexcolor_name(rcolor), _hexcolor_name(pcolor)

    para = (
        f"Algoritma <b>{algo}</b> diuji untuk membedakan trafik serangan dari trafik normal pada "
        f"dataset <b>{ds}</b>. Dari total <b>{_grp(b['total'])}</b> aliran jaringan yang diuji "
        f"(<b>{_grp(b['attack_total'])}</b> benar-benar serangan dan "
        f"<b>{_grp(b['normal_total'])}</b> normal), model berhasil mendeteksi "
        f"<b><font color='{rc}'>{_pct(rec)}</font></b> serangan ({rlabel} — {rclause}). "
        f"Sebanyak <b><font color='{_hexcolor_name(_CRIT)}'>{_grp(b['fn'])}</font></b> serangan "
        f"lolos tanpa terdeteksi, dan <b>{_grp(b['fp'])}</b> aliran normal salah ditandai sebagai "
        f"serangan (false alarm). "
        f"Ketika model menyalakan alarm 'serangan', alarm itu tepat sebesar "
        f"<b><font color='{pc}'>{_pct(prec)}</font></b> ({plabel} — {pclause})."
    )
    story.append(Paragraph(para, styles["normal"]))

    # Honest one-liner about label provenance for EVE.
    if ctx["is_eve"]:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            "Catatan: pada dataset EVE/Suricata, label 'serangan' diturunkan dari alert "
            "Suricata (bukan kebenaran lapangan/ground-truth eksternal). Angka di atas adalah "
            "metrik kelas serangan pada natural-holdout (distribusi asli).",
            styles["note"],
        ))


# ─── B. Konteks Eksperimen ────────────────────────────────────────────────

def _section_b_konteks(story, styles, ctx):
    _section_heading(story, styles, "B", "Konteks Eksperimen")

    if ctx["is_eve"]:
        label_origin = ("Turunan dari alert Suricata pada trafik TLS, lalu disempurnakan "
                        "secara konservatif (cap konversi label). BUKAN ground-truth eksternal.")
        fmt = "NDJSON (catatan EVE Suricata, satu objek JSON per baris)"
        feat_kind = ("Fitur statistik aliran (flow) hasil pipeline cbr 14 fase: volume byte/paket, "
                     "laju, durasi, agregasi per jendela waktu, dan karakteristik port/protokol.")
    else:
        label_origin = ("Label ground-truth bawaan dataset HIKARI2021 (varian ALLFLOWMETER): "
                        "biner benign vs malicious.")
        fmt = "CSV (fitur flow ALLFLOWMETER yang sudah diekstraksi)"
        feat_kind = ("Fitur numerik berbasis flow (varian ALLFLOWMETER): statistik payload, "
                     "perhitungan header/paket, dan atribut koneksi.")

    rows = [
        ["Dataset", _none_or(ctx["dataset_type"])],
        ["Format berkas", fmt],
        ["Asal label", label_origin],
        ["Algoritma", _none_or(ctx["algorithm"])],
        ["Berkas sumber", _none_or(ctx["dataset_path"])],
        ["Tanggal eksperimen", _none_or(ctx["created_at"])],
    ]
    if ctx["wall_clock"]:
        rows.append(["Durasi total (queue + eksekusi)", ctx["wall_clock"]])
    b = ctx["breakdown"]
    if b:
        rows.append(["Aliran diuji (test set)",
                     f"{_grp(b['total'])} (serangan {_grp(b['attack_total'])} / "
                     f"normal {_grp(b['normal_total'])})"])
    story.append(_kv_table(rows))

    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(f"<b>Jenis fitur:</b> {feat_kind}", styles["normal"]))

    # Key locked configuration (from get_info) — concise, real values only.
    cfg = ctx["fixed_params"]
    if cfg:
        compact = ", ".join(f"{k}={v}" for k, v in list(cfg.items())[:8])
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            f"<b>Konfigurasi kunci (terkunci):</b> {compact}", styles["normal"]))


# ─── C. Hasil Deteksi — Interpretasi Jaringan (INTI) ──────────────────────

def _section_c_deteksi(story, styles, ctx):
    _section_heading(story, styles, "C", "Hasil Deteksi — Interpretasi Jaringan")

    b = ctx["breakdown"]
    if not b:
        story.append(Paragraph(
            "Confusion matrix tidak tersedia atau bukan biner, sehingga hasil tidak dapat "
            "diterjemahkan ke kuadran operasional. Lihat tabel metrik teknis pada Lampiran.",
            styles["italic"],
        ))
        return

    story.append(Paragraph(
        "Tabel berikut menerjemahkan hasil model ke empat kemungkinan operasional. "
        "Tiap angka adalah jumlah aliran nyata pada data uji.",
        styles["normal"],
    ))
    story.append(Spacer(1, 2*mm))

    an, nn = b["attack_name"], b["normal_name"]
    quad_rows = [
        ["Kategori", "Jumlah", "Arti operasional"],
        [f"Serangan terdeteksi (TP)", _grp(b["tp"]),
         f"{an} yang berhasil dikenali model — deteksi yang benar."],
        [f"Serangan LOLOS (FN)", _grp(b["fn"]),
         f"{an} yang TIDAK terdeteksi (dianggap normal) — risiko keamanan paling kritis."],
        [f"False alarm (FP)", _grp(b["fp"]),
         f"{nn} yang salah ditandai sebagai serangan — membebani analis (alert fatigue)."],
        [f"Normal benar (TN)", _grp(b["tn"]),
         f"{nn} yang benar dibiarkan lewat — tidak mengganggu operasi."],
    ]
    # Wrap the long 'arti' column via Paragraphs for proper line breaking.
    qt = Table(
        [quad_rows[0]] + [
            [r[0], r[1], Paragraph(r[2], styles["cell"])] for r in quad_rows[1:]
        ],
        colWidths=[4.2*cm, 2.3*cm, 9.5*cm],
    )
    qt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 2), (-1, 2), _CRIT_FILL),
        ("TEXTCOLOR", (0, 2), (0, 2), _CRIT),
        ("FONTNAME", (0, 2), (0, 2), "Helvetica-Bold"),
        ("BACKGROUND", (0, 3), (-1, 3), _WARN_FILL),
    ]))
    story.append(qt)

    # Critical highlight callout — value-driven.
    story.append(Spacer(1, 3*mm))
    if b["attack_total"]:
        miss_pct = b["fn"] / b["attack_total"]
        story.append(_callout(
            f"<b><font color='{_hexcolor_name(_CRIT)}'>Serangan lolos (paling kritis):</font></b> "
            f"<b>{_grp(b['fn'])}</b> dari <b>{_grp(b['attack_total'])}</b> serangan "
            f"(<b>{_pct(miss_pct)}</b>) tidak terdeteksi dan akan melewati sistem tanpa alarm.",
            styles, fill=_CRIT_FILL, border=_CRIT,
        ))
    if b["normal_total"] and b["fp_rate"] is not None:
        story.append(Spacer(1, 2*mm))
        story.append(_callout(
            f"<b><font color='{_hexcolor_name(_WARN)}'>Beban false alarm:</font></b> "
            f"<b>{_grp(b['fp'])}</b> dari <b>{_grp(b['normal_total'])}</b> aliran normal "
            f"(<b>{_pct(b['fp_rate'])}</b>) memicu alarm palsu — biaya investigasi bagi analis.",
            styles, fill=_WARN_FILL, border=_WARN,
        ))

    # Labeled confusion-matrix figure.
    story.append(Spacer(1, 3*mm))
    try:
        cm_img = _render_network_confusion_matrix(b)
        story.append(Image(cm_img, width=12*cm, height=10*cm))
    except Exception as e:
        story.append(Paragraph(f"<i>Gagal merender confusion matrix: {e}</i>", styles["italic"]))


# ─── D. Metrik Performa — Penjelasan Awam ─────────────────────────────────

def _section_d_metrik(story, styles, ctx):
    _section_heading(story, styles, "D", "Metrik Performa — Penjelasan Awam")

    b = ctx["breakdown"]
    is_eve = ctx["is_eve"]

    if b:
        intro = (
            "Recall, Precision, dan F1 di bawah dihitung untuk <b>kelas serangan</b> — sudut "
            "pandang yang paling relevan secara operasional — langsung dari jumlah deteksi "
            "(confusion matrix di Bagian C)."
        )
        if not is_eve:
            intro += (" Catatan: metrik headline weighted (rata-rata seluruh kelas) tersedia "
                      "pada Lampiran.")
    else:
        intro = ("Nilai metrik diambil apa adanya dari hasil eksperimen; penjelasan disesuaikan "
                 "untuk pembaca non-ML.")
    story.append(Paragraph(intro, styles["normal"]))
    story.append(Spacer(1, 2*mm))

    # Operational framing always uses attack-class values derived from the
    # confusion matrix (correct & consistent for both families). When the
    # matrix is unavailable, fall back to the stored headline values.
    if b:
        recall_val = b["attack_recall"]
        precision_val = b["attack_precision"]
        f1_val = b["attack_f1"]
    else:
        recall_val = ctx["recall"]
        precision_val = ctx["precision"]
        f1_val = ctx["f1_score"]

    items = []

    if recall_val is not None:
        color, label, clause = _recall_verdict(recall_val)
        extra = ""
        if b:
            extra = f" Artinya {_grp(b['fn'])} dari {_grp(b['attack_total'])} serangan lolos."
        items.append((
            "Recall (tingkat deteksi serangan)", recall_val, color, label,
            f"Dari semua serangan yang sebenarnya ada, {_pct(recall_val)} berhasil terdeteksi "
            f"(sisanya lolos).{extra}"
        ))

    if precision_val is not None:
        color, label, clause = _precision_verdict(precision_val)
        extra = ""
        if b:
            extra = f" Dari {_grp(b['pred_attack'])} alarm, {_grp(b['fp'])} adalah false alarm."
        items.append((
            "Precision (ketepatan alarm)", precision_val, color, label,
            f"Dari semua yang ditandai sebagai serangan, {_pct(precision_val)} benar-benar "
            f"serangan (sisanya false alarm).{extra}"
        ))

    if f1_val is not None:
        color, label, clause = _f1_verdict(f1_val)
        items.append((
            "F1-score (keseimbangan)", f1_val, color, label,
            "Keseimbangan antara tidak meloloskan serangan dan tidak membuat false alarm. "
            f"{clause.capitalize()}."
        ))

    if ctx["accuracy"] is not None:
        # Accuracy can mislead under class imbalance — warn using the real ratio.
        imbalanced = bool(b and b["imbalance_ratio"] and b["imbalance_ratio"] >= 1.5)
        color = _WARN if imbalanced else _GOOD
        label = "baca dengan hati-hati" if imbalanced else "informatif"
        desc = (f"Proporsi seluruh prediksi yang benar ({_pct(ctx['accuracy'])}).")
        if imbalanced:
            share = b["attack_share"]
            desc += (f" PERHATIAN: data tidak seimbang (serangan hanya {_pct(share)} dari "
                     f"total), sehingga accuracy bisa terlihat tinggi meski sebagian serangan "
                     f"lolos — utamakan Recall & Precision di atas.")
        items.append(("Accuracy (akurasi keseluruhan)", ctx["accuracy"], color, label, desc))

    if ctx["roc_auc"] is not None:
        color, label, clause = _auc_verdict(ctx["roc_auc"])
        items.append((
            "ROC-AUC (daya pisah)", ctx["roc_auc"], color, label,
            f"Kemampuan model memisahkan serangan dari trafik normal secara keseluruhan "
            f"(1,0 = sempurna; 0,5 = tebak acak). {clause.capitalize()}."
        ))

    for name, value, color, label, desc in items:
        ch = _hexcolor_name(color)
        head = (f"<b>{name}: <font color='{ch}'>{value:.4f}</font></b> "
                f"<font color='{ch}'>({label})</font>")
        story.append(Paragraph(head, styles["normal"]))
        story.append(Paragraph(desc, styles["cell"]))
        story.append(Spacer(1, 2*mm))


# ─── E. Fitur Jaringan Paling Berpengaruh ─────────────────────────────────

def _section_e_fitur(story, styles, ctx):
    fi = ctx["feature_importance"]
    if not fi:
        # Only show the section header + honest note for algorithms that
        # genuinely lack importances; otherwise hide entirely.
        algo = (ctx["algorithm"] or "").lower()
        if any(k in algo for k in ("knn", "naive", "nearest", "logistic", "svc", "svm")):
            _section_heading(story, styles, "E", "Fitur Jaringan Paling Berpengaruh")
            story.append(Paragraph(
                f"Algoritma {ctx['algorithm']} tidak menghasilkan skor kepentingan fitur "
                "(feature importance) yang dapat dipetakan ke fitur jaringan asli, sehingga "
                "bagian ini tidak ditampilkan.",
                styles["italic"],
            ))
        return

    _section_heading(story, styles, "E", "Fitur Jaringan Paling Berpengaruh")
    story.append(Paragraph(
        "Fitur berikut paling menentukan keputusan model. Bagi network engineer, ini menunjukkan "
        "sinyal trafik apa yang paling membedakan serangan dari trafik normal.",
        styles["normal"],
    ))
    story.append(Spacer(1, 2*mm))
    try:
        fi_img = _render_feature_importance(fi)
        story.append(Image(fi_img, width=14*cm, height=8*cm))
    except Exception as e:
        story.append(Paragraph(f"<i>Gagal merender feature importance: {e}</i>", styles["italic"]))

    story.append(Spacer(1, 2*mm))
    story.append(Paragraph("Arti fitur teratas dalam istilah jaringan:", styles["subsection"]))
    shown = 0
    for item in fi[:6]:
        name = item.get("feature")
        meaning = _feature_network_meaning(name)
        if not name:
            continue
        if meaning:
            story.append(Paragraph(
                f"<b>{name}</b> — {meaning}.", styles["cell"]))
        else:
            # Honest: do not invent a meaning for an unrecognized name.
            story.append(Paragraph(
                f"<b>{name}</b> — statistik aliran jaringan (makna spesifik tidak dipetakan).",
                styles["cell"],
            ))
        story.append(Spacer(1, 1*mm))
        shown += 1
        if shown >= 5:
            break


# ─── F. Catatan Metodologis (kejujuran) ───────────────────────────────────

def _section_f_metodologi(story, styles, ctx):
    _section_heading(story, styles, "F", "Catatan Metodologis (Kejujuran)")

    notes = []
    if ctx["is_eve"]:
        notes.append(
            "Semantik metrik: precision/recall/F1 dihitung untuk <b>kelas serangan</b> pada "
            "<b>natural-holdout</b> (distribusi asli, apa adanya) — bukan rata-rata berbobot. "
            "Ini sengaja dipilih agar angka jujur terhadap kelas minoritas (serangan)."
        )
        notes.append(
            "Asal label: label serangan diturunkan dari <b>alert Suricata</b> lalu disempurnakan "
            "konservatif (cap konversi). Ini bukan kebenaran lapangan eksternal, sehingga hasil "
            "harus dibaca sebagai kesepakatan model terhadap alert, bukan deteksi mutlak."
        )
        al = ctx["anti_leakage"]
        if al:
            parts = []
            if al.get("group_split"):
                parts.append(f"pemisahan data berbasis grup ({al['group_split']})")
            if al.get("pipeline_scaling"):
                parts.append("penskalaan di dalam pipeline (tanpa kebocoran ke data uji)")
            if al.get("dual_holdout"):
                parts.append("dual holdout: natural (utama) + balanced (sekunder)")
            if al.get("forbidden_feature_guard"):
                parts.append("penjaga fitur terlarang (kolom yang membocorkan label diblokir)")
            if parts:
                notes.append("Anti-kebocoran (anti-leakage): " + "; ".join(parts) + ".")
    else:
        notes.append(
            "Semantik metrik: precision/recall/F1 headline adalah <b>rata-rata berbobot "
            "(weighted)</b> antar kelas. Untuk fokus pada kelas serangan, lihat baris kelas "
            "Malicious pada Lampiran (Per-Class Report) dan kuadran deteksi di Bagian C."
        )
        notes.append(
            "Asal label: <b>ground-truth</b> bawaan dataset HIKARI2021 (benign vs malicious)."
        )
        notes.append(
            "Anti-kebocoran: scaler/PCA/penyeimbang (balancing) di-<i>fit</i> hanya pada data "
            "latih setelah split, lalu diterapkan ke data uji — mencegah kebocoran informasi."
        )

    # Imbalance honesty (computed).
    b = ctx["breakdown"]
    if b and b["attack_share"] is not None:
        notes.append(
            f"Keseimbangan kelas pada data uji: serangan {_pct(b['attack_share'])} dari total "
            f"({_grp(b['attack_total'])} serangan vs {_grp(b['normal_total'])} normal). "
            "Pada data timpang, accuracy tunggal dapat menyesatkan."
        )

    for n in notes:
        story.append(Paragraph(f"• {n}", styles["normal"]))
        story.append(Spacer(1, 1.5*mm))

    # Conditional algorithm caveat (only when relevant).
    algo = (ctx["algorithm"] or "").lower()
    if "svc" in algo or "svm" in algo:
        story.append(Paragraph(
            "• Keterbatasan algoritma: Support Vector Classifier berskala O(n²) dan sangat lambat "
            "pada data ratusan ribu baris; platform menampilkan peringatan runtime sebelum eksekusi.",
            styles["note"],
        ))
    if ctx["runtime_warning"]:
        story.append(Paragraph(f"• {ctx['runtime_warning']}", styles["note"]))


# ─── G. Informasi Reproducibility ─────────────────────────────────────────

def _section_g_reproducibility(story, styles, ctx):
    _section_heading(story, styles, "G", "Informasi Reproducibility")
    story.append(Paragraph(
        "Eksperimen dirancang dapat direproduksi: selama hash dataset, kode pipeline, dan "
        "environment sama, metrik yang dihasilkan identik antar eksekusi.",
        styles["normal"],
    ))
    story.append(Spacer(1, 2*mm))
    rows = [
        ["Dataset SHA-256", ctx["dataset_hash"]],
        ["random_state / seed", "42 (terkunci untuk seluruh operasi stokastik)"],
        ["Python", _none_or(ctx["python_version"])],
        ["scikit-learn", _none_or(ctx["sklearn_version"])],
        ["pandas / numpy", f"{_none_or(ctx['pandas_version'])} / {_none_or(ctx['numpy_version'])}"],
        ["Platform", _none_or(ctx["platform_str"])],
        ["Docker", "Ya" if ctx["is_docker"] else ("Tidak" if ctx["is_docker"] is False else "[tidak tercatat]")],
    ]
    story.append(_kv_table(rows))
    story.append(Paragraph(
        "Untuk membuktikan reproducibility: jalankan pipeline yang sama dua kali pada dataset yang "
        "sama, lalu bandingkan nilai metrik (accuracy/precision/recall/F1/AUC) — harus identik, "
        "dan hash dataset di atas harus sama.",
        styles["note"],
    ))


# ─── Lampiran Teknis (supporting ML detail) ───────────────────────────────

def _section_lampiran(story, styles, ctx):
    story.append(PageBreak())
    _section_heading(story, styles, "Lampiran", "Detail Teknis ML")

    metrics = ctx["metrics"]
    _avg = "kelas attack, natural-holdout" if ctx["is_eve"] else "weighted"

    def _fmt(v):
        return f"{v:.6f}" if isinstance(v, (int, float)) else "[tidak tersedia]"

    rows = [["Metrik", "Nilai"]]
    rows += [
        ["Accuracy", _fmt(ctx["accuracy"])],
        [f"Precision ({_avg})", _fmt(ctx["precision"])],
        [f"Recall ({_avg})", _fmt(ctx["recall"])],
        [f"F1-score ({_avg})", _fmt(ctx["f1_score"])],
    ]
    if ctx["roc_auc"] is not None:
        rows.append(["ROC-AUC", _fmt(ctx["roc_auc"])])
    rows.append(["Wall-clock (created → completed)", ctx["wall_clock"] or "[tidak dapat dihitung]"])
    t = Table(rows, colWidths=[8*cm, 6*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Wall-clock mencakup waktu antrian (queue) untuk mode asinkron; bukan inference latency.",
        styles["note"],
    ))

    # ROC curve.
    if ctx["roc_auc"] is not None or "roc_curve" in metrics:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("ROC Curve", styles["subsection"]))
        try:
            story.append(Image(_render_roc_curve(metrics), width=12*cm, height=10*cm))
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender ROC curve: {e}</i>", styles["italic"]))

    # Per-class classification report (HIKARI).
    if ctx["classification_report"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Per-Class Classification Report", styles["subsection"]))
        rep = ctx["classification_report"]
        class_rows = {k: v for k, v in rep.items() if isinstance(v, dict)}
        if class_rows:
            data = [["Class", "Precision", "Recall", "F1-Score", "Support"]]
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

    # Learning curve (HIKARI).
    if ctx["learning_curve"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Learning Curve", styles["subsection"]))
        try:
            story.append(Image(_render_learning_curve(ctx["learning_curve"]), width=14*cm, height=9*cm))
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender learning curve: {e}</i>", styles["italic"]))

    # Locked hyperparameters (from get_info).
    if ctx["fixed_params"]:
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("Hyperparameter Terkunci", styles["subsection"]))
        story.append(_kv_table([[k, str(v)] for k, v in ctx["fixed_params"].items()],
                               col_widths=(6*cm, 10*cm)))


# ─── Footer ───────────────────────────────────────────────────────────────

def _footer(story, styles, ctx):
    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRID))
    story.append(Paragraph(
        f"Dihasilkan oleh IDS Research Pipeline System  -  "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}  -  "
        f"experiment {ctx['experiment_id']}",
        styles["small_muted"],
    ))


# ─── Chart render helpers ─────────────────────────────────────────────────

def _render_network_confusion_matrix(b: dict) -> io.BytesIO:
    """Confusion matrix labeled in network terms (Serangan/Normal) with the
    meaning of each quadrant annotated. Built entirely from the breakdown dict.

    Layout (rows = Aktual, cols = Prediksi), order [Normal, Serangan]:
        TN  FP
        FN  TP
    """
    an, nn = b["attack_name"], b["normal_name"]
    grid = np.array([[b["tn"], b["fp"]], [b["fn"], b["tp"]]], dtype=float)
    quad_labels = [["Normal benar\n(TN)", "False alarm\n(FP)"],
                   ["Serangan LOLOS\n(FN)", "Serangan terdeteksi\n(TP)"]]
    # Cell background hue: green=good (TN/TP), red=critical (FN), amber=FP.
    cell_colors = [["#dcfce7", "#fef3c7"], ["#fee2e2", "#dcfce7"]]

    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.invert_yaxis()

    for i in range(2):
        for j in range(2):
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=cell_colors[i][j],
                                       edgecolor="#333333", linewidth=1.2))
            count = int(grid[i][j])
            ax.text(j + 0.5, i + 0.34, f"{count:,}".replace(",", "."),
                    ha="center", va="center", fontsize=15, fontweight="bold",
                    color="#111111")
            ax.text(j + 0.5, i + 0.66, quad_labels[i][j],
                    ha="center", va="center", fontsize=8.5, color="#333333")

    ax.set_xticks([0.5, 1.5])
    ax.set_yticks([0.5, 1.5])
    ax.set_xticklabels([f"Prediksi: {nn}", f"Prediksi: {an}"], fontsize=9)
    ax.set_yticklabels([f"Aktual: {nn}", f"Aktual: {an}"], fontsize=9, rotation=90, va="center")
    ax.set_title("Confusion Matrix (istilah jaringan)", fontsize=11, fontweight="bold")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
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
        fpr = roc.get("fpr")
        tpr = roc.get("tpr")
        if isinstance(fpr, list) and isinstance(tpr, list) and fpr and tpr:
            ax.plot(fpr, tpr, label=f"ROC (AUC = {metrics.get('roc_auc', 0):.4f})", linewidth=2)
        elif isinstance(fpr, dict):
            for cls_name in fpr:
                ax.plot(fpr[cls_name], tpr[cls_name], label=cls_name, linewidth=1.5)
    elif "roc_curves_per_class" in metrics:
        for cls_name, curve in metrics["roc_curves_per_class"].items():
            ax.plot(curve["fpr"], curve["tpr"], label=cls_name, linewidth=1.5)

    ax.plot([0, 1], [0, 1], 'k--', alpha=0.5, label="Tebak acak")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate (Recall)")
    ax.set_title(f"ROC Curve (AUC = {metrics.get('roc_auc', 0):.4f})")
    ax.legend(loc="lower right")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _render_feature_importance(feature_importance: list[dict]) -> io.BytesIO:
    """Render feature importance bar chart as PNG and return as BytesIO.

    Limited to the top 20 features for readability. Title states the limit
    and the total count explicitly when truncation occurs, so the PDF reader
    cannot mistake the chart for the full feature set.
    """
    n_total = len(feature_importance)
    top_n = 20
    fi = feature_importance[:top_n]
    fig, ax = plt.subplots(figsize=(8, max(4, len(fi) * 0.3)))
    ax.barh(
        [item["feature"] for item in reversed(fi)],
        [item["importance"] for item in reversed(fi)],
        color="#2563EB",
    )
    ax.set_xlabel("Importance")
    title = f"Top {len(fi)} Feature Importance"
    if n_total > len(fi):
        title += f" (dari {n_total} fitur)"
    ax.set_title(title)
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
