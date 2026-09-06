"""
Rantai penuh pipeline kontribusi: unggah → uji → setujui → aktif → JALAN.

Cacat yang membuat berkas ini ada: pipeline kontribusi yang sudah disetujui
dan diaktifkan tidak pernah muncul di katalog Run Experiment. Ia terdaftar,
aktif, dapat dimuat worker, dan dapat dipilih — tetapi katalog membaca
registry STATIS, jadi seluruh rantai unggah→validasi→uji→setujui→aktivasi
tidak menghasilkan apa pun yang terlihat.

Karena itu yang diuji di sini adalah HASIL AKHIR rantainya, bukan potongan:
sebuah pipeline yang menempuh seluruh jalur harus benar-benar muncul, dapat
dipilih, dan benar-benar berjalan.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pandas as pd
import pytest

from database import trials as trial_db
from database.migration import apply_migrations
from database.models import KIND_PIPELINE, SUBMISSION_PENDING
from orchestrator import dynamic_registry as dr

REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

#: Pipeline kontribusi yang SAH: mewarisi kontrak, mengembalikan PipelineResult.
CONTRIB_SOURCE = '''
from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineResult


class ContribPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        df = pipeline_input.df
        return PipelineResult(
            accuracy=1.0, precision=1.0, recall=1.0, f1_score=1.0,
            confusion_matrix=[[len(df), 0], [0, 0]],
            model=None, feature_names=list(df.columns)[:2],
            label_mapping={"0": "Benign", "1": "Attack"})

    def get_info(self):
        return {"algorithm": "ContribAlgo", "paper": "kontribusi"}
'''


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "chain.db"
    apply_migrations(str(path))
    monkeypatch.setattr("database.db.DB_PATH", str(path), raising=False)
    return str(path)


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "contrib_pipeline.py").write_text(CONTRIB_SOURCE,
                                                encoding="utf-8")
    return folder


@pytest.fixture
def small_csv():
    """Dataset kecil di folder yang diizinkan platform."""
    path = Path("storage/datasets/_chain_fixture.csv")
    pd.DataFrame({"a": range(20), "b": range(20),
                  "Label": [0, 1] * 10}).to_csv(path, index=False)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _submit(db_path, package_dir) -> int:
    """Pengajuan pipeline yang LOLOS pemeriksaan statis."""
    metadata = {"entry_filename": "contrib_pipeline.py",
                "class_name": "ContribPipeline",
                "entry_class": "ContribPipeline",
                "name": "contrib_demo",
                "dataset_type": "HIKARI2021"}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json,
                validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (KIND_PIPELINE, SUBMISSION_PENDING, "andi", "2026-01-01T00:00:00",
             "contrib_pipeline.py", str(package_dir), "a" * 64, 100,
             json.dumps(metadata), json.dumps({"valid": True})))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _pass_trial(db_path, submission_id, dataset_path):
    """Uji coba yang BERHASIL pada isi paket saat ini."""
    from orchestrator.submission_service import get_submission
    from orchestrator.trial_service import submission_fingerprint

    item = get_submission(submission_id, db_path)
    trial_id = str(uuid.uuid4())
    trial_db.create_trial(
        trial_id=trial_id, submission_id=submission_id,
        package_hash=submission_fingerprint(item),
        dataset_type="HIKARI2021", dataset_path=str(dataset_path),
        started_by="boss", started_at="2026-01-01T01:00:00", db_path=db_path)
    trial_db.finish_trial(
        trial_id, status=trial_db.STATUS_PASSED,
        finished_at="2026-01-01T01:01:00", duration_s=1.0, rows_used=20,
        metrics={"accuracy": 1.0}, db_path=db_path)
    return trial_id


def _approve_and_activate(db_path, submission_id, monkeypatch) -> str:
    """Setujui pengajuan → pipeline terdaftar & aktif. Kembalikan pipeline_id."""
    from orchestrator import submission_service as ss

    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    ss.approve_submission(submission_id, actor=ADMIN,
                          dataset_type="HIKARI2021", db_path=db_path)
    rows = [r for r in dr.list_registered(db_path=db_path)
            if r["submission_id"] == submission_id]
    assert len(rows) == 1, rows
    return rows[0]["pipeline_id"]


def _catalog_ids(db_path):
    """pipeline_id yang BENAR-BENAR muncul di katalog Run Experiment."""
    from ui.components.pipeline_catalog import build_catalog

    catalog = build_catalog(
        registry_reader=lambda: dr.get_all_pipelines(db_path))
    return catalog, [a["pipeline_id"] for g in catalog
                     for a in g["algorithms"]]


# ── RANTAI PENUH ─────────────────────────────────────────────────────────

def test_the_full_chain_ends_with_a_runnable_pipeline(db, package, small_csv,
                                                      monkeypatch):
    """Unggah → uji → setujui → aktif → MUNCUL → DAPAT DIPILIH → BERJALAN.

    Inilah acuan keberhasilan: memeriksa potongan-potongannya saja tidak
    menangkap cacat yang membuat berkas ini ada.
    """
    # 1. pengajuan yang lolos pemeriksaan statis
    sid = _submit(db, package)

    # 2. uji coba berhasil
    _pass_trial(db, sid, small_csv)
    from orchestrator.trial_service import may_approve
    from orchestrator.submission_service import get_submission

    assert may_approve(get_submission(sid, db), db)

    # 3. setujui & aktifkan
    pid = _approve_and_activate(db, sid, monkeypatch)
    assert dr.get_registered(pid, db)["active"] == 1

    # 4. MUNCUL di katalog Run Experiment
    catalog, ids = _catalog_ids(db)
    assert pid in ids, f"{pid} tidak muncul di katalog: {ids}"

    # 5. DAPAT DIPILIH untuk dijalankan
    selectable = dr.get_pipelines_for_dataset_merged("HIKARI2021", db)
    assert pid in selectable, f"{pid} tidak dapat dipilih"

    # 6. WORKER benar-benar dapat memuat & MENJALANKANNYA
    from contracts.dataset_schemas import get_schema
    from contracts.pipeline_contracts import PipelineInput
    from workers.local_worker import run_pipeline

    instance = dr.get_pipeline_instance_merged(pid, db)
    assert instance is not None, "worker tidak dapat memuat pipeline"
    result = run_pipeline(instance, PipelineInput(
        df=pd.read_csv(small_csv),
        label_column=get_schema("HIKARI2021")["label_column"],
        dataset_type="HIKARI2021", dataset_path=str(small_csv),
        param_overrides={}))
    assert result.accuracy == 1.0

    # 7. dinonaktifkan → tidak lagi dapat dipilih, catatan lama UTUH
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    dr.set_pipeline_active(pid, False, actor=ADMIN, db_path=db)

    assert pid not in dr.get_pipelines_for_dataset_merged("HIKARI2021", db)
    assert pid not in _catalog_ids(db)[1]
    row = dr.get_registered(pid, db)
    assert row is not None and row["active"] == 0
    assert row["file_hash"] and row["version"] == 1   # catatan tetap utuh


# ── Sebab cacatnya: ketiga pembaca harus SEPAKAT ────────────────────────

def test_catalog_selection_and_worker_read_the_same_set(db, package,
                                                        small_csv, monkeypatch):
    sid = _submit(db, package)
    _pass_trial(db, sid, small_csv)
    pid = _approve_and_activate(db, sid, monkeypatch)

    _, catalog_ids = _catalog_ids(db)
    selection = dr.get_pipelines_for_dataset_merged("HIKARI2021", db)
    worker = dr.get_pipeline_instance_merged(pid, db)

    assert pid in catalog_ids
    assert pid in selection
    assert worker is not None


def test_the_catalog_no_longer_defaults_to_the_static_registry():
    """Sebab cacatnya, dijaga di tempatnya."""
    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    assert "from orchestrator.dynamic_registry import get_all_pipelines" in src
    assert "registry_reader = get_all_pipelines" in src
    assert "registry_reader = list_all_pipelines" not in src


# ── Pipeline bawaan tetap utuh ───────────────────────────────────────────

def test_all_ten_built_in_pipelines_still_appear(db):
    from config.pipeline_registry import PIPELINE_REGISTRY

    _, ids = _catalog_ids(db)
    assert len(PIPELINE_REGISTRY) == 10
    for pid in PIPELINE_REGISTRY:
        assert pid in ids, pid


def test_a_contributed_pipeline_can_never_overwrite_a_built_in(db, package,
                                                               monkeypatch):
    """Entri statis SELALU menang."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    merged = dr.get_all_pipelines(db)
    for pid, entry in PIPELINE_REGISTRY.items():
        assert merged[pid] is entry or merged[pid] == entry


