"""Penyunting berkas — titik paling berisiko pada seluruh fitur.

Di sinilah kode yang akan DIEKSEKUSI platform diubah manusia. Yang dijaga:

* **celah utama tertutup**: periksa kode bersih → ubah menjadi berbahaya →
  simpan. Status kembali "belum diperiksa", tombol simpan mati, dan memaksa
  memanggil fungsi simpan tetap DITOLAK tanpa menulis apa pun;
* paket banyak berkas dapat disunting seluruhnya, dan versi baru selalu
  LENGKAP — berkas yang tidak diubah ikut, sehingga versi itu berdiri sendiri;
* versi lama tetap utuh beserta hash-nya;
* kode yang disunting tidak pernah di-import, dijalankan, atau dievaluasi.
"""
import ast
import sqlite3
from pathlib import Path

import pytest

from config.pipeline_registry import PIPELINE_REGISTRY
from database.db import init_db
from orchestrator.auth_service import PermissionDenied
from orchestrator.dynamic_registry import (
    file_sha256, get_registered, list_registered, register_pipeline,
)
from orchestrator import pipeline_versions as pv
from ui.views import manage_pipelines as mp

REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_SRC = (REPO_ROOT / "ui" / "views"
              / "manage_pipelines.py").read_text(encoding="utf-8")

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}
VISITOR = None

ENTRY = '''
import helper

from pipelines.base import BasePipeline


class Up(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return helper.label()

    def get_info(self):
        return {"paper": "p", "algorithm": "a"}
'''
HELPER = "def label():\n    return 'v1'\n"
MALICIOUS_ENTRY = ENTRY.replace("import helper", "import subprocess\nimport helper")
MALICIOUS_HELPER = "import socket\n\n\ndef label():\n    return socket.gethostname()\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Paket DUA berkas: satu titik masuk + satu pendukung."""
    db_path = str(tmp_path / "edit.db")
    init_db(db_path)
    monkeypatch.setattr(pv, "VERSIONS_ROOT", tmp_path / "versions")

    def _conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    for module in ("database.db", "orchestrator.dynamic_registry",
                   "orchestrator.pipeline_versions"):
        monkeypatch.setattr(f"{module}.get_connection", _conn)

    pkg = tmp_path / "approved"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "up.py").write_text(ENTRY, encoding="utf-8")
    (pkg / "helper.py").write_text(HELPER, encoding="utf-8")

    v1 = register_pipeline(name="paket", dataset_type="HIKARI2021",
                           entry_class="Up", entry_file=pkg / "up.py",
                           registered_by="boss", db_path=db_path)
    return {"db": db_path, "v1": v1, "pkg": pkg}


# ── CELAH UTAMA: hasil pemeriksaan basi ───────────────────────────────────

def test_a_stale_check_disables_saving():
    """Periksa bersih -> ubah -> status kembali dan tombol mati."""
    clean = {"up.py": ENTRY, "helper.py": HELPER}
    report = pv.validate_package(clean)
    fingerprint = mp.package_fingerprint(clean)

    assert report["valid"]
    assert mp.check_status(clean, report, fingerprint) == mp.STATUS_PASS
    assert mp.save_blocker(clean, report, fingerprint, "catatan") == ""

    # …lalu kode diubah menjadi berbahaya, TANPA diperiksa ulang.
    tampered = {**clean, "up.py": MALICIOUS_ENTRY}
    assert mp.check_status(tampered, report, fingerprint) == mp.STATUS_STALE
    blocker = mp.save_blocker(tampered, report, fingerprint, "catatan")
    assert blocker
    assert "tidak berlaku" in blocker


def test_a_change_in_a_support_file_also_invalidates_the_check():
    """Sidik jarinya mencakup SELURUH berkas, bukan hanya titik masuk."""
    clean = {"up.py": ENTRY, "helper.py": HELPER}
    report = pv.validate_package(clean)
    fingerprint = mp.package_fingerprint(clean)

    tampered = {**clean, "helper.py": MALICIOUS_HELPER}
    assert mp.check_status(tampered, report, fingerprint) == mp.STATUS_STALE


def test_forcing_the_save_on_tampered_code_is_refused(env):
    """Lapis aksi tetap menolak, dan tidak ada versi maupun berkas tertulis."""
    with pytest.raises(pv.PipelineEditError):
        pv.save_new_version(env["v1"]["pipeline_id"],
                            files={"up.py": MALICIOUS_ENTRY,
                                   "helper.py": HELPER},
                            change_note="diam-diam", actor=ADMIN,
                            db_path=env["db"])

    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]
    assert not list(Path(pv.VERSIONS_ROOT).rglob("*.py"))


