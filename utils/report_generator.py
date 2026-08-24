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


# ─── Network meaning of features (PRESERVED) ──────────────────────────────

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
    "interaction_bytes_rate_packet_rate": "interaksi antara laju byte dan laju paket per detik",
    "interaction_total_bytes_duration": "interaksi antara total byte dan durasi aliran",
    "interaction_total_pkts_duration": "interaksi antara total paket dan durasi aliran",
    "flow_duration": "durasi aliran (lama koneksi berlangsung)",
    "down_up_ratio": "rasio volume unduh terhadap unggah pada aliran",
    "fwd_subflow_bytes": "volume byte pada subflow arah maju (klien->server)",
    "bwd_subflow_bytes": "volume byte pada subflow arah balik (server->klien)",
    "fwd_init_window_size": "ukuran TCP receive window awal arah maju (kontrol aliran)",
    "bwd_init_window_size": "ukuran TCP receive window awal arah balik (kontrol aliran)",
}


def _feature_network_meaning(name: str) -> str | None:
    """Plain-Indonesian network meaning of a feature, derived from its name.
    Returns None when the name carries no recognizable network token."""
    if not name:
        return None
    key = str(name).lower()
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

    rules = [
        ("init_window", "ukuran TCP receive window awal (kontrol aliran)"),
        ("window_size", "ukuran TCP receive window (kontrol aliran)"),
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


def _none_or(v, fallback="[tidak tersedia]"):
    if v is None or v == "":
        return fallback
    return str(v)


def _hexcolor_name(c) -> str:
    return '#%02x%02x%02x' % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))


# ─── Masthead (title + identity + abstract) ───────────────────────────────

def _compose_abstract(ctx) -> str:
    """3–5 computed sentences (abstract-like). Never a blank template."""
    algo = ctx["algorithm"] or "Model machine learning"
    ds = "EVE/Suricata (trafik TLS)" if ctx["is_eve"] else (ctx["dataset_type"] or "dataset terpilih")
    sem = ("kelas serangan pada natural-holdout" if ctx["is_eve"]
           else "rata-rata berbobot (weighted) seluruh kelas")
    b = ctx["breakdown"]
    if b and b["attack_recall"] is not None:
        _, rlabel, _ = _recall_verdict(b["attack_recall"])
        f1 = b["attack_f1"]
        f1txt = f", dengan F1 kelas serangan {f1:.4f}" if isinstance(f1, (int, float)) else ""
        return (
            f"Eksperimen ini mengevaluasi algoritma {algo} sebagai <i>detection engine</i> pada "
            f"dataset {ds}. Dari {_grp(b['total'])} aliran uji ({_grp(b['attack_total'])} serangan "
            f"dan {_grp(b['normal_total'])} normal), model mendeteksi {_pct(b['attack_recall'])} "
            f"serangan ({_grp(b['tp'])} dari {_grp(b['attack_total'])}) dengan ketepatan alarm "
            f"{_pct(b['attack_precision'])}{f1txt}. Sebanyak {_grp(b['fn'])} serangan lolos tanpa "
            f"terdeteksi dan {_grp(b['fp'])} aliran normal salah ditandai sebagai serangan "
            f"(false alarm), menempatkan performa deteksi pada kategori “{rlabel}”. "
            f"Seluruh metrik dilaporkan sebagai {sem}; rincian dan catatan semantik disajikan pada "
            f"bagian-bagian berikut."
        )
    # Fallback when the confusion matrix is unavailable/non-binary.
    parts = []
    if isinstance(ctx["accuracy"], (int, float)):
        parts.append(f"accuracy {ctx['accuracy']:.4f}")
    if isinstance(ctx["f1_score"], (int, float)):
        parts.append(f"F1 {ctx['f1_score']:.4f}")
    if isinstance(ctx["roc_auc"], (int, float)):
        parts.append(f"AUC {ctx['roc_auc']:.4f}")
    metr = (", ".join(parts)) if parts else "metrik tersedia pada tabel hasil"
    return (
        f"Eksperimen ini mengevaluasi algoritma {algo} pada dataset {ds}. Metrik utama: {metr}. "
        f"Confusion matrix biner tidak tersedia sehingga interpretasi operasional (serangan "
        f"terdeteksi/lolos, false alarm) tidak dapat dihitung; metrik dilaporkan sebagai {sem}."
    )