# ── Keadaan bermasalah: TERLIHAT, bukan hilang ──────────────────────────

def test_a_tampered_pipeline_is_shown_as_broken_with_its_reason(
        db, package, small_csv, monkeypatch):
    """Berkas yang berubah setelah pendaftaran tidak boleh hilang diam-diam."""
    from ui.components import pipeline_catalog as pc

    sid = _submit(db, package)
    _pass_trial(db, sid, small_csv)
    pid = _approve_and_activate(db, sid, monkeypatch)

    # Berkasnya diubah di luar platform, setelah hash-nya tercatat.
    entry_file = Path(dr.get_registered(pid, db)["entry_file"])
    entry_file.write_text(CONTRIB_SOURCE + "\n# disunting\n", encoding="utf-8")

    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)
    catalog, ids = _catalog_ids(db)

    # TETAP muncul — menghilangkannya membuat pengguna mencari sesuatu yang
    # tidak pernah menjelaskan dirinya.
    assert pid in ids

    entry = next(a for g in catalog for a in g["algorithms"]
                 if a["pipeline_id"] == pid)
    assert entry["state"] == pc.STATE_BROKEN
    assert entry["state_reason"], "sebabnya harus disebut"

    # Sebabnya juga muncul sebagai KALIMAT, bukan hanya tooltip.
    group = next(g for g in catalog
                 if any(a["pipeline_id"] == pid for a in g["algorithms"]))
    problems = pc.group_problems(group)
    assert problems and any(entry["algorithm"] in p for p in problems)