def test_a_malicious_support_file_is_refused_too(env):
    """Berkas pendukung tetap wajib lolos pemeriksaan KEAMANAN."""
    with pytest.raises(pv.PipelineEditError):
        pv.save_new_version(env["v1"]["pipeline_id"],
                            files={"up.py": ENTRY,
                                   "helper.py": MALICIOUS_HELPER},
                            change_note="ubah", actor=ADMIN,
                            db_path=env["db"])
    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]


@pytest.mark.parametrize("status, expected", [
    (None, "Belum diperiksa"),
    ("stale", "tidak berlaku"),
])
def test_the_blocker_reason_is_always_stated(status, expected):
    files = {"up.py": ENTRY, "helper.py": HELPER}
    if status is None:
        blocker = mp.save_blocker(files, None, None, "catatan")
    else:
        report = pv.validate_package(files)
        blocker = mp.save_blocker({**files, "up.py": MALICIOUS_ENTRY}, report,
                                  mp.package_fingerprint(files), "catatan")
    assert expected in blocker


def test_an_empty_note_blocks_saving_even_when_valid():
    files = {"up.py": ENTRY, "helper.py": HELPER}
    report = pv.validate_package(files)
    fingerprint = mp.package_fingerprint(files)
    for note in ("", "   "):
        assert "catatan perubahan" in mp.save_blocker(files, report,
                                                      fingerprint, note)


def test_a_failing_check_blocks_saving_with_its_cause():
    files = {"up.py": MALICIOUS_ENTRY, "helper.py": HELPER}
    report = pv.validate_package(files)
    assert not report["valid"]
    blocker = mp.save_blocker(files, report, mp.package_fingerprint(files), "x")
    assert blocker and "tidak dapat disimpan" in blocker


def test_the_fingerprint_notices_every_kind_of_change():
    base = {"a.py": "x", "b.py": "y"}
    assert mp.package_fingerprint(base) == mp.package_fingerprint(dict(base))
    assert mp.package_fingerprint(base) != mp.package_fingerprint(
        {"a.py": "x", "b.py": "z"})                     # isi berubah
    assert mp.package_fingerprint(base) != mp.package_fingerprint(
        {"a.py": "x"})                                  # berkas hilang
    assert mp.package_fingerprint(base) != mp.package_fingerprint(
        {**base, "c.py": ""})                           # berkas bertambah


# ── Paket banyak berkas ───────────────────────────────────────────────────

def test_the_editor_reads_the_whole_package_not_just_the_entry(env):
    files = pv.read_package(env["v1"]["pipeline_id"], env["db"])
    assert set(files) == {"up.py", "helper.py"}
    assert files["helper.py"] == HELPER


def test_saving_writes_a_complete_package(env):
    """Berkas yang TIDAK diubah ikut, sehingga versi baru berdiri sendiri."""
    created = pv.save_new_version(
        env["v1"]["pipeline_id"], files={"up.py": ENTRY,
                                         "helper.py": HELPER.replace("v1", "v2")},
        change_note="ubah pendukung", actor=ADMIN, db_path=env["db"])

    folder = Path(created["entry_file"]).parent
    assert sorted(p.name for p in folder.glob("*.py")) == ["helper.py", "up.py"]
    assert (folder / "helper.py").read_text(encoding="utf-8") != HELPER
    assert (folder / "up.py").read_text(encoding="utf-8") == ENTRY


def test_editing_only_the_entry_still_carries_the_support_file(env):
    """Jalur sumber-tunggal pun menghasilkan versi LENGKAP.

    Sebelumnya versi hasil suntingan lahir tanpa berkas pendukungnya, sehingga
    versi itu tidak dapat dimuat sendiri — ketertelusurannya bocor.
    """
    created = pv.save_new_version(env["v1"]["pipeline_id"],
                                  ENTRY.replace("helper.label()", "helper.label"),
                                  change_note="ubah titik masuk", actor=ADMIN,
                                  db_path=env["db"])
    folder = Path(created["entry_file"]).parent
    assert (folder / "helper.py").is_file()
    assert (folder / "helper.py").read_text(encoding="utf-8") == HELPER


def test_the_entry_point_must_be_present_when_saving_a_package(env):
    with pytest.raises(pv.PipelineEditError, match="titik masuk"):
        pv.save_new_version(env["v1"]["pipeline_id"],
                            files={"helper.py": HELPER},
                            change_note="ubah", actor=ADMIN, db_path=env["db"])


def test_exactly_one_entry_point_is_still_enforced(env):
    """Aturan tingkat paket tidak dilonggarkan oleh penyunting."""
    second_entry = ENTRY.replace("class Up", "class Kedua")
    with pytest.raises(pv.PipelineEditError):
        pv.save_new_version(env["v1"]["pipeline_id"],
                            files={"up.py": ENTRY, "helper.py": second_entry},
                            change_note="dua titik masuk", actor=ADMIN,
                            db_path=env["db"])
    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]


