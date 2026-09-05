"""
Penutup rangkaian dua bahasa — apa yang tidak boleh rusak lagi.

Berkas ini menjaga hal-hal yang baru saja diperbaiki, terutama satu cacat yang
sempat lolos: kalimat penjelas ditanam sebagai teks Indonesia lalu DISAMBUNG
dengan klausa penilaian yang berasal dari katalog, sehingga satu kalimat pada
laporan Inggris memuat dua bahasa sekaligus.

Yang dijaga di sini:

* tidak ada kalimat laporan yang bercampur dua bahasa — khususnya catatan kaki
  Recall, Precision, F1, dan ROC-AUC yang berpola sama;
* penanda nilai kosong mengikuti bahasa aktif, bukan tertanam;
* seluruh pesan validator punya entri di kedua bahasa, sementara KEPUTUSANNYA
  (nama, status, nomor baris) tetap identik;
* rumusan wajib tidak melemah pada bahasa mana pun;
* judul kolom tetap muat pada lebar kolomnya.
"""
import re
from pathlib import Path

import pytest

import ui.i18n.core as core
from ui.i18n import CATALOG
from ui.i18n.core import lookup

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Kata FUNGSI Indonesia. Sengaja bukan istilah teknis: "dataset", "pipeline",
#: "false alarm", dan "detection engine" memang dipakai apa adanya di dalam
#: kalimat Indonesia, jadi memasukkannya akan menuduh teks yang sudah benar.
INDONESIAN = {
    "yang", "tidak", "belum", "dapat", "untuk", "dengan", "pada", "dari",
    "akan", "sudah", "harus", "adalah", "atau", "dan", "agar", "bila",
    "karena", "sebagai", "seluruh", "setiap", "hanya", "juga", "ini", "itu",
    "lebih", "masih", "tetap", "saat", "oleh", "ada", "berkas", "pengguna",
    "eksperimen", "serangan", "aliran", "kelas", "nilai", "hasil",
}
#: Kata FUNGSI Inggris, dengan alasan yang sama dari arah sebaliknya.
ENGLISH = {
    "the", "and", "with", "that", "were", "was", "are", "from", "this",
    "those", "these", "their", "its", "not", "but", "they", "them", "than",
    "when", "which", "while", "have", "has", "been", "being", "every", "of",
}

_TAG = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[A-Za-z]+")


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(_TAG.sub(" ", text or ""))}


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── Tidak ada kalimat dua bahasa ─────────────────────────────────────────

#: Catatan kaki keempat metrik yang dulu dirakit dari dua sumber.
METRIC_DESC_KEYS = [
    "rpt.desc_recall", "rpt.desc_recall_detail",
    "rpt.desc_precision", "rpt.desc_precision_detail",
    "rpt.desc_f1", "rpt.desc_f1_excellent", "rpt.desc_f1_good",
    "rpt.desc_f1_attention", "rpt.desc_f1_weak",
    "rpt.desc_accuracy", "rpt.desc_accuracy_imbalanced",
    "rpt.desc_auc", "rpt.desc_auc_excellent", "rpt.desc_auc_good",
    "rpt.desc_auc_attention", "rpt.desc_auc_weak",
]


@pytest.mark.parametrize("key", METRIC_DESC_KEYS)
def test_a_metric_footnote_is_one_whole_sentence_per_language(key):
    """Kalimatnya UTUH per bahasa, bukan potongan yang disambung.

    Ini test inti berkas ini: versi lama menyambung f-string Indonesia dengan
    klausa penilaian dari katalog, sehingga laporan Inggris memuat kalimat
    seperti "Keseimbangan antara … The balance … is very good."
    """
    assert key in CATALOG, key
    english = _words(CATALOG[key]["en"])
    assert not english & INDONESIAN, (key, sorted(english & INDONESIAN))


def test_the_verdict_clause_is_never_appended_to_embedded_text():
    """Tidak ada lagi penyambungan klausa penilaian di modul laporan."""
    src = (REPO_ROOT / "utils" / "report_generator.py").read_text(
        encoding="utf-8")
    # `.capitalize()` dulu dipakai untuk menempelkan klausa ke ujung kalimat
    # Indonesia; ia juga akan merusak huruf besar istilah metrik.
    assert "clause.capitalize()" not in src
    # Kalimat penjelasnya tidak lagi ditanam sebagai f-string.
    assert "Keseimbangan antara tidak meloloskan serangan" not in src
    assert "Kemampuan memisahkan serangan dari trafik normal (1,0" not in src


def test_every_report_sentence_stays_in_one_language():
    """Tidak satu pun entri laporan memuat kata fungsi dari kedua bahasa."""
    mixed = []
    for key, entry in CATALOG.items():
        if not key.startswith("rpt."):
            continue
        english = _words(entry["en"])
        if len(english & INDONESIAN) >= 2 and len(english & ENGLISH) >= 2:
            mixed.append(key)
    assert not mixed, mixed


