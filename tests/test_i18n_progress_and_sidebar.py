"""
Penutup: halaman Progress & Status, kalimat kaitan halaman, dan letak sidebar.

Tiga hal dijaga di sini.

**Kalimat kaitan halaman** dulu menyamakan dua aturan yang berbeda — dataset
tersimpan langsung, pipeline menunggu persetujuan. Menyamakannya membuat
pengunggah dataset menunggu sesuatu yang tidak pernah datang, jadi yang diuji
bukan hanya "ada terjemahannya" melainkan "isinya benar".

**Progress & Status** adalah halaman dengan paling banyak teks kecil: judul
kolom, penyaring, keterangan tabel, dan dua modal. Yang diuji adalah teks yang
BENAR-BENAR dirender, termasuk saat modal terbuka.

**Sidebar** kini berurutan pengalih bahasa → label mode → dropdown mode, dan
urutan itu diuji dari sumbernya karena ia keputusan tata letak, bukan gaya.
"""
import re
import tempfile
from pathlib import Path

import pytest

import ui.i18n.core as core
from ui.i18n import CATALOG
from ui.i18n.core import lookup

REPO_ROOT = Path(__file__).resolve().parents[1]

INDONESIAN = {
    "yang", "tidak", "belum", "dapat", "untuk", "dengan", "pada", "dari",
    "akan", "sudah", "harus", "adalah", "atau", "dan", "agar", "bila",
    "karena", "sebagai", "seluruh", "setiap", "hanya", "juga", "ini", "itu",
    "lebih", "masih", "tetap", "saat", "oleh", "ada", "berkas", "pengguna",
    "eksperimen", "kolom", "baris", "nilai", "hasil", "pilih", "saring",
    "waktu", "durasi", "catatan", "versi", "terpilih", "bawaan", "gagal",
}
_WORD = re.compile(r"[A-Za-z]+")
_TAG = re.compile(r"<[^>]+>")


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(_TAG.sub(" ", text or ""))}


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── (1) Kalimat kaitan halaman: dua bahasa DAN benar ─────────────────────

def test_the_related_pages_line_exists_in_both_languages():
    for lang in ("id", "en"):
        assert lookup("ap.related_pages", lang), lang


@pytest.mark.parametrize("lang, dataset_idea, pipeline_idea", [
    ("id", "langsung", "disetujui"),
    ("en", "straight away", "approves"),
])
def test_the_related_pages_line_matches_the_real_rule(lang, dataset_idea,
                                                      pipeline_idea):
    """Dataset tersedia langsung; pipeline menunggu persetujuan.

    Kalimat lama ("Setelah disetujui, dataset & pipeline muncul di …")
    menyamakan keduanya. Test ini menuntut keduanya DIBEDAKAN, pada kedua
    bahasa, supaya kekeliruan yang sama tidak kembali lewat terjemahan.
    """
    text = lookup("ap.related_pages", lang).lower()
    assert "dataset" in text
    assert "pipeline" in text
    assert dataset_idea.lower() in text
    assert pipeline_idea.lower() in text


def test_the_related_pages_line_does_not_lump_them_together():
    """Bentuk lama — satu syarat untuk keduanya — tidak boleh kembali."""
    for lang in ("id", "en"):
        text = lookup("ap.related_pages", lang).lower()
        assert "dataset & pipeline" not in text, lang
        assert "dataset and pipeline" not in text, lang
    src = (REPO_ROOT / "ui" / "components" / "contribute_context.py").read_text(
        encoding="utf-8")
    assert "Setelah disetujui, dataset & pipeline" not in src


def test_the_page_name_comes_from_the_catalog():
    """Nama halaman disisipkan, bukan ditulis ulang di dalam kalimat."""
    assert "{page}" in CATALOG["ap.related_pages"]["id"]
    assert "{page}" in CATALOG["ap.related_pages"]["en"]
    assert lookup("page.run_experiment", "en") == "Run Experiment"


# ── (2) Progress & Status: seluruh unsur dua bahasa ──────────────────────