def test_changed_files_are_flagged():
    original = {"up.py": ENTRY, "helper.py": HELPER}
    assert mp.changed_files(dict(original), original) == []
    edited = {**original, "helper.py": HELPER + "\n"}
    assert mp.changed_files(edited, original) == ["helper.py"]


# ── Versi lama tetap utuh ─────────────────────────────────────────────────

def test_the_previous_version_survives_a_package_save(env):
    before = {p.name: p.read_bytes() for p in env["pkg"].glob("*.py")}
    before_hash = env["v1"]["file_hash"]

    pv.save_new_version(env["v1"]["pipeline_id"],
                        files={"up.py": ENTRY, "helper.py": HELPER + "\n"},
                        change_note="ubah", actor=ADMIN, db_path=env["db"])

    after = {p.name: p.read_bytes() for p in env["pkg"].glob("*.py")}
    assert after == before                              # byte demi byte
    assert file_sha256(env["pkg"] / "up.py") == before_hash
    row = get_registered(env["v1"]["pipeline_id"], env["db"])
    assert row["file_hash"] == before_hash


# ── Pengaman lain tetap berlaku ──────────────────────────────────────────

@pytest.mark.parametrize("pipeline_id", sorted(PIPELINE_REGISTRY))
def test_a_built_in_pipeline_cannot_enter_the_editor(env, pipeline_id):
    with pytest.raises(pv.PipelineEditError, match="bukan pipeline kontribusi"):
        pv.read_package(pipeline_id, env["db"])
    with pytest.raises(pv.PipelineEditError, match="bukan pipeline kontribusi"):
        pv.save_new_version(pipeline_id, files={"a.py": ENTRY},
                            change_note="ubah", actor=ADMIN, db_path=env["db"])


@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR],
                         ids=["pengunjung", "kontributor"])
def test_only_a_research_admin_may_save(env, actor):
    with pytest.raises(PermissionDenied):
        pv.save_new_version(env["v1"]["pipeline_id"],
                            files={"up.py": ENTRY, "helper.py": HELPER},
                            change_note="ubah", actor=actor, db_path=env["db"])
    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]


def test_a_missing_note_is_refused_by_the_function(env):
    for note in ("", "   ", None):
        with pytest.raises(pv.PipelineEditError, match="[Cc]atatan perubahan"):
            pv.save_new_version(env["v1"]["pipeline_id"],
                                files={"up.py": ENTRY, "helper.py": HELPER},
                                change_note=note, actor=ADMIN,
                                db_path=env["db"])


