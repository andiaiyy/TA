"""
Tahap 3 — pesan sistem dalam dua bahasa, KEPUTUSAN tidak berubah.

Yang paling mudah rusak pada tahap ini bukan terjemahannya, melainkan
keputusannya: sebuah berkas yang dulu ditolak harus tetap ditolak, dengan
temuan yang sama, di baris yang sama. Karena itu berkas ini memuat **test
regresi keputusan** lebih dulu, baru kemudian test bahasa.
"""
import sqlite3
from pathlib import Path

import pytest

from orchestrator.pipeline_validator import (
    FAIL, FORBIDDEN_CALLS, FORBIDDEN_MODULES, PASS, WARN,
    ValidationCheck, validate_pipeline_source,
)
from ui.components.validator_messages import (
    REASON_EN, check_message, reason_text,
)
from ui.i18n import CATALOG
import ui.i18n.core as core

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Contoh berkas — sama dengan yang dipakai test lama ───────────────────

VALID = '''
from pipelines.base import BasePipeline


class Good(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return {"ok": True}

    def get_info(self):
        return {"paper": "P", "algorithm": "A"}
'''

NO_BASE = '''
class Orphan:
    def run(self, pipeline_input, progress=None):
        return 1

    def get_info(self):
        return {}
'''

FORBIDDEN_MODULE = VALID.replace(
    "from pipelines.base import BasePipeline",
    "import subprocess\nfrom pipelines.base import BasePipeline")

FORBIDDEN_CALL = VALID.replace('return {"ok": True}', 'return eval("1 + 1")')

MISSING_METHOD = '''
from pipelines.base import BasePipeline


class Half(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return 1
'''

BROKEN = "def broken(:\n    pass\n"

#: Keputusan yang direkam SEBELUM Tahap 3 menyentuh apa pun.
#: (valid, jumlah check, himpunan status)
DECISIONS = {
    "valid": (VALID, True, 6, {PASS, WARN}),
    "tanpa_kelas_dasar": (NO_BASE, False, 2, {PASS, FAIL}),
    "modul_terlarang": (FORBIDDEN_MODULE, False, 7, {PASS, WARN, FAIL}),
    "pemanggilan_terlarang": (FORBIDDEN_CALL, False, 7, {PASS, WARN, FAIL}),
    "metode_kurang": (MISSING_METHOD, False, 5, {PASS, FAIL}),
    "sintaks_rusak": (BROKEN, False, 1, {FAIL}),
}


@pytest.fixture(autouse=True)
def indonesian():
    """Tiap test mulai dari bahasa bawaan, apa pun urutan jalannya."""
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── REGRESI KEPUTUSAN ────────────────────────────────────────────────────

@pytest.mark.parametrize("case", sorted(DECISIONS))
def test_the_validator_decision_is_unchanged(case):
    """Status & jumlah temuan HARUS sama seperti sebelum Tahap 3."""
    source, valid, n_checks, statuses = DECISIONS[case]
    report = validate_pipeline_source(source, f"{case}.py")

    assert report.valid is valid, case
    assert len(report.checks) == n_checks, (case, len(report.checks))
    assert {c.status for c in report.checks} == statuses, case


@pytest.mark.parametrize("case", sorted(DECISIONS))
def test_the_decision_does_not_depend_on_the_language(case):
    """Bahasa mengubah KALIMAT, tidak pernah keputusan."""
    source = DECISIONS[case][0]

    core.st.session_state[core.LANG_KEY] = "id"
    a = validate_pipeline_source(source, f"{case}.py")
    core.st.session_state[core.LANG_KEY] = "en"
    b = validate_pipeline_source(source, f"{case}.py")

    assert a.valid == b.valid
    assert [(c.name, c.status, c.line) for c in a.checks] == \
           [(c.name, c.status, c.line) for c in b.checks]


def test_the_stored_message_stays_indonesian_so_old_artifacts_are_untouched():
    """``message`` adalah nilai yang dicatat & diuji test lama.

    Ia sengaja TIDAK berubah: artefak dan pengajuan lama menyimpan kalimat ini
    apa adanya, dan mengubahnya berarti mengubah data lama.
    """
    report = validate_pipeline_source(FORBIDDEN_MODULE, "x.py")
    failure = next(c for c in report.checks if c.status == FAIL)
    assert "tidak diizinkan" in failure.message
    core.st.session_state[core.LANG_KEY] = "en"
    again = validate_pipeline_source(FORBIDDEN_MODULE, "x.py")
    assert next(c for c in again.checks
                if c.status == FAIL).message == failure.message


# ── Kalimat mengikuti bahasa ─────────────────────────────────────────────

def test_the_message_follows_the_active_language():
    report = validate_pipeline_source(FORBIDDEN_MODULE, "x.py")
    failure = next(c for c in report.checks if c.status == FAIL)

    core.st.session_state[core.LANG_KEY] = "id"
    indonesian_text = check_message(failure)
    core.st.session_state[core.LANG_KEY] = "en"
    english_text = check_message(failure)

    assert indonesian_text != english_text
    assert "tidak diizinkan" in indonesian_text
    assert "is not allowed" in english_text


def test_a_check_without_a_key_still_reads():
    """Pemeriksaan lama tanpa kunci tetap terbaca, tidak kosong."""
    check = ValidationCheck("x", FAIL, "Kalimat lama.", 3)
    core.st.session_state[core.LANG_KEY] = "en"
    assert check_message(check) == "Kalimat lama."