#: Unsur yang diminta diperiksa satu per satu.
PS_ELEMENTS = {
    "judul kolom": ["ps.col_time", "ps.col_duration", "ps.col_pipeline",
                    "ps.col_dataset", "ps.col_file", "ps.col_owner",
                    "ps.col_status", "ps.col_dataset_hash",
                    "ps.col_pipeline_version", "ps.col_mode_header"],
    "keterangan tabel": ["ps.semantics_note", "ps.best_mark_note",
                         "ps.param_provenance", "ps.mode_column_note"],
    "keadaan kosong": ["ps.empty_history", "ps.empty_filtered",
                       "ps.empty_columns", "ps.empty_running",
                       "ps.empty_artifacts"],
    "penyaring": ["ps.f_pipeline", "ps.f_dataset", "ps.f_status",
                  "ps.f_run_mode", "ps.f_date_from", "ps.f_date_to",
                  "ps.f_metric_search", "ps.mode_filter_default_note"],
    "pemilih kolom": ["ps.dlg_columns", "ps.group_identity", "ps.group_param",
                      "ps.group_metric", "ps.btn_core_columns"],
    "jumlah hasil": ["ps.result_summary"],
    "tombol ekspor": ["ps.btn_csv", "ps.btn_pdf", "ps.help_csv_summary"],
    "dialog perbandingan": ["ps.dlg_compare", "ps.cmp_reading",
                            "ps.only_diff_label", "ps.all_same_note",
                            "ps.compare_need_two", "ps.compare_too_many",
                            "ps.cmp_col_experiment", "ps.btn_compare_selected"],
    "dialog detail": ["ps.dlg_detail_title", "ps.detail_selected_line",
                      "ps.detail_identity", "ps.params_used_line",
                      "ps.params_legacy_line", "ps.exp_artifact_viewer"],
    "tooltip": ["ps.help_open_detail", "ps.help_drop", "ps.help_drop_too_few",
                "ps.help_compare_hint"],
}


@pytest.mark.parametrize("group", sorted(PS_ELEMENTS))
def test_every_progress_element_exists_in_both_languages(group):
    missing = [key for key in PS_ELEMENTS[group]
               if key not in CATALOG
               or not CATALOG[key].get("id") or not CATALOG[key].get("en")]
    assert not missing, (group, missing)


@pytest.mark.parametrize("group", sorted(PS_ELEMENTS))
def test_no_progress_element_is_left_in_indonesian(group):
    """Entri Inggrisnya benar-benar Inggris, bukan salinan Indonesia."""
    left = []
    for key in PS_ELEMENTS[group]:
        english = CATALOG[key]["en"]
        if len(_words(english) & INDONESIAN) >= 2:
            left.append(key)
    assert not left, (group, left)


#: Judul kolom lebih panjang dari ini akan terpotong pada lebar kolomnya.
MAX_COLUMN_LABEL = 20


@pytest.mark.parametrize("lang", ["id", "en"])
def test_a_progress_column_heading_fits_its_column(lang):
    for key in PS_ELEMENTS["judul kolom"]:
        label = lookup(key, lang)
        assert label, (key, lang)
        assert len(label) <= MAX_COLUMN_LABEL, (key, lang, label)


def test_the_column_width_lookup_is_not_keyed_by_a_translated_label():
    """Lebar kolom dicari lewat KUNCI kolom.

    Judul kolom kini mengikuti bahasa; mencari lebar berdasarkan judul akan
    meleset pada mode Inggris dan seluruh kolom diam-diam jatuh ke lebar
    cadangan — tata letak bergeser tanpa satu pun galat.
    """
    import ui.views.view_results as vr

    from ui.components.experiment_table import COLUMN_LABEL_KEYS

    for key in vr._COLUMN_WIDTHS:
        assert key in COLUMN_LABEL_KEYS, key
    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(
        encoding="utf-8")
    assert '_COLUMN_WIDTHS.get(col["key"]' in src
    assert '_COLUMN_WIDTHS.get(col["label"]' not in src


def test_the_column_keys_never_change_with_the_language():
    """Kunci kolom adalah PENGENAL: pilihan pengguna tidak boleh hilang."""
    from ui.components import experiment_table as et

    core.st.session_state[core.LANG_KEY] = "id"
    indonesian = [c["key"] for c in et.build_columns()]
    core.st.session_state[core.LANG_KEY] = "en"
    english = [c["key"] for c in et.build_columns()]
    assert indonesian == english
    # Judulnya justru HARUS berbeda.
    core.st.session_state[core.LANG_KEY] = "id"
    id_labels = [c["label"] for c in et.build_columns()]
    core.st.session_state[core.LANG_KEY] = "en"
    en_labels = [c["label"] for c in et.build_columns()]
    assert id_labels != en_labels


