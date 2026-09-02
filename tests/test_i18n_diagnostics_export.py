"""
Tahap 3A — kalimat diagnosa, kolom keterangan ekspor, dan teks tertanam.

Yang paling mudah rusak di sini bukan terjemahannya, melainkan KEPUTUSAN
diagnosa: dataset yang dulu dinyatakan tidak cocok harus tetap tidak cocok,
dengan status pemeriksaan yang sama persis. Karena itu berkas ini dibuka dengan
test regresi keputusan, baru kemudian test bahasa.
"""
import ast
import shutil
from pathlib import Path

import pytest

from orchestrator.dataset_diagnostics import diagnose_dataset
from ui.components.validator_messages import (
    diagnostic_message, diagnostic_title, run_mode_badge_text,
)
from ui.i18n import CATALOG, untranslated_report
import ui.i18n.core as core

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Berkas contoh HARUS berada DI DALAM proyek: `resolve_dataset_path` menolak
#: lintasan di luarnya (pengaman path traversal), jadi `tmp_path` tidak bisa
#: dipakai untuk diagnosa.
PROBE_DIR = REPO_ROOT / "storage" / "_diag_test"

HEAD = "uid,originh,responh,flow_duration,fwd_pkts_tot,Label,traffic_category"


def _rows(maker, n):
    return "\n".join([HEAD] + [maker(i) for i in range(n)])


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


@pytest.fixture(scope="module")
def samples():
    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    def write(name, text):
        path = PROBE_DIR / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def mixed(i):
        kind = "Benign" if i % 2 == 0 else "Bruteforce"
        return f"u{i},10.0.0.{i},10.0.1.{i},{i}.5,{i},{i % 2},{kind}"

    def single(i):
        return f"u{i},10.0.0.{i},10.0.1.{i},{i}.5,{i},0,Benign"

    def texty(i):
        kind = "Benign" if i % 2 == 0 else "Bruteforce"
        return f"u{i},10.0.0.{i},10.0.1.{i},lama,banyak,{i % 2},{kind}"

    no_label = "\n".join(["uid,originh,flow_duration"]
                         + [f"u{i},10.0.0.{i},{i}.0" for i in range(20)])
    ndjson_line = '{"a": 1}'

    made = {
        "cocok": write("ok.csv", _rows(mixed, 40)),
        "label_hilang": write("no_label.csv", no_label),
        "format_salah": write("wrong.ndjson",
                              "\n".join([ndjson_line] * 10)),
        "satu_kelas": write("one_class.csv", _rows(single, 30)),
        "fitur_non_numerik": write("text_feat.csv", _rows(texty, 30)),
    }
    yield made
    shutil.rmtree(PROBE_DIR, ignore_errors=True)


#: Keputusan yang direkam SEBELUM Tahap 3A menyentuh apa pun.
DECISIONS = {
    "cocok": (False, [("format", "pass"), ("label", "pass"),
                      ("features", "fail"), ("dtype", "pass"),
                      ("classes", "pass")]),
    "label_hilang": (False, [("format", "pass"), ("label", "fail"),
                             ("features", "fail"), ("dtype", "pass"),
                             ("classes", "skip")]),
    "format_salah": (False, [("format", "fail"), ("label", "skip"),
                             ("features", "skip"), ("dtype", "skip"),
                             ("classes", "skip")]),
    "satu_kelas": (False, [("format", "pass"), ("label", "pass"),
                           ("features", "fail"), ("dtype", "pass"),
                           ("classes", "fail")]),
    "fitur_non_numerik": (False, [("format", "pass"), ("label", "pass"),
                                  ("features", "fail"), ("dtype", "warn"),
                                  ("classes", "pass")]),
}


# ── REGRESI KEPUTUSAN ────────────────────────────────────────────────────

@pytest.mark.parametrize("case", sorted(DECISIONS))
def test_the_diagnostic_decision_is_unchanged(samples, case):
    """Status tiap pemeriksaan & hasil kecocokan SAMA PERSIS."""
    compatible, decisions = DECISIONS[case]
    result = diagnose_dataset(samples[case], "HIKARI2021")

    assert bool(result["compatible"]) is compatible, case
    assert [(c["key"], c["status"]) for c in result["checks"]] == decisions, case


@pytest.mark.parametrize("case", sorted(DECISIONS))
def test_the_decision_does_not_depend_on_the_language(samples, case):
    core.st.session_state[core.LANG_KEY] = "id"
    a = diagnose_dataset(samples[case], "HIKARI2021")
    core.st.session_state[core.LANG_KEY] = "en"
    b = diagnose_dataset(samples[case], "HIKARI2021")

    assert a["compatible"] == b["compatible"]
    assert [(c["key"], c["status"], c.get("count")) for c in a["checks"]] == \
           [(c["key"], c["status"], c.get("count")) for c in b["checks"]]


