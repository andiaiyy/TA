"""Bagian "Menunggu tinjauan" — gerbang terakhir sebelum kode asing dijalankan.

Yang dijaga di sini:

* seluruh yang ditampilkan berasal dari pengajuan yang TERSIMPAN — metadata
  formulir, penjelasan per berkas dari pengunggah, ukuran & hash, waktu, pengaju
  — bukan nilai tetap;
* pengajuan multi-berkas ditinjau SELURUHNYA, bukan hanya titik masuknya;
* menolak tanpa alasan tidak pernah terjadi, dan menyetujui membuat versi 1
  beserta hash-nya;
* jalur peninjauan TIDAK PERNAH meng-import atau menjalankan kode pengajuan.
"""
import ast
import sqlite3
from pathlib import Path

import pytest

from database.db import init_db
from orchestrator.auth_service import PermissionDenied
from ui.components import submission_review as sr
from tests._trial_helpers import pass_trial

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
CARD_BODY = CONTRIB_SRC.split("def _render_submission_review_card(")[1].split(
    chr(10) + "def ")[0]

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}
VISITOR = None

ENTRY = '''
from pipelines.base import BasePipeline


class Up(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return 1

    def get_info(self):
        return {"paper": "p", "algorithm": "a"}
'''
HELPER = "def helper(value):\n    return str(value)\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Pengajuan multi-berkas NYATA di dalam tmp_path."""
    import orchestrator.submission_service as svc

    db_path = str(tmp_path / "review.db")
    init_db(db_path)

    def _conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    for module in ("database.db", "orchestrator.submission_service",
                   "orchestrator.dynamic_registry"):
        monkeypatch.setattr(f"{module}.get_connection", _conn)

    monkeypatch.setitem(svc.SUBMISSION_DIRS, svc.KIND_PIPELINE, {
        svc.SUBMISSION_PENDING: tmp_path / "pipes" / "pending",
        svc.SUBMISSION_APPROVED: tmp_path / "pipes" / "approved",
        svc.SUBMISSION_REJECTED: tmp_path / "pipes" / "rejected",
    })

    item = svc.submit_pipeline(
        [("up.py", ENTRY), ("helper.py", HELPER)], "up.py", user=CONTRIBUTOR,
        metadata={"name": "RF Kontribusi", "dataset_type": "HIKARI2021",
                  "algorithm": "Random Forest", "paper": "Rayyan (2024)",
                  "notes": "versi awal", "entry_class": "Up"},
        validation={"valid": True, "entry_points": ["up.py"], "files": [
            {"filename": "up.py", "role": "entry point", "package_ok": True,
             "description": "kelas pipeline utama"},
            {"filename": "helper.py", "role": "pendukung", "package_ok": True,
             "description": "pembantu konversi"}]},
        db_path=db_path)
    return {"db": db_path, "item": item, "svc": svc}


# ── Data berasal dari pengajuan tersimpan ─────────────────────────────────

def test_the_metadata_shown_comes_from_the_submission(env):
    rows = dict(sr.metadata_rows(env["item"]))
    assert rows["Nama pipeline"] == "RF Kontribusi"
    assert rows["Dataset target"] == "HIKARI2021"
    assert rows["Algoritma"] == "Random Forest"
    assert rows["Paper / rujukan"] == "Rayyan (2024)"
    assert rows["Catatan pengaju"] == "versi awal"
    assert rows["Kelas titik masuk"] == "Up"
    assert rows["Diajukan oleh"] == CONTRIBUTOR["username"]
    assert rows["Waktu"] == (env["item"]["submitted_at"] or "")[:19]
    assert env["item"]["file_hash"][:16] in rows["SHA-256 titik masuk"]


def test_nothing_is_invented_when_the_submission_is_bare():
    """Metadata kosong -> nilai kosong, bukan karangan."""
    rows = dict(sr.metadata_rows({"submitted_by": "", "submitted_at": ""}))
    assert set(rows.values()) == {""}


def test_the_uploader_per_file_notes_are_read_from_the_submission(env):
    notes = sr.uploader_notes(env["item"])
    assert notes == {"up.py": "kelas pipeline utama",
                     "helper.py": "pembantu konversi"}


def test_the_stored_file_list_carries_size_and_hash(env):
    files = {f["filename"]: f for f in sr.stored_files(env["item"])}
    assert set(files) == {"up.py", "helper.py"}
    for entry in files.values():
        assert entry["size"] > 0
        assert len(entry["sha256"]) == 64


# ── Seluruh berkas paket dapat ditinjau ───────────────────────────────────