def test_a_healthy_pipeline_is_not_flagged(db, package, small_csv, monkeypatch):
    from ui.components import pipeline_catalog as pc

    sid = _submit(db, package)
    _pass_trial(db, sid, small_csv)
    pid = _approve_and_activate(db, sid, monkeypatch)
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    catalog, _ = _catalog_ids(db)
    entry = next(a for g in catalog for a in g["algorithms"]
                 if a["pipeline_id"] == pid)
    assert entry["state"] == pc.STATE_OK
    assert entry["uploaded"] is True
    assert entry["version"] == 1


# ── Jenis dataset tanpa pasangan: terlihat, dengan keterangan ───────────

def test_a_pipeline_with_no_matching_dataset_stays_visible(db, package,
                                                           monkeypatch):
    from ui.components import pipeline_catalog as pc

    entry_file = package / "contrib_pipeline.py"
    row = dr.register_pipeline(
        name="own_format", dataset_type="MY_OWN_FORMAT",
        entry_class="ContribPipeline", entry_file=str(entry_file),
        algorithm="ContribAlgo", registered_by="boss", submission_id=99,
        db_path=db)
    pid = row["pipeline_id"] if isinstance(row, dict) else row
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    catalog, ids = _catalog_ids(db)
    assert pid in ids, "pipeline tanpa dataset pasangan tidak boleh disembunyikan"

    entry = next(a for g in catalog for a in g["algorithms"]
                 if a["pipeline_id"] == pid)
    assert entry["state"] == pc.STATE_NO_DATASET
    assert "dataset" in entry["state_reason"].lower()


def test_an_unknown_dataset_type_gets_an_honest_group_title(db, package,
                                                            monkeypatch):
    """Judul grup bukan pengenal mentah."""
    entry_file = package / "contrib_pipeline.py"
    dr.register_pipeline(
        name="own_format2", dataset_type="MY_OWN_FORMAT",
        entry_class="ContribPipeline", entry_file=str(entry_file),
        algorithm="ContribAlgo", registered_by="boss", submission_id=98,
        db_path=db)
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    catalog, _ = _catalog_ids(db)
    group = next(g for g in catalog if g["dataset_type"] == "MY_OWN_FORMAT")
    assert group["title"] != "MY_OWN_FORMAT"
    assert "MY_OWN_FORMAT" in group["title"]      # pengenalnya tetap disebut


# ── Penanda pada chip ────────────────────────────────────────────────────

def test_the_chip_states_the_origin_and_version():
    from ui.components.pipeline_catalog import chips_html

    html = chips_html([{"algorithm": "ContribAlgo", "uploaded": True,
                        "version": 3, "state": "ok", "state_reason": ""}])
    assert "ContribAlgo" in html
    assert "3" in html


def test_the_chip_carries_the_reason_when_broken():
    from ui.components.pipeline_catalog import STATE_BROKEN, chips_html

    html = chips_html([{"algorithm": "Rusak", "uploaded": True, "version": 1,
                        "state": STATE_BROKEN,
                        "state_reason": "hash tidak cocok"}])
    assert "hash tidak cocok" in html         # sebabnya ikut, sebagai tooltip
    assert "ids-cat-chip-broken" in html