# ── (2b) Keterangan WAJIB tetap bermakna sama ────────────────────────────

MANDATORY = [
    ("ps.mode_column_note", ["resmi", "terkunci", "eksplorasi"],
     ["official", "locked", "exploration"]),
    ("ps.mixed_mode_warning", ["tidak sebanding", "parameter"],
     ["not comparable", "parameters"]),
    ("ps.semantics_hikari", ["berbobot"], ["weighted"]),
    ("ps.semantics_eve", ["natural-holdout"], ["natural holdout"]),
    ("ps.cross_family_warning", ["tidak sebanding"], ["not directly"]),
    ("ps.dataset_mismatch_warning", ["hash berbeda"], ["different hashes"]),
    ("ps.rv_explain_fn", ["paling kritis"], ["most critical"]),
]


@pytest.mark.parametrize("key, id_ideas, en_ideas", MANDATORY)
def test_a_mandatory_progress_note_keeps_its_meaning(key, id_ideas, en_ideas):
    for lang, ideas in (("id", id_ideas), ("en", en_ideas)):
        text = " ".join(lookup(key, lang).split()).lower()
        for idea in ideas:
            assert idea.lower() in text, (key, lang, idea)


def test_the_metric_semantics_thresholds_are_untouched():
    """Terjemahan tidak boleh menggeser keputusan mana keluarga mana."""
    from ui.components import experiment_table as et

    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        assert et.family_of("HIKARI2021") == et.FAMILY_HIKARI, lang
        assert et.family_of("EVE_SURICATA") == et.FAMILY_EVE, lang
        assert et.family_of("entah apa") is None, lang


# ── (3) Urutan unsur pada sidebar ────────────────────────────────────────

def _mode_switch_source() -> str:
    src = (REPO_ROOT / "ui" / "views" / "login.py").read_text(encoding="utf-8")
    return src.split("def render_mode_switch()")[1].split("\ndef ")[0]


def test_the_sidebar_puts_the_language_switch_above_the_mode_label():
    """Urutan: pengalih bahasa → label mode → dropdown mode.

    Label mode menjelaskan dropdown tepat di bawahnya; menaruh pengalih
    bahasa di antara keduanya memisahkan pasangan yang seharusnya terbaca
    sebagai satu kesatuan.
    """
    body = _mode_switch_source()
    lang_at = body.index("render_language_switch()")
    label_at = body.index("_MODE_LABEL_OPEN")
    picker_at = body.index("st.selectbox(")
    assert lang_at < label_at < picker_at


def test_the_identity_block_stays_at_the_bottom_of_the_sidebar():
    """Jangkar yang mendorong blok ini ke dasar tetap terpasang."""
    body = _mode_switch_source()
    assert "_MODE_ANCHOR" in body
    css = (REPO_ROOT / "ui" / "components" / "theme.py").read_text(
        encoding="utf-8")
    assert ".ids-mode-anchor" in css
    assert "margin-top: auto;" in css


def test_the_mode_label_is_tied_to_its_dropdown():
    """Pasangan label+dropdown dirapatkan, tidak mengambang di tengah."""
    css = (REPO_ROOT / "ui" / "components" / "theme.py").read_text(
        encoding="utf-8")
    assert ".ids-mode-label" in css
    # Aturannya tersebar di beberapa selector; yang diperiksa keberadaannya,
    # bukan urutannya.
    block = css.split(".ids-mode-label")[-1][:600]
    assert "margin-top:" in block
    assert "margin-bottom: 0;" in css


def test_picking_a_mode_still_grants_nothing():
    """Perilaku dropdown TIDAK berubah: memilih peran bukan memberi peran."""
    body = _mode_switch_source()
    # Tidak ada satu pun penulisan peran ke session_state di blok ini.
    assert 'session_state["role"]' not in body
    assert "auth_user'] = " not in body
    # Jalurnya tetap: keluar, atau membuka dialog masuk.
    assert "logout()" in body