def test_every_file_in_the_package_is_reviewed_not_just_the_entry_point(env):
    reviewed = sr.review_stored_package(env["item"])
    rows = sr.file_rows(env["item"], reviewed)

    assert [r["filename"] for r in rows] == ["up.py", "helper.py"]
    assert rows[0]["role"] == "entry point"        # titik masuk lebih dulu
    assert rows[1]["role"] == "pendukung"
    for row in rows:
        assert row["size"]                          # ukuran dari pengajuan
        assert row["description"]                   # penjelasan pengunggah
        assert row["entry"]["source"]               # sumbernya ikut, sebagai teks


def test_each_file_carries_its_own_grouped_checks(env):
    from ui.components.pipeline_upload import GROUP_SECURITY, GROUP_STRUCTURE

    reviewed = sr.review_stored_package(env["item"])
    for row in sr.file_rows(env["item"], reviewed):
        groups = row["entry"]["groups"]
        assert GROUP_STRUCTURE in groups
        assert GROUP_SECURITY in groups


def test_findings_expose_their_line_numbers(env):
    """Nomor baris itulah yang menghubungkan temuan dengan kodenya."""
    reviewed = sr.review_stored_package(env["item"])
    entry = next(r["entry"] for r in sr.file_rows(env["item"], reviewed)
                 if r["role"] == "entry point")

    checks = entry["report"]["checks"]
    assert any(c.get("line") for c in checks)
    # `finding_lines` hanya memuat WARN/FAIL, urut & unik.
    lines = sr.finding_lines(entry)
    assert lines == sorted(set(lines))
    for line in lines:
        assert any(c["line"] == line and c["status"] in ("warn", "fail")
                   for c in checks)


def test_the_status_constants_come_from_the_validator():
    """Membandingkan status dengan huruf besar gagal DIAM-DIAM: peringatan tak
    pernah terdeteksi dan nomor baris tak pernah muncul."""
    src = (REPO_ROOT / "ui" / "components"
           / "submission_review.py").read_text(encoding="utf-8")
    assert "from orchestrator.pipeline_validator import FAIL, WARN" in src
    assert '"WARN"' not in src and '"FAIL"' not in src


def test_the_code_is_numbered_so_findings_can_be_located():
    numbered = sr.numbered_source("satu\ndua\ntiga")
    assert numbered.splitlines() == ["1 | satu", "2 | dua", "3 | tiga"]
    # Nomor rata kanan supaya kolom kode tetap lurus.
    wide = sr.numbered_source("\n".join(str(i) for i in range(12)))
    assert wide.splitlines()[0].startswith(" 1 |")
    assert wide.splitlines()[-1].startswith("12 |")


# ── Verdict & daftar ──────────────────────────────────────────────────────

def test_a_clean_package_is_distinguished_from_one_with_warnings():
    clean = {"valid": True, "files": [
        {"filename": "a.py", "report": {"checks": [{"status": "pass"}]}}]}
    warned = {"valid": True, "files": [
        {"filename": "a.py", "report": {"checks": [
            {"status": "pass"}, {"status": "warn", "name": "x", "line": 3}]}}]}
    broken = {"valid": False, "n_problem_files": 1, "files": []}

    assert sr.verdict_of(clean) == sr.VERDICT_CLEAN
    assert sr.verdict_of(warned) == sr.VERDICT_WARN
    assert sr.verdict_of(broken) == sr.VERDICT_PROBLEM

    # Penanda visualnya berbeda, dan keduanya tetap boleh disetujui.
    assert sr.VERDICT_MARK[sr.VERDICT_CLEAN] != sr.VERDICT_MARK[sr.VERDICT_WARN]
    assert "peringatan" in sr.verdict_text(warned)
    assert "(1)" in sr.verdict_text(warned)             # jumlah peringatan


def test_the_pending_list_is_ordered_oldest_first():
    items = [{"id": 3, "submitted_at": "2026-03-01T00:00:00"},
             {"id": 1, "submitted_at": "2026-01-01T00:00:00"},
             {"id": 2, "submitted_at": "2026-02-01T00:00:00"}]
    assert [s["id"] for s in sr.sort_pending(items)] == [1, 2, 3]
    assert sr.sort_pending([]) == []


