"""
Tahap 4A — panduan kontrak pipeline dalam dua bahasa.

Bagian ini memuat NAMA FIELD dan POTONGAN KODE yang disalin apa adanya oleh
pengunggah; menerjemahkannya akan menghasilkan kode yang tidak berjalan. Yang
berbahasa hanya penjelasan di sekitarnya.

Tiga rumusan di sini tidak boleh melemah pada bahasa mana pun:

* **daftar larangan** — ia yang memisahkan masukan yang dikendalikan pengguna
  dari parameter yang ditetapkan eksperimen;
* **pembagian tahapan** — mana yang dikerjakan platform, mana pipeline;
* **wajib vs disarankan** pada isi ``get_info()``.
"""
from pathlib import Path

import pytest

from ui.components import instructions as ins
from ui.i18n import CATALOG, untranslated_report
import ui.i18n.core as core

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── Konstanta lama tidak tersentuh ───────────────────────────────────────

def test_the_old_constants_are_unchanged():
    """Diimpor & diuji test lama; nama tahap dipakai sebagai KUNCI di sana."""
    names = {name for _n, name, _o, _note in ins.EXECUTION_STAGES}
    assert "Validasi masukan" in names
    assert "Simpan artefak" in names
    assert ins.FORBIDDEN_ACTIONS[0] == "Mengubah dataset asli."
    assert "bukan wajib" in ins.SUGGESTED_INFO_NOTE
    assert "anti-kebocoran" in ins.ANTI_LEAK_NOTE


def test_the_constants_do_not_depend_on_the_language():
    """Konstanta modul dievaluasi sekali saat impor — ia tidak boleh berbahasa."""
    core.st.session_state[core.LANG_KEY] = "en"
    assert ins.FORBIDDEN_ACTIONS[0] == "Mengubah dataset asli."
    assert ins.EXECUTION_STAGES[0][1] == "Validasi masukan"


# ── Tampilan mengikuti bahasa ────────────────────────────────────────────

def test_the_stages_follow_the_language():
    core.st.session_state[core.LANG_KEY] = "id"
    indonesian = ins.execution_stages_display()
    core.st.session_state[core.LANG_KEY] = "en"
    english = ins.execution_stages_display()

    assert indonesian[0][1] == "Validasi masukan"
    assert english[0][1] == "Validate input"
    # Struktur & jumlah tahap TIDAK berubah.
    assert len(indonesian) == len(english) == len(ins.EXECUTION_STAGES)


def test_switching_back_restores_indonesian():
    core.st.session_state[core.LANG_KEY] = "en"
    assert ins.execution_stages_display()[0][1] == "Validate input"
    core.st.session_state[core.LANG_KEY] = "id"
    assert ins.execution_stages_display()[0][1] == "Validasi masukan"


# ── Pembagian tugas tetap jelas ──────────────────────────────────────────

@pytest.mark.parametrize("lang", ["id", "en"])
def test_the_owner_of_each_stage_never_changes(lang):
    """Pemilik tahap adalah PENGENAL, bukan teks — ia tidak berbahasa."""
    core.st.session_state[core.LANG_KEY] = lang
    owners = {number: owner for number, _name, owner, _note
              in ins.execution_stages_display()}
    # Tahap 1 & 8 dikerjakan PLATFORM, sisanya PIPELINE.
    assert owners[1] == ins.OWNER_PLATFORM, lang
    assert owners[8] == ins.OWNER_PLATFORM, lang
    for number in (2, 3, 4, 5, 6, 7, 9):
        assert owners[number] == ins.OWNER_PIPELINE, (lang, number)


def test_the_platform_stages_say_so_in_both_languages():
    """Jangan menyiratkan pipeline mengerjakan tahap milik orchestrator."""
    for lang, ideas in (("id", ["platform", "sebelum pipeline dipanggil"]),
                        ("en", ["platform", "before the pipeline is called"])):
        text = CATALOG["ins.stage1_note"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)

    for lang, idea in (("id", "ditulis platform"), ("en", "by the platform")):
        assert idea.lower() in CATALOG["ins.stage8_note"][lang].lower(), lang


# ── Daftar larangan tetap TEGAS ──────────────────────────────────────────

def test_every_forbidden_action_is_translated():
    core.st.session_state[core.LANG_KEY] = "en"
    english = ins.forbidden_actions_display()
    assert len(english) == len(ins.FORBIDDEN_ACTIONS)
    for text in english:
        assert text and text not in ins.FORBIDDEN_ACTIONS