def _masthead(story, styles, ctx):
    story.append(Paragraph("Laporan Eksperimen Deteksi Intrusi", styles["title"]))
    story.append(Paragraph(
        "IDS Research Pipeline Execution System &mdash; artefak penelitian yang reproducible",
        styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1.0, color=_HEAD, spaceAfter=3*mm))

    story.append(_kv_table(styles, [
        ["Experiment ID", _none_or(ctx["experiment_id"])],
        ["Pipeline", _none_or(ctx["pipeline_id"])],
        ["Algoritma", _none_or(ctx["algorithm"])],
        ["Dataset", _none_or(ctx["dataset_type"])],
        ["Waktu (dibuat → selesai)", f"{_none_or(ctx['created_at'])} → {_none_or(ctx['completed_at'])}"],
        ["Mode eksekusi", _run_mode.RUN_MODE_LABELS[ctx["run_mode"]]
         + " — " + _run_mode.RUN_MODE_HINTS[ctx["run_mode"]]],
    ]))

    # Penanda run eksplorasi di HALAMAN PERTAMA, sebelum satu angka pun
    # terbaca — laporan ini bisa beredar terpisah dari aplikasi.
    if _run_mode.is_exploration(ctx["run_mode"]):
        story.append(Spacer(1, 2*mm))
        story.append(_callout(
            "<b>Run eksplorasi.</b> " + _run_mode.EXPLORATION_WARNING,
            styles, fill=colors.HexColor("#fff4e5"),
            border=colors.HexColor("#e8a33d")))

    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("Abstrak", styles["abstract_h"]))
    story.append(Paragraph(_compose_abstract(ctx), styles["abstract"]))


# ─── 1. Konfigurasi Eksperimen ────────────────────────────────────────────

def _section_1_konfigurasi(story, styles, ctx):
    _section(story, styles, ctx, "Konfigurasi Eksperimen")

    if ctx["is_eve"]:
        fmt = "NDJSON (catatan EVE Suricata, satu objek JSON per baris)"
        label_origin = ("turunan alert Suricata pada trafik TLS (disempurnakan konservatif) "
                        "— bukan ground-truth eksternal")
    else:
        fmt = "CSV (fitur flow ALLFLOWMETER yang sudah diekstraksi)"
        label_origin = "ground-truth bawaan HIKARI2021 (benign vs malicious)"

    rows = [
        ["Algoritma", _none_or(ctx["algorithm"])],
        ["Rujukan (paper)", _none_or(ctx["paper"])],
        ["Format dataset", fmt],
        ["Asal label", label_origin],
        ["Berkas sumber", _none_or(ctx["dataset_path"])],
    ]
    if ctx["feature_selection"]:
        rows.append(["Feature selection", str(ctx["feature_selection"])])
    b = ctx["breakdown"]
    if b:
        rows.append(["Distribusi kelas (data uji)",
                     f"{_grp(b['total'])} aliran — serangan {_grp(b['attack_total'])} "
                     f"({_pct(b['attack_share'])}) / normal {_grp(b['normal_total'])}"])
    story.append(_kv_table(styles, rows))

    steps = ctx["preprocessing_steps"]
    if steps:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("Praproses:", styles["subsection"]))
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
            heading = ("Hyperparameter yang dipakai run ini, disertai split & seed:"
                       if not changed else
                       "Hyperparameter yang dipakai run ini (tanda * = berbeda "
                       "dari nilai terkunci):")
            caption = ("Parameter tercatat saat eksperimen berjalan."
                       if not changed else
                       "Parameter tercatat saat eksperimen berjalan; nilai bertanda * "
                       "disesuaikan pengguna pada run eksplorasi, sehingga hasil ini "
                       "TIDAK sebanding dengan run resmi.")
            header = ["Parameter", "Nilai", "Nilai terkunci"]
            rows_cfg = []
            for k, v in cfg.items():
                mark = "*" if k in changed else ""
                base = locked_cfg.get(k, "—")
                rows_cfg.append([f"{k}{mark}", str(v),
                                 str(base) if k in changed else "sama"])
            data = [header] + rows_cfg
            widths = [5.6*cm, 5.5*cm, 5.5*cm]
        else:
            heading = "Hyperparameter terkunci (paper-faithful), disertai split & seed:"
            caption = ("Konfigurasi terkunci pipeline, dibaca dari definisi pipeline "
                       "pada kode saat ini — eksperimen ini dijalankan sebelum "
                       "parameter dicatat per run.")
            data = [["Parameter", "Nilai"]] + [[str(k), str(v)] for k, v in cfg.items()]
            widths = [7*cm, 9.6*cm]
        story.append(Paragraph(heading, styles["subsection"]))
        _table_caption(story, styles, ctx, caption)
        story.append(_data_table(data, widths))


