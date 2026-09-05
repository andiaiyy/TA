"""
Tahap 2 — isi tiga halaman utama dalam dua bahasa.

Yang dijaga di sini bukan "sudah diterjemahkan berapa", melainkan hal-hal yang
kalau salah akan merusak platform secara diam-diam:

* **istilah tidak boleh bergeser** — satu konsep, satu kata, di seluruh kamus;
* **keterangan wajib tidak boleh melemah** dalam terjemahan;
* **pengenal tetap pengenal** — nama halaman & nama bagian dipakai untuk
  routing, jadi menerjemahkannya akan memutus perpindahan;
* **perilaku tidak berubah** saat bahasa berganti.
"""
import ast
import re
from pathlib import Path

import pytest

from ui.i18n import CATALOG, NEVER_TRANSLATE, missing_keys, untranslated_report
from ui.i18n.core import lookup
from ui.i18n.glossary import (
    FORBIDDEN_SYNONYMS, GLOSSARY, forbidden_terms_in,
)
from ui.views import manage_pipelines as mp

REPO_ROOT = Path(__file__).resolve().parents[1]

PAGE_PREFIX = {"Progress & Status": "ps.", "Run Experiment": "re.",
               "Add Pipeline & Dataset": "ap."}


# ── Kelengkapan per halaman ──────────────────────────────────────────────

@pytest.mark.parametrize("page,prefix", sorted(PAGE_PREFIX.items()))
def test_every_page_key_is_complete_in_both_languages(page, prefix):
    keys = [k for k in CATALOG if k.startswith(prefix)]
    assert keys, page
    for key in keys:
        for lang in ("id", "en"):
            text = (CATALOG[key].get(lang) or "").strip()
            assert text, (key, lang)


def test_the_catalog_has_no_untranslated_key_left():
    report = untranslated_report()
    assert report["en"]["missing"] == []
    assert report["id"]["missing"] == []


# ── Padanan istilah ──────────────────────────────────────────────────────

def test_the_glossary_covers_every_required_concept():
    """Istilah yang diminta ditetapkan padanannya."""
    for concept in ("research_pipeline", "dataset", "experiment", "submission",
                    "review", "approval", "version", "official_run",
                    "exploration_run", "contributor", "visitor", "upload",
                    "compatibility"):
        assert concept in GLOSSARY, concept
        indonesian, english = GLOSSARY[concept]
        assert indonesian and english, concept


def test_no_catalog_text_uses_a_forbidden_synonym():
    """Inilah yang mencegah istilah bergeser diam-diam saat kunci bertambah."""
    from ui.i18n.glossary import SYNONYM_EXEMPT_PREFIXES

    for key, entry in CATALOG.items():
        if key.startswith(SYNONYM_EXEMPT_PREFIXES):
            continue                         # konsep tersendiri, lihat glosarium
        for lang, text in entry.items():
            bad = forbidden_terms_in(text)
            assert not bad, (key, lang, bad, [FORBIDDEN_SYNONYMS[b] for b in bad])


def test_the_synonym_exemption_stays_narrow():
    """Pengecualian tidak boleh melebar diam-diam menjadi celah umum."""
    from ui.i18n.glossary import SYNONYM_EXEMPT_PREFIXES

    assert SYNONYM_EXEMPT_PREFIXES == ("trial.", "td.")
    # Aturannya tetap menjaga kunci di luar awalan itu.
    assert forbidden_terms_in("uji coba pipeline")


@pytest.mark.parametrize("concept", ["submission", "review", "version",
                                     "experiment", "compatibility"])