def test_the_stored_message_field_never_changes(samples):
    """`message` adalah field LAMA — tetap Indonesia di bahasa mana pun."""
    core.st.session_state[core.LANG_KEY] = "id"
    a = diagnose_dataset(samples["cocok"], "HIKARI2021")
    core.st.session_state[core.LANG_KEY] = "en"
    b = diagnose_dataset(samples["cocok"], "HIKARI2021")
    assert [c["message"] for c in a["checks"]] == \
           [c["message"] for c in b["checks"]]


def test_every_diagnostic_check_carries_a_message_key():
    """Tanpa kunci, kalimatnya berhenti di bahasa Indonesia."""
    src = (REPO_ROOT / "orchestrator"
           / "dataset_diagnostics.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "DiagnosticCheck"]
    assert calls
    for call in calls:
        assert any(k.arg == "msg_key" for k in call.keywords), \
            ast.dump(call)[:140]


# ── Kalimat mengikuti bahasa ─────────────────────────────────────────────

def test_diagnostic_sentences_follow_the_language(samples):
    result = diagnose_dataset(samples["fitur_non_numerik"], "HIKARI2021")
    dtype = next(c for c in result["checks"] if c["key"] == "dtype")

    core.st.session_state[core.LANG_KEY] = "id"
    indonesian = diagnostic_message(dtype)
    core.st.session_state[core.LANG_KEY] = "en"
    english = diagnostic_message(dtype)

    assert indonesian != english
    assert "bukan numerik" in indonesian
    assert "not numeric" in english


def test_diagnostic_titles_follow_the_language(samples):
    result = diagnose_dataset(samples["cocok"], "HIKARI2021")
    label = next(c for c in result["checks"] if c["key"] == "label")

    core.st.session_state[core.LANG_KEY] = "id"
    assert diagnostic_title(label) == "Kolom label"
    core.st.session_state[core.LANG_KEY] = "en"
    assert diagnostic_title(label) == "Label column"


# ── Nilai sisipan TIDAK diterjemahkan ────────────────────────────────────

def test_column_names_and_counts_are_never_translated(samples):
    result = diagnose_dataset(samples["fitur_non_numerik"], "HIKARI2021")
    dtype = next(c for c in result["checks"] if c["key"] == "dtype")
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        text = diagnostic_message(dtype)
        assert "flow_duration" in text, lang        # nama kolom apa adanya
        assert str(dtype["count"]) in text, lang    # jumlah apa adanya


def test_the_label_column_name_survives_both_languages(samples):
    result = diagnose_dataset(samples["label_hilang"], "HIKARI2021")
    label = next(c for c in result["checks"] if c["key"] == "label")
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        assert "Label" in diagnostic_message(label), lang


def test_the_required_format_is_named_in_both_languages(samples):
    """Saran tindakan harus tetap DAPAT DITINDAKLANJUTI."""
    result = diagnose_dataset(samples["format_salah"], "HIKARI2021")
    fmt = next(c for c in result["checks"] if c["key"] == "format")
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        text = diagnostic_message(fmt)
        assert "CSV" in text, lang           # format yang DIBUTUHKAN disebut
        assert "NDJSON" in text, lang        # format yang TERDETEKSI disebut


# ── Dilewati BUKAN gagal ─────────────────────────────────────────────────

def test_a_skipped_check_says_skipped_not_failed(samples):
    result = diagnose_dataset(samples["format_salah"], "HIKARI2021")
    skipped = [c for c in result["checks"] if c["status"] == "skip"]
    assert skipped

    core.st.session_state[core.LANG_KEY] = "id"
    assert "Tidak diperiksa" in diagnostic_message(skipped[0])
    core.st.session_state[core.LANG_KEY] = "en"
    english = diagnostic_message(skipped[0])
    assert "Not checked" in english
    assert "failed" not in english.lower()


# ── Keterangan WAJIB ─────────────────────────────────────────────────────

def test_the_eve_label_note_keeps_its_meaning():
    """Label EVE DITURUNKAN dari alert Suricata — bukan kolom yang kurang."""
    for lang, ideas in (("id", ["tidak perlu ada", "alert Suricata"]),
                        ("en", ["does not need to exist", "Suricata alerts"])):
        text = CATALOG["dx.eve_label_derived"][lang]
        for idea in ideas:
            assert idea in text, (lang, idea)


def test_the_sample_based_note_survives_in_both_languages():
    for lang, ideas in (("id", ["cuplikan", "bukan seluruh"]),
                        ("en", ["sample", "not the whole"])):
        text = CATALOG["dx.sample_note"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


# ── Ekspor CSV ───────────────────────────────────────────────────────────

def _export(lang):
    import ui.components.experiment_table as et

    core.st.session_state[core.LANG_KEY] = lang
    columns = [c for c in et.build_columns()
               if c["key"] in ("pipeline", "accuracy")]
    rows = [{"id": "e1", "pipeline": "hikari2021.dt_pipeline",
             "accuracy": 0.9, "dataset": "HIKARI2021", "_mode": "exploration"}]
    return et.to_csv(rows, columns)


def test_the_note_columns_are_translated():
    for lang, expected in (("id", ["Semantik metrik", "Mode eksekusi",
                                   "Parameter dipakai"]),
                           ("en", ["Metric semantics", "Run mode",
                                   "Parameters used"])):
        header = _export(lang).splitlines()[0]
        for column in expected:
            assert column in header, (lang, column)


def test_the_data_column_names_never_change():
    """Berkas diolah lintas bahasa: skrip yang mencari "Accuracy" harus tetap
    menemukannya berapa pun bahasa saat ekspor dibuat."""
    for lang in ("id", "en"):
        header = _export(lang).splitlines()[0]
        assert "Pipeline" in header, lang
        assert "Accuracy" in header, lang


def test_the_metric_semantics_note_survives_in_both_languages():
    """Tanpa baris ini, angka HIKARI & EVE terbaca seolah setara."""
    for lang, idea in (("id", "rata-rata berbobot"),
                       ("en", "weighted average")):
        body = _export(lang).splitlines()[1]
        assert "HIKARI2021" in body       # nama keluarga TIDAK diterjemahkan
        assert idea in body, (lang, idea)


def test_the_run_mode_note_survives_in_both_languages():
    for lang, badge in (("id", "Eksplorasi"), ("en", "Exploration")):
        assert badge in _export(lang).splitlines()[1], lang


def test_the_pipeline_name_is_never_translated_in_the_export():
    for lang in ("id", "en"):
        assert "hikari2021.dt_pipeline" in _export(lang), lang


def test_the_old_export_constants_are_unchanged():
    """Diimpor & diuji test lama — nilainya tidak boleh bergeser."""
    import ui.components.experiment_table as et

    assert et.CSV_SEMANTICS_COLUMN == "Semantik metrik"
    assert et.CSV_MODE_COLUMN == "Mode eksekusi"
    assert et.CSV_PARAMS_COLUMN == "Parameter dipakai"


def test_the_run_mode_module_stays_language_free():
    """`orchestrator/run_mode` adalah lapisan logika — tidak tahu soal bahasa."""
    from orchestrator import run_mode as rm

    assert rm.RUN_MODE_BADGES["official"] == "🔒 Resmi"
    assert rm.RUN_MODE_LABELS["exploration"] == "Run eksplorasi"
    src = (REPO_ROOT / "orchestrator" / "run_mode.py").read_text(encoding="utf-8")
    assert "ui.i18n" not in src
    assert "from ui." not in src


def test_the_run_mode_badge_follows_the_language():
    core.st.session_state[core.LANG_KEY] = "id"
    assert run_mode_badge_text("official") == "🔒 Resmi"
    core.st.session_state[core.LANG_KEY] = "en"
    assert run_mode_badge_text("official") == "🔒 Official"


# ── Perenderan diagnosa tidak bergantung pada TEKS ───────────────────────

def test_the_renderer_groups_by_key_not_by_sentence():
    """Mengelompokkan skip berdasarkan kalimat akan berhenti bekerja saat
    bahasanya berganti — kuncinya yang stabil."""
    src = (REPO_ROOT / "ui" / "views"
           / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("skip_groups: dict[str, list[str]] = {}")[1][:1400]
    assert "msg_key" in body
    # Satuan kolom/kunci JSON ditentukan dari KUNCI, bukan dari isi kalimat.
    assert 'c["message"].find(' not in src


# ── Kamus tetap lengkap ──────────────────────────────────────────────────

def test_the_catalog_has_no_half_finished_key():
    report = untranslated_report()
    assert report["id"]["missing"] == []
    assert report["en"]["missing"] == []
    assert report["en"]["percent"] == 100.0


# ── Jebakan: t() di TINGKAT MODUL ────────────────────────────────────────

def test_no_module_level_constant_is_frozen_to_one_language():
    """Konstanta modul dievaluasi SEKALI saat impor.

    Mengisinya dengan hasil `t()` mengunci teksnya pada bahasa yang kebetulan
    aktif saat modul pertama diimpor — dan teks itu tidak akan pernah ikut
    berganti bahasa lagi. Kegagalannya senyap, jadi dijaga di sini.
    """
    offenders = []
    for path in sorted((REPO_ROOT / "ui").rglob("*.py")):
        if "i18n" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:              # HANYA tingkat modul
            if not isinstance(node, ast.Assign):
                continue
            for child in ast.walk(node.value):
                if (isinstance(child, ast.Call)
                        and getattr(child.func, "id", "") == "t"):
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    offenders.append(f"{rel}:{node.lineno}")
                    break
    assert not offenders, offenders