def test_plain_names_still_render(db):
    """Bentuk lama (daftar nama) tetap didukung."""
    from ui.components.pipeline_catalog import chips_html

    assert "Random Forest" in chips_html(["Random Forest"])


# ── Langkah uji coba dengan jenis dataset yang BENAR-BENAR terisi ────────

def _real_trial(db_path, sid, small_csv, source, monkeypatch):
    """Jalankan uji coba SUNGGUHAN lewat run_trial, bukan catatan tempelan."""
    import orchestrator.trial_service as ts

    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    # Hanya PELAKSANANYA yang dipalsukan — pipeline pihak ketiga tidak
    # dijalankan di test. Catatannya tetap DITUTUP seperti aslinya, karena
    # status itulah yang membuka gerbang persetujuan; stub yang lupa menutup
    # catatan akan membuat test ini lulus karena alasan yang salah.
    def fake_execute(**kw):
        trial_db.finish_trial(
            kw["trial_id"], status=trial_db.STATUS_PASSED,
            finished_at="2026-01-01T02:00:00", duration_s=0.1, rows_used=20,
            metrics={"accuracy": 1.0}, db_path=kw.get("db_path"))
        return {"success": True, "trial_id": kw["trial_id"],
                "metrics": {"accuracy": 1.0}, "duration_s": 0.1,
                "rows_used": 20}

    monkeypatch.setattr(ts, "_execute_trial", fake_execute)
    return ts.run_trial(sid, dataset_path=str(small_csv), actor=ADMIN,
                        source=source, db_path=db_path)


def test_the_chain_trial_step_records_a_real_dataset_type(db, package,
                                                          small_csv,
                                                          monkeypatch):
    """Cacat yang membuat test ini ada: jenisnya kosong dan gagal di DB."""
    import orchestrator.trial_service as ts

    sid = _submit(db, package)
    out = _real_trial(db, sid, small_csv, ts.SOURCE_PLATFORM, monkeypatch)

    assert out["success"] is True
    trial = trial_db.latest_trial(sid, db)
    assert trial["dataset_type"], "jenis dataset TIDAK boleh kosong"
    from orchestrator.dataset_diagnostics import supported_datasets

    assert trial["dataset_type"] in set(supported_datasets())


def test_the_chain_trial_step_works_on_the_attached_path(db, package,
                                                         small_csv,
                                                         monkeypatch):
    """Jalur lampiran juga menghasilkan jenis yang terisi."""
    import io

    import orchestrator.trial_service as ts
    from orchestrator import trial_dataset_service as tds

    sid = _submit(db, package)
    info = tds.store_attachment(io.BytesIO(small_csv.read_bytes()),
                                "sample.csv", package_name=f"chain{sid}")
    tds.attach_to_submission(sid, info, db)

    out = _real_trial(db, sid, small_csv, ts.SOURCE_ATTACHED, monkeypatch)
    assert out["success"] is True
    trial = trial_db.latest_trial(sid, db)
    assert trial["dataset_type"] == "HIKARI2021"   # jenis dari pengajuan
    tds.discard_attachment(_submission_row(db, sid), db)


def _submission_row(db_path, sid):
    from orchestrator.submission_service import get_submission

    return get_submission(sid, db_path)


def test_the_trial_step_gates_the_rest_of_the_chain(db, package, small_csv,
                                                    monkeypatch):
    """Rantai tetap utuh: uji sungguhan membuka persetujuan."""
    import orchestrator.trial_service as ts
    from orchestrator.submission_service import get_submission

    sid = _submit(db, package)
    assert not ts.may_approve(get_submission(sid, db), db)

    _real_trial(db, sid, small_csv, ts.SOURCE_PLATFORM, monkeypatch)
    assert ts.may_approve(get_submission(sid, db), db)

    pid = _approve_and_activate(db, sid, monkeypatch)
    assert pid in _catalog_ids(db)[1]


# ── Keterangan pipeline kontribusi: dipotret, bukan dimuat ───────────────
# Katalog tetap TIDAK PERNAH memuat kode pipeline kontribusi: memanggil
# `get_info()` berarti meng-import modulnya, dan katalog dirender setiap kali
# halaman Run Experiment dibuka. Yang berubah adalah dari mana keterangannya
# datang — sebuah POTRET `get_info()` yang diambil sekali saat pendaftaran.
# Yang tersisa kosong hanyalah baris yang terdaftar SEBELUM potret itu ada, dan
# kekosongan itu harus tetap DINYATAKAN, bukan tampil sebagai bidang hampa.