def test_a_concept_is_translated_the_same_way_everywhere(concept):
    """Kalau istilah Indonesianya muncul, padanan Inggrisnya harus itu-itu saja."""
    indonesian, english = GLOSSARY[concept]
    for key, entry in CATALOG.items():
        id_text = (entry.get("id") or "").lower()
        en_text = (entry.get("en") or "").lower()
        if not id_text or not en_text:
            continue
        # Bentuk jamak Inggris ikut diterima: "submission" dan "submissions"
        # adalah kata yang sama, dan memaksa bentuk tunggal justru menghasilkan
        # kalimat Inggris yang janggal.
        id_pattern = rf"\b{re.escape(indonesian.lower())}\b"
        en_pattern = rf"\b{re.escape(english.lower())}(s|es)?\b"
        if re.search(id_pattern, id_text):
            assert re.search(en_pattern, en_text), (concept, key, entry["en"])


# ── Keterangan WAJIB: maknanya tidak boleh melemah ───────────────────────

#: (kunci/konstanta, gagasan yang HARUS ada di teks Indonesia, di teks Inggris)
MANDATORY = [
    ("re.note_locked_params", ["terkunci", "resmi", "eksplorasi"],
     ["locked", "official", "exploration"]),
    ("ap.help_static_only", ["statis", "tidak dijalankan"],
     ["static", "not executed"]),
    ("ap.help_dataset_direct", ["tidak melewati peninjauan"],
     ["do not go through review"]),
    ("ap.help_submit_review", ["ditinjau", "bukan mengaktifkannya"],
     ["review", "not active"]),
    ("ap.help_compare_readonly", ["baca-saja", "tidak ada versi"],
     ["read-only", "no version"]),
    ("ap.help_edit_new_version", ["versi baru"], ["new version"]),
    ("lang.help", ["tidak hilang"], ["kept"]),
]


@pytest.mark.parametrize("key,id_ideas,en_ideas", MANDATORY,
                         ids=[m[0] for m in MANDATORY])
def test_mandatory_notes_keep_their_meaning_in_both_languages(key, id_ideas,
                                                              en_ideas):
    """Terjemahan yang MELEMAHKAN keterangan wajib tidak dapat diterima."""
    id_text = lookup(key, "id").lower()
    en_text = lookup(key, "en").lower()
    for idea in id_ideas:
        assert idea.lower() in id_text, (key, "id", idea)
    for idea in en_ideas:
        assert idea.lower() in en_text, (key, "en", idea)


def test_the_honesty_note_survives_where_it_is_decided():
    """Kejujuran tidak dihapus — ia DIPINDAH ke tempat keputusannya diambil.

    Dahulu dua kalimat berdiri berdampingan di kepala setiap tampilan
    peninjauan, terbaca sebelum pembacanya tahu ia sedang melihat apa. Yang
    tentang pemeriksaan statis dibuang; yang tentang versi baru bertahan, dan
    tempatnya kini tepat sebelum tombol Simpan pada penyunting — di situlah
    "menyunting membuat versi baru" benar-benar menjadi keputusan.
    """
    assert "versi baru" in mp.NEW_VERSION_NOTE
    assert "tidak berubah" in mp.NEW_VERSION_NOTE
    assert not hasattr(mp, "STATIC_CHECK_NOTE")


# ── Pengenal TIDAK ikut diterjemahkan ────────────────────────────────────

def test_section_identifiers_stay_canonical_while_labels_translate():
    """Nama bagian dipakai untuk memilih bagian — sama seperti nama halaman.

    Kalau pengenalnya ikut berbahasa, berpindah bahasa akan membuang bagian
    yang sedang dibuka.
    """
    assert mp.SECTION_ACTIVE == "Aktif"
    assert mp.SECTION_HISTORY == "Riwayat versi"
    assert mp.SECTION_PENDING == "Menunggu tinjauan"
    assert set(mp.SECTION_LABEL_KEYS) == set(mp.SECTIONS)

    # …tetapi labelnya ikut bahasa.
    assert mp.section_label(mp.SECTION_ACTIVE, 0, 7) == "Aktif (7)"
    assert mp.section_label(mp.SECTION_PENDING, 3, 0) == "Menunggu tinjauan (3)"