def test_check_message_accepts_the_flattened_dict_form():
    """Hasil validasi kadang sudah menjadi JSON sebelum sampai ke tampilan."""
    report = validate_pipeline_source(FORBIDDEN_MODULE, "x.py")
    flat = report.to_dict()["checks"]
    core.st.session_state[core.LANG_KEY] = "en"
    messages = [check_message(c) for c in flat]
    assert any("is not allowed" in m for m in messages)


# ── Nilai sisipan TIDAK diterjemahkan ────────────────────────────────────

def test_inserted_values_are_never_translated():
    """Nama modul, nama pemanggilan, dan nomor baris tetap apa adanya."""
    report = validate_pipeline_source(FORBIDDEN_MODULE, "x.py")
    failure = next(c for c in report.checks if c.status == FAIL)
    assert failure.values["module"] == "subprocess"
    assert failure.values["line"] == 2

    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        text = check_message(failure)
        assert "subprocess" in text, lang        # nama modul apa adanya
        assert "2" in text, lang                 # nomor baris apa adanya


def test_the_line_number_survives_into_both_languages():
    report = validate_pipeline_source(FORBIDDEN_CALL, "x.py")
    failure = next(c for c in report.checks if c.status == FAIL)
    assert failure.line is not None
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        assert str(failure.line) in check_message(failure), lang


# ── Alasan penolakan tetap SPESIFIK ──────────────────────────────────────

def test_every_forbidden_reason_has_an_english_counterpart():
    """Tanpa ini, kalimat Inggris memuat potongan bahasa Indonesia."""
    reasons = set(FORBIDDEN_MODULES.values()) | set(FORBIDDEN_CALLS.values())
    missing = sorted(r for r in reasons if r not in REASON_EN)
    assert not missing, missing


def test_the_security_reason_is_never_generalised():
    """"Kode tidak aman" tidak cukup — sebabnya harus disebut."""
    report = validate_pipeline_source(FORBIDDEN_MODULE, "x.py")
    failure = next(c for c in report.checks if c.status == FAIL)

    core.st.session_state[core.LANG_KEY] = "en"
    text = check_message(failure)
    assert "runs another process" in text        # sebab yang SPESIFIK
    assert "unsafe code" not in text.lower()
    assert "not safe" not in text.lower()


@pytest.mark.parametrize("module,reason", sorted(FORBIDDEN_MODULES.items()))
def test_each_forbidden_module_keeps_its_own_reason(module, reason):
    core.st.session_state[core.LANG_KEY] = "en"
    english = reason_text(reason)
    assert english
    # Sebabnya diterjemahkan, bukan dibuang.
    if reason in REASON_EN:
        assert english == REASON_EN[reason]


def test_reason_text_is_a_passthrough_in_indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    for reason in FORBIDDEN_MODULES.values():
        assert reason_text(reason) == reason


def test_an_unknown_reason_is_passed_through_rather_than_dropped():
    core.st.session_state[core.LANG_KEY] = "en"
    assert reason_text("sebab yang belum terdaftar") == "sebab yang belum terdaftar"


# ── Keterangan WAJIB ─────────────────────────────────────────────────────

MANDATORY = [
    ("vc.static_only", ["statis", "tidak dijalankan"],
     ["static", "never executed"]),
    ("vc.pass_is_not_active", ["tidak berarti", "aktif"],
     ["does not", "active"]),
    ("vc.sample_based", ["cuplikan", "bukan seluruh"],
     ["sample", "not the whole"]),
    ("vc.metric_semantics", ["tidak selalu bermakna sama", "satu keluarga"],
     ["do not mean the same", "one family"]),
    ("vc.run_mode_note", ["resmi", "eksplorasi", "terkunci"],
     ["official", "exploration", "locked"]),
    ("vc.old_versions_kept", ["versi lama", "tertelusur"],
     ["older versions", "traceable"]),
]


@pytest.mark.parametrize("key,id_ideas,en_ideas", MANDATORY,
                         ids=[m[0] for m in MANDATORY])
def test_mandatory_notes_mean_the_same_in_both_languages(key, id_ideas,
                                                         en_ideas):
    assert key in CATALOG, key
    id_text = CATALOG[key]["id"].lower()
    en_text = CATALOG[key]["en"].lower()
    for idea in id_ideas:
        assert idea.lower() in id_text, (key, "id", idea)
    for idea in en_ideas:
        assert idea.lower() in en_text, (key, "en", idea)


# ── Log pengembang TIDAK diterjemahkan ───────────────────────────────────

def test_developer_logs_are_left_alone():
    """Log dibaca pengembang saat menelusuri galat — menerjemahkannya justru
    menyulitkan, dan ia tidak pernah sampai ke pengguna."""
    import ast

    src = (REPO_ROOT / "orchestrator"
           / "dataset_diagnostics.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("debug", "info", "warning", "error",
                                       "exception")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"):
            for arg in node.args:
                # Tidak ada log yang dibungkus t(...) — itu tandanya seseorang
                # keliru menerjemahkan log.
                assert not (isinstance(arg, ast.Call)
                            and getattr(arg.func, "id", "") == "t"), \
                    ast.dump(node)