def test_the_summary_line_helps_choose_what_to_open(env):
    reviewed = sr.review_stored_package(env["item"])
    row = sr.summary_row(env["item"], reviewed)
    line = sr.summary_line(row)

    assert row["file_count"] == 2
    assert "RF Kontribusi" in line                      # nama
    assert CONTRIBUTOR["username"] in line              # pengaju
    assert "2 berkas" in line                           # jumlah berkas
    assert row["verdict_text"] in line                  # ringkasan validasi
    assert row["submitted_at"] in line                  # waktu


def test_there_is_an_empty_state():
    assert sr.EMPTY_STATE
    assert "Tidak ada" in sr.EMPTY_STATE
    assert sr.EMPTY_STATE in CONTRIB_SRC or "sr.EMPTY_STATE" in CONTRIB_SRC


# ── Keputusan ─────────────────────────────────────────────────────────────

def test_rejecting_without_a_reason_is_refused_in_the_ui(env):
    """Tombol Tolak tidak menjalankan apa pun tanpa alasan."""
    assert "if not note.strip():" in CARD_BODY
    reject_at = CARD_BODY.index("review_reject_")
    guard_at = CARD_BODY.index("if not note.strip():")
    assert reject_at < guard_at                         # penjaga SESUDAH tombol
    assert 't("ap.msg_need_reject_reason")' in CARD_BODY


def test_rejecting_without_a_reason_is_refused_in_the_function(env):
    """Dan lapis aksi tetap menolak identitas tanpa hak."""
    from orchestrator.submission_service import reject_submission

    with pytest.raises(PermissionDenied):
        reject_submission(env["item"]["id"], actor=CONTRIBUTOR, note="tidak",
                          db_path=env["db"])


def test_rejecting_keeps_the_files(env):
    from orchestrator.submission_service import get_submission, reject_submission

    reject_submission(env["item"]["id"], actor=ADMIN, note="belum sesuai",
                      db_path=env["db"])
    done = get_submission(env["item"]["id"], env["db"])
    assert done["status"] == "rejected"
    assert done["review_note"] == "belum sesuai"
    assert done["reviewed_by"] == ADMIN["username"]
    assert done["reviewed_at"]
    assert Path(done["stored_path"]).exists()           # berkas tidak dihapus


def test_approving_registers_version_one_with_its_hash(env):
    from orchestrator.dynamic_registry import list_registered
    from orchestrator.submission_service import approve_submission

    pass_trial(env["item"]["id"], env["db"])
    approve_submission(env["item"]["id"], actor=ADMIN, note="ok",
                       dataset_type="HIKARI2021", db_path=env["db"])

    rows = [r for r in list_registered(db_path=env["db"])
            if r["submission_id"] == env["item"]["id"]]
    assert len(rows) == 1
    created = rows[0]
    assert created["version"] == 1
    assert len(created["file_hash"]) == 64
    assert created["active"] == 1
    assert created["registered_by"] == ADMIN["username"]


def test_the_decision_is_recorded_with_who_and_when(env):
    from orchestrator.submission_service import approve_submission, get_submission

    pass_trial(env["item"]["id"], env["db"])
    approve_submission(env["item"]["id"], actor=ADMIN, note="lolos",
                       dataset_type="HIKARI2021", db_path=env["db"])
    done = get_submission(env["item"]["id"], env["db"])
    assert done["status"] == "approved"
    assert done["reviewed_by"] == ADMIN["username"]
    assert done["reviewed_at"]
    assert done["review_note"] == "lolos"


@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR],
                         ids=["pengunjung", "kontributor"])
def test_only_a_research_admin_may_decide(env, actor):
    from orchestrator.submission_service import approve_submission, get_submission

    with pytest.raises(PermissionDenied):
        approve_submission(env["item"]["id"], actor=actor, db_path=env["db"])
    assert get_submission(env["item"]["id"], env["db"])["status"] == "pending"


def test_the_consequence_is_stated_before_the_approve_button():
    """Akibatnya dinyatakan SEBELUM tombolnya, bukan sesudah."""
    consequence_at = CARD_BODY.index("APPROVAL_CONSEQUENCE")
    # Label tombol kini dari katalog; yang diuji tetap URUTANNYA.
    approve_at = CARD_BODY.index('t("action.approve")')
    assert consequence_at < approve_at
    assert "langsung dapat" in sr.APPROVAL_CONSEQUENCE
    assert "versi 1" in sr.APPROVAL_CONSEQUENCE


def test_the_warning_reminder_appears_only_when_there_are_warnings():
    assert "WARNING_REMINDER" in CARD_BODY
    reminder_at = CARD_BODY.index("WARNING_REMINDER")
    guard_at = CARD_BODY.index("warnings = sr.warning_checks(reviewed)")
    assert guard_at < reminder_at
    assert "belum tentu masalah" in sr.WARNING_REMINDER


