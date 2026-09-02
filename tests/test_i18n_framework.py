"""
Kerangka dua bahasa (Tahap 1).

Yang dijaga di sini adalah MEKANISMEnya, bukan kelengkapan terjemahannya —
Tahap 2 & 3 yang mengisi sisanya. Empat hal yang harus benar sejak awal, karena
memperbaikinya setelah ribuan string masuk jauh lebih mahal:

* pengambilan teks & cadangan Indonesia — antarmuka tidak boleh pernah kosong
  atau menampilkan kunci mentah;
* penyisipan BERNAMA — urutan kata berbeda antar bahasa;
* daftar "tidak diterjemahkan" — nama penelitian, identitas pipeline, kolom
  dataset harus identik di kedua bahasa;
* berpindah bahasa tidak mengganggu keadaan apa pun.
"""
import ast
from pathlib import Path

import pytest

from ui.components import language_switch as ls
from ui.components import sidebar_chrome as chrome
from ui.i18n import (
    CATALOG, DEFAULT_LANG, LANGUAGES, NEVER_TRANSLATE, is_protected,
    missing_keys, untranslated_report,
)
from ui.i18n.core import LANG_KEY, humanise, lookup
from ui.i18n.rules import PROTECTED_VALUES, protected_group

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Mekanisme pengambilan ────────────────────────────────────────────────

def test_the_default_language_is_indonesian():
    assert DEFAULT_LANG == "id"
    assert set(LANGUAGES) == {"id", "en"}


def test_lookup_returns_the_requested_language():
    assert lookup("nav.run_experiment", "id") == "Jalankan Eksperimen"
    assert lookup("nav.run_experiment", "en") == "Run Experiment"


def test_a_key_without_an_english_text_falls_back_to_indonesian():
    """Selama Tahap 2 & 3 belum jalan, ini keadaan yang paling sering terjadi."""
    catalog = {"x.y": {"id": "Teks Indonesia", "en": ""}}
    from ui.i18n import core

    assert core.CATALOG is CATALOG          # yang dipakai produksi
    # Perilaku cadangan diuji lewat kamus buatan agar tidak bergantung pada
    # kunci mana yang kebetulan belum diterjemahkan.
    entry = catalog["x.y"]
    resolved = entry.get("en") or entry.get(DEFAULT_LANG)
    assert resolved == "Teks Indonesia"


def test_a_missing_english_text_in_the_real_catalog_falls_back(monkeypatch):
    from ui.i18n import core

    monkeypatch.setitem(core.CATALOG, "_probe.only_id",
                        {"id": "Hanya Indonesia", "en": ""})
    assert lookup("_probe.only_id", "en") == "Hanya Indonesia"


def test_an_unknown_key_never_shows_a_raw_key_or_an_empty_string():
    """Kunci mentah di layar adalah kebocoran detail teknis ke pengguna."""
    out = lookup("tidak.pernah.ada", "en")
    assert out
    assert out != "tidak.pernah.ada"
    assert "." not in out
    assert out == "Ada"                     # ruas terakhir, dibaca manusia


def test_humanise_never_returns_empty():
    for key in ("", "a", "a.b.c_d", "nav.run_experiment"):
        assert humanise(key).strip()


# ── Penyisipan BERNAMA ───────────────────────────────────────────────────

def test_named_interpolation_works_in_both_languages():
    for lang, expected in (("id", "3 dari 48 eksperimen"),
                           ("en", "3 of 48 experiments")):
        assert lookup("progress.of_total", lang).format(done=3, total=48) == expected


def test_no_catalog_text_uses_positional_placeholders():
    """Penyisipan berdasarkan posisi tertukar diam-diam saat urutan kata berubah."""
    import re

    for key, entry in CATALOG.items():
        for lang, text in entry.items():
            if not text:
                continue
            assert "{}" not in text, (key, lang)
            assert "%s" not in text and "%d" not in text, (key, lang)
            # Setiap placeholder harus BERNAMA.
            for holder in re.findall(r"\{([^}]*)\}", text):
                assert holder.strip(), (key, lang)
                assert not holder.strip().isdigit(), (key, lang, holder)


def test_both_languages_use_the_same_placeholders():
    """Kalimat boleh berbeda urutan; nilai yang disisipkan harus sama."""
    import re

    for key, entry in CATALOG.items():
        id_text, en_text = entry.get("id") or "", entry.get("en") or ""
        if not id_text or not en_text:
            continue
        assert (set(re.findall(r"\{([^}]+)\}", id_text))
                == set(re.findall(r"\{([^}]+)\}", en_text))), key


