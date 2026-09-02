"""
Tahap 3B — pesan kesalahan pada JALUR GALAT.

Ini jalur yang berjalan justru ketika ada yang salah, jadi yang dijaga bukan
terjemahannya melainkan keutuhan jalurnya:

* jenis pengecualian & kondisi pemicu **tidak berubah**;
* tidak ada kesalahan yang **tertelan** — yang dulu sampai ke pengguna tetap
  sampai;
* pesan kegagalan yang **tersimpan** pada catatan lama tampil apa adanya;
* log pengembang **tidak** diterjemahkan.
"""
import ast
import sqlite3
from pathlib import Path

import pytest

from orchestrator.auth_service import (
    AuthError, PermissionDenied, require_approve, require_manage_users,
    require_upload,
)
from orchestrator.dynamic_registry import DynamicRegistryError, load_pipeline_class
from orchestrator.pipeline_versions import PipelineEditError
from orchestrator.run_mode import ParamError
from orchestrator.submission_service import SubmissionError
from orchestrator.user_errors import UserFacingMixin
from ui.components.validator_messages import error_message, stored_error_message
from ui.i18n import CATALOG, untranslated_report
import ui.i18n.core as core

REPO_ROOT = Path(__file__).resolve().parents[1]

CONTRIB = {"username": "andi", "role": "contributor", "status": "active"}
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}


@pytest.fixture(autouse=True)
def indonesian():
    core.st.session_state[core.LANG_KEY] = "id"
    yield
    core.st.session_state[core.LANG_KEY] = "id"


# ── Mekanisme ADITIF: str(exc) tidak berubah ─────────────────────────────

ERROR_CLASSES = [AuthError, PermissionDenied, SubmissionError,
                 DynamicRegistryError, PipelineEditError, ParamError]


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda c: c.__name__)
def test_the_exception_text_is_unchanged(cls):
    """`str(exc)` adalah nilai yang TERCATAT & diuji test lama."""
    exc = cls("pesan lama")
    assert str(exc) == "pesan lama"
    assert exc.key == ""
    assert exc.values == {}


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda c: c.__name__)
def test_the_marker_is_optional(cls):
    """Pengecualian tanpa kunci tetap bekerja & tetap tampil."""
    exc = cls("apa adanya")
    core.st.session_state[core.LANG_KEY] = "en"
    assert error_message(exc) == "apa adanya"


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda c: c.__name__)
def test_the_class_still_subclasses_its_original_base(cls):
    """Jenis pengecualian tidak berubah — `except` lama tetap menangkapnya."""
    assert issubclass(cls, Exception)
    assert issubclass(cls, UserFacingMixin)


def test_permission_denied_is_still_an_auth_error():
    """Hierarki pengecualian tidak boleh bergeser: `except AuthError` di UI
    harus tetap menangkap penolakan hak."""
    assert issubclass(PermissionDenied, AuthError)
    assert issubclass(SubmissionError, AuthError)
    assert issubclass(PipelineEditError, DynamicRegistryError)


# ── REGRESI: jenis & kondisi pemicu tetap sama ───────────────────────────

@pytest.mark.parametrize("gate,actor", [
    (require_approve, None), (require_approve, CONTRIB),
    (require_manage_users, None), (require_manage_users, CONTRIB),
])
def test_the_permission_gate_still_raises_the_same_type(gate, actor):
    with pytest.raises(PermissionDenied):
        gate(actor)


def test_an_allowed_actor_still_passes():
    """Kondisi pemicu tidak bergeser: yang berhak tetap lolos."""
    require_approve(ADMIN)
    require_manage_users(ADMIN)


def test_the_hash_mismatch_still_raises_and_is_not_swallowed(tmp_path):
    """Penanda INTEGRITAS: berkas berbeda dari yang tercatat."""
    entry = tmp_path / "up.py"
    entry.write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(DynamicRegistryError) as caught:
        load_pipeline_class(entry, "Up", "0" * 64)

    exc = caught.value
    assert exc.key == "err.hash_mismatch"
    # Kedua nilai hash ikut — itulah yang membuatnya dapat ditelusuri.
    assert exc.values["recorded"] == "0" * 12
    assert exc.values["found"]
    assert exc.values["file"] == "up.py"


def test_a_missing_pipeline_file_still_raises(tmp_path):
    with pytest.raises(DynamicRegistryError) as caught:
        load_pipeline_class(tmp_path / "hilang.py", "Up", "0" * 64)
    assert caught.value.key == "err.pipeline_file_missing"


# ── Pesan mengikuti bahasa, nilai TIDAK diterjemahkan ────────────────────

def test_the_permission_message_follows_the_language():
    try:
        require_approve(CONTRIB)
    except PermissionDenied as exc:
        core.st.session_state[core.LANG_KEY] = "id"
        indonesian = error_message(exc)
        core.st.session_state[core.LANG_KEY] = "en"
        english = error_message(exc)
    assert indonesian != english
    assert "Research Admin" in indonesian
    assert "Research Admin" in english          # nama peran TIDAK diterjemahkan


