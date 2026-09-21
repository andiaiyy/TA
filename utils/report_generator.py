"""
PDF report generator — academic-paper style (ReportLab).

Design goal: read like a short research paper — serif typography with a clear
hierarchy, a MUTED (desaturated) palette that survives grayscale printing,
thin booktabs-style rules, and numbered captions ("Tabel 1", "Gambar 1"). Every
number and interpretive sentence is computed from the experiment's ACTUAL data
(metrics.json / extra_info / metadata) at render time — never fabricated, never
recomputed differently. Absent fields are skipped with an honest note.

Family-aware semantics (stated explicitly as a methodological note, never
conflated): HIKARI metrics are weighted-average over ground-truth labels;
EVE-cbr metrics are attack-class on the natural holdout (labels derived from
Suricata alerts). Operational counts (detected / missed / false alarm) are
ALWAYS derived from the confusion matrix (attack = positive class).

Structure (paper-like):
  Masthead  title + identity + Abstrak (computed)
  1. Konfigurasi Eksperimen
  2. Hasil dan Metrik            (Tabel: metrik utama + catatan semantik)
  3. Interpretasi Keamanan       (Tabel kuadran + Gambar CM + sorotan)
  4. Analisis Metrik             (verdict per metrik, dihitung)
  5. Fitur Berpengaruh           (Gambar + makna per-fitur; defensif)
  6. Diagnostik                  (ROC, learning curve / dual-holdout, per-kelas)
  7. Catatan Metodologis
  8. Reproducibility

Signature, return type (bytes), and ReportLab mechanism are preserved exactly so
the call sites in ui/ keep working. ``_confusion_breakdown`` is public-by-use
(imported by ui/components/result_views.py and tests) and kept intact.

Rules: No database access. No UI imports. Reads provided data only.
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
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import HexColor
from reportlab.lib import colors

from orchestrator import run_mode as _run_mode
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable,
)

# ── Muted academic palette (single source; grayscale-safe by lightness) ────
_INK       = HexColor('#2b2f36')   # body text — soft near-black
_HEAD      = HexColor('#33404d')   # headings & rules — slate
_MUTED     = HexColor('#717784')   # captions / secondary text
_RULE      = HexColor('#d7dbe0')   # thin light rules / row separators
_HEADFILL  = HexColor('#eef1f4')   # light table-header fill (dark text on top)
_ACCENT    = HexColor('#5b7fa6')   # muted slate-blue (used sparingly)
_GOOD      = HexColor('#4a7c59')   # sage green (text)
_WARN      = HexColor('#9c7b3a')   # soft amber (text)
_CRIT      = HexColor('#9e5b52')   # faded brick red (text)
_GOOD_FILL = HexColor('#e9f0ea')
_WARN_FILL = HexColor('#f4efe3')
_CRIT_FILL = HexColor('#f0e5e2')
_NOTE_FILL = HexColor('#eef1f4')

# Chart palette (muted; distinguishable in grayscale by lightness)
_C_TNTP  = '#e4ece5'   # sage (correct)
_C_FP    = '#f0e9d8'   # soft amber (false alarm)
_C_FN    = '#e9dad6'   # faded brick (missed attack — darkest fill)
_C_EDGE  = '#c9ccd1'
_C_BAR   = '#6f8aa8'   # muted slate-blue bars
_C_LINE  = '#5b7fa6'
_C_LINE2 = '#9c7b3a'
_C_DIAG  = '#9aa0a8'
_C_TEXT  = '#2b2f36'

# Serif family for an academic feel (ReportLab built-in Type-1 fonts).
_SERIF = "Times-Roman"
_SERIF_B = "Times-Bold"
_SERIF_I = "Times-Italic"


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
    """Generate the academic-style PDF and return it as bytes."""
    ctx = _build_context(
        experiment_id=experiment_id, dataset_type=dataset_type,
        dataset_path=dataset_path, dataset_hash=dataset_hash,
        pipeline_id=pipeline_id, pipeline_info=pipeline_info or {},
        metrics=metrics or {}, metadata=metadata or {},
        label_mapping=label_mapping, feature_names=feature_names,
    )
    # Numbering counters for sections / tables / figures (paper-style captions).
    ctx["_counters"] = {"sec": 0, "tab": 0, "fig": 0}

    # BAHASA laporan ditetapkan SEKALI, di sini, lalu dibawa di `ctx`. Membaca
    # bahasa aktif berulang kali saat menggambar akan membuat satu laporan bisa
    # separuh berganti bila pengguna mengubah bahasa di tengah pembuatan.
    #
    # Impor dilakukan di dalam fungsi, bukan di tingkat modul: `utils/` dan
    # `orchestrator/` tidak boleh bergantung pada lapisan antarmuka.
    from ui.i18n.core import current_lang, lookup

    ctx["lang"] = current_lang()
    ctx["_t"] = lambda key, **values: (
        lookup(key, ctx["lang"]).format(**values) if values
        else lookup(key, ctx["lang"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.2*cm, rightMargin=2.2*cm,
        topMargin=2.0*cm, bottomMargin=2.0*cm,
        title=f"Laporan Eksperimen {pipeline_id}",
        author="IDS Research Pipeline Execution System",
    )
    styles = _build_styles()
    story: list = []

    _masthead(story, styles, ctx)

    for section_fn in (
        _section_1_konfigurasi,
        _section_2_hasil,
        _section_3_keamanan,
        _section_4_analisis,
        _section_5_fitur,
        _section_6_diagnostik,
        _section_7_metodologi,
        _section_8_reproducibility,
    ):
        try:
            section_fn(story, styles, ctx)
        except Exception as e:
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

    breakdown = _confusion_breakdown(metrics.get("confusion_matrix"), label_mapping)

    return {
        "experiment_id": kw.get("experiment_id"),
        "dataset_type": dataset_type,
        "is_eve": dataset_type == "EVE_SURICATA",
        "dataset_path": kw.get("dataset_path"),
        "dataset_hash": kw.get("dataset_hash") or "N/A",
        "pipeline_id": kw.get("pipeline_id"),
        "label_mapping": label_mapping,
        "feature_names": kw.get("feature_names") or md.get("feature_names"),
        "paper": pinfo.get("paper"),
        "algorithm": pinfo.get("algorithm"),
        "preprocessing_steps": pinfo.get("preprocessing_steps") or [],
        "feature_selection": pinfo.get("feature_selection"),
        "fixed_params": pinfo.get("fixed_params") or {},
        # Mode & parameter dibaca dari METADATA artefak — yaitu apa yang
        # benar-benar dipakai saat run itu — bukan dari definisi pipeline pada
        # kode saat ini. Artefak lama tidak punya keduanya; NULL/absen dibaca
        # sebagai run RESMI, sama seperti di basis data.
        "run_mode": _run_mode.normalize_run_mode(md.get("run_mode")),
        "run_mode_recorded": bool(md.get("run_mode")),
        "params_used": md.get("params_used") if isinstance(md.get("params_used"), dict) else {},
        "params_locked": md.get("params_locked") if isinstance(md.get("params_locked"), dict) else {},
        "params_changed": list(md.get("params_changed") or []),
        "train_test_split": pinfo.get("train_test_split") or {},
        "anti_leakage_info": pinfo.get("anti_leakage"),
        "metrics_policy": pinfo.get("metrics_policy"),
        "runtime_warning": pinfo.get("runtime_warning"),
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
        "natural_holdout": metrics.get("natural_holdout") if isinstance(metrics.get("natural_holdout"), dict) else {},
        "balanced_holdout": metrics.get("balanced_holdout") if isinstance(metrics.get("balanced_holdout"), dict) else {},
        "anti_leakage": metrics.get("anti_leakage") if isinstance(metrics.get("anti_leakage"), dict) else {},
        "evaluation": metrics.get("evaluation") if isinstance(metrics.get("evaluation"), dict) else {},
        "selected_combo": metrics.get("selected_combo") if isinstance(metrics.get("selected_combo"), dict) else {},
        "created_at": created_at or "N/A",
        "completed_at": completed_at or "N/A",
        "wall_clock": wall_clock,
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


# ─── Operational engine (PRESERVED — computed from real numbers) ──────────

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
    """AMBANGNYA TIDAK BERUBAH — hanya label & klausanya kini berupa kunci."""
    if r is None:
        return _MUTED, "vd.unavailable", ""
    if r >= 0.95:
        return _GOOD, "vd.excellent", "vd.recall_excellent"
    if r >= 0.85:
        return _GOOD, "vd.good", "vd.recall_good"
    if r >= 0.60:
        return _WARN, "vd.attention", "vd.recall_attention"
    return _CRIT, "vd.weak", "vd.recall_weak"


def _precision_verdict(p):
    if p is None:
        return _MUTED, "vd.unavailable", ""
    if p >= 0.90:
        return _GOOD, "vd.excellent", "vd.precision_excellent"
    if p >= 0.75:
        return _GOOD, "vd.good", "vd.precision_good"
    if p >= 0.50:
        return _WARN, "vd.attention", "vd.precision_attention"
    return _CRIT, "vd.weak", "vd.precision_weak"


def _f1_verdict(f):
    if f is None:
        return _MUTED, "vd.unavailable", ""
    if f >= 0.90:
        return _GOOD, "vd.excellent", "vd.f1_excellent"
    if f >= 0.75:
        return _GOOD, "vd.good", "vd.f1_good"
    if f >= 0.55:
        return _WARN, "vd.attention", "vd.f1_attention"
    return _CRIT, "vd.weak", "vd.f1_weak"


def _auc_verdict(a):
    """AMBANGNYA TIDAK BERUBAH — hanya label & klausanya kini berupa kunci."""
    if a is None:
        return _MUTED, "vd.unavailable", ""
    if a >= 0.90:
        return _GOOD, "vd.excellent", "vd.auc_excellent"
    if a >= 0.80:
        return _GOOD, "vd.good", "vd.auc_good"
    if a >= 0.70:
        return _WARN, "vd.attention", "vd.auc_attention"
    return _CRIT, "vd.weak", "vd.auc_weak"


# ─── Network meaning of features (PRESERVED) ──────────────────────────────

_FEATURE_EXACT = {
    "bytes_per_sec": "rpt.feat_bytes_per_sec",
    "pkts_per_sec": "rpt.feat_pkts_per_sec",
    "bytes_per_pkt": "rpt.feat_bytes_per_pkt",
    "total_bytes": "rpt.feat_total_bytes",
    "total_pkts": "rpt.feat_total_pkts",
    "duration": "rpt.feat_flow_duration",
    "bytes_toserver": "rpt.feat_bytes_toserver",
    "pkts_toserver": "rpt.feat_pkts_toserver",
    "pkts_toclient": "rpt.feat_pkts_toclient",
    "bytes_toserver_ratio": "rpt.feat_bytes_toserver_ratio",
    "pkts_toserver_ratio": "rpt.feat_pkts_toserver_ratio",
    "src_port": "rpt.feat_src_port",
    "src_port_class": "rpt.feat_src_port_class",
    "dest_port_class": "rpt.feat_dest_port_class",
    "unique_dest_port_window": "rpt.feat_unique_dest_port_window",
    "unique_dest_ip_window": "rpt.feat_unique_dest_ip_window",
    "event_count_window": "rpt.feat_event_count_window",
    "no_alert_count_window": "rpt.feat_no_alert_count_window",
    "total_bytes_window": "rpt.feat_total_bytes_window",
    "total_pkts_window": "rpt.feat_total_pkts_window",
    "bytes_per_event_window": "rpt.feat_bytes_per_event_window",
    "pkts_per_event_window": "rpt.feat_pkts_per_event_window",
    "ts_hour": "rpt.feat_ts_hour",
    "app_proto_h": "rpt.feat_app_proto_h",
    "interaction_bytes_rate_packet_rate": "rpt.feat_interaction_bytes_rate_packet_rate",
    "interaction_total_bytes_duration": "rpt.feat_interaction_total_bytes_duration",
    "interaction_total_pkts_duration": "rpt.feat_interaction_total_pkts_duration",
    "flow_duration": "rpt.feat_flow_duration",
    "down_up_ratio": "rpt.feat_down_up_ratio_flow",
    "fwd_subflow_bytes": "rpt.feat_fwd_subflow_bytes",
    "bwd_subflow_bytes": "rpt.feat_bwd_subflow_bytes",
    "fwd_init_window_size": "rpt.feat_fwd_init_window_size",
    "bwd_init_window_size": "rpt.feat_bwd_init_window_size",
}


def _feature_network_meaning(name: str, t) -> str | None:
    """Arti jaringan sebuah fitur, diturunkan dari namanya.

    Mengembalikan kalimat yang SUDAH diterjemahkan, atau None bila nama fitur
    tidak memuat token jaringan yang dikenali. Pencocokannya identik dengan
    versi sebelumnya; hanya kalimatnya yang kini berasal dari katalog.
    """
    if not name:
        return None
    key = str(name).lower()
    if key in _FEATURE_EXACT:
        return t(_FEATURE_EXACT[key])

    # Awalan dicatat dulu, dipasang belakangan secara BERSARANG — urutan
    # katanya boleh berbeda antar bahasa, jadi tidak boleh disambung.
    wrappers = []
    work = key
    if work.startswith("log_"):
        wrappers.append("rpt.feat_log_of")
        work = work[4:]
    if work.startswith("interaction_"):
        wrappers.append("rpt.feat_interaction_of")
        work = work[len("interaction_"):]

    def _wrap(text: str) -> str:
        for wrapper in wrappers:
            text = t(wrapper, meaning=text)
        return text

    if work in _FEATURE_EXACT:
        return _wrap(t(_FEATURE_EXACT[work]))

    rules = [
        ("init_window", "rpt.feat_init_window"),
        ("window_size", "rpt.feat_window_size"),
        ("duration", "rpt.feat_duration_short"),
        ("iat", "rpt.feat_iat"),
        ("per_sec", "rpt.feat_per_sec"),
        ("_rate", "rpt.feat_rate"),
        ("down_up_ratio", "rpt.feat_down_up_ratio"),
        ("ratio", "rpt.feat_ratio"),
        ("unique_dest_port", "rpt.feat_unique_dest_port"),
        ("unique_dest_ip", "rpt.feat_unique_dest_ip"),
        ("port_class", "rpt.feat_port_class"),
        ("dest_port", "rpt.feat_dest_port"),
        ("src_port", "rpt.feat_src_port"),
        ("toserver", "rpt.feat_toserver"),
        ("toclient", "rpt.feat_toclient"),
        ("subflow", "rpt.feat_subflow"),
        ("payload", "rpt.feat_payload"),
        ("header", "rpt.feat_header"),
        ("flag", "rpt.feat_flag"),
        ("bulk", "rpt.feat_bulk"),
        ("active", "rpt.feat_active"),
        ("idle", "rpt.feat_idle"),
        ("seg_size", "rpt.feat_seg_size"),
        ("window", "rpt.feat_window"),
        ("bytes", "rpt.feat_bytes"),
        ("pkts", "rpt.feat_pkts"),
        ("packet", "rpt.feat_pkts"),
        ("alert", "rpt.feat_alert"),
        ("event", "rpt.feat_event"),
        ("proto", "rpt.feat_proto"),
        ("hour", "rpt.feat_hour"),
        ("flow", "rpt.feat_flow"),
    ]
    for token, meaning_key in rules:
        if token in work:
            return _wrap(t(meaning_key))
    return None


# ─── Style sheet (serif, academic hierarchy) ──────────────────────────────

def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontName=_SERIF_B,
                                 fontSize=18, leading=22, textColor=_INK, spaceAfter=2*mm),
        "subtitle": ParagraphStyle("Sub", parent=base["Normal"], fontName=_SERIF_I,
                                    fontSize=10.5, textColor=_MUTED, spaceAfter=3*mm,
                                    alignment=TA_CENTER),
        "abstract_h": ParagraphStyle("AbsH", parent=base["Normal"], fontName=_SERIF_B,
                                      fontSize=10.5, textColor=_HEAD, spaceAfter=1*mm),
        "abstract": ParagraphStyle("Abstract", parent=base["Normal"], fontName=_SERIF,
                                    fontSize=9.5, leading=13.5, textColor=_INK,
                                    alignment=TA_JUSTIFY),
        "section": ParagraphStyle("Section", parent=base["Heading2"], fontName=_SERIF_B,
                                   fontSize=12.5, leading=15, spaceBefore=6*mm,
                                   spaceAfter=2*mm, textColor=_HEAD),
        "subsection": ParagraphStyle("Subsec", parent=base["Heading3"], fontName=_SERIF_B,
                                      fontSize=10.5, spaceBefore=3*mm, spaceAfter=1.5*mm,
                                      textColor=_HEAD),
        "normal": ParagraphStyle("Body", parent=base["Normal"], fontName=_SERIF,
                                 fontSize=10, leading=14, textColor=_INK,
                                 alignment=TA_JUSTIFY),
        "italic": ParagraphStyle("Italic", parent=base["Normal"], fontName=_SERIF_I,
                                 fontSize=10, textColor=_INK),
        "caption": ParagraphStyle("Caption", parent=base["Normal"], fontName=_SERIF_I,
                                   fontSize=8.5, leading=11, textColor=_MUTED, spaceAfter=1*mm),
        "small_muted": ParagraphStyle("SmallMuted", parent=base["Normal"], fontName=_SERIF,
                                      fontSize=8, textColor=_MUTED, alignment=TA_CENTER),
        "note": ParagraphStyle("Note", parent=base["Normal"], fontName=_SERIF_I,
                               fontSize=9, leading=12.5, textColor=_MUTED),
        "cell": ParagraphStyle("Cell", parent=base["Normal"], fontName=_SERIF,
                               fontSize=9, leading=12, textColor=_INK),
        "cell_key": ParagraphStyle("CellKey", parent=base["Normal"], fontName=_SERIF_B,
                                   fontSize=9, leading=12, textColor=_HEAD),
    }


# ─── Numbering + reusable mini-blocks ─────────────────────────────────────

def _next(ctx, key) -> int:
    ctx["_counters"][key] += 1
    return ctx["_counters"][key]


def _section(story, styles, ctx, title: str) -> None:
    n = _next(ctx, "sec")
    story.append(Paragraph(f"{n}.&nbsp;&nbsp;{title}", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color=_RULE,
                            spaceBefore=0.5*mm, spaceAfter=2*mm))


def _table_caption(story, styles, ctx, text: str) -> None:
    n = _next(ctx, "tab")
    story.append(Paragraph(f"<b>Tabel {n}.</b> {text}", styles["caption"]))


def _figure(story, styles, ctx, img, width, height, text: str) -> None:
    story.append(Image(img, width=width, height=height))
    n = _next(ctx, "fig")
    story.append(Spacer(1, 1*mm))
    story.append(Paragraph(f"<b>Gambar {n}.</b> {text}", styles["caption"]))


def _kv_table(styles, rows: list[list[str]], col_widths=(5*cm, 11.6*cm)):
    """Key/value reference block — thin booktabs style, light header column."""
    wrapped = []
    for r in rows:
        wrapped.append([Paragraph(str(r[0]), styles["cell_key"]),
                        Paragraph(str(r[1]), styles["cell"])])
    t = Table(wrapped, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, _HEAD),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, _HEAD),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _data_table(data, col_widths, *, num_cols=None, highlight_rows=None):
    """Booktabs-style data table: top rule, header rule, bottom rule; light
    header fill; thin row separators. ``highlight_rows`` maps row-index -> fill."""
    t = Table(data, colWidths=col_widths)
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), _SERIF),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # header
        ("FONTNAME", (0, 0), (-1, 0), _SERIF_B),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEAD),
        ("BACKGROUND", (0, 0), (-1, 0), _HEADFILL),
        # booktabs rules
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, _HEAD),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, _HEAD),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, _RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, _HEAD),
    ]
    for c in (num_cols or []):
        cmds.append(("ALIGN", (c, 1), (c, -1), "CENTER"))
    for ridx, fill in (highlight_rows or {}).items():
        cmds.append(("BACKGROUND", (0, ridx), (-1, ridx), fill))
    t.setStyle(TableStyle(cmds))
    return t


def _callout(text: str, styles, *, fill, border):
    p = Paragraph(text, styles["cell"])
    t = Table([[p]], colWidths=[16.6*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, border),   # left accent rule (grayscale-safe)
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _none_or(v, fallback):
    """Nilai, atau penanda kosong. `fallback` WAJIB diisi pemanggil.

    Dulu penandanya adalah bawaan berbahasa Indonesia, sehingga bocor ke
    setiap sel kosong pada laporan Inggris. Tanpa bawaan, kelalaian yang sama
    menjadi galat yang terlihat, bukan teks salah bahasa yang diam.
    """
    if v is None or v == "":
        return fallback
    return str(v)


def _hexcolor_name(c) -> str:
    return '#%02x%02x%02x' % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))


# ─── Masthead (title + identity + abstract) ───────────────────────────────

def _compose_abstract(ctx) -> str:
    """3–5 computed sentences (abstract-like). Never a blank template."""
    t = ctx["_t"]
    algo = ctx["algorithm"] or t("rpt.abs_algo_fallback")
    ds = (t("rpt.abs_dataset_eve") if ctx["is_eve"]
          else (ctx["dataset_type"] or t("rpt.abs_dataset_fallback")))
    sem = t("rpt.abs_semantics_eve" if ctx["is_eve"]
            else "rpt.abs_semantics_weighted")
    b = ctx["breakdown"]
    if b and b["attack_recall"] is not None:
        _, rlabel_key, _ = _recall_verdict(b["attack_recall"])
        f1 = b["attack_f1"]
        # Dua kalimat UTUH, bukan satu kalimat plus tempelan: klausa F1 yang
        # dulu disambung membuat urutan katanya terkunci pada tata bahasa
        # Indonesia.
        values = dict(
            algo=algo, dataset=ds, total=_grp(b["total"]),
            attacks=_grp(b["attack_total"]), normals=_grp(b["normal_total"]),
            recall=_pct(b["attack_recall"]), tp=_grp(b["tp"]),
            precision=_pct(b["attack_precision"]), missed=_grp(b["fn"]),
            false_alarms=_grp(b["fp"]), verdict=t(rlabel_key), semantics=sem)
        if isinstance(f1, (int, float)):
            return t("rpt.abs_main_f1", f1=f"{f1:.4f}", **values)
        return t("rpt.abs_main", **values)
    # Fallback when the confusion matrix is unavailable/non-binary.
    parts = []
    if isinstance(ctx["accuracy"], (int, float)):
        parts.append(f"accuracy {ctx['accuracy']:.4f}")
    if isinstance(ctx["f1_score"], (int, float)):
        parts.append(f"F1 {ctx['f1_score']:.4f}")
    if isinstance(ctx["roc_auc"], (int, float)):
        parts.append(f"AUC {ctx['roc_auc']:.4f}")
    metr = (", ".join(parts)) if parts else t("rpt.abs_metrics_fallback")
    return t("rpt.abs_no_confusion", algo=algo, dataset=ds, metrics=metr,
             semantics=sem)


#: Mode eksekusi → kunci kamus. Konstanta di `orchestrator/run_mode` TIDAK
#: diubah; pemetaannya hidup di sini, di lapisan keluaran.
_RUN_MODE_LABEL_KEYS = {
    _run_mode.RUN_MODE_OFFICIAL: "mode.official_label",
    _run_mode.RUN_MODE_EXPLORATION: "mode.exploration_label",
}
_RUN_MODE_HINT_KEYS = {
    _run_mode.RUN_MODE_OFFICIAL: "mode.official_hint",
    _run_mode.RUN_MODE_EXPLORATION: "mode.exploration_hint",
}


def _masthead(story, styles, ctx):
    t = ctx["_t"]
    na = t("rpt.na")
    story.append(Paragraph(t("rpt.main_title"), styles["title"]))
    story.append(Paragraph(t("rpt.subtitle"), styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1.0, color=_HEAD, spaceAfter=3*mm))

    story.append(_kv_table(styles, [
        # "Experiment ID", "Pipeline", "Algoritma", "Dataset" adalah nama
        # teknis yang sengaja TIDAK diterjemahkan — sama seperti nama kolom
        # pada ekspor CSV, supaya laporan tetap dapat dibaca lintas bahasa.
        ["Experiment ID", _none_or(ctx["experiment_id"], na)],
        ["Pipeline", _none_or(ctx["pipeline_id"], na)],
        ["Algoritma", _none_or(ctx["algorithm"], na)],
        ["Dataset", _none_or(ctx["dataset_type"], na)],
        [t("rpt.lbl_time"),
         f"{_none_or(ctx['created_at'], na)} → {_none_or(ctx['completed_at'], na)}"],
        [t("rpt.lbl_run_mode"), t(_RUN_MODE_LABEL_KEYS[ctx["run_mode"]])
         + " — " + t(_RUN_MODE_HINT_KEYS[ctx["run_mode"]])],
        # Bahasa laporan DICATAT pada laporannya sendiri, supaya pembaca tahu
        # dalam bahasa apa kalimat-kalimatnya ditulis.
        [t("rpt.lbl_language"), t("rpt.language_name")],
    ]))

    # Penanda run eksplorasi di HALAMAN PERTAMA, sebelum satu angka pun
    # terbaca — laporan ini bisa beredar terpisah dari aplikasi.
    if _run_mode.is_exploration(ctx["run_mode"]):
        story.append(Spacer(1, 2*mm))
        story.append(_callout(
            "<b>" + t("rpt.exploration_badge") + "</b> "
            + t("rpt.exploration_warning"),
            styles, fill=colors.HexColor("#fff4e5"),
            border=colors.HexColor("#e8a33d")))

    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(t("rpt.abstract_h"), styles["abstract_h"]))
    story.append(Paragraph(_compose_abstract(ctx), styles["abstract"]))


# ─── 1. Konfigurasi Eksperimen ────────────────────────────────────────────

def _section_1_konfigurasi(story, styles, ctx):
    t = ctx["_t"]
    na = t("rpt.na")
    _section(story, styles, ctx, t("rpt.sec_config"))

    if ctx["is_eve"]:
        fmt = t("rpt.fmt_ndjson")
        label_origin = t("rpt.label_origin_eve")
    else:
        fmt = t("rpt.fmt_csv")
        label_origin = t("rpt.label_origin_hikari")

    rows = [
        [t("rpt.lbl_algorithm"), _none_or(ctx["algorithm"], na)],
        [t("rpt.lbl_paper"), _none_or(ctx["paper"], na)],
        [t("rpt.lbl_dataset_format"), fmt],
        [t("rpt.lbl_label_origin"), label_origin],
        [t("rpt.lbl_source_file"), _none_or(ctx["dataset_path"], na)],
    ]
    if ctx["feature_selection"]:
        rows.append(["Feature selection", str(ctx["feature_selection"])])
    b = ctx["breakdown"]
    if b:
        rows.append([t("rpt.lbl_class_distribution"),
                     t("rpt.class_distribution_value", total=_grp(b["total"]),
                       attacks=_grp(b["attack_total"]),
                       share=_pct(b["attack_share"]),
                       normals=_grp(b["normal_total"]))])
    story.append(_kv_table(styles, rows))

    steps = ctx["preprocessing_steps"]
    if steps:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(t("rpt.lbl_preprocessing"), styles["subsection"]))
        story.append(Paragraph(
            "; ".join(str(s) for s in steps) + ".", styles["cell"]))

    # Parameter yang BENAR-BENAR dipakai run ini bila artefaknya mencatatnya;
    # bila tidak (artefak lama), definisi pipeline pada kode saat ini — dan
    # perbedaan asal-usul itu dikatakan di judul & keterangan tabel, bukan
    # disamarkan.
    used = ctx["params_used"]
    locked_cfg = ctx["params_locked"] or ctx["fixed_params"]
    cfg = used or ctx["fixed_params"]
    changed = set(ctx["params_changed"] or [])
    if cfg:
        story.append(Spacer(1, 2*mm))
        if used:
            heading = t("rpt.params_heading_used_changed" if changed
                        else "rpt.params_heading_used")
            caption = t("rpt.params_caption_used_changed" if changed
                        else "rpt.params_caption_used")
            header = ["Parameter", t("rpt.col_value"), t("rpt.col_locked_value")]
            rows_cfg = []
            for k, v in cfg.items():
                mark = "*" if k in changed else ""
                base = locked_cfg.get(k, "—")
                rows_cfg.append([f"{k}{mark}", str(v),
                                 str(base) if k in changed
                                 else t("rpt.val_same")])
            data = [header] + rows_cfg
            widths = [5.6*cm, 5.5*cm, 5.5*cm]
        else:
            heading = t("rpt.params_heading_locked")
            caption = t("rpt.params_caption_locked")
            data = ([["Parameter", t("rpt.col_value")]]
                    + [[str(k), str(v)] for k, v in cfg.items()])
            widths = [7*cm, 9.6*cm]
        story.append(Paragraph(heading, styles["subsection"]))
        _table_caption(story, styles, ctx, caption)
        story.append(_data_table(data, widths))


# ─── 2. Hasil dan Metrik ──────────────────────────────────────────────────

def _section_2_hasil(story, styles, ctx):
    t = ctx["_t"]
    na = t("rpt.na")
    _section(story, styles, ctx, t("rpt.sec_results"))

    # "weighted" adalah istilah metrik yang dipakai apa adanya di kedua bahasa.
    _avg = t("rpt.scope_eve") if ctx["is_eve"] else "weighted"

    def _fmt(v):
        return f"{v:.6f}" if isinstance(v, (int, float)) else na

    data = [[t("rpt.col_metric"), t("rpt.col_value"), t("rpt.col_scope")]]
    data += [
        ["Accuracy", _fmt(ctx["accuracy"]), t("rpt.scope_all_classes")],
        ["Precision", _fmt(ctx["precision"]), _avg],
        ["Recall", _fmt(ctx["recall"]), _avg],
        ["F1-score", _fmt(ctx["f1_score"]), _avg],
    ]
    if ctx["roc_auc"] is not None:
        data.append(["ROC-AUC", _fmt(ctx["roc_auc"]), t("rpt.scope_binary")])

    _table_caption(story, styles, ctx, t("rpt.cap_metrics"))
    story.append(_data_table(data, [5.2*cm, 5.4*cm, 6*cm], num_cols=[1]))

    # Mandatory metric-semantics footnote (family-aware; never conflated).
    foot = t("rpt.foot_metric_eve" if ctx["is_eve"]
             else "rpt.foot_metric_hikari")
    story.append(Spacer(1, 1.5*mm))
    story.append(Paragraph(foot, styles["note"]))


# ─── 3. Interpretasi Keamanan (dihitung dari confusion matrix) ────────────

def _section_3_keamanan(story, styles, ctx):
    _section(story, styles, ctx, ctx["_t"]("rpt.sec_security"))

    b = ctx["breakdown"]
    if not b:
        story.append(Paragraph(ctx["_t"]("rpt.sec_no_confusion"),
                               styles["italic"]))
        return

    an, nn = b["attack_name"], b["normal_name"]
    story.append(Paragraph(
        ctx["_t"]("rpt.sec_quadrant_intro", attack=an), styles["normal"]))
    story.append(Spacer(1, 2*mm))

    t = ctx["_t"]
    quad = [
        [t("rpt.col_category"), t("rpt.col_count"), t("rpt.col_meaning")],
        [t("rpt.quad_tp"), _grp(b["tp"]),
         Paragraph(t("rpt.quad_tp_note", attack=an), styles["cell"])],
        [t("rpt.quad_fn"), _grp(b["fn"]),
         Paragraph(t("rpt.quad_fn_note", attack=an, normal=nn), styles["cell"])],
        [t("rpt.quad_fp"), _grp(b["fp"]),
         Paragraph(t("rpt.quad_fp_note", normal=nn), styles["cell"])],
        [t("rpt.quad_tn"), _grp(b["tn"]),
         Paragraph(t("rpt.quad_tn_note", normal=nn), styles["cell"])],
    ]
    _table_caption(story, styles, ctx, t("rpt.cap_quadrants"))
    story.append(_data_table(
        quad, [4.6*cm, 2.2*cm, 9.8*cm], num_cols=[1],
        highlight_rows={2: _CRIT_FILL, 3: _WARN_FILL},
    ))

    # Computed security sentence.
    story.append(Spacer(1, 2.5*mm))
    story.append(Paragraph(
        t("rpt.sec_summary_sentence", missed=_grp(b["fn"]),
          total=_grp(b["attack_total"]), recall=_pct(b["attack_recall"]),
          fp=_grp(b["fp"]), fpr=_pct(b["fp_rate"])), styles["normal"]))

    story.append(Spacer(1, 2*mm))
    if b["attack_total"]:
        miss_pct = b["fn"] / b["attack_total"]
        story.append(_callout(
            f"<b><font color='{_hexcolor_name(_CRIT)}'>"
            + t("rpt.callout_missed_label") + "</font></b> "
            + t("rpt.callout_missed_body", missed=_grp(b["fn"]),
                total=_grp(b["attack_total"]), pct=_pct(miss_pct)),
            styles, fill=_CRIT_FILL, border=_CRIT))
    if b["normal_total"] and b["fp_rate"] is not None:
        story.append(Spacer(1, 1.5*mm))
        story.append(_callout(
            f"<b><font color='{_hexcolor_name(_WARN)}'>"
            + t("rpt.callout_fp_label") + "</font></b> "
            + t("rpt.callout_fp_body", fp=_grp(b["fp"]),
                total=_grp(b["normal_total"]), pct=_pct(b["fp_rate"])),
            styles, fill=_WARN_FILL, border=_WARN))

    story.append(Spacer(1, 3*mm))
    try:
        cm_img = _render_network_confusion_matrix(b, t)
        _figure(story, styles, ctx, cm_img, 11*cm, 9.2*cm,
                t("rpt.cap_confusion"))
    except Exception as e:
        story.append(Paragraph(t("rpt.err_render_confusion", error=e),
                               styles["italic"]))


#: Kunci klausa penilaian → kunci KALIMAT UTUH untuk metrik yang kalimatnya
#: memang berubah menurut penilaian. Pemetaan hidup di lapisan penyajian;
#: ambang penilaian ada di `_f1_verdict`/`_auc_verdict` dan tidak berubah.
_F1_DESC_KEYS = {
    "vd.f1_excellent": "rpt.desc_f1_excellent",
    "vd.f1_good": "rpt.desc_f1_good",
    "vd.f1_attention": "rpt.desc_f1_attention",
    "vd.f1_weak": "rpt.desc_f1_weak",
}
_AUC_DESC_KEYS = {
    "vd.auc_excellent": "rpt.desc_auc_excellent",
    "vd.auc_good": "rpt.desc_auc_good",
    "vd.auc_attention": "rpt.desc_auc_attention",
    "vd.auc_weak": "rpt.desc_auc_weak",
}

#: Legenda skala ROC-AUC. SATU sumber untuk kedua bahasa: disisipkan sebagai
#: nilai, tidak ditulis ulang per bahasa, sehingga angkanya mustahil bergeser.
_AUC_SCALE = {"perfect": "1,0", "chance": "0,5"}


# ─── 4. Analisis Metrik (verdict per metrik, dihitung) ────────────────────

def _section_4_analisis(story, styles, ctx):
    t = ctx["_t"]
    _section(story, styles, ctx, t("rpt.sec_analysis"))
    b = ctx["breakdown"]

    if b:
        recall_val, precision_val, f1_val = b["attack_recall"], b["attack_precision"], b["attack_f1"]
        story.append(Paragraph(t("rpt.analysis_intro_attack"), styles["normal"]))
    else:
        recall_val, precision_val, f1_val = ctx["recall"], ctx["precision"], ctx["f1_score"]
        story.append(Paragraph(t("rpt.analysis_intro_plain"), styles["normal"]))
    story.append(Spacer(1, 1.5*mm))

    items = []
    if recall_val is not None:
        color, label_key, _ = _recall_verdict(recall_val)
        label = t(label_key)
        desc = (t("rpt.desc_recall_detail", pct=_pct(recall_val),
                  missed=_grp(b["fn"]), total=_grp(b["attack_total"])) if b
                else t("rpt.desc_recall", pct=_pct(recall_val)))
        items.append((t("rpt.metric_recall"), recall_val, color, label, desc))
    if precision_val is not None:
        color, label_key, _ = _precision_verdict(precision_val)
        label = t(label_key)
        desc = (t("rpt.desc_precision_detail", pct=_pct(precision_val),
                  alarms=_grp(b["pred_attack"]), fp=_grp(b["fp"])) if b
                else t("rpt.desc_precision", pct=_pct(precision_val)))
        items.append((t("rpt.metric_precision"), precision_val, color, label, desc))
    if f1_val is not None:
        color, label_key, clause_key = _f1_verdict(f1_val)
        items.append((t("rpt.metric_f1"), f1_val, color, t(label_key),
                      t(_F1_DESC_KEYS.get(clause_key, "rpt.desc_f1"))))
    if ctx["accuracy"] is not None:
        imbalanced = bool(b and b["imbalance_ratio"] and b["imbalance_ratio"] >= 1.5)
        color = _WARN if imbalanced else _GOOD
        label = t("vd.accuracy_careful" if imbalanced
                  else "vd.accuracy_informative")
        desc = (t("rpt.desc_accuracy_imbalanced", pct=_pct(ctx["accuracy"]),
                  share=_pct(b["attack_share"])) if imbalanced
                else t("rpt.desc_accuracy", pct=_pct(ctx["accuracy"])))
        items.append((t("rpt.metric_accuracy"), ctx["accuracy"], color, label, desc))
    if ctx["roc_auc"] is not None:
        color, label_key, clause_key = _auc_verdict(ctx["roc_auc"])
        items.append((t("rpt.metric_auc"), ctx["roc_auc"], color, t(label_key),
                      t(_AUC_DESC_KEYS.get(clause_key, "rpt.desc_auc"),
                        **_AUC_SCALE)))

    for name, value, color, label, desc in items:
        ch = _hexcolor_name(color)
        story.append(Paragraph(
            f"<b>{name}: <font color='{ch}'>{value:.4f}</font></b> "
            f"<font color='{ch}'>({label})</font>", styles["normal"]))
        story.append(Paragraph(desc, styles["cell"]))
        story.append(Spacer(1, 1.8*mm))


# ─── 5. Fitur Berpengaruh ─────────────────────────────────────────────────

def _section_5_fitur(story, styles, ctx):
    t = ctx["_t"]
    _section(story, styles, ctx, t("rpt.sec_features"))
    fi = ctx["feature_importance"]
    if not fi:
        story.append(Paragraph(
            t("rpt.fi_unavailable",
              algo=ctx["algorithm"] or t("rpt.fi_algo_fallback")),
            styles["italic"]))
        return

    story.append(Paragraph(t("rpt.fi_intro"), styles["normal"]))
    story.append(Spacer(1, 2*mm))
    try:
        fi_img = _render_feature_importance(fi, t)
        _figure(story, styles, ctx, fi_img, 14*cm, 8*cm,
                t("rpt.cap_feature_importance"))
    except Exception as e:
        story.append(Paragraph(t("rpt.err_render_fi", error=e),
                               styles["italic"]))

    story.append(Spacer(1, 1.5*mm))
    story.append(Paragraph(t("rpt.fi_meanings_heading"), styles["subsection"]))
    shown = 0
    for item in fi[:6]:
        name = item.get("feature")
        if not name:
            continue
        meaning = _feature_network_meaning(name, t) or t("rpt.feat_unmapped")
        story.append(Paragraph(f"<b>{name}</b> — {meaning}.", styles["cell"]))
        shown += 1
        if shown >= 5:
            break


# ─── 6. Diagnostik (ROC, learning curve / dual-holdout, per-class) ────────

def _section_6_diagnostik(story, styles, ctx):
    t = ctx["_t"]
    _section(story, styles, ctx, t("rpt.sec_diagnostics"))
    metrics = ctx["metrics"]
    rendered_any = False

    # ROC
    if ctx["roc_auc"] is not None or "roc_curve" in metrics:
        story.append(Paragraph(t("rpt.sub_roc"), styles["subsection"]))
        try:
            _figure(story, styles, ctx, _render_roc_curve(metrics, t),
                    11*cm, 9.2*cm, t("rpt.cap_roc"))
            rendered_any = True
        except Exception as e:
            story.append(Paragraph(t("rpt.err_render_roc", error=e),
                                   styles["italic"]))

    # Learning curve (HIKARI) OR dual-holdout comparison (EVE-cbr)
    if ctx["learning_curve"]:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("Learning Curve", styles["subsection"]))
        try:
            _figure(story, styles, ctx,
                    _render_learning_curve(ctx["learning_curve"]),
                    14*cm, 8.5*cm, t("rpt.cap_learning_curve"))
            rendered_any = True
        except Exception as e:
            story.append(Paragraph(t("rpt.err_render_lc", error=e),
                                   styles["italic"]))
    else:
        nat, bal = ctx["natural_holdout"], ctx["balanced_holdout"]
        if nat and bal:
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph(t("rpt.sub_dual_holdout"),
                                   styles["subsection"]))
            story.append(Paragraph(t("rpt.dual_holdout_intro"),
                                   styles["normal"]))
            labels = [("precision_attack", "Precision (attack)"), ("recall_attack", "Recall (attack)"),
                      ("f1_attack", "F1 (attack)"), ("auc", "AUC"), ("accuracy", "Accuracy")]
            data = [[t("rpt.col_metric"), "Natural-holdout",
                     "Balanced-holdout"]]
            for k, lab in labels:
                if k in nat or k in bal:
                    def _f(x):
                        return f"{x:.4f}" if isinstance(x, (int, float)) else "—"
                    data.append([lab, _f(nat.get(k)), _f(bal.get(k))])
            if len(data) > 1:
                _table_caption(story, styles, ctx, t("rpt.cap_dual_holdout"))
                story.append(_data_table(data, [5.6*cm, 5.5*cm, 5.5*cm], num_cols=[1, 2]))
                rendered_any = True

    # Per-class report (HIKARI)
    rep = ctx["classification_report"]
    class_rows = {k: v for k, v in rep.items() if isinstance(v, dict)} if rep else {}
    if class_rows:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(t("rpt.sub_per_class"), styles["subsection"]))
        data = [[t("rpt.col_class"), "Precision", "Recall", "F1-Score",
                 "Support"]]
        for cls, m in class_rows.items():
            data.append([cls, f"{m.get('precision', 0):.4f}", f"{m.get('recall', 0):.4f}",
                         f"{m.get('f1-score', 0):.4f}", str(int(m.get('support', 0)))])
        _table_caption(story, styles, ctx, t("rpt.cap_per_class"))
        story.append(_data_table(data, [4*cm, 2.9*cm, 2.9*cm, 2.9*cm, 2.9*cm], num_cols=[1, 2, 3, 4]))
        rendered_any = True

    if not rendered_any:
        story.append(Paragraph(t("rpt.no_extra_diagnostics"),
                               styles["italic"]))


# ─── 7. Catatan Metodologis ───────────────────────────────────────────────

def _section_7_metodologi(story, styles, ctx):
    t = ctx["_t"]
    _section(story, styles, ctx, t("rpt.sec_methodology"))
    notes = []
    if ctx["is_eve"]:
        notes.append(t("rpt.note_semantics_eve"))
        notes.append(t("rpt.note_label_origin_eve"))
        al = ctx["anti_leakage"]
        if al:
            # Potongan-potongan ini SEMUANYA dari katalog, jadi menggabungnya
            # tidak dapat mencampur bahasa.
            parts = []
            if al.get("group_split"):
                parts.append(t("rpt.leak_group_split", value=al["group_split"]))
            if al.get("pipeline_scaling"):
                parts.append(t("rpt.leak_pipeline_scaling"))
            if al.get("dual_holdout"):
                parts.append(t("rpt.leak_dual_holdout"))
            if al.get("forbidden_feature_guard"):
                parts.append(t("rpt.leak_forbidden_guard"))
            if parts:
                notes.append(t("rpt.note_antileak", parts="; ".join(parts)))
    else:
        notes.append(t("rpt.note_semantics_hikari"))
        notes.append(t("rpt.note_label_origin_hikari"))
        notes.append(t("rpt.note_antileak_hikari"))

    b = ctx["breakdown"]
    if b and b["attack_share"] is not None:
        notes.append(t("rpt.note_class_balance", share=_pct(b["attack_share"]),
                       attacks=_grp(b["attack_total"]),
                       normals=_grp(b["normal_total"])))

    for n in notes:
        story.append(Paragraph(f"• {n}", styles["normal"]))
        story.append(Spacer(1, 1.2*mm))

    algo = (ctx["algorithm"] or "").lower()
    if "svc" in algo or "svm" in algo:
        story.append(Paragraph("• " + t("rpt.note_svc_limit"), styles["note"]))
    if ctx["runtime_warning"]:
        story.append(Paragraph(f"• {ctx['runtime_warning']}", styles["note"]))


# ─── 8. Reproducibility ───────────────────────────────────────────────────

def _section_8_reproducibility(story, styles, ctx):
    t = ctx["_t"]
    na = t("rpt.na")
    _section(story, styles, ctx, t("rpt.sec_reproducibility"))
    story.append(Paragraph(t("rpt.repro_intro"), styles["normal"]))
    story.append(Spacer(1, 2*mm))
    # Seed dibaca dari parameter yang TERCATAT untuk run ini. Menuliskan "42"
    # apa adanya akan berbohong pada run eksplorasi yang mengubah seed —
    # justru pada baris yang menjadi dasar klaim dapat-diulang.
    seed = (ctx["params_used"] or {}).get("random_state")
    if seed is None:
        # Tidak tercatat: tampilkan nilai bawaan platform, tetap lewat kunci
        # yang sama supaya kalimatnya tidak bercabang.
        seed_text = t("rpt.seed_locked", seed=42)
    elif "random_state" in set(ctx["params_changed"] or []):
        base = (ctx["params_locked"] or {}).get("random_state", 42)
        seed_text = t("rpt.seed_adjusted", seed=seed, base=base)
    else:
        seed_text = t("rpt.seed_locked", seed=seed)

    rows = [
        ["Dataset SHA-256", ctx["dataset_hash"]],
        [t("rpt.lbl_seed"), seed_text],
        ["Python", _none_or(ctx["python_version"], na)],
        ["scikit-learn", _none_or(ctx["sklearn_version"], na)],
        ["pandas / numpy", f"{_none_or(ctx['pandas_version'], na)} / {_none_or(ctx['numpy_version'], na)}"],
        ["Platform", _none_or(ctx["platform_str"], na)],
        ["Docker", t("rpt.yes") if ctx["is_docker"]
         else (t("rpt.no") if ctx["is_docker"] is False
               else t("rpt.not_recorded"))],
    ]
    if ctx["wall_clock"]:
        rows.append([t("rpt.lbl_wall_clock"), ctx["wall_clock"]])
    story.append(_kv_table(styles, rows))
    story.append(Spacer(1, 1.5*mm))
    story.append(Paragraph(t("rpt.repro_how"), styles["note"]))
    if _run_mode.is_exploration(ctx["run_mode"]):
        # Run eksplorasi TETAP dapat diulang — parameternya tercatat — tetapi
        # bukan dasar klaim replikasi paper. Dua hal berbeda, dikatakan terpisah.
        story.append(Paragraph(t("rpt.repro_exploration"), styles["note"]))


# ─── Footer ───────────────────────────────────────────────────────────────

def _footer(story, styles, ctx):
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE))
    story.append(Paragraph(
        ctx["_t"]("rpt.footer",
                  time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                  experiment=ctx["experiment_id"]), styles["small_muted"]))


# ─── Chart render helpers (muted palette, no chartjunk) ───────────────────

def _render_network_confusion_matrix(b: dict, t) -> io.BytesIO:
    """Confusion matrix labeled in network terms, muted palette. Built from the
    breakdown dict. Layout rows=Aktual, cols=Prediksi, order [Normal, Serangan]."""
    an, nn = b["attack_name"], b["normal_name"]
    grid = np.array([[b["tn"], b["fp"]], [b["fn"], b["tp"]]], dtype=float)
    quad_labels = [[t("rpt.cm_tn"), t("rpt.cm_fp")],
                   [t("rpt.cm_fn"), t("rpt.cm_tp")]]
    cell_colors = [[_C_TNTP, _C_FP], [_C_FN, _C_TNTP]]

    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 2)
    ax.invert_yaxis()
    for i in range(2):
        for j in range(2):
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=cell_colors[i][j],
                                       edgecolor=_C_EDGE, linewidth=1.0))
            ax.text(j + 0.5, i + 0.34, f"{int(grid[i][j]):,}".replace(",", "."),
                    ha="center", va="center", fontsize=15, fontweight="bold", color=_C_TEXT)
            ax.text(j + 0.5, i + 0.66, quad_labels[i][j],
                    ha="center", va="center", fontsize=8.5, color="#555b63")
    ax.set_xticks([0.5, 1.5]); ax.set_yticks([0.5, 1.5])
    ax.set_xticklabels([t("rpt.cm_predicted", name=nn),
                        t("rpt.cm_predicted", name=an)],
                       fontsize=9, color=_C_TEXT)
    ax.set_yticklabels([t("rpt.cm_actual", name=nn),
                        t("rpt.cm_actual", name=an)],
                       fontsize=9, rotation=90, va="center", color=_C_TEXT)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    fig.tight_layout()
    return _save(fig)


def _render_roc_curve(metrics: dict, t) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(6, 5))
    if "roc_curve" in metrics:
        roc = metrics["roc_curve"]
        fpr, tpr = roc.get("fpr"), roc.get("tpr")
        if isinstance(fpr, list) and isinstance(tpr, list) and fpr and tpr:
            ax.plot(fpr, tpr, label=f"ROC (AUC = {metrics.get('roc_auc', 0):.4f})",
                    linewidth=2, color=_C_LINE)
        elif isinstance(fpr, dict):
            for cls_name in fpr:
                ax.plot(fpr[cls_name], tpr[cls_name], label=str(cls_name), linewidth=1.4)
    elif "roc_curves_per_class" in metrics:
        for cls_name, curve in metrics["roc_curves_per_class"].items():
            ax.plot(curve["fpr"], curve["tpr"], label=str(cls_name), linewidth=1.4)
    ax.plot([0, 1], [0, 1], linestyle="--", alpha=0.7, color=_C_DIAG,
            label=t("rpt.chart_random_guess"))
    ax.set_xlabel("False Positive Rate", color=_C_TEXT)
    ax.set_ylabel("True Positive Rate (Recall)", color=_C_TEXT)
    ax.set_title(t("rpt.chart_roc_title",
                   auc=f"{metrics.get('roc_auc', 0):.4f}"),
                 color=_C_TEXT, fontsize=11)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.tick_params(colors="#555b63")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(_C_EDGE)
    fig.tight_layout()
    return _save(fig)


def _render_feature_importance(feature_importance: list[dict], t) -> io.BytesIO:
    n_total = len(feature_importance)
    fi = feature_importance[:20]
    fig, ax = plt.subplots(figsize=(8, max(4, len(fi) * 0.3)))
    ax.barh([item["feature"] for item in reversed(fi)],
            [item["importance"] for item in reversed(fi)],
            color=_C_BAR, edgecolor=_C_EDGE, linewidth=0.4)
    ax.set_xlabel("Importance", color=_C_TEXT)
    title = (t("rpt.chart_fi_title_total", shown=len(fi), total=n_total)
             if n_total > len(fi)
             else t("rpt.chart_fi_title", shown=len(fi)))
    ax.set_title(title, color=_C_TEXT, fontsize=11)
    ax.tick_params(colors="#555b63")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(_C_EDGE)
    fig.tight_layout()
    return _save(fig)


def _render_learning_curve(lc: dict) -> io.BytesIO:
    train_sizes = lc["train_sizes"]
    train_mean = lc["train_scores_mean"]
    train_std = lc.get("train_scores_std", [0] * len(train_sizes))
    val_mean = lc.get("val_scores_mean", lc.get("test_scores_mean", []))
    val_std = lc.get("val_scores_std", [0] * len(train_sizes))
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.fill_between(train_sizes, [m - s for m, s in zip(train_mean, train_std)],
                    [m + s for m, s in zip(train_mean, train_std)], alpha=0.12, color=_C_LINE)
    if val_mean:
        ax.fill_between(train_sizes, [m - s for m, s in zip(val_mean, val_std)],
                        [m + s for m, s in zip(val_mean, val_std)], alpha=0.12, color=_C_LINE2)
    ax.plot(train_sizes, train_mean, 'o-', color=_C_LINE, label="Training", linewidth=1.8, markersize=4)
    if val_mean:
        ax.plot(train_sizes, val_mean, 'o-', color=_C_LINE2, label="Validation", linewidth=1.8, markersize=4)
    ax.set_xlabel("Training Set Size", color=_C_TEXT)
    ax.set_ylabel("F1 Score (Weighted)", color=_C_TEXT)
    ax.set_title("Learning Curve", color=_C_TEXT, fontsize=11)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.grid(True, alpha=0.18, color=_C_EDGE)
    ax.tick_params(colors="#555b63")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(_C_EDGE)
    fig.tight_layout()
    return _save(fig)


def _save(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf
