"""Identitas research pipeline yang dinamis (Tahap 1).

Sampai tahap ini, sebuah unggahan tidak pernah bisa berdiri sendiri: ia harus
MENUMPANG salah satu ``dataset_type`` bawaan, karena hanya
``contracts/dataset_schemas.py`` dan ``config/research_attribution.py`` yang
mendefinisikan apa itu "research pipeline" — dan keduanya statis. Itulah sebab
kartu peninjauan sempat harus bertanya "ini ikut research pipeline mana".

Yang dijaga di sini bukan fiturnya, melainkan tiga sifat yang membuat
penambahan ini aman:

* **statis selalu menang** — unggahan tidak dapat menimpa research bawaan;
* **kegagalan membaca tidak merusak yang bawaan** — sepuluh pipeline bawaan
  tetap utuh walau tabel unggahan hilang;
* **data lama tidak berubah arti** — baris yang sudah ada tetap menumpang
  keluarga bawaan, persis seperti sebelumnya, tanpa diisi mundur.
"""
from __future__ import annotations

import sqlite3

import pytest

from contracts.dataset_schemas import DATASET_SCHEMAS
from database.migration import apply_migrations
from database.models import (
    RESEARCH_PREFIX, build_research_dataset_type, is_uploaded_research,
)
from orchestrator import research_registry as rr

DECLARED = {
    "label_column": "attack",
    "expected_columns": ["flow_duration", "src_port", "attack"],
    "file_format": "csv",
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "rr.db"
    apply_migrations(str(path))
    monkeypatch.setattr("database.db.DB_PATH", str(path), raising=False)
    return str(path)


def _register(db_path, name="Jaringan Kampus"):
    dtype = build_research_dataset_type(name)
    rr.register_research(dataset_type=dtype, name=name, schema=DECLARED,
                         registered_by="boss", db_path=db_path)
    return dtype


# ── Pengenal ─────────────────────────────────────────────────────────────

def test_the_identifier_is_namespaced():
    dtype = build_research_dataset_type("Jaringan Kampus")
    assert dtype.startswith(RESEARCH_PREFIX)
    assert is_uploaded_research(dtype)
    assert not is_uploaded_research("HIKARI2021")


def test_the_identifier_cannot_collide_with_a_built_in():
    """Bukan "tidak sengaja bertabrakan" — tidak DAPAT bertabrakan."""
    for built_in in DATASET_SCHEMAS:
        assert build_research_dataset_type(built_in) not in DATASET_SCHEMAS


def test_an_unsafe_name_is_sanitised():
    dtype = build_research_dataset_type("../../etc/passwd")
    assert "/" not in dtype and ".." not in dtype


def test_an_empty_name_yields_no_identifier():
    assert build_research_dataset_type("   ") == ""


# ── Statis SELALU menang ─────────────────────────────────────────────────

def test_a_built_in_schema_is_never_replaced(db):
    """Bahkan bila sebuah baris unggahan entah bagaimana memakai nama bawaan."""
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO research_pipelines (dataset_type, name, schema_json,"
            " registered_by, registered_at, active) VALUES (?,?,?,?,?,1)",
            ("HIKARI2021", "penyusup", '{"label_column": "x"}', "boss", "now"))
        conn.commit()

    schema = rr.schema_for("HIKARI2021", db)
    assert schema["label_column"] == "Label"        # milik yang bawaan
    assert schema is DATASET_SCHEMAS["HIKARI2021"] or schema == DATASET_SCHEMAS["HIKARI2021"]


def test_registering_a_built_in_name_is_refused(db):
    with pytest.raises(ValueError):
        rr.register_research(dataset_type="HIKARI2021", name="x",
                             schema=DECLARED, registered_by="boss",
                             db_path=db)


def test_an_unnamespaced_identifier_is_refused(db):
    with pytest.raises(ValueError):
        rr.register_research(dataset_type="kampus", name="x", schema=DECLARED,
                             registered_by="boss", db_path=db)


# ── Skema DIDEKLARASIKAN, tidak ditebak ──────────────────────────────────

def test_the_declared_schema_is_returned_as_given(db):
    dtype = _register(db)
    schema = rr.schema_for(dtype, db)
    assert schema["label_column"] == "attack"
    assert schema["expected_columns"] == DECLARED["expected_columns"]
    assert schema["file_format"] == "csv"


def test_an_unknown_type_still_returns_none(db):
    """Perilaku yang SAMA dengan `get_schema`, supaya pemanggil lama yang
    sudah menangani None tidak berubah sama sekali."""
    assert rr.schema_for("NGACO", db) is None


def test_a_deactivated_research_stops_resolving(db):
    dtype = _register(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE research_pipelines SET active = 0 WHERE dataset_type = ?",
                     (dtype,))
        conn.commit()
    assert rr.schema_for(dtype, db) is None
    assert dtype not in rr.all_dataset_types(db)


def test_the_type_list_puts_built_ins_first(db):
    dtype = _register(db)
    types = rr.all_dataset_types(db)
    assert types[:len(DATASET_SCHEMAS)] == list(DATASET_SCHEMAS)
    assert dtype in types


# ── Kegagalan membaca tidak merusak yang bawaan ──────────────────────────

def test_a_missing_table_leaves_the_built_ins_intact(tmp_path, monkeypatch):
    """Basis data tanpa tabel research sama sekali."""
    bare = tmp_path / "bare.db"
    sqlite3.connect(str(bare)).close()

    assert rr.list_research(db_path=str(bare)) == []
    assert rr.all_dataset_types(str(bare)) == list(DATASET_SCHEMAS)
    assert rr.schema_for("HIKARI2021", str(bare)) is not None


def test_a_corrupt_schema_row_does_not_crash(db):
    dtype = build_research_dataset_type("rusak")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO research_pipelines (dataset_type, name, schema_json,"
            " registered_by, registered_at, active) VALUES (?,?,?,?,?,1)",
            (dtype, "rusak", "{bukan json", "boss", "now"))
        conn.commit()
    assert rr.schema_for(dtype, db) is None       # ditolak, bukan meledak


# ── Atribusi ─────────────────────────────────────────────────────────────

def test_a_built_in_attribution_is_never_replaced(db):
    entry = rr.attribution_for("HIKARI2021", db)
    assert "Rayyan" in entry.get("display_name", "")


def test_an_uploaded_research_always_has_a_display_name(db):
    """Pembaca berhak tahu ini research kontribusi, bukan pengenal mentah."""
    dtype = _register(db)
    name = rr.display_name_for(dtype, db)
    assert name != dtype
    assert "kontribusi" in name.lower()


def test_an_unknown_type_falls_back_to_its_own_identifier(db):
    assert rr.display_name_for("NGACO", db) == "NGACO"


# ── Data lama tidak berubah arti ─────────────────────────────────────────

def test_an_existing_uploaded_pipeline_keeps_its_built_in_dataset_type(db):
    """Baris `registered_pipelines` lama menumpang keluarga bawaan.

    Itu semantik LAMA, dan tahap ini tidak mengubahnya maupun mengisinya
    mundur: pipeline itu tetap HIKARI2021 dan tetap memakai skema bawaan.
    """
    from orchestrator import dynamic_registry as dr

    entry = tmp = None
    src = "from pipelines.base import BasePipeline\n"
    path = __import__("pathlib").Path(db).parent / "old.py"
    path.write_text(src, encoding="utf-8")
    dr.register_pipeline(name="lama", dataset_type="HIKARI2021",
                         entry_class="X", entry_file=str(path),
                         registered_by="boss", db_path=db)

    rows = dr.list_registered(db_path=db)
    assert rows and rows[0]["dataset_type"] == "HIKARI2021"
    # …dan skemanya tetap yang bawaan, bukan sesuatu yang baru.
    assert rr.schema_for(rows[0]["dataset_type"], db) == DATASET_SCHEMAS["HIKARI2021"]
    assert entry is tmp is None      # tidak ada identitas research yang dibuat


def test_no_research_row_is_created_for_legacy_uploads(db):
    from orchestrator import dynamic_registry as dr

    path = __import__("pathlib").Path(db).parent / "old2.py"
    path.write_text("x = 1\n", encoding="utf-8")
    dr.register_pipeline(name="lama2", dataset_type="EVE_SURICATA",
                         entry_class="X", entry_file=str(path),
                         registered_by="boss", db_path=db)
    assert rr.list_research(db_path=db) == []


# ── Diagnosa memakai sumber yang DISUNTIKKAN, bukan impor ────────────────
# `dataset_diagnostics` melarang impor `database/` di docstring-nya, sementara
# skema research terunggah hanya ada di sana. Injeksi adalah satu-satunya jalan
# yang tidak membalik arah impor lapisan.

def test_diagnostics_never_imports_the_database_layer():
    """Batasan impornya harus tetap benar setelah perubahan ini."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "orchestrator"
           / "dataset_diagnostics.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("database"), node.module
            assert not node.module.startswith("ui"), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("database"), alias.name


def test_diagnostics_falls_back_to_the_static_source(db):
    """Tanpa pemasangan, perilakunya persis seperti sebelumnya."""
    from orchestrator import dataset_diagnostics as dd

    dd.use_schema_source(None, None)
    try:
        assert dd._schema("HIKARI2021") is not None
        assert dd._schema("NGACO") is None
        assert dd._known_types() == list(DATASET_SCHEMAS)
    finally:
        dd.use_schema_source(None, None)


def test_an_injected_source_reaches_the_diagnostics(db):
    from orchestrator import dataset_diagnostics as dd

    dtype = _register(db)
    dd.use_schema_source(lambda dt: rr.schema_for(dt, db),
                         lambda: rr.all_dataset_types(db))
    try:
        assert dd._schema(dtype)["label_column"] == "attack"
        assert dtype in dd._known_types()
    finally:
        dd.use_schema_source(None, None)


def test_a_broken_injected_source_falls_back_instead_of_crashing(db):
    """Sumber yang meledak tidak boleh menjatuhkan diagnosa."""
    from orchestrator import dataset_diagnostics as dd

    def _boom(*a, **k):
        raise RuntimeError("sumber rusak")

    dd.use_schema_source(_boom, _boom)
    try:
        assert dd._schema("HIKARI2021") is not None     # jatuh ke statis
        assert dd._known_types() == list(DATASET_SCHEMAS)
    finally:
        dd.use_schema_source(None, None)


def test_the_composition_root_wires_the_source():
    """Pemasangannya hidup di titik komposisi, bukan di dalam modulnya."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "app.py").read_text(
        encoding="utf-8")
    assert "use_schema_source(schema_for, all_dataset_types)" in src


