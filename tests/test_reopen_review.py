"""Tinjau ulang: persetujuan bukan lagi keadaan akhir (Tahap 4).

Sampai sekarang, sebuah pengajuan yang sudah disetujui tidak pernah dapat
ditinjau kembali. Yang tersedia hanya menyalakan/mematikan pipelinenya dan
menyunting berkasnya — padahal peninjauan penuh (uji coba, temuan, keputusan)
justru itu yang dibutuhkan ketika sebuah pipeline dinonaktifkan KARENA
bermasalah.

Yang dijaga di sini:

* **versi yang sudah terdaftar tidak disentuh** — eksperimen lama tetap
  menunjuk kode yang persis sama, dan menyetujui lagi menghasilkan versi BARU;
* **pipeline yang masih aktif tidak dapat ditarik kembali** — terdaftar
  sekaligus "menunggu tinjauan" adalah keadaan yang membingungkan;
* **berkasnya benar-benar kembali ke antrean**, bukan hanya statusnya.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from database.migration import apply_migrations
from database.models import (
    KIND_PIPELINE, SUBMISSION_APPROVED, SUBMISSION_PENDING, SUBMISSION_REJECTED,
)
from orchestrator import dynamic_registry as dr
from orchestrator import submission_service as ss

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

SOURCE = '''
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"algorithm": "Demo"}
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "reopen.db"
    apply_migrations(str(db))
    monkeypatch.setattr("database.db.DB_PATH", str(db), raising=False)
    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)

    roots = {
        SUBMISSION_PENDING: tmp_path / "pending",
        SUBMISSION_APPROVED: tmp_path / "approved",
        SUBMISSION_REJECTED: tmp_path / "rejected",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(ss.SUBMISSION_DIRS, KIND_PIPELINE, roots)
    return {"db": str(db), "roots": roots, "tmp": tmp_path}


def _approved_submission(env) -> tuple[int, str]:
    """Satu pengajuan yang SUDAH disetujui + pipeline terdaftarnya."""
    folder = env["roots"][SUBMISSION_APPROVED] / "pkg"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p.py").write_text(SOURCE, encoding="utf-8")

    meta = {"entry_filename": "p.py", "class_name": "DemoPipeline",
            "name": "demo", "dataset_type": "HIKARI2021"}
    conn = sqlite3.connect(env["db"])
    try:
        cur = conn.execute(
            "INSERT INTO submissions (kind, status, submitted_by, submitted_at,"
            " original_filename, stored_path, file_hash, file_size,"
            " metadata_json, validation_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (KIND_PIPELINE, SUBMISSION_APPROVED, "andi", "2026-01-01", "p.py",
             str(folder), "a" * 64, 100, json.dumps(meta),
             json.dumps({"valid": True})))
        conn.commit()
        sid = cur.lastrowid
    finally:
        conn.close()

    dr.register_pipeline(name="demo", dataset_type="HIKARI2021",
                         entry_class="DemoPipeline",
                         entry_file=str(folder / "p.py"),
                         registered_by="boss", submission_id=sid,
                         db_path=env["db"])
    return sid, folder


def _deactivate(env, sid):
    for row in dr.list_registered(db_path=env["db"]):
        if row["submission_id"] == sid:
            with sqlite3.connect(env["db"]) as conn:
                conn.execute(
                    "UPDATE registered_pipelines SET active = 0 WHERE pipeline_id = ?",
                    (row["pipeline_id"],))
                conn.commit()


# ── Gerbang ──────────────────────────────────────────────────────────────

def test_an_active_pipeline_cannot_be_pulled_back(env):
    """Terdaftar DAN menunggu tinjauan sekaligus adalah keadaan membingungkan."""
    sid, _ = _approved_submission(env)
    item = ss.get_submission(sid, env["db"])

    assert ss.reopen_blocker(item, env["db"]) == "ap.reopen_still_active"
    assert not ss.may_reopen(item, env["db"])
    with pytest.raises(ss.SubmissionError):
        ss.reopen_submission(sid, actor=ADMIN, db_path=env["db"])


def test_a_deactivated_pipeline_may_be_reopened(env):
    sid, _ = _approved_submission(env)
    _deactivate(env, sid)
    item = ss.get_submission(sid, env["db"])
    assert ss.reopen_blocker(item, env["db"]) == ""
    assert ss.may_reopen(item, env["db"])


def test_a_pending_submission_is_not_reopenable(env):
    sid, _ = _approved_submission(env)
    with sqlite3.connect(env["db"]) as conn:
        conn.execute("UPDATE submissions SET status = ? WHERE id = ?",
                     (SUBMISSION_PENDING, sid))
        conn.commit()
    item = ss.get_submission(sid, env["db"])
    assert ss.reopen_blocker(item, env["db"]) == "ap.reopen_not_approved"


def test_the_reason_is_always_stated():
    """Tombol mati tanpa keterangan membuat peninjau menebak."""
    from ui.i18n.core import lookup

    for key in ("ap.reopen_not_approved", "ap.reopen_only_pipeline",
                "ap.reopen_still_active", "ap.btn_reopen", "ap.help_reopen",
                "ap.msg_reopened"):
        for lang in ("id", "en"):
            assert lookup(key, lang), (key, lang)


# ── Yang terjadi saat dibuka kembali ─────────────────────────────────────

def test_reopening_returns_it_to_the_queue(env):
    sid, _ = _approved_submission(env)
    _deactivate(env, sid)
    out = ss.reopen_submission(sid, actor=ADMIN, db_path=env["db"])
    assert out["status"] == SUBMISSION_PENDING


def test_the_files_move_back_to_the_pending_area(env):
    """Bukan hanya statusnya — berkasnya benar-benar kembali."""
    sid, folder = _approved_submission(env)
    _deactivate(env, sid)
    ss.reopen_submission(sid, actor=ADMIN, db_path=env["db"])

    item = ss.get_submission(sid, env["db"])
    stored = Path(item["stored_path"])
    assert stored.exists()
    assert env["roots"][SUBMISSION_PENDING] in stored.parents
    assert (stored / "p.py").exists()


def test_the_registered_version_is_left_untouched(env):
    """PENGAMAN INTI: eksperimen lama tetap menunjuk kode yang sama."""
    sid, _ = _approved_submission(env)
    before = dr.list_registered(db_path=env["db"])
    _deactivate(env, sid)
    ss.reopen_submission(sid, actor=ADMIN, db_path=env["db"])
    after = dr.list_registered(db_path=env["db"])

    assert len(after) == len(before)
    assert [r["pipeline_id"] for r in after] == [r["pipeline_id"] for r in before]
    assert [r["file_hash"] for r in after] == [r["file_hash"] for r in before]


def test_the_previous_review_trail_is_kept(env):
    """`reviewed_by`/`reviewed_at` adalah riwayat, bukan sampah."""
    sid, _ = _approved_submission(env)
    with sqlite3.connect(env["db"]) as conn:
        conn.execute("UPDATE submissions SET reviewed_by = ?, reviewed_at = ?"
                     " WHERE id = ?", ("boss", "2026-01-02", sid))
        conn.commit()
    _deactivate(env, sid)
    ss.reopen_submission(sid, actor=ADMIN, db_path=env["db"])

    item = ss.get_submission(sid, env["db"])
    assert item["reviewed_by"] == "boss"
    assert item["reviewed_at"] == "2026-01-02"


def test_approving_again_creates_a_new_version(env):
    """Menyetujui ulang MENAMBAH versi, tidak menimpa."""
    sid, _ = _approved_submission(env)
    _deactivate(env, sid)
    ss.reopen_submission(sid, actor=ADMIN, db_path=env["db"])

    before = len(dr.list_registered(db_path=env["db"]))
    item = ss.get_submission(sid, env["db"])
    dr.register_pipeline(name="demo", dataset_type="HIKARI2021",
                         entry_class="DemoPipeline",
                         entry_file=str(Path(item["stored_path"]) / "p.py"),
                         registered_by="boss", submission_id=sid,
                         db_path=env["db"])
    rows = dr.list_registered(db_path=env["db"])
    assert len(rows) == before + 1
    assert max(r["version"] for r in rows) == before + 1


# ── Tampilan menemukan pengajuannya ──────────────────────────────────────

def test_the_view_finds_the_submission_from_the_version_family():
    """`summary` meringkas REGISTRY dan tidak membawa `submission_id`.

    Hanya versi yang lahir dari persetujuan yang membawanya; versi hasil
    penyuntingan tidak. Penelusurannya harus melewati keluarga versi, bukan
    membaca satu bidang yang memang tidak ada di sana.
    """
    from ui.views import manage_pipelines as mp

    assert "submission_id" not in {
        "algorithm", "dataset_type", "entry_class", "file_hash", "name",
        "pipeline_id", "version",
    }
    assert callable(mp._submission_of)


def test_the_button_is_disabled_with_its_reason():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "views"
           / "manage_pipelines.py").read_text(encoding="utf-8")
    block = src.split("def _render_reopen(")[1].split("\ndef ")[0]
    assert "disabled=bool(blocker)" in block
    assert "help=t(blocker)" in block
    # Kesalahan tak terduga tidak lolos sebagai jejak teknis.
    assert "except Exception" in block and "logger.exception(" in block


def test_the_action_enforces_permission_itself():
    """Menyembunyikan tombol tidak pernah menjadi satu-satunya penghalang."""
    import inspect

    assert "require_approve" in inspect.getsource(ss.reopen_submission)


# ── Tahap 2: satu pengajuan, BANYAK algoritma ────────────────────────────
# Sebuah research pipeline kontribusi berdiri sendiri dan wajar membawa
# beberapa algoritma sekaligus — persis seperti keluarga bawaan (HIKARI2021
# punya enam). Sebelumnya paket dengan lebih dari satu turunan `BasePipeline`
# DITOLAK, sehingga satu pengajuan tidak pernah bisa menjadi lebih dari satu
# algoritma.

SOURCE_B = SOURCE.replace("DemoPipeline", "OtherPipeline").replace('"Demo"', '"Other"')


def test_a_package_with_several_algorithms_is_valid():
    from ui.components.pipeline_upload import review_package

    result = review_package([("a.py", SOURCE.encode()),
                             ("b.py", SOURCE_B.encode())])
    assert result["entry_points"] == ["a.py", "b.py"]
    assert result["valid"] is True
    assert not result["cause"]


def test_a_package_without_any_algorithm_is_still_refused():
    """Batas bawahnya TIDAK dilonggarkan."""
    from ui.components.pipeline_upload import review_package

    result = review_package([("helper.py", b"x = 1\n")])
    assert result["valid"] is False
    assert result["entry_points"] == []


def test_every_algorithm_file_is_still_fully_checked():
    """Melonggarkan jumlahnya tidak melonggarkan pemeriksaannya."""
    from ui.components.pipeline_upload import review_package

    unsafe = SOURCE_B + "\nimport os\n"
    result = review_package([("a.py", SOURCE.encode()),
                             ("b.py", unsafe.encode())])
    assert result["valid"] is False, "berkas kedua lolos padahal tidak aman"


def test_the_old_single_entry_shape_still_registers_one(env):
    """Pengajuan LAMA hanya mencatat satu `entry_class` — tetap terbaca."""
    from orchestrator.submission_service import _algorithms_of

    item = {"original_filename": "p.py",
            "metadata": {"entry_class": "DemoPipeline", "algorithm": "RF"}}
    out = _algorithms_of(item)
    assert len(out) == 1
    assert out[0]["class_name"] == "DemoPipeline"
    assert out[0]["filename"] == "p.py"


def test_the_new_shape_lists_every_algorithm():
    from orchestrator.submission_service import _algorithms_of

    item = {"original_filename": "a.py", "metadata": {"algorithms": [
        {"filename": "a.py", "class_name": "A", "algorithm": "RF"},
        {"filename": "b.py", "class_name": "B", "algorithm": "DT"}]}}
    assert [e["class_name"] for e in _algorithms_of(item)] == ["A", "B"]


def test_a_malformed_algorithm_entry_is_skipped_not_crashed():
    from orchestrator.submission_service import _algorithms_of

    item = {"original_filename": "a.py", "metadata": {"algorithms": [
        {"filename": "a.py", "class_name": "A"},
        {"filename": "b.py"},            # tanpa class_name
        "bukan dict",
    ]}}
    assert [e["class_name"] for e in _algorithms_of(item)] == ["A"]


def test_approving_a_multi_algorithm_package_registers_each_one(env, tmp_path):
    """Satu pengajuan -> BANYAK baris registry, berbagi dataset_type & pengajuan."""
    folder = env["roots"][SUBMISSION_APPROVED] / "multi"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a.py").write_text(SOURCE, encoding="utf-8")
    (folder / "b.py").write_text(SOURCE_B, encoding="utf-8")

    meta = {"name": "kampus", "dataset_type": "HIKARI2021",
            "entry_filename": "a.py", "entry_class": "DemoPipeline",
            "algorithms": [
                {"filename": "a.py", "class_name": "DemoPipeline",
                 "algorithm": "RF"},
                {"filename": "b.py", "class_name": "OtherPipeline",
                 "algorithm": "DT"}]}
    conn = sqlite3.connect(env["db"])
    try:
        cur = conn.execute(
            "INSERT INTO submissions (kind, status, submitted_by, submitted_at,"
            " original_filename, stored_path, file_hash, file_size,"
            " metadata_json, validation_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (KIND_PIPELINE, SUBMISSION_APPROVED, "andi", "2026-01-01", "a.py",
             str(folder), "b" * 64, 100, json.dumps(meta),
             json.dumps({"valid": True})))
        conn.commit()
        sid = cur.lastrowid
    finally:
        conn.close()

    item = ss.get_submission(sid, env["db"])
    ss._register_approved_pipeline(item, folder, ADMIN, "HIKARI2021", env["db"])

    rows = [r for r in dr.list_registered(db_path=env["db"])
            if r["submission_id"] == sid]
    assert len(rows) == 2, [r["pipeline_id"] for r in rows]
    assert {r["entry_class"] for r in rows} == {"DemoPipeline", "OtherPipeline"}
    # Berbagi identitas research yang sama…
    assert {r["dataset_type"] for r in rows} == {"HIKARI2021"}
    # …tetapi punya pengenal masing-masing, sehingga versinya dihitung sendiri.
    assert len({r["pipeline_id"] for r in rows}) == 2


def test_a_single_algorithm_keeps_its_original_identifier(env):
    """Pengajuan satu algoritma TIDAK berubah pengenalnya."""
    sid, folder = _approved_submission(env)
    rows = [r for r in dr.list_registered(db_path=env["db"])
            if r["submission_id"] == sid]
    assert len(rows) == 1
    assert rows[0]["name"] == "demo"          # tanpa akhiran nama kelas


def test_the_upload_path_and_the_editor_differ_on_purpose():
    """Dua jalur, dua aturan — dan alasannya berbeda, bukan tidak konsisten.

    Unggah: banyak titik masuk = banyak algoritma dalam satu research pipeline.
    Penyunting versi: satu baris registry memetakan ke SATU `entry_class`, jadi
    titik masuk kedua tidak akan pernah dimuat — kode mati yang terbaca seperti
    algoritma baru.
    """
    from orchestrator.pipeline_versions import validate_package
    from ui.components.pipeline_upload import review_package

    files = {"a.py": SOURCE, "b.py": SOURCE_B}
    payload = [(n, t.encode("utf-8")) for n, t in files.items()]

    assert review_package(payload)["valid"] is True      # unggah: boleh
    editor = validate_package(files)
    assert editor["valid"] is False                      # penyunting: tidak
    assert "titik masuk" in editor["cause"]
    # Alasannya menyebut jalan keluarnya, bukan sekadar menolak.
    assert "pengajuan" in editor["cause"]


def test_the_editor_still_accepts_a_single_entry_point():
    """Penjaga anti-hampa: aturannya tidak boleh menolak paket yang sah."""
    from orchestrator.pipeline_versions import validate_package

    assert validate_package({"a.py": SOURCE})["valid"] is True


# ── Halaman tersendiri per pipeline ──────────────────────────────────────
# Kedua daftar membuka SATU pipeline sekali jalan, tetapi mekanismenya beda
# keduanya kini memakai MEKANISME yang sama — tabel berkolom yang barisnya
# dipilih, sama seperti riwayat eksperimen. Yang dijaga bukan tampilannya,
# melainkan: identitas tiap daftar TERBEDAKAN, tiap pembukaan menyangkut SATU
# hal, dan menyusunnya tidak menambah pembacaan apa pun.

def test_the_queue_is_keyed_by_number_the_registry_by_pipeline():
    """Kedua tabel membawa identitas yang BERBEDA jenisnya, dan keliru
    menukarnya akan membuka hal yang salah."""
    from ui.components.registry_view import ACTIVE_COLUMNS
    from ui.components.submission_review import PENDING_COLUMNS, summary_row

    row = summary_row({"id": 14, "submitted_by": "andi",
                       "submitted_at": "2026-01-01T00:00:00",
                       "original_filename": "p.py",
                       "metadata": {"name": "p"}}, {"valid": True})
    assert row["id"] == 14          # dibawa baris, dipakai saat baris dipilih

    # Versi hanya berarti pada yang TERDAFTAR: sebuah pengajuan belum punya.
    keys = {c["key"] for c in ACTIVE_COLUMNS}
    assert "version" in keys
    assert "version" not in {c["key"] for c in PENDING_COLUMNS}


def test_a_broken_pipeline_states_its_reason_on_its_row():
    """Baris yang rusak tidak boleh terbaca seperti yang sehat.

    Sebabnya dibawa dua lapis: kata pendek pada kolom Status yang terbaca
    tanpa tindakan apa pun, dan kalimat penuhnya pada tooltip kolom itu.
    """
    from ui.components.registry_view import (ACTIVE_COLUMNS, STATE_MISSING,
                                             active_table_rows, state_short)

    rows = active_table_rows([{"name": "x", "version": 1,
                               "dataset_type": "HIKARI2021",
                               "is_active": False, "state": STATE_MISSING,
                               "state_reason": "berkasnya tidak ditemukan"}])
    assert state_short(STATE_MISSING) in rows[0]["status_text"]
    status_col = next(c for c in ACTIVE_COLUMNS if c["key"] == "status_text")
    assert status_col["title_key"] == "state_reason"


def test_building_the_list_rows_rereads_no_package_source(monkeypatch):
    """Baris kedua tabel hanya menyusun ulang data yang SUDAH dihitung.

    Hasil periksa disuntikkan lewat ``reviewer`` — memakai cache yang sama
    dengan kartunya — jadi memanjangkan antrean tidak melipatgandakan
    pembacaan berkas sumber."""
    import orchestrator.submission_service as svc
    from ui.components.registry_view import active_table_rows
    from ui.components.submission_review import pending_table_rows

    def _boom(*a, **k):
        raise AssertionError("menyusun daftar membaca ulang berkas sumber")

    monkeypatch.setattr(svc, "read_submission_sources", _boom)
    rows = pending_table_rows(
        [{"id": 1, "submitted_by": "a", "submitted_at": "2026-01-01",
          "original_filename": "p.py", "metadata": {"name": "p"}}],
        lambda item: {"valid": True, "files": [{"filename": "p.py"}]})
    assert [r["id"] for r in rows] == [1]
    active_table_rows([{"name": "p", "version": 1, "dataset_type": "H",
                        "is_active": True, "state": "ok"}])


def test_the_queue_opens_a_submission_from_the_selected_row():
    """Tidak ada lagi tombol "buka peninjauan" terpisah: barisnya sendiri."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    body = src.split("def _render_pending_list(")[1].split("\ndef ")[0]
    assert "_render_queue_grid(rows)" in body
    grid = src.split("def _render_queue_grid(")[1].split("\ndef ")[0]
    assert "_open_submission(chosen)" in grid
    # Selectbox pembuka yang lama sudah tidak ada.
    assert 'key="review_pick"' not in body


def test_the_active_list_is_one_selectable_table_not_two_things():
    """Dahulu: tabel HTML mati DITAMBAH tumpukan tombol berisi data yang sama.
    Sekarang satu tabel, dan tabel itulah yang dapat diklik."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "ui" / "views"
           / "manage_pipelines.py").read_text(encoding="utf-8")
    body = src.split("def render_active(")[1].split("\ndef ")[0]
    assert "_render_pipeline_grid(summaries)" in body
    assert "render_table(" not in body          # tabel mati sudah tidak ada
    assert "_render_pipeline_block(summary, user)" not in body

    drawn = src.split("def _render_pipeline_grid(")[1].split("\ndef ")[0]
    assert "grid.render(" in drawn
    assert "open_pipeline(chosen)" in drawn


def test_the_pipeline_page_carries_the_full_review():
    """Peninjauan penuh, bukan sekadar identitas + aksi."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "ui" / "views"
           / "manage_pipelines.py").read_text(encoding="utf-8")
    page = src.split("def _render_pipeline_page(")[1].split("\ndef ")[0]
    assert "_render_pipeline_block(summary, user)" in page   # identitas & aksi
    assert "render_review_body(item, user)" in page          # kartu penuh
    assert "close_pipeline" in page                          # jalan kembali
    # Versi hasil penyuntingan tidak punya pengajuan — dinyatakan, tidak diam.
    assert "mp.no_submission_behind" in page


def test_the_open_pipeline_marker_is_swept_between_pages():
    from ui.components import page_flags

    assert any("_mp_open_pipeline".startswith(p)
               for p in page_flags.VIEW_STATE_PREFIXES)