# ─── 2. Hasil dan Metrik ──────────────────────────────────────────────────

def _section_2_hasil(story, styles, ctx):
    _section(story, styles, ctx, "Hasil dan Metrik")

    _avg = "kelas attack, natural-holdout" if ctx["is_eve"] else "weighted"

    def _fmt(v):
        return f"{v:.6f}" if isinstance(v, (int, float)) else "[tidak tersedia]"

    data = [["Metrik", "Nilai", "Cakupan"]]
    data += [
        ["Accuracy", _fmt(ctx["accuracy"]), "seluruh kelas"],
        ["Precision", _fmt(ctx["precision"]), _avg],
        ["Recall", _fmt(ctx["recall"]), _avg],
        ["F1-score", _fmt(ctx["f1_score"]), _avg],
    ]
    if ctx["roc_auc"] is not None:
        data.append(["ROC-AUC", _fmt(ctx["roc_auc"]), "biner"])

    _table_caption(story, styles, ctx, "Metrik performa utama eksperimen.")
    story.append(_data_table(data, [5.2*cm, 5.4*cm, 6*cm], num_cols=[1]))

    # Mandatory metric-semantics footnote (family-aware; never conflated).
    if ctx["is_eve"]:
        foot = ("<b>Catatan semantik metrik.</b> Precision/Recall/F1 di atas adalah metrik "
                "<b>kelas attack pada natural-holdout</b> (distribusi kelas asli), <i>bukan</i> "
                "rata-rata berbobot. Dipilih agar jujur terhadap kelas minoritas (serangan).")
    else:
        foot = ("<b>Catatan semantik metrik.</b> Precision/Recall/F1 di atas adalah "
                "<b>rata-rata berbobot (weighted)</b> seluruh kelas, <i>bukan</i> kelas attack "
                "natural-holdout seperti pada pipeline EVE-cbr. Untuk fokus kelas serangan, lihat "
                "Interpretasi Keamanan (kuadran) dan Per-Class Report.")
    story.append(Spacer(1, 1.5*mm))
    story.append(Paragraph(foot, styles["note"]))


# ─── 3. Interpretasi Keamanan (dihitung dari confusion matrix) ────────────