def test_the_denial_still_reads_as_a_permission_refusal():
    """Harus jelas DITOLAK KARENA HAK, bukan kesalahan sistem."""
    try:
        require_manage_users(None)
    except PermissionDenied as exc:
        core.st.session_state[core.LANG_KEY] = "en"
        text = error_message(exc).lower()
    assert "only a research admin" in text
    for wrong in ("failed", "error", "went wrong"):
        assert wrong not in text, wrong


def test_the_hash_values_are_never_translated(tmp_path):
    entry = tmp_path / "up.py"
    entry.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(DynamicRegistryError) as caught:
        load_pipeline_class(entry, "Up", "a" * 64)

    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        text = error_message(caught.value)
        assert "up.py" in text, lang            # nama berkas apa adanya
        assert "a" * 12 in text, lang           # hash tercatat apa adanya


def test_the_hash_message_keeps_its_integrity_meaning():
    """Bukan sekadar "gagal": berkasnya BERBEDA dari yang tercatat."""
    for lang, ideas in (("id", ["tidak cocok", "tercatat", "ditemukan",
                                "berubah atau rusak"]),
                        ("en", ["does not match", "recorded", "found",
                                "changed or is corrupt"])):
        text = CATALOG["err.hash_mismatch"][lang].lower()
        for idea in ideas:
            assert idea.lower() in text, (lang, idea)


def test_every_error_message_says_what_to_do_where_it_can():
    """Pesan yang membantu menyebut langkah berikutnya, bukan hanya kegagalan."""
    actionable = ("err.hash_mismatch", "err.entry_file_missing",
                  "err.pipeline_file_missing", "err.pipeline_not_registered")
    for key in actionable:
        for lang in ("id", "en"):
            text = CATALOG[key][lang]
            assert len(text) > 40, (key, lang)     # ada kalimat lanjutannya


# ── Pesan TERSIMPAN pada catatan lama ────────────────────────────────────

def test_a_stored_failure_message_is_returned_untouched():
    """Catatan lama adalah rekaman apa yang terjadi saat itu.

    Menerjemahkannya ulang berarti menulis ulang riwayat — dan kalimat itu
    mungkin dibuat versi platform yang sudah berbeda.
    """
    stored = "Gagal memuat up.py: ModuleNotFoundError: No module named 'helper'"
    for lang in ("id", "en"):
        core.st.session_state[core.LANG_KEY] = lang
        assert stored_error_message(stored) == stored, lang


def test_the_stored_path_is_distinct_from_the_live_path():
    """Dua fungsi berbeda, sengaja: satu untuk pesan BARU, satu untuk TERSIMPAN."""
    src = (REPO_ROOT / "ui" / "components"
           / "validator_messages.py").read_text(encoding="utf-8")
    assert "def error_message(" in src
    assert "def stored_error_message(" in src
    # Yang tersimpan tidak pernah melewati kamus.
    body = src.split("def stored_error_message(")[1]
    assert "t(" not in body.split("return")[0]


# ── Tidak ada kesalahan yang tertelan ────────────────────────────────────