# ── Formulir mendeklarasikan kontrak datasetnya ──────────────────────────

def test_the_form_always_declares_a_dataset_contract():
    """Deklarasi SELALU diminta — tidak ada lagi jenis bawaan untuk ditumpangi.

    Setiap unggahan adalah research pipeline yang berdiri sendiri, jadi
    platform tidak pernah punya skema siap pakai untuk paket itu dan tidak
    boleh mengarang satu dari nama berkas maupun isinya.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    flow = src.split("def _render_pipeline_flow(")[1].split("\ndef ")[0]

    assert "declared_schema" in flow
    # Pertanyaan "ikut research pipeline mana" sudah TIDAK ADA di mana pun.
    assert "dtype_choice" not in flow
    assert "_OTHER_DATASET_OPTION" not in src
    assert "ap.lbl_research_pipeline" not in src
    for key in ("ap.lbl_label_column", "ap.lbl_required_columns",
                "ap.lbl_file_format"):
        assert key in flow, key


def test_the_form_refuses_to_validate_without_a_name_or_a_contract():
    """Tanpa keduanya pengajuannya tidak akan pernah dapat disetujui — dan itu
    harus ketahuan di formulir, bukan di meja peninjau."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    flow = src.split("def _render_pipeline_flow(")[1].split("\ndef ")[0]

    gate = flow.split("blocked = ")[1].split("if st.button(")[0]
    assert "missing" in gate
    button = flow.split('key="contrib_validate"')[1][:300]
    assert "disabled=not may_upload or bool(blocked)" in button
    assert "help=blocked or None" in button      # alasannya menempel di tombol


def test_the_declared_contract_travels_with_the_submission():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    flow = src.split("def _render_pipeline_flow(")[1].split("\ndef ")[0]
    # Masuk ke `form`, yang menjadi metadata pengajuan.
    assert '"declared_schema": declared_schema' in flow


def test_an_incomplete_contract_is_stated_not_silently_accepted():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    assert "ap.err_schema_incomplete" in src


@pytest.mark.parametrize("key", [
    "ap.sec_declare_schema", "ap.help_declare_schema", "ap.lbl_label_column",
    "ap.lbl_file_format", "ap.lbl_required_columns",
    "ap.help_required_columns", "ap.err_schema_incomplete",
])
def test_the_declaration_texts_exist_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


def test_the_declared_shape_matches_what_the_platform_reads():
    """Bentuk deklarasi harus menghasilkan bidang yang BENAR-BENAR dibaca.

    Kalau formulir menghasilkan bidang lain, skemanya tersimpan tapi tidak
    pernah dipakai — gagal yang senyap.
    """
    declared = {"label_column": "attack", "expected_columns": ["a", "b"],
                "file_format": "csv"}
    assert set(declared) <= set(rr.SCHEMA_FIELDS)


# ── Tahap 3: dataset MENYATU dan TERIKAT ─────────────────────────────────
# Sebelumnya lampiran dataset bersifat SEMENTARA — hanya hidup selama
# peninjauan lalu dibuang. Research pipeline yang berdiri sendiri membutuhkan
# datasetnya secara permanen; tanpa itu algoritmanya terdaftar tetapi tidak
# pernah dapat dijalankan.

def test_a_research_without_a_dataset_reports_nothing(db):
    dtype = _register(db)
    assert rr.dataset_for(dtype, db) == {}
    assert rr.dataset_files_for(dtype, db) == []


def test_a_bound_dataset_is_returned(db, tmp_path):
    dtype = _register(db)
    path = tmp_path / "kampus.csv"
    path.write_text("attack\n1\n", encoding="utf-8")

    rr.bind_dataset(dtype, {"filename": "kampus.csv",
                            "stored_path": str(path)}, db)
    assert rr.dataset_for(dtype, db)["filename"] == "kampus.csv"
    assert rr.dataset_files_for(dtype, db) == [str(path)]


def test_a_missing_bound_file_offers_nothing(db, tmp_path):
    """Pilihan yang PASTI gagal saat dijalankan tidak boleh ditawarkan."""
    dtype = _register(db)
    rr.bind_dataset(dtype, {"filename": "hilang.csv",
                            "stored_path": str(tmp_path / "hilang.csv")}, db)
    assert rr.dataset_for(dtype, db)["filename"] == "hilang.csv"   # tercatat
    assert rr.dataset_files_for(dtype, db) == []                   # tidak ditawarkan


def test_a_built_in_research_never_binds_a_dataset(db):
    """Keluarga bawaan memakai `storage/datasets/`; jalurnya tidak berubah."""
    with pytest.raises(ValueError):
        rr.bind_dataset("HIKARI2021", {"filename": "x.csv"}, db)
    assert rr.dataset_files_for("HIKARI2021", db) == []


def test_the_bound_dataset_is_not_offered_to_other_research(db, tmp_path):
    """Inilah inti "terikat": dataset kontribusi tidak bocor ke pipeline lain."""
    dtype = _register(db)
    path = tmp_path / "kampus.csv"
    path.write_text("attack\n1\n", encoding="utf-8")
    rr.bind_dataset(dtype, {"filename": "kampus.csv",
                            "stored_path": str(path)}, db)

    other = build_research_dataset_type("lain")
    rr.register_research(dataset_type=other, name="Lain", schema=DECLARED,
                         registered_by="boss", db_path=db)
    assert rr.dataset_files_for(other, db) == []
    assert rr.dataset_files_for("HIKARI2021", db) == []


def test_the_run_page_asks_the_registry_for_uploaded_research():
    """Titik integrasinya: daftar dataset menghormati ikatan itu."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "ui" / "views"
           / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("def _list_dataset_files(")[1].split("\ndef ")[0]
    assert "is_uploaded_research" in body
    assert "dataset_files_for" in body
    # …dan jalur bawaan tetap membaca folder platform.
    assert "DATASETS_DIR" in body


# ── Penyambungan ke alur persetujuan ─────────────────────────────────────
# Mesin identitas research sudah ada sejak Tahap 1, tetapi `register_research`
# dan `bind_dataset` NOL PEMANGGIL — sehingga setiap unggahan masih menumpang
# keluarga bawaan. Bagian ini yang menyambungkannya.

STANDALONE_META = {
    "name": "Jaringan Kampus",
    "entry_filename": "p.py",
    "entry_class": "DemoPipeline",
    "declared_schema": DECLARED,
}


def test_a_submission_that_declares_its_contract_stands_alone():
    from database.models import KIND_PIPELINE
    from orchestrator.submission_service import is_standalone

    assert is_standalone({"kind": KIND_PIPELINE, "metadata": STANDALONE_META})


def test_a_legacy_submission_still_hitchhikes():
    """Pengajuan lama tidak punya deklarasi — perilakunya tidak berubah."""
    from database.models import KIND_PIPELINE
    from orchestrator.submission_service import is_standalone

    assert not is_standalone({"kind": KIND_PIPELINE,
                              "metadata": {"dataset_type": "HIKARI2021"}})


def test_a_half_declared_contract_is_not_a_declaration():
    """Skema tanpa kolom label ATAU tanpa kolom wajib tidak dapat memeriksa
    apa pun, jadi ia bukan deklarasi."""
    from database.models import KIND_PIPELINE
    from orchestrator.submission_service import is_standalone

    for partial in ({"label_column": "a"}, {"expected_columns": ["a"]}, {}):
        assert not is_standalone({"kind": KIND_PIPELINE,
                                  "metadata": {"declared_schema": partial}})


def test_the_identifier_is_planned_before_anything_moves():
    """Nama yang tidak sah ditolak SEBELUM satu berkas pun bergerak."""
    from orchestrator.submission_service import (
        SubmissionError, _plan_research_identity,
    )

    with pytest.raises(SubmissionError):
        _plan_research_identity({"original_filename": "",
                                 "metadata": {"name": "   ",
                                              "declared_schema": DECLARED}})


def test_the_planned_identifier_is_namespaced():
    from orchestrator.submission_service import _plan_research_identity

    dtype, name, schema = _plan_research_identity(
        {"original_filename": "p.py", "metadata": STANDALONE_META})
    assert dtype.startswith(RESEARCH_PREFIX)
    assert name == "Jaringan Kampus"
    assert schema == DECLARED


def test_the_approval_flow_creates_the_identity_before_registering(db):
    """Algoritmanya harus terdaftar di bawah `dataset_type` BARUNYA."""
    from pathlib import Path as _P

    from orchestrator.submission_service import _create_research_identity

    item = {"id": 7, "original_filename": "p.py", "metadata": STANDALONE_META}
    dtype = _create_research_identity(item, {"username": "boss"}, db)

    assert dtype.startswith(RESEARCH_PREFIX)
    row = rr.get_research(dtype, db)
    assert row["submission_id"] == 7
    assert rr.schema_for(dtype, db)["label_column"] == "attack"
    # Atribusinya menyebut bahwa ini kontribusi.
    assert "kontribusi" in rr.display_name_for(dtype, db).lower()


def test_a_failed_approval_leaves_no_research_identity(db):
    from orchestrator.submission_service import (
        _create_research_identity, _undo_research_identity,
    )

    item = {"id": 8, "original_filename": "p.py", "metadata": STANDALONE_META}
    dtype = _create_research_identity(item, {"username": "boss"}, db)
    assert rr.get_research(dtype, db) is not None

    _undo_research_identity(dtype, db)
    assert rr.get_research(dtype, db) is None
    assert dtype not in rr.all_dataset_types(db)


def test_the_rollback_restores_the_original_review_trail():
    """Pengajuan yang persetujuannya GAGAL tidak boleh terlihat sudah ditinjau."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "orchestrator"
           / "submission_service.py").read_text(encoding="utf-8")
    body = src.split("def _restore_submission_row(")[1].split("\ndef ")[0]
    for field in ("reviewed_by", "reviewed_at", "status", "stored_path"):
        assert field in body, field
    # …dan rollback-nya BENAR-BENAR dipanggil dari jalur persetujuan.
    approve = src.split("def approve_submission(")[1].split("\ndef ")[0]
    assert "_restore_submission_row(item, db_path)" in approve
    assert "_undo_registered_pipelines(" in approve
    assert "_undo_research_identity(" in approve