def _section_3_keamanan(story, styles, ctx):
    _section(story, styles, ctx, "Interpretasi Keamanan")

    b = ctx["breakdown"]
    if not b:
        story.append(Paragraph(
            "Confusion matrix tidak tersedia atau bukan biner, sehingga hasil tidak dapat "
            "diterjemahkan ke kuadran operasional.", styles["italic"]))
        return

    an, nn = b["attack_name"], b["normal_name"]
    story.append(Paragraph(
        f"Empat kuadran berikut diterjemahkan langsung dari confusion matrix (kelas positif = "
        f"{an}). Tiap angka adalah jumlah aliran nyata pada data uji.", styles["normal"]))
    story.append(Spacer(1, 2*mm))

    quad = [
        ["Kategori", "Jumlah", "Arti operasional"],
        ["Serangan terdeteksi (TP)", _grp(b["tp"]),
         Paragraph(f"{an} yang berhasil dikenali model — deteksi yang benar.", styles["cell"])],
        ["Serangan LOLOS (FN)", _grp(b["fn"]),
         Paragraph(f"{an} yang TIDAK terdeteksi (dianggap {nn}) — risiko keamanan paling kritis.", styles["cell"])],
        ["False alarm (FP)", _grp(b["fp"]),
         Paragraph(f"{nn} salah ditandai sebagai serangan — membebani analis (alert fatigue).", styles["cell"])],
        ["Normal benar (TN)", _grp(b["tn"]),
         Paragraph(f"{nn} yang benar dibiarkan lewat — tidak mengganggu operasi.", styles["cell"])],
    ]
    _table_caption(story, styles, ctx, "Kuadran deteksi operasional (dihitung dari confusion matrix).")
    story.append(_data_table(
        quad, [4.6*cm, 2.2*cm, 9.8*cm], num_cols=[1],
        highlight_rows={2: _CRIT_FILL, 3: _WARN_FILL},
    ))

    # Computed security sentence.
    story.append(Spacer(1, 2.5*mm))
    story.append(Paragraph(
        f"Secara operasional, model <b>melewatkan {_grp(b['fn'])} serangan dari "
        f"{_grp(b['attack_total'])}</b> (tingkat deteksi {_pct(b['attack_recall'])}) dan "
        f"<b>menandai {_grp(b['fp'])} lalu lintas benign sebagai serangan</b> "
        f"(false positive rate {_pct(b['fp_rate'])}).", styles["normal"]))

    story.append(Spacer(1, 2*mm))
    if b["attack_total"]:
        miss_pct = b["fn"] / b["attack_total"]
        story.append(_callout(
            f"<b><font color='{_hexcolor_name(_CRIT)}'>Serangan lolos (paling kritis):</font></b> "
            f"{_grp(b['fn'])} dari {_grp(b['attack_total'])} serangan ({_pct(miss_pct)}) tidak "
            f"terdeteksi dan melewati sistem tanpa alarm.",
            styles, fill=_CRIT_FILL, border=_CRIT))
    if b["normal_total"] and b["fp_rate"] is not None:
        story.append(Spacer(1, 1.5*mm))
        story.append(_callout(
            f"<b><font color='{_hexcolor_name(_WARN)}'>Beban false alarm:</font></b> "
            f"{_grp(b['fp'])} dari {_grp(b['normal_total'])} aliran normal ({_pct(b['fp_rate'])}) "
            f"memicu alarm palsu — biaya investigasi bagi analis.",
            styles, fill=_WARN_FILL, border=_WARN))

    story.append(Spacer(1, 3*mm))
    try:
        cm_img = _render_network_confusion_matrix(b)
        _figure(story, styles, ctx, cm_img, 11*cm, 9.2*cm,
                "Confusion matrix dalam istilah jaringan (hijau = benar, amber = false alarm, "
                "merah = serangan lolos).")
    except Exception as e:
        story.append(Paragraph(f"<i>Gagal merender confusion matrix: {e}</i>", styles["italic"]))


# ─── 4. Analisis Metrik (verdict per metrik, dihitung) ────────────────────