def test_a_contributed_entry_carries_its_own_details(
        db, package, small_csv, monkeypatch):
    """Yang dijanjikan `get_info()` paket ini muncul di katalog — tanpa
    katalog pernah menyentuh kodenya."""
    from ui.components import pipeline_catalog as pc

    sid = _submit(db, package)
    _pass_trial(db, sid, small_csv)
    pid = _approve_and_activate(db, sid, monkeypatch)
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    catalog, _ = _catalog_ids(db)
    entry = next(a for g in catalog for a in g["algorithms"]
                 if a["pipeline_id"] == pid)

    assert entry["summary"], "ringkasan dibiarkan kosong tanpa penjelasan"
    assert entry["details"], "detail dibiarkan kosong tanpa penjelasan"
    assert entry["summary"] != pc.uploaded_notice(),         "keterangan nyata seharusnya menggantikan kalimat kekosongan"
    assert entry["info"], "potret get_info() tidak sampai ke katalog"


def test_a_row_registered_before_the_snapshot_says_so(
        db, package, small_csv, monkeypatch):
    """Baris LAMA tidak punya potret. Alasannya hidup di SATU tempat —
    ringkasan dan detail memakai kalimat yang sama."""
    from database.db import get_connection
    from ui.components import pipeline_catalog as pc

    sid = _submit(db, package)
    _pass_trial(db, sid, small_csv)
    pid = _approve_and_activate(db, sid, monkeypatch)
    # Keadaan sebuah baris pra-migrasi 29, dibuat apa adanya.
    with get_connection(db) as conn:
        conn.execute("UPDATE registered_pipelines SET info_json = NULL "
                     "WHERE pipeline_id = ?", (pid,))
        conn.commit()
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    catalog, _ = _catalog_ids(db)
    entry = next(a for g in catalog for a in g["algorithms"]
                 if a["pipeline_id"] == pid)

    assert entry["summary"] == pc.uploaded_notice()
    assert [value for _label, value in entry["details"]] == [pc.uploaded_notice()]


def test_the_notice_says_how_to_fill_it_in(db):
    """Menyatakan kekosongan tanpa jalan keluar hanya memindahkan kebingungan."""
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        text = lookup("re.cat_uploaded_no_info", lang)
        assert "Research Admin" in text, lang


def test_a_built_in_entry_is_untouched_by_the_notice(db, monkeypatch):
    """Pipeline bawaan tetap membawa keterangan aslinya."""
    from ui.components import pipeline_catalog as pc

    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)
    catalog, _ = _catalog_ids(db)
    entry = next(a for g in catalog for a in g["algorithms"]
                 if a["pipeline_id"] == "hikari2021.lr_pipeline")

    assert entry["summary"] != pc.uploaded_notice()
    assert entry["summary"], "keterangan pipeline bawaan ikut hilang"
    labels = {label for label, _ in entry["details"]}
    assert "Langkah preprocessing" in labels
    assert entry["uploaded"] is False


def test_building_the_catalog_never_loads_contributed_code(
        db, package, small_csv, monkeypatch):
    """PENJAGA UTAMA keputusan ini.

    Katalog dirender pada setiap pembukaan halaman. Bila ia memuat kode
    kontribusi, modul asing dieksekusi setiap kali — persis yang ditolak di
    sini. Jebakan dipasang pada KEDUA pintu pemuatan.
    """
    sid = _submit(db, package)
    _pass_trial(db, sid, small_csv)
    _approve_and_activate(db, sid, monkeypatch)
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    def _boom(*a, **k):
        raise AssertionError("katalog memuat kode pipeline kontribusi")

    monkeypatch.setattr(dr, "load_pipeline_class", _boom)
    monkeypatch.setattr(dr, "get_pipeline_instance_merged", _boom)
    monkeypatch.setattr(dr, "load_registered_instance", _boom)

    catalog, ids = _catalog_ids(db)
    assert any(i.startswith("uploaded.") for i in ids), (
        "penjaga menjadi hampa: tidak ada pipeline kontribusi di katalog")


@pytest.mark.parametrize("key", ["re.cat_uploaded_no_info",
                                 "re.cat_uploaded_no_info_label"])
def test_the_notice_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)