def test_a_missing_value_does_not_break_the_render(monkeypatch):
    from ui.i18n import core

    monkeypatch.setitem(core.CATALOG, "_probe.needs", {"id": "{a} dan {b}",
                                                       "en": "{a} and {b}"})
    monkeypatch.setattr(core, "current_lang", lambda: "id")
    # Kurang satu nilai: kalimatnya kembali apa adanya, tidak melempar.
    assert core.t("_probe.needs", a=1) == "{a} dan {b}"


# ── Alat pemeriksa kelengkapan ───────────────────────────────────────────

def test_the_completeness_checker_reports_untranslated_keys(monkeypatch):
    from ui.i18n import core

    monkeypatch.setitem(core.CATALOG, "_probe.untranslated",
                        {"id": "Ada", "en": ""})
    assert "_probe.untranslated" in missing_keys("en")
    assert "_probe.untranslated" not in missing_keys("id")


def test_the_report_counts_both_languages():
    report = untranslated_report()
    assert set(report) == {"id", "en"}
    for lang, data in report.items():
        assert data["total"] == len(CATALOG)
        assert data["done"] + len(data["missing"]) == data["total"]
        assert 0 <= data["percent"] <= 100


def test_the_checker_works_on_an_arbitrary_catalog():
    """Alatnya murni — dapat dipakai pada kamus mana pun, termasuk saat Tahap 2."""
    catalog = {"a": {"id": "A", "en": "A"}, "b": {"id": "B", "en": ""}}
    assert missing_keys("en", catalog) == ["b"]
    assert missing_keys("id", catalog) == []
    assert untranslated_report(catalog)["en"]["percent"] == 50.0


# ── Daftar "tidak diterjemahkan" ─────────────────────────────────────────

def test_the_never_translate_rule_is_written_down_as_code():
    """Aturannya harus dapat dieksekusi, bukan sekadar diingat."""
    for group in ("atribusi_penelitian", "identitas_pipeline", "nama_dataset",
                  "kolom_dataset", "field_kontrak", "metode_dan_kelas",
                  "nama_algoritma", "istilah_metrik"):
        assert group in NEVER_TRANSLATE, group
        assert NEVER_TRANSLATE[group], group


@pytest.mark.parametrize("value", sorted(PROTECTED_VALUES))
def test_protected_values_are_identical_in_both_languages(value):
    """Nilai yang dilindungi tidak boleh punya terjemahan sama sekali."""
    assert is_protected(value)
    assert protected_group(value)
    for key, entry in CATALOG.items():
        id_text, en_text = entry.get("id") or "", entry.get("en") or ""
        if id_text.strip() == value and en_text:
            assert en_text.strip() == value, key


def test_the_research_attribution_is_never_translated():
    """Nama karya orang — menerjemahkannya adalah salah kutip pada skripsi."""
    for name in NEVER_TRANSLATE["atribusi_penelitian"]:
        assert is_protected(name)
        # Tidak ada kunci kamus yang mengandung judul penelitian.
        for key, entry in CATALOG.items():
            for text in entry.values():
                assert name not in (text or ""), key


def test_dataset_columns_and_pipeline_ids_are_not_in_the_catalog():
    for value in (NEVER_TRANSLATE["kolom_dataset"]
                  + NEVER_TRANSLATE["identitas_pipeline"]
                  + NEVER_TRANSLATE["field_kontrak"]):
        for key, entry in CATALOG.items():
            for lang, text in entry.items():
                assert (text or "").strip() != value, (key, lang, value)


def test_algorithm_and_metric_terms_stay_as_they_are():
    """Dipakai apa adanya di kedua bahasa — itu memang istilah lazimnya."""
    for value in (NEVER_TRANSLATE["nama_algoritma"]
                  + NEVER_TRANSLATE["istilah_metrik"]):
        assert is_protected(value)


def test_research_admin_is_spelled_the_same_in_both_languages():
    entry = CATALOG["mode.research_admin"]
    assert entry["id"] == entry["en"] == "Research Admin"


# ── Pengenal halaman TIDAK ikut diterjemahkan ────────────────────────────

def test_page_identifiers_stay_canonical_while_labels_translate():
    """Routing memakai pengenal; bahasa hanya mengubah tulisannya.

    Kalau pengenalnya ikut berubah, berpindah bahasa akan memutus routing dan
    membuang halaman aktif — persis yang dilarang butir 15.
    """
    app_src = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    assert '_PAGES = ("Progress & Status", "Run Experiment", ' \
           '"Add Pipeline & Dataset")' in app_src
    assert "_PAGE_LABEL_KEYS" in app_src
    # Hasil menu dipetakan KEMBALI ke pengenal.
    assert "_PAGES[labels.index(chosen)]" in app_src


def test_the_breadcrumb_translates_the_label_not_the_identifier():
    assert chrome.page_label("Run Experiment") == "Jalankan Eksperimen"
    # Pengenal tak dikenal dipakai apa adanya, bukan dihilangkan.
    assert chrome.page_label("Halaman Baru") == "Halaman Baru"
    assert "Jalankan Eksperimen" in chrome.breadcrumb_text("Run Experiment")