def test_the_editor_never_runs_the_code_it_edits():
    banned = {"exec", "eval", "compile", "__import__",
              "spec_from_file_location", "exec_module", "load_pipeline_class",
              "load_registered_instance", "get_pipeline_instance_merged"}
    for rel in ("ui/views/manage_pipelines.py",
                "orchestrator/pipeline_versions.py"):
        called = set()
        for node in ast.walk(ast.parse(
                (REPO_ROOT / rel).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    owner = getattr(func.value, "id", None)
                    called.add(f"{owner}.{func.attr}" if owner else func.attr)
        assert not (called & banned), (rel, called & banned)


def test_the_validator_rules_are_not_touched_by_the_editor():
    src = (REPO_ROOT / "orchestrator"
           / "pipeline_versions.py").read_text(encoding="utf-8")
    assert "review_package" in src                       # dipakai apa adanya
    for tampering in ("FORBIDDEN_MODULES", "ALLOWED_MODULES", "checks.remove",
                      "checks.clear", '["valid"] =', ".valid = "):
        assert tampering not in src, tampering


# ── Tampilan penyunting ───────────────────────────────────────────────────

def test_the_editor_offers_a_file_picker_with_roles():
    body = EDITOR_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    assert 'st.selectbox(' in body
    assert "_file_label" in EDITOR_SRC
    label_body = EDITOR_SRC.split("def _file_label(")[1].split(chr(10) + "def ")[0]
    assert "titik masuk" in label_body and "pendukung" in label_body


def test_the_editor_keeps_the_edits_between_interactions():
    body = EDITOR_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    assert "st.session_state[_PACKAGE_KEY] = files" in body
    loader = EDITOR_SRC.split("def _load_package(")[1].split(chr(10) + "def ")[0]
    assert "st.session_state.get(_PACKAGE_KEY)" in loader


def test_reverting_asks_for_confirmation():
    body = EDITOR_SRC.split("def _render_revert_confirm(")[1].split(
        chr(10) + "def ")[0]
    assert "REVERT_WARNING" in body
    assert 't("ap.btn_yes_revert")' in body
    assert 't("action.cancel")' in body
    assert "akan hilang" in mp.REVERT_WARNING


def test_findings_are_split_into_failing_and_warning():
    body = EDITOR_SRC.split("def _render_findings(")[1].split(chr(10) + "def ")[0]
    assert '"Menggagalkan"' in body and '"Peringatan"' in body
    assert "source_lines[line - 1]" in body              # kutipan barisnya
    assert "menggagalkan" in mp.FINDING_NOTE.lower()
    assert "peringatan" in mp.FINDING_NOTE.lower()


def test_the_context_and_running_warning_are_shown():
    body = EDITOR_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    for label in ("Versi aktif", "Hash aktif", "Kelas titik masuk",
                  "Jenis dataset"):
        assert label in body, label
    assert "running_experiments(" in body
    assert "sedang BERJALAN" in body
    assert "tidak mengubahnya" in body
    assert "versi lama, yang tetap tersimpan" in body
    assert "NEW_VERSION_NOTE" in body


def test_saving_reopens_the_editor_on_the_new_version():
    body = EDITOR_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    save_at = body.index("save_new_version(")
    tail = body[save_at:]
    assert "_clear_editor()" in tail
    assert 'st.session_state[_EDIT_KEY] = created["pipeline_id"]' in tail
    assert "kini" in tail and "aktif" in tail            # konfirmasi ringkas


def test_the_save_call_always_passes_the_whole_package():
    body = EDITOR_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    assert "save_new_version(pipeline_id, files=files," in body


# ── AppTest ───────────────────────────────────────────────────────────────

def _script(repo: str, db: str, tmp: str) -> str:
    return f'''
import sqlite3, sys
sys.path.insert(0, r"{repo}")
import streamlit as st
import database.db as dbmod
import orchestrator.dynamic_registry as dr
import orchestrator.pipeline_versions as pv
from database.db import init_db
from pathlib import Path

DB = r"{db}"
TMP = Path(r"{tmp}")

def conn(path=None):
    c = sqlite3.connect(path or DB)
    c.row_factory = sqlite3.Row
    return c

dbmod.get_connection = conn
dr.get_connection = conn
pv.get_connection = conn
pv.VERSIONS_ROOT = TMP / "versions"
init_db(DB)

if not dr.list_registered(db_path=DB):
    pkg = TMP / "approved"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "up.py").write_text({ENTRY!r}, encoding="utf-8")
    (pkg / "helper.py").write_text({HELPER!r}, encoding="utf-8")
    row = dr.register_pipeline(name="paket", dataset_type="HIKARI2021",
                               entry_class="Up", entry_file=pkg / "up.py",
                               registered_by="boss", db_path=DB)
    st.session_state["_mp_editing"] = row["pipeline_id"]

from ui.components import theme
theme.inject()
st.session_state["_current_page"] = "Add Pipeline & Dataset"
st.session_state["_contrib_mode"] = "review"
from ui.views.contribute import render
render()
'''


def _run(tmp_path):
    """Jalankan halaman, lalu KEMBALIKAN state global (AppTest sekerja proses)."""
    import database.db as dbmod
    import orchestrator.dynamic_registry as dr
    from streamlit.testing.v1 import AppTest

    from ui.views import login

    saved = (dbmod.get_connection, dr.get_connection, pv.get_connection,
             pv.VERSIONS_ROOT)
    try:
        script = tmp_path / "page.py"
        script.write_text(_script(str(REPO_ROOT), str(tmp_path / "at.db"),
                                  str(tmp_path)), encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.session_state[login.SESSION_USER_KEY] = ADMIN
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        (dbmod.get_connection, dr.get_connection, pv.get_connection,
         pv.VERSIONS_ROOT) = saved


def test_the_editor_renders_with_the_save_button_disabled(tmp_path):
    at = _run(tmp_path)
    text = " ".join(m.value for m in at.markdown)

    assert "Status pemeriksaan" in text
    assert mp.STATUS_UNCHECKED in text
    save = next(b for b in at.button if b.label == "Simpan sebagai versi baru")
    assert save.disabled is True                        # belum diperiksa
    assert "Belum diperiksa" in text                    # alasannya dinyatakan

    # Jalan keluarnya SATU dan jelas: penyunting kini tampilan tersendiri.
    labels = {b.label for b in at.button}
    assert {"Periksa", "Kembalikan", "← Kembali ke daftar aktif"} <= labels
    assert "Tutup" not in labels, "dua tombol keluar membuat pengguna menebak"
    # Pemilih berkas memuat kedua berkas paket.
    picker = next(s for s in at.selectbox if s.key == "_mp_active_file")
    labels = " ".join(picker.options)
    assert "up.py" in labels and "helper.py" in labels
    # Perannya tertandai pada pilihannya.
    assert "titik masuk" in labels and "pendukung" in labels