def _section_4_analisis(story, styles, ctx):
    _section(story, styles, ctx, "Analisis Metrik")
    b = ctx["breakdown"]

    if b:
        recall_val, precision_val, f1_val = b["attack_recall"], b["attack_precision"], b["attack_f1"]
        story.append(Paragraph(
            "Recall, Precision, dan F1 berikut ditinjau untuk <b>kelas serangan</b> (paling relevan "
            "secara operasional), dihitung langsung dari confusion matrix.", styles["normal"]))
    else:
        recall_val, precision_val, f1_val = ctx["recall"], ctx["precision"], ctx["f1_score"]
        story.append(Paragraph("Nilai metrik diambil apa adanya dari hasil eksperimen.", styles["normal"]))
    story.append(Spacer(1, 1.5*mm))

    items = []
    if recall_val is not None:
        color, label, _ = _recall_verdict(recall_val)
        extra = f" Artinya {_grp(b['fn'])} dari {_grp(b['attack_total'])} serangan lolos." if b else ""
        items.append(("Recall (tingkat deteksi serangan)", recall_val, color, label,
                      f"Dari semua serangan yang ada, {_pct(recall_val)} terdeteksi (sisanya lolos).{extra}"))
    if precision_val is not None:
        color, label, _ = _precision_verdict(precision_val)
        extra = f" Dari {_grp(b['pred_attack'])} alarm, {_grp(b['fp'])} adalah false alarm." if b else ""
        items.append(("Precision (ketepatan alarm)", precision_val, color, label,
                      f"Dari semua yang ditandai serangan, {_pct(precision_val)} benar-benar serangan.{extra}"))
    if f1_val is not None:
        color, label, clause = _f1_verdict(f1_val)
        items.append(("F1-score (keseimbangan)", f1_val, color, label,
                      f"Keseimbangan antara tidak meloloskan serangan dan tidak membuat false alarm. {clause.capitalize()}."))
    if ctx["accuracy"] is not None:
        imbalanced = bool(b and b["imbalance_ratio"] and b["imbalance_ratio"] >= 1.5)
        color = _WARN if imbalanced else _GOOD
        label = "baca dengan hati-hati" if imbalanced else "informatif"
        desc = f"Proporsi seluruh prediksi yang benar ({_pct(ctx['accuracy'])})."
        if imbalanced:
            desc += (f" Perhatian: data timpang (serangan hanya {_pct(b['attack_share'])} dari total), "
                     f"accuracy dapat terlihat tinggi meski sebagian serangan lolos — utamakan Recall & Precision.")
        items.append(("Accuracy (akurasi keseluruhan)", ctx["accuracy"], color, label, desc))
    if ctx["roc_auc"] is not None:
        color, label, clause = _auc_verdict(ctx["roc_auc"])
        items.append(("ROC-AUC (daya pisah)", ctx["roc_auc"], color, label,
                      f"Kemampuan memisahkan serangan dari trafik normal (1,0 = sempurna; 0,5 = tebak acak). {clause.capitalize()}."))

    for name, value, color, label, desc in items:
        ch = _hexcolor_name(color)
        story.append(Paragraph(
            f"<b>{name}: <font color='{ch}'>{value:.4f}</font></b> "
            f"<font color='{ch}'>({label})</font>", styles["normal"]))
        story.append(Paragraph(desc, styles["cell"]))
        story.append(Spacer(1, 1.8*mm))


# ─── 5. Fitur Berpengaruh ─────────────────────────────────────────────────

def _section_5_fitur(story, styles, ctx):
    _section(story, styles, ctx, "Fitur Berpengaruh")
    fi = ctx["feature_importance"]
    if not fi:
        story.append(Paragraph(
            f"Algoritma {ctx['algorithm'] or 'ini'} tidak menghasilkan skor kepentingan fitur "
            "(feature importance) yang dapat dipetakan ke fitur jaringan asli (mis. K-Nearest "
            "Neighbors atau Gaussian Naive Bayes); bagian ini dilewati tanpa grafik kosong.",
            styles["italic"]))
        return

    story.append(Paragraph(
        "Fitur berikut paling menentukan keputusan model — menunjukkan sinyal trafik yang paling "
        "membedakan serangan dari trafik normal.", styles["normal"]))
    story.append(Spacer(1, 2*mm))
    try:
        fi_img = _render_feature_importance(fi)
        _figure(story, styles, ctx, fi_img, 14*cm, 8*cm,
                "Kepentingan fitur (top-N); nilai diambil apa adanya dari metrics.json.")
    except Exception as e:
        story.append(Paragraph(f"<i>Gagal merender feature importance: {e}</i>", styles["italic"]))

    story.append(Spacer(1, 1.5*mm))
    story.append(Paragraph("Arti fitur teratas dalam istilah jaringan:", styles["subsection"]))
    shown = 0
    for item in fi[:6]:
        name = item.get("feature")
        if not name:
            continue
        meaning = _feature_network_meaning(name)
        if meaning:
            story.append(Paragraph(f"<b>{name}</b> — {meaning}.", styles["cell"]))
        else:
            story.append(Paragraph(
                f"<b>{name}</b> — statistik aliran jaringan (makna spesifik tidak dipetakan).",
                styles["cell"]))
        shown += 1
        if shown >= 5:
            break