# ── Penanda nilai kosong ─────────────────────────────────────────────────

def test_the_empty_value_marker_follows_the_language():
    assert lookup("rpt.na", "id") == "[tidak tersedia]"
    assert lookup("rpt.na", "en") == "[not available]"


def test_the_empty_value_marker_has_no_indonesian_default():
    """Bawaan berbahasa akan bocor ke SETIAP sel kosong tanpa terlihat."""
    src = (REPO_ROOT / "utils" / "report_generator.py").read_text(
        encoding="utf-8")
    assert 'def _none_or(v, fallback):' in src
    assert 'fallback="[tidak tersedia]"' not in src


# ── Validator: seluruh pesan punya entri, keputusan tetap ────────────────

def _validator_checks():
    """Seluruh pemeriksaan dari berkas pipeline NYATA di repositori."""
    from orchestrator.pipeline_validator import validate_pipeline_file

    checks = []
    for path in sorted((REPO_ROOT / "pipelines").rglob("*.py")):
        try:
            report = validate_pipeline_file(str(path))
        except Exception:                     # berkas pendukung, bukan pipeline
            continue
        checks.extend(getattr(report, "checks", []) or [])
    return checks


def test_every_validator_message_has_an_entry_in_both_languages():
    """Dihitung, bukan diasumsikan: berapa pesan, berapa yang punya entri."""
    checks = _validator_checks()
    assert checks, "tidak ada pemeriksaan yang terkumpul"

    without_key = [c.name for c in checks if not getattr(c, "key", "")]
    assert not without_key, sorted(set(without_key))

    incomplete = [c.key for c in checks
                  if c.key not in CATALOG
                  or not CATALOG[c.key].get("id")
                  or not CATALOG[c.key].get("en")]
    assert not incomplete, sorted(set(incomplete))


def test_no_validator_message_is_still_indonesian_in_english():
    from ui.components.validator_messages import check_message

    core.st.session_state[core.LANG_KEY] = "en"
    left = {m for m in (check_message(c) for c in _validator_checks())
            if len(_words(m) & INDONESIAN) >= 2}
    assert not left, sorted(left)


def test_the_validator_decisions_are_identical_in_both_languages():
    """Bahasa mengubah KALIMAT, tidak pernah lolos/gagal maupun nomor baris."""
    core.st.session_state[core.LANG_KEY] = "id"
    indonesian = [(c.name, c.status, c.line) for c in _validator_checks()]
    core.st.session_state[core.LANG_KEY] = "en"
    english = [(c.name, c.status, c.line) for c in _validator_checks()]
    assert indonesian == english


def test_a_check_name_keeps_its_identifier():
    """Nama check dipakai untuk mencocokkan; hanya labelnya yang berbahasa."""
    from ui.components.pipeline_upload import _CAUSE_PRIORITY
    from ui.components.validator_messages import CHECK_NAME_KEYS, check_name

    for name in CHECK_NAME_KEYS:
        assert name in _CAUSE_PRIORITY, name
    core.st.session_state[core.LANG_KEY] = "en"
    assert check_name({"name": "sintaks Python"}) == "Python syntax"
    # Pengenalnya sendiri tidak ikut berubah.
    assert "sintaks Python" in _CAUSE_PRIORITY


# ── Rumusan wajib tidak melemah ──────────────────────────────────────────

MANDATORY = [
    # (kunci, gagasan Indonesia, gagasan Inggris)
    ("ins.anti_leak_note", ["split", "data latih"], ["split", "training data"]),
    ("ins.forbidden_frame", ["dikendalikan pengguna", "dapat diulang"],
     ["user-controlled", "reproduced"]),
    ("rpt.note_antileak_hikari", ["hanya", "data latih"],
     ["training data only"]),
    ("rpt.note_label_origin_eve", ["bukan kebenaran lapangan eksternal"],
     ["not external ground truth"]),
    ("mode.exploration_hint", ["disesuaikan", "di luar perbandingan resmi"],
     ["adjusted", "outside the official comparison"]),
    ("mode.official_hint", ["terkunci", "paper rujukan"],
     ["locked", "reference paper"]),
]


@pytest.mark.parametrize("key, id_ideas, en_ideas", MANDATORY)
def test_a_mandatory_statement_keeps_its_force(key, id_ideas, en_ideas):
    for lang, ideas in (("id", id_ideas), ("en", en_ideas)):
        text = " ".join(lookup(key, lang).split()).lower()
        for idea in ideas:
            assert idea.lower() in text, (key, lang, idea)


def test_the_forbidden_list_is_never_softened():
    """Kelima larangan tetap larangan, tidak menjadi saran."""
    from ui.components import instructions as ins

    core.st.session_state[core.LANG_KEY] = "en"
    english = ins.forbidden_actions_display()
    assert len(english) == len(ins.FORBIDDEN_ACTIONS)
    softened = [t for t in english
                if any(w in t.lower()
                       for w in ("try to avoid", "preferably", "if possible",
                                 "we suggest", "consider not"))]
    assert not softened, softened