@pytest.mark.parametrize("lang", ["id", "en"])
def test_the_mode_labels_stay_short_enough_for_the_sidebar(lang):
    """Sidebar sempit; label yang panjang akan terpotong atau melipat."""
    for key in ("mode.visitor_line", "ap.role_contributor",
                "ap.role_research_admin"):
        assert len(lookup(key, lang)) <= 32, (key, lang)


# ── Halaman × bahasa × identitas, termasuk modal ─────────────────────────

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


def _render(page: str, module: str, user, lang: str, extra=None):
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
    at = AppTest.from_file(str(script), default_timeout=900)
    at.session_state[core.LANG_KEY] = lang
    if user:
        at.session_state["auth_user"] = user
    for key, value in (extra or {}).items():
        at.session_state[key] = value
    at.run()
    return at


def _recent_experiment_ids(limit: int = 2):
    from database.db import get_connection
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM experiments ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [r[0] for r in rows]
    except Exception:                        # basis data kosong / belum ada
        return []


@pytest.mark.parametrize("lang", ["id", "en"])
@pytest.mark.parametrize("who", sorted(IDENTITIES))
@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_page_renders_in_both_languages(page, who, lang):
    at = _render(page, PAGES[page], IDENTITIES[who], lang)
    assert not at.exception, (page, who, lang)


@pytest.mark.parametrize("lang", ["id", "en"])
def test_the_progress_dialogs_render_in_both_languages(lang):
    """Modal detail & perbandingan ikut diuji — di situlah teks bersembunyi."""
    ids = _recent_experiment_ids(2)
    if not ids:
        pytest.skip("belum ada eksperimen pada basis data")

    admin = IDENTITIES["research_admin"]
    detail = _render("Progress & Status", PAGES["Progress & Status"], admin,
                     lang, {"_detail_id": ids[0]})
    assert not detail.exception, ("detail", lang)

    if len(ids) >= 2:
        compare = _render("Progress & Status", PAGES["Progress & Status"],
                          admin, lang, {"_hist_compare_ids": ids[:2]})
        assert not compare.exception, ("compare", lang)


def _visible_text(at) -> list[str]:
    out = []
    for kind in ("markdown", "title", "header", "subheader", "caption", "info",
                 "warning", "error", "success", "text", "button", "metric",
                 "selectbox", "multiselect", "radio", "checkbox"):
        try:
            for e in getattr(at, kind):
                for attr in ("value", "label", "body"):
                    v = getattr(e, attr, None)
                    if isinstance(v, str):
                        out.append(v)
        except Exception:
            pass
    return out


@pytest.mark.parametrize("who", sorted(IDENTITIES))
def test_the_progress_page_shows_no_indonesian_in_english(who):
    at = _render("Progress & Status", PAGES["Progress & Status"],
                 IDENTITIES[who], "en")
    left = []
    for text in _visible_text(at):
        flat = " ".join(_TAG.sub(" ", text).split())
        if flat.lstrip().startswith(("/*", ".ids", "@media", "<style")):
            continue                       # lembar gaya, bukan kalimat
        if len(flat) > 12 and len(_words(flat) & INDONESIAN) >= 2:
            left.append(flat[:110])
    assert not left, (who, left)


def test_the_progress_dialogs_show_no_indonesian_in_english():
    ids = _recent_experiment_ids(2)
    if not ids:
        pytest.skip("belum ada eksperimen pada basis data")

    admin = IDENTITIES["research_admin"]
    cases = {"detail": {"_detail_id": ids[0]}}
    if len(ids) >= 2:
        cases["compare"] = {"_hist_compare_ids": ids[:2]}

    for name, extra in cases.items():
        at = _render("Progress & Status", PAGES["Progress & Status"], admin,
                     "en", extra)
        left = []
        for text in _visible_text(at):
            flat = " ".join(_TAG.sub(" ", text).split())
            if flat.lstrip().startswith(("/*", ".ids", "@media", "<style")):
                continue
            if len(flat) > 12 and len(_words(flat) & INDONESIAN) >= 2:
                left.append(flat[:110])
        assert not left, (name, left)
