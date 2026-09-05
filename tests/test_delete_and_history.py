"""Menghapus, tabel antrean, dan riwayat peninjauan yang padat.

Empat perubahan pada sub-tampilan "Peninjauan Pengajuan", dan yang dijaga di
sini bukan tampilannya melainkan batas-batasnya:

* **ketertelusuran eksperimen tidak boleh putus** — versi yang pernah dipakai
  eksperimen tidak dapat dihapus, dan penolakannya berlaku di fungsi, bukan
  hanya dengan menyembunyikan tombol;
* **dataset yang sudah terikat bukan milik pengajuannya lagi** — menghapus
  pengajuan tidak boleh ikut menghapusnya;
* **antrean satu benda, bukan dua** — barisnya sendiri yang dapat ditekan;
* **riwayat menyebut yang sudah tersimpan** — kapan diputuskan, siapa yang
  mengajukan, dan bagaimana hasil uji cobanya.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

SOURCE = '''
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"algorithm": "Demo"}
'''
SOURCE_B = SOURCE.replace("DemoPipeline", "OtherPipeline")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "del.db"
    apply_migrations(str(db))
    monkeypatch.setattr("database.db.DB_PATH", str(db), raising=False)
    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)

    roots = {
        SUBMISSION_PENDING: tmp_path / "pending",
        SUBMISSION_APPROVED: tmp_path / "approved",
        SUBMISSION_REJECTED: tmp_path / "rejected",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(ss.SUBMISSION_DIRS, KIND_PIPELINE, roots)
    return {"db": str(db), "roots": roots, "tmp": tmp_path}


def _submission(env, name="pkg"):
    folder = env["roots"][SUBMISSION_APPROVED] / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "p.py").write_text(SOURCE, encoding="utf-8")
    meta = {"entry_filename": "p.py", "class_name": "DemoPipeline",
            "name": name, "dataset_type": "HIKARI2021"}
    conn = sqlite3.connect(env["db"])
    try:
        cur = conn.execute(
            "INSERT INTO submissions (kind, status, submitted_by, submitted_at,"
            " original_filename, stored_path, file_hash, file_size,"
            " metadata_json, validation_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (KIND_PIPELINE, SUBMISSION_APPROVED, "andi", "2026-01-01", "p.py",
             str(folder), "a" * 64, 100, json.dumps(meta),
             json.dumps({"valid": True})))
        conn.commit()
        sid = cur.lastrowid
    finally:
        conn.close()
    dr.register_pipeline(name=name, dataset_type="HIKARI2021",
                         entry_class="DemoPipeline",
                         entry_file=str(folder / "p.py"),
                         registered_by="boss", submission_id=sid,
                         db_path=env["db"])
    return sid, folder


def _experiment_on(env, pipeline_id, *, running=False):
    from database.db import create_experiment, set_running

    create_experiment(experiment_id=f"e_{pipeline_id}",
                      dataset_type="HIKARI2021", dataset_path="/d.csv",
                      dataset_hash="h", created_at="2026-01-01T00:00:00",
                      pipeline_id=pipeline_id, db_path=env["db"])
    if running:
        set_running(f"e_{pipeline_id}", started_at="2026-01-01T00:01:00",
                    db_path=env["db"])


# ── Menghapus pipeline terdaftar ─────────────────────────────────────────

def test_an_unused_version_may_be_deleted(env):
    from orchestrator.pipeline_versions import delete_blocker, delete_version

    _submission(env)
    pid = dr.list_registered(db_path=env["db"])[0]["pipeline_id"]

    assert delete_blocker(pid, env["db"]) == ""
    out = delete_version(pid, actor=ADMIN, db_path=env["db"])
    assert out["pipeline_id"] == pid
    assert not dr.list_registered(db_path=env["db"])


def test_a_used_version_cannot_be_deleted(env):
    """PENGAMAN INTI: ketertelusuran eksperimen tidak boleh putus."""
    from orchestrator.pipeline_versions import (
        PipelineEditError, delete_blocker, delete_version, may_delete,
    )

    _submission(env)
    pid = dr.list_registered(db_path=env["db"])[0]["pipeline_id"]
    _experiment_on(env, pid)

    assert delete_blocker(pid, env["db"]) == "mp.delete_blocked_used"
    assert not may_delete(pid, env["db"])
    with pytest.raises(PipelineEditError):
        delete_version(pid, actor=ADMIN, db_path=env["db"])
    assert dr.list_registered(db_path=env["db"]), "barisnya ikut hilang"


def test_the_refusal_lives_in_the_function_not_only_the_view():
    import inspect

    from orchestrator.pipeline_versions import delete_version

    src = inspect.getsource(delete_version)
    assert "delete_blocker(" in src
    assert "require_approve" in src


def test_deleting_one_version_leaves_the_others(env):
    from orchestrator.pipeline_versions import delete_version

    sid, folder = _submission(env)
    second = folder / "b.py"
    second.write_text(SOURCE_B, encoding="utf-8")
    dr.register_pipeline(name="lain", dataset_type="HIKARI2021",
                         entry_class="OtherPipeline", entry_file=str(second),
                         registered_by="boss", submission_id=sid,
                         db_path=env["db"])

    before = {r["pipeline_id"] for r in dr.list_registered(db_path=env["db"])}
    target = sorted(before)[0]
    delete_version(target, actor=ADMIN, db_path=env["db"])
    after = {r["pipeline_id"] for r in dr.list_registered(db_path=env["db"])}
    assert after == before - {target}


def test_the_deleted_version_file_is_gone(env):
    from orchestrator.pipeline_versions import delete_version

    _submission(env)
    row = dr.list_registered(db_path=env["db"])[0]
    entry = Path(row["entry_file"])
    assert entry.is_file()

    delete_version(row["pipeline_id"], actor=ADMIN, db_path=env["db"])
    assert not entry.is_file()


# ── Menghapus pengajuan ──────────────────────────────────────────────────

def test_deleting_a_submission_removes_its_row_and_folder(env):
    sid, folder = _submission(env)
    assert folder.is_dir()

    ss.delete_submission(sid, actor=ADMIN, db_path=env["db"])
    assert ss.get_submission(sid, env["db"]) is None
    assert not folder.is_dir()


def test_the_summary_states_what_goes_with_it(env):
    sid, _ = _submission(env)
    summary = ss.deletion_summary(ss.get_submission(sid, env["db"]), env["db"])

    assert summary["files"] >= 1
    assert summary["registered"] == 1      # peringatan pipeline terdaftar


def test_a_bound_dataset_is_not_removed_with_its_submission(env):
    """Dataset yang sudah terikat milik PIPELINE-nya, bukan pengajuannya."""
    from orchestrator import research_registry as rr
    from orchestrator.trial_dataset_service import attach_to_submission

    sid, _ = _submission(env)
    data = env["tmp"] / "bound.csv"
    data.write_text("a\n1\n", encoding="utf-8")
    attach_to_submission(sid, {"filename": "bound.csv",
                               "stored_path": str(data),
                               "sha256": "x", "size": 4}, env["db"])
    rr.register_research(dataset_type="uploaded:terikat", name="Terikat",
                         schema={"label_column": "a",
                                 "expected_columns": ["a"]},
                         registered_by="boss", submission_id=sid,
                         db_path=env["db"])
    rr.bind_dataset("uploaded:terikat",
                    {"filename": "bound.csv", "stored_path": str(data)},
                    env["db"])

    item = ss.get_submission(sid, env["db"])
    assert ss.deletion_summary(item, env["db"])["attachment_kept"] is True

    ss.delete_submission(sid, actor=ADMIN, db_path=env["db"])
    assert data.exists(), "dataset terikat ikut terhapus"


def test_an_unbound_attachment_is_removed(env):
    """Yang BELUM terikat memang milik pengajuannya."""
    from orchestrator.trial_dataset_service import attach_to_submission

    sid, _ = _submission(env)
    data = env["tmp"] / "loose.csv"
    data.write_text("a\n1\n", encoding="utf-8")
    attach_to_submission(sid, {"filename": "loose.csv",
                               "stored_path": str(data),
                               "sha256": "x", "size": 4}, env["db"])

    item = ss.get_submission(sid, env["db"])
    assert ss.deletion_summary(item, env["db"])["attachment_kept"] is False


@pytest.mark.parametrize("status", [SUBMISSION_PENDING, SUBMISSION_APPROVED,
                                    SUBMISSION_REJECTED])
def test_deleting_works_on_every_status(env, status):
    sid, _ = _submission(env, name=f"pkg_{status}")
    with sqlite3.connect(env["db"]) as conn:
        conn.execute("UPDATE submissions SET status = ? WHERE id = ?",
                     (status, sid))
        conn.commit()
    ss.delete_submission(sid, actor=ADMIN, db_path=env["db"])
    assert ss.get_submission(sid, env["db"]) is None


def test_the_page_says_deleted_not_unreadable():
    """Dua keadaan berbeda, tindakannya berbeda."""
    src = (REPO_ROOT / "ui" / "views"
           / "manage_pipelines.py").read_text(encoding="utf-8")
    page = src.split("def _render_pipeline_page(")[1].split("\ndef ")[0]
    assert "mp.submission_deleted" in page
    assert "mp.submission_unreadable" in page
    assert "_UNREAD" in page           # gagal-baca dibedakan dari None


def test_the_delete_button_states_what_is_lost():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    body = src.split("def _render_delete_submission(")[1].split("\ndef ")[0]
    # Dilewatkan sebagai REFERENSI ke `_safe_read`, jadi tanpa kurung —
    # pembacaannya sendiri tidak boleh menjatuhkan kartu.
    assert "deletion_summary" in body        # dihitung SEBELUM konfirmasi
    assert "_safe_read(" in body
    assert "ap.delete_confirm" in body
    assert "except Exception" in body           # tidak ada jejak mentah


# ── Antrean: SATU benda ──────────────────────────────────────────────────

def test_the_queue_rows_are_clickable_like_the_experiment_history():
    """Mekanismenya SAMA dengan riwayat eksperimen: tabel, baris dipilih.

    Sebelumnya antrean digambar sebagai tabel HTML yang tidak dapat diklik,
    lalu daftar tombol di bawahnya — dua benda untuk satu maksud. Sekarang
    barisnya sendiri yang dibuka, tanpa tombol "buka" terpisah.
    """
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    body = src.split("def _render_pending_list(")[1].split("\ndef ")[0]
    assert "_render_queue_grid(rows)" in body
    assert "render_table(sr.PENDING_COLUMNS" not in body

    drawn = src.split("def _render_queue_grid(")[1].split("\ndef ")[0]
    assert "grid.render(sr.PENDING_COLUMNS" in drawn
    assert "_open_submission(chosen)" in drawn


def test_every_selectable_list_goes_through_the_same_module():
    """Tiga daftar, SATU mekanisme.

    Ketiganya menjawab pertanyaan yang sama — "yang mana yang saya maksud?" —
    jadi memperbaiki perilaku tabel harus berarti memperbaikinya sekali, bukan
    menambal tiga salinan yang perlahan menyimpang.
    """
    grid_src = (REPO_ROOT / "ui" / "components" / "grid.py").read_text(
        encoding="utf-8")
    assert "AgGrid(" in grid_src
    assert "GridUpdateMode.SELECTION_CHANGED" in grid_src

    for rel in (("ui", "views", "contribute.py"),
                ("ui", "views", "manage_pipelines.py"),
                ("ui", "views", "view_results.py")):
        src = (REPO_ROOT.joinpath(*rel)).read_text(encoding="utf-8")
        assert "from ui.components import grid" in src, rel
        # Tidak ada lagi pembaca pilihan sendiri-sendiri.
        assert "_full_id" not in src or rel[-1] == "view_results.py", rel


def test_only_one_row_can_be_opened_at_a_time():
    """Membuka dua pengajuan sekaligus tidak berarti apa-apa di sini."""
    from ui.components import grid

    import inspect

    signature = inspect.signature(grid.options)
    assert signature.parameters["selection_mode"].default == "single"

    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    drawn = src.split("def _render_queue_grid(")[1].split("\ndef ")[0]
    assert "selection_mode=" not in drawn      # memakai bawaan: satu baris


def test_the_grid_reuses_the_shared_column_labels():
    """Judul kolomnya SATU sumber dengan tabel lain, bukan salinan."""
    grid_src = (REPO_ROOT / "ui" / "components" / "grid.py").read_text(
        encoding="utf-8")
    body = grid_src.split("def dataframe(")[1].split("\ndef ")[0]
    assert "tbl._label(col)" in body
    assert "tbl.cell(row, col)" in body        # format sel pun satu sumber

    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "grid.render(sr.PENDING_COLUMNS" in src


def test_numbers_stay_numbers_so_sorting_is_truthful():
    """Kolom angka yang diubah jadi teks akan mengurutkan 11 sebelum 9, dan
    tabel yang diurutkan salah lebih buruk daripada tabel tanpa urutan."""
    from ui.components import grid
    from ui.components import tables as tbl

    columns = (tbl.column("Berkas", "file_count", kind=tbl.KIND_NUM),)
    df = grid.dataframe(columns, [{"id": 1, "file_count": 9},
                                  {"id": 2, "file_count": 11}], id_key="id")
    assert df["Berkas"].tolist() == [9, 11]
    assert df["Berkas"].max() == 11


def test_a_shortened_cell_keeps_its_full_value_in_a_tooltip():
    """Hash dipendekkan agar kolomnya muat; yang penuh tidak boleh hilang."""
    from ui.components import grid
    from ui.components import tables as tbl

    full = "a" * 64
    columns = (tbl.column("Hash", "file_hash", kind=tbl.KIND_HASH),)
    df = grid.dataframe(columns, [{"id": 1, "file_hash": full}], id_key="id")
    assert df["Hash"][0] != full                       # dipendekkan…
    assert df["Hash" + grid.TIP_SUFFIX][0] == full     # …tetapi tetap dibawa

    options = grid.options(df, columns)
    tip = next(c for c in options["columnDefs"] if c["field"] == "Hash")
    assert tip["tooltipField"] == "Hash" + grid.TIP_SUFFIX
    hidden = {c["field"] for c in options["columnDefs"] if c.get("hide")}
    assert hidden == {grid.ID_FIELD, "Hash" + grid.TIP_SUFFIX}


def test_closing_the_detail_clears_the_grid_selection():
    """Tanpa ini, kembali ke daftar langsung membuka lagi yang barusan ditutup:
    barisnya masih tercentang di sisi frontend."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    close = src.split("def _close_submission(")[1].split("\ndef ")[0]
    assert "_GRID_NONCE_KEY" in close
    drawn = src.split("def _render_queue_grid(")[1].split("\ndef ")[0]
    assert "_GRID_NONCE_KEY" in drawn      # nonce ikut ke kunci grid

    # Daftar pipeline terdaftar menempuh jalan yang sama.
    mp = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    assert "_GRID_NONCE_KEY" in mp.split("def close_pipeline(")[1].split("\ndef ")[0]


def test_the_selection_reader_handles_both_aggrid_shapes():
    """Bentuk kembalian AgGrid berbeda antar versi — keduanya ditangani."""
    import pandas as pd

    from ui.components.grid import ID_FIELD, selected_id, selected_ids

    assert selected_id({"selected_rows": None}) is None
    assert selected_id({"selected_rows": []}) is None
    assert selected_id({"selected_rows": pd.DataFrame()}) is None
    assert selected_id({"selected_rows": [{ID_FIELD: 7}]}) == 7
    assert selected_id({"selected_rows": pd.DataFrame([{ID_FIELD: 9}])}) == 9
    # Tabel yang memang memilih banyak tetap mendapat semuanya.
    many = {"selected_rows": [{ID_FIELD: "a"}, {ID_FIELD: "b"}]}
    assert selected_ids(many) == ["a", "b"]
    assert selected_ids(many, cast=str) == ["a", "b"]


# ── Riwayat peninjauan ───────────────────────────────────────────────────

def test_the_history_shows_what_was_never_shown_before():
    from ui.components.submission_review import HISTORY_COLUMNS

    keys = {c["key"] for c in HISTORY_COLUMNS}
    assert {"reviewed_at", "submitted_by", "trial"} <= keys


def test_the_trial_outcome_is_read_from_the_stored_trail():
    from ui.components.submission_review import trial_outcome

    assert "lolos" in trial_outcome(
        {"trial_json": '{"status":"PASSED","rows_used":10,"duration_s":1}'})
    assert "gagal" in trial_outcome(
        {"trial_json": '{"status":"FAILED","error_stage":"memuat"}'})
    # Tidak pernah diuji, dan jejak rusak: sama-sama "—", bukan meledak.
    assert trial_outcome({}) == "—"
    assert trial_outcome({"trial_json": "{rusak"}) == "—"


def test_a_long_note_is_shortened_but_never_lost():
    from ui.components.submission_review import NOTE_PREVIEW, history_rows

    row = history_rows([{"id": 1, "original_filename": "p.py",
                         "status": "approved", "review_note": "x" * 200}],
                       status_label=str)[0]
    assert len(row["note"]) <= NOTE_PREVIEW
    assert len(row["note_full"]) == 200     # penuh tetap ada di tooltip


def test_building_history_rows_reads_nothing(monkeypatch):
    import orchestrator.submission_service as svc
    from ui.components.submission_review import history_rows

    def _boom(*a, **k):
        raise AssertionError("riwayat membaca berkas")

    monkeypatch.setattr(svc, "read_submission_sources", _boom)
    history_rows([{"id": 1, "original_filename": "p.py",
                   "status": "approved"}], status_label=str)


def test_the_history_is_a_table_now():
    """Riwayat tinjauan kini tinggal di tab "Riwayat versi" — lihat
    `test_review_history_placement.py` untuk alasannya."""
    src = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    body = src.split("def _render_review_history(")[1].split("\ndef ")[0]
    assert "sr.HISTORY_COLUMNS" in body
    assert "sr.history_rows(" in body