# ── Judul kolom & kartu tetap muat ───────────────────────────────────────

#: Judul kolom lebih panjang dari ini akan terpotong pada lebar kolomnya.
MAX_COLUMN_LABEL = 18


@pytest.mark.parametrize("lang", ["id", "en"])
def test_a_column_heading_fits_its_column(lang):
    from ui.components import registry_view as rv, submission_review as sr

    for columns in (rv.ACTIVE_COLUMNS, rv.HISTORY_COLUMNS, sr.PENDING_COLUMNS):
        for col in columns:
            key = col.get("label_key")
            assert key, col["label"]
            label = lookup(key, lang)
            assert label, (key, lang)
            assert len(label) <= MAX_COLUMN_LABEL, (key, lang, label)


def test_every_review_column_carries_a_key():
    """Judul kolom yang tertinggal tanpa kunci akan diam-diam tetap Indonesia."""
    from ui.components import registry_view as rv, submission_review as sr

    missing = [col["label"]
               for columns in (rv.ACTIVE_COLUMNS, rv.HISTORY_COLUMNS,
                               sr.PENDING_COLUMNS)
               for col in columns if not col.get("label_key")]
    assert not missing, missing


# ── Atribusi: judul karya vs deskripsi platform ──────────────────────────

def test_the_research_title_is_never_translated():
    from config.research_attribution import RESEARCH_ATTRIBUTION
    from ui.i18n.rules import is_protected

    for entry in RESEARCH_ATTRIBUTION.values():
        assert is_protected(entry["display_name"]), entry["display_name"]


def test_the_research_scope_is_a_description_and_is_translated():
    """Cakupan ditulis platform — ia teks antarmuka, bukan judul karya."""
    from config.research_attribution import RESEARCH_ATTRIBUTION
    from ui.i18n.rules import TRANSLATE_ANYWAY, is_protected

    assert "scope" in TRANSLATE_ANYWAY
    for entry in RESEARCH_ATTRIBUTION.values():
        key = entry["scope_key"]
        assert key in CATALOG, key
        assert lookup(key, "id") == entry["scope"]
        assert lookup(key, "en") != entry["scope"]
        assert not is_protected(entry["scope"])


# ── Ketiga halaman × kedua bahasa × ketiga status pengguna ───────────────

PAGES = {
    "Progress & Status": "ui.views.view_results",
    "Run Experiment": "ui.views.run_experiment",
    "Add Pipeline & Dataset": "ui.views.contribute",
}
IDENTITIES = {
    "pengunjung": None,
    "kontributor": {"username": "andi", "role": "contributor",
                    "status": "active"},
    "research_admin": {"username": "boss", "role": "research_admin",
                       "status": "active"},
}


def _render(page: str, module: str, user, lang: str):
    """Render satu halaman lewat AppTest pada bahasa & identitas tertentu."""
    import tempfile
    from streamlit.testing.v1 import AppTest

    script = Path(tempfile.mkdtemp()) / "app.py"
    script.write_text(
        f"import sys\nsys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        f"st.session_state['_current_page'] = {page!r}\n"
        f"from {module} import render\n"
        "render()\n", encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=600)
    at.session_state[core.LANG_KEY] = lang
    if user:
        at.session_state["auth_user"] = user
    at.run()
    return at


@pytest.mark.parametrize("lang", ["id", "en"])
@pytest.mark.parametrize("who", sorted(IDENTITIES))
@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_page_renders_in_both_languages(page, who, lang):
    """Sembilan kombinasi per bahasa — tidak satu pun boleh melempar."""
    at = _render(page, PAGES[page], IDENTITIES[who], lang)
    assert not at.exception, (page, who, lang)


@pytest.mark.parametrize("who", sorted(IDENTITIES))
@pytest.mark.parametrize("page", sorted(PAGES))
def test_no_page_shows_indonesian_prose_in_english(page, who):
    """Teks yang TAMPIL, bukan literal di kode.

    Komentar CSS di dalam ``<style>`` sengaja dilewati: ia tidak pernah
    dirender sebagai teks, dan komentar pengembang memang tidak diterjemahkan.
    """
    at = _render(page, PAGES[page], IDENTITIES[who], "en")

    shown: list[str] = []
    for kind in ("markdown", "title", "header", "subheader", "caption",
                 "info", "warning", "error", "success", "text"):
        try:
            shown += [str(e.value) for e in getattr(at, kind)]
        except Exception:
            pass
    try:
        shown += [str(b.label) for b in at.button]
    except Exception:
        pass

    left = []
    for text in shown:
        flat = " ".join(_TAG.sub(" ", text).split())
        if flat.lstrip().startswith(("/*", ".ids", "@media")):
            continue                       # lembar gaya, bukan kalimat
        if len(flat) > 12 and len(_words(flat) & INDONESIAN) >= 2:
            left.append(flat[:110])
    assert not left, (page, who, left)