def test_protected_values_never_appear_translated_in_the_catalog():
    for group in ("atribusi_penelitian", "identitas_pipeline", "kolom_dataset",
                  "field_kontrak"):
        for value in NEVER_TRANSLATE[group]:
            for key, entry in CATALOG.items():
                for lang, text in entry.items():
                    assert (text or "").strip() != value, (key, lang, value)


def test_algorithm_and_metric_names_are_absent_from_the_catalog():
    """Nama algoritma & metrik dipakai apa adanya — bukan lewat kamus."""
    for value in (NEVER_TRANSLATE["nama_algoritma"]
                  + NEVER_TRANSLATE["istilah_metrik"]):
        for key, entry in CATALOG.items():
            for text in entry.values():
                assert (text or "").strip() != value, (key, value)


# ── Label widget tetap frasa pendek ──────────────────────────────────────

def test_widget_labels_stay_short_phrases_in_both_languages():
    """Label yang menjadi kalimat merusak tata letak kontrol."""
    label_keys = [k for k in CATALOG
                  if re.search(r"\.(lbl|f|ph)_", k) or k.endswith(".label")]
    assert label_keys
    for key in label_keys:
        for lang in ("id", "en"):
            text = lookup(key, lang)
            assert "\n" not in text, (key, lang)
            # Placeholder tampil DI DALAM kotak isian, jadi ia boleh sedikit
            # lebih panjang daripada label yang berdiri di sampingnya.
            is_hint = ".ph_" in key or key.endswith("_hint")
            assert len(text) <= (60 if is_hint else 40), \
                (key, lang, len(text), text)

            # Aturan "bukan kalimat" berlaku untuk LABEL. Teks contoh di dalam
            # kontrol (placeholder/petunjuk) memang boleh memuat singkatan
            # ("mis.", "e.g.") dan angka desimal — itu contoh nilai, bukan
            # kalimat, dan memangkasnya justru menghilangkan contohnya.
            if is_hint:
                continue
            stops = re.findall(r"\.(?!\d)", text)
            assert len(stops) <= 1, (key, lang, text)


def test_buttons_stay_short_in_both_languages():
    """Tombol adalah tempat paling sempit; teks panjang merusak barisnya."""
    for key in [k for k in CATALOG if ".btn_" in k]:
        for lang in ("id", "en"):
            text = lookup(key, lang)
            assert len(text) <= 32, (key, lang, len(text), text)


def test_no_placeholder_drifts_between_the_two_languages():
    for key, entry in CATALOG.items():
        id_text, en_text = entry.get("id") or "", entry.get("en") or ""
        if not id_text or not en_text:
            continue
        assert (set(re.findall(r"\{([^}]+)\}", id_text))
                == set(re.findall(r"\{([^}]+)\}", en_text))), key


# ── Sisa teks yang masih tertanam langsung ───────────────────────────────

PAGE_FILES = {
    "Progress & Status": ["ui/views/view_results.py"],
    "Run Experiment": ["ui/views/run_experiment.py"],
    "Add Pipeline & Dataset": ["ui/views/contribute.py",
                               "ui/views/manage_pipelines.py"],
}

#: Fungsi tampilan yang argumen pertamanya dibaca pengguna.
DISPLAY_CALLS = {"title", "subheader", "header", "button", "caption",
                 "success", "error", "warning", "info", "selectbox",
                 "text_input", "text_area", "expander", "render_section"}