def test_no_display_site_silently_drops_the_error():
    """Setiap `except` yang dulu menampilkan pesan harus tetap menampilkan."""
    for rel in ("ui/views/contribute.py", "ui/views/manage_pipelines.py",
                "ui/views/login.py", "ui/components/run_mode_controls.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        # Penggantian `str(e)` → `error_message(e)` bersifat satu-untuk-satu.
        assert "st.error(str(e))" not in src, rel
        assert "st.error(error_message(e))" in src, rel


def test_error_message_never_returns_empty():
    """Pesan kosong = kesalahan yang tertelan di layar."""
    for cls in ERROR_CLASSES:
        for lang in ("id", "en"):
            core.st.session_state[core.LANG_KEY] = lang
            assert error_message(cls("sesuatu")).strip(), (cls, lang)


def test_an_unknown_key_falls_back_to_the_original_text():
    """Kunci salah tulis tidak boleh membuat pesan hilang."""
    exc = DynamicRegistryError("teks asli", key="err.tidak.ada")
    core.st.session_state[core.LANG_KEY] = "en"
    assert error_message(exc) == "teks asli"


# ── Log pengembang ───────────────────────────────────────────────────────

def test_developer_logs_are_never_translated():
    """Log dibaca pengembang saat menelusuri galat — menerjemahkannya
    menyulitkan, dan ia tidak pernah sampai ke pengguna."""
    for path in sorted((REPO_ROOT / "orchestrator").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("debug", "info", "warning", "error",
                                           "exception", "critical")):
                for arg in node.args:
                    assert not (isinstance(arg, ast.Call)
                                and getattr(arg.func, "id", "") == "t"), \
                        f"{path.name}:{node.lineno}"


def test_the_orchestrator_never_imports_the_language_layer():
    """Lapisan logika tidak boleh tahu soal bahasa antarmuka."""
    for path in sorted((REPO_ROOT / "orchestrator").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        assert "from ui.i18n" not in src, path.name
        assert "import ui.i18n" not in src, path.name


# ── Kamus ────────────────────────────────────────────────────────────────

def test_the_catalog_stays_complete():
    report = untranslated_report()
    assert report["id"]["missing"] == []
    assert report["en"]["missing"] == []


# ═══════════════════════════════════════════════════════════════════════
# TAHAP 4B — penerapan ke seluruh modul
# ═══════════════════════════════════════════════════════════════════════

from orchestrator.run_mode import validate_overrides
from orchestrator.submission_service import SubmissionError as _SubErr


#: `n_estimators` punya batas aman di `PARAM_BOUNDS`, jadi ia BOLEH
#: disesuaikan; `max_depth` tidak punya batas, jadi ia tetap TERKUNCI meski ada
#: di `fixed_params`. Dua keadaan itu keputusan platform yang tidak boleh
#: bergeser, dan keduanya diuji.
TUNABLE_INFO = {"fixed_params": {"n_estimators": 100, "max_depth": 5}}


def _keyed_raises(rel: str):
    """(baris, kunci) tiap `raise` yang sudah punya penanda pesan."""
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        for kw in node.exc.keywords:
            if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                out.append((node.lineno, kw.value.value))
    return out


MODULES = [
    "orchestrator/auth_service.py",
    "orchestrator/pipeline_versions.py",
    "orchestrator/submission_service.py",
    "orchestrator/run_mode.py",
    "orchestrator/dynamic_registry.py",
]


@pytest.mark.parametrize("rel", MODULES)
def test_every_key_used_by_a_raise_exists_in_the_catalog(rel):
    """Kunci salah tulis = pesan jatuh ke cadangan tanpa ada yang tahu."""
    for line, key in _keyed_raises(rel):
        assert key in CATALOG, f"{rel}:{line} -> {key}"


@pytest.mark.parametrize("rel", MODULES)
def test_the_module_carries_no_language_import(rel):
    """Lapisan logika tidak boleh tahu soal bahasa antarmuka."""
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "ui.i18n" not in src, rel


# ── Regresi jalur galat per modul ────────────────────────────────────────

def test_parameter_validation_still_refuses_the_same_things():
    """Jenis & kondisi pemicu tidak bergeser."""
    # Kunci yang tidak dikenal tetap ditolak.
    with pytest.raises(ParamError):
        validate_overrides("x.y", {"tidak_ada": 1}, info=TUNABLE_INFO)
    # Tipe salah tetap ditolak.
    with pytest.raises(ParamError):
        validate_overrides("x.y", {"n_estimators": "bukan angka"},
                           info=TUNABLE_INFO)
    # Di luar batas aman tetap ditolak.
    with pytest.raises(ParamError):
        validate_overrides("x.y", {"n_estimators": 99999}, info=TUNABLE_INFO)
    # Parameter TANPA batas aman tetap terkunci.
    with pytest.raises(ParamError):
        validate_overrides("x.y", {"max_depth": 7}, info=TUNABLE_INFO)
    # Bukan pasangan nama-nilai tetap ditolak.
    with pytest.raises(ParamError):
        validate_overrides("x.y", ["bukan", "dict"], info=TUNABLE_INFO)


def test_a_valid_override_still_passes():
    """Kondisi pemicu tidak melebar: yang sah tetap lolos."""
    assert validate_overrides("x.y", {"n_estimators": 250},
                              info=TUNABLE_INFO) == {"n_estimators": 250}


def test_parameter_errors_name_the_parameter_in_both_languages():
    try:
        validate_overrides("x.y", {"n_estimators": "bukan angka"},
                           info=TUNABLE_INFO)
    except ParamError as exc:
        for lang in ("id", "en"):
            core.st.session_state[core.LANG_KEY] = lang
            text = error_message(exc)
            assert "n_estimators" in text, lang   # nama parameter apa adanya
            assert "100" in text, lang            # nilai bawaan apa adanya


def test_a_locked_parameter_says_why_in_both_languages():
    """Terkunci ≠ salah ketik: nama parameternya harus ikut."""
    try:
        validate_overrides("x.y", {"max_depth": 7}, info=TUNABLE_INFO)
    except ParamError as exc:
        assert exc.key == "err.param_locked"
        for lang in ("id", "en"):
            core.st.session_state[core.LANG_KEY] = lang
            assert "max_depth" in error_message(exc), lang


def test_the_submission_error_hierarchy_is_unchanged():
    """`except AuthError` di UI harus tetap menangkap kegagalan pengajuan."""
    assert issubclass(_SubErr, AuthError)


def test_no_user_facing_raise_lost_its_message():
    """Setiap `raise` berpenanda tetap punya pesan Indonesia sebagai cadangan."""
    for rel in MODULES:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            if not any(k.arg == "key" for k in node.exc.keywords):
                continue
            # Argumen pertama (pesan) tetap ada — tidak diganti kunci saja.
            assert node.exc.args, f"{rel}:{node.lineno}"