FORBIDDEN_IDEAS = [
    ("ins.forbid_dataset", ["dataset asli"], ["original dataset"]),
    ("ins.forbid_params", ["terkunci", "saat berjalan", "run eksplorasi"],
     ["locked", "run time", "exploration run"]),
    ("ins.forbid_fit_test", ["fit", "data uji"], ["fitting", "test data"]),
    ("ins.forbid_algorithm", ["mengganti algoritma"], ["swapping the algorithm"]),
    ("ins.forbid_features", ["seleksi fitur", "tidak dideklarasikan"],
     ["feature selection", "without declaring"]),
]


@pytest.mark.parametrize("key,id_ideas,en_ideas", FORBIDDEN_IDEAS,
                         ids=[f[0] for f in FORBIDDEN_IDEAS])
def test_a_forbidden_action_is_never_softened(key, id_ideas, en_ideas):
    """Diperhalus sampai kabur = larangan yang tidak lagi memisahkan apa pun."""
    for lang, ideas in (("id", id_ideas), ("en", en_ideas)):
        text = CATALOG[key][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (key, lang, idea)


def test_the_framing_sentence_keeps_its_reason():
    for lang, ideas in (("id", ["memisahkan", "perbandingan yang adil",
                                "dapat diulang"]),
                        ("en", ["separates", "fair", "repeatable"])):
        text = CATALOG["ins.forbid_frame"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


# ── Wajib vs disarankan ──────────────────────────────────────────────────

def test_required_and_suggested_stay_distinguishable():
    for lang, required, suggested in (
            ("id", "wajib", "disarankan"), ("en", "required", "suggested")):
        req = CATALOG["ins.required_info"][lang].lower()
        sug = CATALOG["ins.suggested_info"][lang].lower()
        assert required in req, lang
        assert suggested in sug, lang
        # "Disarankan" harus menyatakan TIDAK diperiksa validator.
        assert ("tidak diperiksa" in sug) or ("does not check" in sug), lang


# ── Keterangan wajib platform ────────────────────────────────────────────

def test_the_static_check_note_is_present_in_both_languages():
    for lang, ideas in (("id", ["statis", "dibaca", "tidak dijalankan"]),
                        ("en", ["static", "read", "never executed"])):
        text = CATALOG["ins.static_check"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


def test_pass_is_not_active_is_present_in_both_languages():
    for lang, ideas in (("id", ["tidak berarti", "aktif", "tinjauan"]),
                        ("en", ["does not make", "active", "review"])):
        text = CATALOG["ins.pass_not_active"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


def test_the_anti_leak_rule_keeps_its_order():
    """Urutannya yang menjadi aturan: split DULU, baru fit."""
    for lang, ideas in (("id", ["split dulu", "hanya pada data latih"]),
                        ("en", ["split first", "only on the training data"])):
        text = CATALOG["ins.anti_leak"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


# ── Nama field & potongan kode TIDAK diterjemahkan ───────────────────────

FIELD_NAMES = ("fixed_params", "PipelineResult", "get_info", "BasePipeline",
               "preprocessing_steps", "feature_selection")


@pytest.mark.parametrize("field", FIELD_NAMES)
def test_a_contract_field_name_is_identical_in_both_languages(field):
    """Pengunggah menyalinnya apa adanya — menerjemahkannya = kode tidak jalan."""
    for key, entry in CATALOG.items():
        id_text = entry.get("id") or ""
        en_text = entry.get("en") or ""
        if field in id_text:
            assert field in en_text, (key, field)


def test_the_code_skeleton_is_never_translated():
    """Kerangka kelas dibangun dari nama field NYATA, bukan dari kamus."""
    skeleton = ins.contract_skeleton()
    assert "class" in skeleton
    assert "BasePipeline" in skeleton
    core.st.session_state[core.LANG_KEY] = "en"
    assert ins.contract_skeleton() == skeleton


def test_the_guide_module_never_freezes_a_translation():
    """Konstanta modul tidak boleh diisi hasil `t()` — ia beku saat impor."""
    import ast

    src = (REPO_ROOT / "ui" / "components"
           / "instructions.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign):
            continue
        for child in ast.walk(node.value):
            assert not (isinstance(child, ast.Call)
                        and getattr(child.func, "id", "") == "t"), node.lineno


# ── Kamus ────────────────────────────────────────────────────────────────

def test_the_catalog_stays_complete():
    report = untranslated_report()
    assert report["id"]["missing"] == []
    assert report["en"]["missing"] == []