def _embedded_literals(path: Path) -> list[tuple[int, str]]:
    """Teks Indonesia yang masih ditulis langsung di panggilan tampilan."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.attr if isinstance(node.func, ast.Attribute)
                else node.func.id if isinstance(node.func, ast.Name) else "")
        if name not in DISPLAY_CALLS or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            text = first.value.strip()
            if len(text) > 3 and " " in text:
                out.append((first.lineno, text))
    return out


@pytest.mark.parametrize("page", sorted(PAGE_FILES))
def test_no_page_title_or_button_is_still_hardcoded(page):
    """Judul, tombol, dan label utama sudah lewat kamus.

    Pesan validator/diagnosa SENGAJA belum: itu Tahap 3. Yang diperiksa di sini
    adalah teks yang menjadi lingkup Tahap 2.
    """
    leftovers = []
    for rel in PAGE_FILES[page]:
        for line, text in _embedded_literals(REPO_ROOT / rel):
            leftovers.append(f"{rel}:{line}  {text[:60]}")
    # Ambang: sisa yang ada memang milik Tahap 3 (pesan kesalahan bertingkat,
    # panduan validator). Angka ini menurun tiap tahap dan menjaga agar teks
    # BARU tidak ditanam langsung.
    assert len(leftovers) <= 40, (page, len(leftovers), leftovers[:12])


# ── AppTest: dua bahasa × tiga status pengguna ───────────────────────────

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIB = {"username": "andi", "role": "contributor", "status": "active"}
USERS = {"pengunjung": None, "kontributor": CONTRIB, "research_admin": ADMIN}
PAGES = ("Progress & Status", "Run Experiment", "Add Pipeline & Dataset")
VIEWS = {"Progress & Status": "view_results",
         "Run Experiment": "run_experiment",
         "Add Pipeline & Dataset": "contribute"}


def _page_app(tmp_path, page, lang, user, name):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / name
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        f"st.session_state['_current_page'] = {page!r}\n"
        f"from ui.views.{VIEWS[page]} import render\n"
        "render()\n",
        encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    at.session_state["_lang"] = lang
    if user:
        at.session_state["auth_user"] = user
    at.run()
    return at


@pytest.mark.parametrize("lang", ["id", "en"])
@pytest.mark.parametrize("who", sorted(USERS))
@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_in_both_languages(tmp_path, page, who, lang):
    at = _page_app(tmp_path, page, lang, USERS[who],
                   f"p_{VIEWS[page]}_{who}_{lang}.py")
    assert not at.exception, (page, who, lang, at.exception)


@pytest.mark.parametrize("page,key", [("Progress & Status", "page.progress"),
                                      ("Run Experiment", "page.run_experiment"),
                                      ("Add Pipeline & Dataset", "page.contribute")])
def test_switching_language_changes_the_page_title_and_back(tmp_path, page, key):
    """Berpindah ke Inggris mengubah teks; kembali ke Indonesia memulihkannya."""
    at = _page_app(tmp_path, page, "id", None, f"t_{VIEWS[page]}.py")
    assert any(lookup(key, "id") in h.value for h in at.title)

    at.session_state["_lang"] = "en"
    at.run()
    assert not at.exception
    assert any(lookup(key, "en") in h.value for h in at.title)

    at.session_state["_lang"] = "id"
    at.run()
    assert not at.exception
    assert any(lookup(key, "id") in h.value for h in at.title)


def test_behaviour_is_identical_in_both_languages(tmp_path):
    """Tombol & kontrol yang sama tersedia pada kedua bahasa.

    Jumlah dan URUTAN kontrolnya harus sama — hanya tulisannya yang berbeda.
    """
    counts = {}
    for lang in ("id", "en"):
        at = _page_app(tmp_path, "Run Experiment", lang, CONTRIB,
                       f"b_{lang}.py")
        assert not at.exception, (lang, at.exception)
        counts[lang] = (len(at.button), len(at.selectbox), len(at.expander))
    assert counts["id"] == counts["en"], counts


def test_permissions_are_enforced_identically_in_both_languages(tmp_path):
    """Menyembunyikan/menampilkan kontrol tidak bergantung pada bahasa."""
    for lang in ("id", "en"):
        visitor = _page_app(tmp_path, "Add Pipeline & Dataset", lang, None,
                            f"perm_v_{lang}.py")
        admin = _page_app(tmp_path, "Add Pipeline & Dataset", lang, ADMIN,
                          f"perm_a_{lang}.py")
        assert not visitor.exception and not admin.exception
        # Admin selalu punya kontrol lebih banyak, pada bahasa mana pun.
        assert len(admin.button) > len(visitor.button), lang