def test_the_static_check_note_is_gone_everywhere():
    """Kalimat itu dibuang, dan dibuang SELURUHNYA.

    Ia dahulu berdiri di kepala setiap tampilan peninjauan — dibaca sebelum
    pembacanya tahu ia sedang melihat apa. Konstanta yang tertinggal tanpa
    pemakai akan mengundang seseorang memasangnya kembali, jadi konstanta,
    kunci katalog, dan entri katalognya ikut dibuang.
    """
    from ui.i18n.catalog import CATALOG
    from ui.views import manage_pipelines as mp

    assert not hasattr(mp, "STATIC_CHECK_NOTE")
    assert not hasattr(mp, "STATIC_CHECK_NOTE_KEY")
    assert not hasattr(sr, "STATIC_CHECK_NOTE")
    assert "mp.static_check_note" not in CATALOG
    assert "STATIC_CHECK_NOTE" not in CONTRIB_SRC


def test_the_new_version_note_survives_where_it_is_decided():
    """Penjaga anti-hampa: yang dibuang dari halaman peninjauan TIDAK dibuang
    dari penyunting — di sanalah "menyunting membuat versi baru" benar-benar
    menjadi keputusan, dibaca tepat sebelum tombol Simpan."""
    from ui.views import manage_pipelines as mp

    assert "versi baru" in mp.NEW_VERSION_NOTE
    editor = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8").split("def render_editor(")[1]
    assert "NEW_VERSION_NOTE" in editor


# ── Statis, selalu ────────────────────────────────────────────────────────

def _called_names(tree) -> set[str]:
    """Nama fungsi yang dipanggil, MEMPERTAHANKAN awalan modulnya.

    `re.compile` bukan `compile`: memeriksa nama telanjang saja akan menuduh
    kompilasi regex sebagai eksekusi kode.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            owner = getattr(func.value, "id", None)
            names.add(f"{owner}.{func.attr}" if owner else func.attr)
    return names


def test_the_review_path_never_imports_or_runs_submitted_code():
    banned = {"exec", "eval", "compile", "__import__",
              "spec_from_file_location", "exec_module",
              "importlib.import_module", "load_pipeline_class",
              "load_registered_instance", "get_pipeline_instance_merged"}
    for rel in ("ui/components/submission_review.py",
                "ui/views/contribute.py"):
        called = _called_names(ast.parse(
            (REPO_ROOT / rel).read_text(encoding="utf-8")))
        assert not (called & banned), (rel, called & banned)
        # `re.compile` sah dan tidak boleh ikut tertuduh.
        assert "compile" not in called


def test_the_sources_are_read_as_text_only(env):
    """`read_submission_sources` mengembalikan TEKS, bukan modul."""
    from orchestrator.submission_service import read_submission_sources

    sources = read_submission_sources(env["item"])
    assert {name for name, _ in sources} == {"up.py", "helper.py"}
    for _name, text in sources:
        assert isinstance(text, str)


def test_the_recheck_uses_the_shared_validator_without_changing_it():
    src = (REPO_ROOT / "ui" / "components"
           / "submission_review.py").read_text(encoding="utf-8")
    assert "review_package" in src
    for tampering in ("FORBIDDEN_MODULES", "ALLOWED_MODULES", "checks.remove",
                      "checks.clear", '["valid"] =', ".valid = "):
        assert tampering not in src, tampering


# ── AppTest: sub-tampilan terender ────────────────────────────────────────

def _script(repo: str, db: str, tmp: str, seed: bool) -> str:
    return f'''
import sqlite3, sys
sys.path.insert(0, r"{repo}")
import streamlit as st
import database.db as dbmod
import orchestrator.submission_service as svc
from database.db import init_db
from pathlib import Path

DB = r"{db}"
TMP = Path(r"{tmp}")

def conn(path=None):
    c = sqlite3.connect(path or DB)
    c.row_factory = sqlite3.Row
    return c

dbmod.get_connection = conn
svc.get_connection = conn
svc.SUBMISSION_DIRS[svc.KIND_PIPELINE] = {{
    svc.SUBMISSION_PENDING: TMP / "pipes" / "pending",
    svc.SUBMISSION_APPROVED: TMP / "pipes" / "approved",
    svc.SUBMISSION_REJECTED: TMP / "pipes" / "rejected",
}}
init_db(DB)

if {seed!r} and not svc.list_submissions(db_path=DB):
    svc.submit_pipeline(
        [("up.py", {ENTRY!r}), ("helper.py", {HELPER!r})], "up.py",
        user={{"username": "rina", "role": "contributor", "status": "active"}},
        metadata={{"name": "RF Kontribusi", "dataset_type": "HIKARI2021",
                  "algorithm": "Random Forest", "paper": "Rayyan (2024)",
                  "notes": "versi awal", "entry_class": "Up"}},
        validation={{"valid": True, "entry_points": ["up.py"], "files": [
            {{"filename": "up.py", "role": "entry point", "package_ok": True,
             "description": "kelas pipeline utama"}},
            {{"filename": "helper.py", "role": "pendukung", "package_ok": True,
             "description": "pembantu konversi"}}]}},
        db_path=DB)

from ui.components import theme
theme.inject()
st.session_state["_current_page"] = "Add Pipeline & Dataset"
st.session_state["_contrib_mode"] = "review"
from ui.views.contribute import render
render()
'''


def _run(tmp_path, *, seed: bool, open_id: int | None = None):
    """Jalankan halaman lewat AppTest, lalu KEMBALIKAN state global.

    ``open_id`` membuka SATU pengajuan. Antrean kini master-detail: daftar
    menampilkan tabel ikhtisar saja, dan isi lengkap sebuah pengajuan baru
    tergambar ketika pengajuan itu dibuka. Sebelumnya tidak perlu — seluruh
    kartu tergambar sekaligus, sehingga test ini tidak dapat membedakan
    "detailnya lengkap" dari "semuanya kebetulan tergambar".

    AppTest menjalankan skripnya DI PROSES YANG SAMA, dan skrip itu memasang
    sambungan basis data sementara dengan penugasan langsung. Tanpa pemulihan
    di sini, `database.db.get_connection` tetap menunjuk basis data sementara
    setelah test ini selesai — dan test berikutnya yang membaca basis data
    nyata akan melihatnya kosong lalu MELEWATI dirinya sendiri tanpa suara.
    """
    import database.db as dbmod
    import orchestrator.submission_service as svc
    from streamlit.testing.v1 import AppTest

    from ui.views import login

    saved = (dbmod.get_connection, svc.get_connection,
             dict(svc.SUBMISSION_DIRS[svc.KIND_PIPELINE]))
    try:
        script = tmp_path / "page.py"
        script.write_text(_script(str(REPO_ROOT), str(tmp_path / "at.db"),
                                  str(tmp_path), seed), encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.session_state[login.SESSION_USER_KEY] = ADMIN
        if open_id is not None:
            at.session_state["_contrib_review_open"] = open_id
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        dbmod.get_connection, svc.get_connection = saved[0], saved[1]
        svc.SUBMISSION_DIRS[svc.KIND_PIPELINE] = saved[2]


def test_the_pending_section_renders_a_full_submission(tmp_path):
    at = _run(tmp_path, seed=True, open_id=1)

    # TANPA expander: nama pengajuan dan kedua berkas tergambar langsung, jadi
    # peninjau melihat ada temuan atau tidak tanpa membuka apa pun.
    assert not at.get("expander"), "expander hidup lagi di halaman detail"

    text = " ".join(m.value for m in at.markdown)
    assert "RF Kontribusi" in text                      # nama pengajuan
    assert "up.py" in text and "helper.py" in text      # kedua berkas
    assert "entry point" in text and "pendukung" in text
    assert "kelas pipeline utama" in text               # penjelasan pengunggah
    assert "langsung dapat" in text                     # akibat menyetujui

    # Kode kedua berkas tampil, bernomor.
    blocks = [c.value for c in at.get("code")]
    assert len(blocks) == 2
    assert all(block.splitlines()[0].lstrip().startswith("1 |")
               for block in blocks)

    assert {"Setujui", "Tolak"} <= {b.label for b in at.button}


def test_the_empty_state_renders(tmp_path):
    """Antrean kosong tetap DINYATAKAN, bukan dibiarkan hilang tanpa kata.

    Tabel antrean sama sekali tidak digambar saat kosong — sebuah tabel tanpa
    baris terbaca seperti kegagalan memuat, jadi keadaannya dikatakan.
    """
    at = _run(tmp_path, seed=False)
    text = " ".join(m.value for m in at.markdown)
    assert sr.EMPTY_STATE in text or "menunggu tinjauan" in text.lower()
    # Tidak ada tabel antrean, dan tidak ada keputusan yang dapat ditekan.
    assert not at.get("component_instance")
    assert not [b for b in at.button if b.label == "Setujui"]