# ─── 6. Diagnostik (ROC, learning curve / dual-holdout, per-class) ────────

def _section_6_diagnostik(story, styles, ctx):
    _section(story, styles, ctx, "Diagnostik")
    metrics = ctx["metrics"]
    rendered_any = False

    # ROC
    if ctx["roc_auc"] is not None or "roc_curve" in metrics:
        story.append(Paragraph("Kurva ROC", styles["subsection"]))
        try:
            _figure(story, styles, ctx, _render_roc_curve(metrics), 11*cm, 9.2*cm,
                    "Kurva ROC; garis diagonal = tebakan acak. Semakin menjauhi diagonal, semakin baik.")
            rendered_any = True
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender ROC curve: {e}</i>", styles["italic"]))

    # Learning curve (HIKARI) OR dual-holdout comparison (EVE-cbr)
    if ctx["learning_curve"]:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("Learning Curve", styles["subsection"]))
        try:
            _figure(story, styles, ctx, _render_learning_curve(ctx["learning_curve"]), 14*cm, 8.5*cm,
                    "Learning curve (skor training vs validation terhadap ukuran data latih).")
            rendered_any = True
        except Exception as e:
            story.append(Paragraph(f"<i>Gagal merender learning curve: {e}</i>", styles["italic"]))
    else:
        nat, bal = ctx["natural_holdout"], ctx["balanced_holdout"]
        if nat and bal:
            story.append(Spacer(1, 2*mm))
            story.append(Paragraph("Evaluasi Dual-Holdout (pengganti learning curve)", styles["subsection"]))
            story.append(Paragraph(
                "Pipeline EVE-cbr tidak menghasilkan learning curve; sebagai gantinya dilaporkan "
                "dua holdout: <b>natural</b> (distribusi asli — metrik yang dilaporkan) dan "
                "<b>balanced</b> (kelas diseimbangkan, pembanding separabilitas).", styles["normal"]))
            labels = [("precision_attack", "Precision (attack)"), ("recall_attack", "Recall (attack)"),
                      ("f1_attack", "F1 (attack)"), ("auc", "AUC"), ("accuracy", "Accuracy")]
            data = [["Metrik", "Natural-holdout", "Balanced-holdout"]]
            for k, lab in labels:
                if k in nat or k in bal:
                    def _f(x):
                        return f"{x:.4f}" if isinstance(x, (int, float)) else "—"
                    data.append([lab, _f(nat.get(k)), _f(bal.get(k))])
            if len(data) > 1:
                _table_caption(story, styles, ctx,
                               "Perbandingan natural- vs balanced-holdout (metrik dilaporkan = natural).")
                story.append(_data_table(data, [5.6*cm, 5.5*cm, 5.5*cm], num_cols=[1, 2]))
                rendered_any = True

    # Per-class report (HIKARI)
    rep = ctx["classification_report"]
    class_rows = {k: v for k, v in rep.items() if isinstance(v, dict)} if rep else {}
    if class_rows:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("Laporan Per-Kelas", styles["subsection"]))
        data = [["Kelas", "Precision", "Recall", "F1-Score", "Support"]]
        for cls, m in class_rows.items():
            data.append([cls, f"{m.get('precision', 0):.4f}", f"{m.get('recall', 0):.4f}",
                         f"{m.get('f1-score', 0):.4f}", str(int(m.get('support', 0)))])
        _table_caption(story, styles, ctx, "Metrik precision/recall/F1 per kelas (HIKARI).")
        story.append(_data_table(data, [4*cm, 2.9*cm, 2.9*cm, 2.9*cm, 2.9*cm], num_cols=[1, 2, 3, 4]))
        rendered_any = True

    if not rendered_any:
        story.append(Paragraph("Tidak ada diagnostik grafik tambahan yang tersedia untuk eksperimen ini.",
                               styles["italic"]))


# ─── 7. Catatan Metodologis ───────────────────────────────────────────────