def test_a_bound_dataset_survives_the_trial_cleanup():
    """Pembersihan hasil uji tidak boleh menghapus dataset yang sudah terikat."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "orchestrator"
           / "trial_service.py").read_text(encoding="utf-8")
    body = src.split("def discard_trials(")[1].split("\ndef ")[0]
    assert "_dataset_is_bound(" in body
    # Tidak tahu = JANGAN dibuang.
    guard = src.split("def _dataset_is_bound(")[1].split("\ndef ")[0]
    assert "return True" in guard


def test_the_review_card_drops_the_question_for_standalone_submissions():
    """Pertanyaan "ini ikut research pipeline mana" hanya bermakna bagi yang
    MENUMPANG. Bagi yang berdiri sendiri, tidak ada pilihan untuk dipilih."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    card = src.split("def _render_submission_review_card(")[1].split("\ndef ")[0]

    assert "if is_standalone(item):" in card
    # Yang berdiri sendiri: identitasnya DITAMPILKAN, bukan ditanyakan.
    assert "ap.lbl_research_identity" in card
    assert "build_research_dataset_type(" in card
    # "Dataset target" sudah TIDAK ADA — bagi siapa pun, termasuk yang lama.
    assert "ap.lbl_target_dataset" not in card
    assert "st.selectbox(" not in card
    # Yang lama pun identitasnya ditampilkan apa adanya, bukan ditanyakan.
    assert "ap.lbl_research_identifier" in card


def test_approval_no_longer_carries_a_reviewer_chosen_type():
    """Peninjau tidak lagi menyodorkan `dataset_type`: layanannya membacanya
    dari metadata pengajuan, dan tidak ada nilai pilihan yang menimpanya."""
    from pathlib import Path as _P

    src = (_P(__file__).resolve().parents[1] / "ui" / "views"
           / "contribute.py").read_text(encoding="utf-8")
    card = src.split("def _render_submission_review_card(")[1].split("\ndef ")[0]
    assert "chosen_type" not in card
    assert "approve_submission(item[\"id\"], actor=user, note=note)" in card


@pytest.mark.parametrize("key", ["ap.lbl_research_identity",
                                 "ap.lbl_research_identifier",
                                 "ap.help_research_identity"])
def test_the_identity_texts_exist_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)