# ── Pengalih bahasa ──────────────────────────────────────────────────────

def test_switching_language_writes_only_the_language_key():
    """Inilah yang membuat berpindah bahasa tidak dapat mengganggu apa pun."""
    func = next(n for n in ast.walk(ast.parse(
        (REPO_ROOT / "ui" / "components"
         / "language_switch.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == "_apply")

    written = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    written.add(ast.dump(target.slice))
    assert len(written) == 1, written
    assert "LANG_KEY" in next(iter(written))


def test_the_switch_never_calls_rerun():
    """`on_change` sudah memicu satu rerun; rerun kedua = kedipan.

    Diperiksa lewat AST: docstring modul ini justru MENJELASKAN aturan tersebut,
    jadi pencarian teks akan menuduh penjelasannya sendiri.
    """
    tree = ast.parse((REPO_ROOT / "ui" / "components"
                      / "language_switch.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "rerun", ast.dump(node)


def test_the_switch_is_available_to_everyone():
    """Bahasa antarmuka bukan hak istimewa."""
    src = (REPO_ROOT / "ui" / "components"
           / "language_switch.py").read_text(encoding="utf-8")
    for gate in ("can_upload", "can_approve", "can_manage_users",
                 "current_user", "require_"):
        assert gate not in src, gate


def test_the_widget_key_differs_from_the_state_key():
    """Satu kunci untuk dua peran adalah sebab kedipan pada pemilih mode."""
    assert ls.WIDGET_KEY != LANG_KEY


# ── AppTest: dua bahasa × tiga status pengguna ───────────────────────────

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIB = {"username": "andi", "role": "contributor", "status": "active"}
USERS = {"pengunjung": None, "kontributor": CONTRIB, "research_admin": ADMIN}
PAGES = ("Progress & Status", "Run Experiment", "Add Pipeline & Dataset")


def _app(tmp_path, name, **state):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / name
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        "from ui.components.sidebar_chrome import render_breadcrumb\n"
        "from ui.views.login import render_mode_switch\n"
        "page = st.session_state.get('_current_page', 'Run Experiment')\n"
        "render_breadcrumb(page)\n"
        "render_mode_switch()\n",
        encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=120)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


@pytest.mark.parametrize("lang", ["id", "en"])
@pytest.mark.parametrize("who", sorted(USERS))
def test_the_shell_renders_in_both_languages_for_every_user(tmp_path, lang, who):
    state = {LANG_KEY: lang}
    if USERS[who]:
        state["auth_user"] = USERS[who]
    at = _app(tmp_path, f"shell_{lang}_{who}.py", **state)
    assert not at.exception, (lang, who, at.exception)


@pytest.mark.parametrize("lang,expected", [("id", "Jalankan Eksperimen"),
                                           ("en", "Run Experiment")])
def test_the_breadcrumb_follows_the_language(tmp_path, lang, expected):
    at = _app(tmp_path, f"crumb_{lang}.py",
              **{LANG_KEY: lang, "_current_page": "Run Experiment"})
    joined = " ".join(m.value for m in at.markdown)
    assert expected in joined


@pytest.mark.parametrize("lang,expected", [("id", "Pengunjung"),
                                           ("en", "Visitor")])
def test_the_mode_picker_follows_the_language(tmp_path, lang, expected):
    at = _app(tmp_path, f"mode_{lang}.py", **{LANG_KEY: lang})
    assert at.selectbox[0].value == expected


def test_switching_language_keeps_the_page_and_the_users_choices(tmp_path):
    """Butir 15: bahasa tidak boleh mengubah halaman, pilihan, atau dialog."""
    keep = {
        "_current_page": "Run Experiment",
        "_selected_dataset": "HIKARI2021",
        "_selected_pipeline": "hikari2021.dt_pipeline",
        "_auth_dialog": "login",
        "_running_watch": [1, 2, 3],
    }
    at = _app(tmp_path, "keep.py", **{LANG_KEY: "id", **keep})
    assert at.session_state["_current_page"] == "Run Experiment"

    # Berpindah bahasa lewat mekanisme yang sebenarnya.
    at.session_state[ls.WIDGET_KEY] = "en"
    at.session_state[LANG_KEY] = "en"
    at.run()

    assert not at.exception
    for key, value in keep.items():
        assert at.session_state[key] == value, key
    # …dan tampilannya memang sudah berganti bahasa.
    assert at.selectbox[0].value == "Visitor"


def test_the_language_choice_survives_across_runs(tmp_path):
    at = _app(tmp_path, "persist.py", **{LANG_KEY: "en"})
    for _ in range(3):
        at.run()
        assert at.session_state[LANG_KEY] == "en"
    assert at.selectbox[0].value == "Visitor"