def _section_7_metodologi(story, styles, ctx):
    _section(story, styles, ctx, "Catatan Metodologis")
    notes = []
    if ctx["is_eve"]:
        notes.append("Semantik metrik: precision/recall/F1 dihitung untuk <b>kelas serangan</b> pada "
                     "<b>natural-holdout</b> (distribusi asli) — bukan rata-rata berbobot.")
        notes.append("Asal label: diturunkan dari <b>alert Suricata</b> (disempurnakan konservatif) — "
                     "bukan kebenaran lapangan eksternal; hasil dibaca sebagai kesepakatan model terhadap alert.")
        al = ctx["anti_leakage"]
        if al:
            parts = []
            if al.get("group_split"):
                parts.append(f"pemisahan berbasis grup ({al['group_split']})")
            if al.get("pipeline_scaling"):
                parts.append("penskalaan di dalam pipeline (tanpa kebocoran ke data uji)")
            if al.get("dual_holdout"):
                parts.append("dual holdout: natural (utama) + balanced (sekunder)")
            if al.get("forbidden_feature_guard"):
                parts.append("penjaga fitur terlarang (kolom pembocor label diblokir)")
            if parts:
                notes.append("Anti-kebocoran: " + "; ".join(parts) + ".")
    else:
        notes.append("Semantik metrik: precision/recall/F1 headline adalah <b>rata-rata berbobot "
                     "(weighted)</b> antar kelas — berbeda dari EVE-cbr yang memakai kelas attack natural-holdout.")
        notes.append("Asal label: <b>ground-truth</b> bawaan HIKARI2021 (benign vs malicious).")
        notes.append("Anti-kebocoran: scaler/PCA/penyeimbang di-<i>fit</i> hanya pada data latih setelah "
                     "split, lalu diterapkan ke data uji.")

    b = ctx["breakdown"]
    if b and b["attack_share"] is not None:
        notes.append(f"Keseimbangan kelas (data uji): serangan {_pct(b['attack_share'])} dari total "
                     f"({_grp(b['attack_total'])} vs {_grp(b['normal_total'])} normal); pada data timpang "
                     "accuracy tunggal dapat menyesatkan.")

    for n in notes:
        story.append(Paragraph(f"• {n}", styles["normal"]))
        story.append(Spacer(1, 1.2*mm))

    algo = (ctx["algorithm"] or "").lower()
    if "svc" in algo or "svm" in algo:
        story.append(Paragraph(
            "• Keterbatasan algoritma: Support Vector Classifier berskala O(n²) dan lambat pada "
            "data ratusan ribu baris.", styles["note"]))
    if ctx["runtime_warning"]:
        story.append(Paragraph(f"• {ctx['runtime_warning']}", styles["note"]))


# ─── 8. Reproducibility ───────────────────────────────────────────────────

def _section_8_reproducibility(story, styles, ctx):
    _section(story, styles, ctx, "Reproducibility")
    story.append(Paragraph(
        "Selama hash dataset, kode pipeline, dan environment sama, metrik yang dihasilkan identik "
        "antar eksekusi — dasar klaim reproducibility artefak penelitian ini.", styles["normal"]))
    story.append(Spacer(1, 2*mm))
    # Seed dibaca dari parameter yang TERCATAT untuk run ini. Menuliskan "42"
    # apa adanya akan berbohong pada run eksplorasi yang mengubah seed —
    # justru pada baris yang menjadi dasar klaim dapat-diulang.
    seed = (ctx["params_used"] or {}).get("random_state")
    if seed is None:
        seed_text = "42 (terkunci untuk seluruh operasi stokastik)"
    elif "random_state" in set(ctx["params_changed"] or []):
        base = (ctx["params_locked"] or {}).get("random_state", 42)
        seed_text = f"{seed} (disesuaikan pada run eksplorasi; nilai terkunci {base})"
    else:
        seed_text = f"{seed} (terkunci untuk seluruh operasi stokastik)"

    rows = [
        ["Dataset SHA-256", ctx["dataset_hash"]],
        ["random_state / seed", seed_text],
        ["Python", _none_or(ctx["python_version"])],
        ["scikit-learn", _none_or(ctx["sklearn_version"])],
        ["pandas / numpy", f"{_none_or(ctx['pandas_version'])} / {_none_or(ctx['numpy_version'])}"],
        ["Platform", _none_or(ctx["platform_str"])],
        ["Docker", "Ya" if ctx["is_docker"] else ("Tidak" if ctx["is_docker"] is False else "[tidak tercatat]")],
    ]
    if ctx["wall_clock"]:
        rows.append(["Wall-clock (queue + eksekusi)", ctx["wall_clock"]])
    story.append(_kv_table(styles, rows))
    story.append(Spacer(1, 1.5*mm))
    story.append(Paragraph(
        "Untuk membuktikan reproducibility: jalankan pipeline yang sama dua kali pada dataset yang "
        "sama; nilai metrik (accuracy/precision/recall/F1/AUC) harus identik dan hash dataset sama.",
        styles["note"]))
    if _run_mode.is_exploration(ctx["run_mode"]):
        # Run eksplorasi TETAP dapat diulang — parameternya tercatat — tetapi
        # bukan dasar klaim replikasi paper. Dua hal berbeda, dikatakan terpisah.
        story.append(Paragraph(
            "Eksperimen ini adalah <b>run eksplorasi</b>: dapat diulang dengan parameter yang "
            "tercantum pada Tabel Konfigurasi, tetapi TIDAK dipakai sebagai dasar replikasi "
            "paper rujukan maupun perbandingan resmi antar pipeline.",
            styles["note"]))


# ─── Footer ───────────────────────────────────────────────────────────────

def _footer(story, styles, ctx):
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE))
    story.append(Paragraph(
        f"Dihasilkan oleh IDS Research Pipeline System &middot; "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} &middot; "
        f"experiment {ctx['experiment_id']}", styles["small_muted"]))


# ─── Chart render helpers (muted palette, no chartjunk) ───────────────────

def _render_network_confusion_matrix(b: dict) -> io.BytesIO:
    """Confusion matrix labeled in network terms, muted palette. Built from the
    breakdown dict. Layout rows=Aktual, cols=Prediksi, order [Normal, Serangan]."""
    an, nn = b["attack_name"], b["normal_name"]
    grid = np.array([[b["tn"], b["fp"]], [b["fn"], b["tp"]]], dtype=float)
    quad_labels = [["Normal benar\n(TN)", "False alarm\n(FP)"],
                   ["Serangan LOLOS\n(FN)", "Serangan terdeteksi\n(TP)"]]
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
    ax.set_xticklabels([f"Prediksi: {nn}", f"Prediksi: {an}"], fontsize=9, color=_C_TEXT)
    ax.set_yticklabels([f"Aktual: {nn}", f"Aktual: {an}"], fontsize=9, rotation=90, va="center", color=_C_TEXT)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    fig.tight_layout()
    return _save(fig)


def _render_roc_curve(metrics: dict) -> io.BytesIO:
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
    ax.plot([0, 1], [0, 1], linestyle="--", alpha=0.7, color=_C_DIAG, label="Tebak acak")
    ax.set_xlabel("False Positive Rate", color=_C_TEXT)
    ax.set_ylabel("True Positive Rate (Recall)", color=_C_TEXT)
    ax.set_title(f"Kurva ROC (AUC = {metrics.get('roc_auc', 0):.4f})", color=_C_TEXT, fontsize=11)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.tick_params(colors="#555b63")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(_C_EDGE)
    fig.tight_layout()
    return _save(fig)


def _render_feature_importance(feature_importance: list[dict]) -> io.BytesIO:
    n_total = len(feature_importance)
    fi = feature_importance[:20]
    fig, ax = plt.subplots(figsize=(8, max(4, len(fi) * 0.3)))
    ax.barh([item["feature"] for item in reversed(fi)],
            [item["importance"] for item in reversed(fi)],
            color=_C_BAR, edgecolor=_C_EDGE, linewidth=0.4)
    ax.set_xlabel("Importance", color=_C_TEXT)
    title = f"Top {len(fi)} Feature Importance"
    if n_total > len(fi):
        title += f" (dari {n_total} fitur)"
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
