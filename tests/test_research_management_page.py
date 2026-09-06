"""Halaman kelola research pipeline — seluruhnya, dan benar-benar tersunting.

Halaman ini sebelumnya menjawab pertanyaan yang salah. Tabelnya dibangun dari
`registered_pipelines`, yaitu daftar VERSI ALGORITMA milik unggahan; HIKARI2021
dan EVE_SURICATA tidak pernah muncul di sana, padahal keduanya research
pipeline yang paling banyak dipakai platform ini. Yang tampil hanyalah jejak
alur pengajuan, bukan katalognya.

Empat hal yang dijaga berkas ini:

1. **Sumbernya pembaca GABUNGAN.** Research bawaan hidup di `contracts/` dan
   `config/`, kontribusi di tabel `research_pipelines`, versi algoritma di
   `registered_pipelines`, dan pengajuan di `submissions`. Hanya satu tempat
   yang mengetahui keempatnya.
2. **Bawaan pun dapat disunting** — lewat baris TIMPAAN di basis data, bukan
   dengan menyentuh berkas definisi. Dan suntingan itu selalu dapat dipulihkan.
3. **Cap waktu tidak pernah dikarang.** Research bawaan tidak punya baris basis
   data, jadi ia memang tidak punya tanggal; itu dikatakan, bukan diisi dengan
   tanggal terdekat yang kebetulan ada.
4. **Keadaan selalu lewat i18n.** "Active" tidak pernah menjadi literal.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ui.components import research_manage as rs

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path) -> str:
    from database.db import init_db

    path = str(tmp_path / "kelola.db")
    init_db(path)
    return path


@pytest.fixture
def admin(db) -> dict:
    from orchestrator.auth_service import create_user

    create_user("bos_kelola", "Sandi#12345", role="research_admin",
                db_path=db)
    return {"username": "bos_kelola", "role": "research_admin"}


def _row(**kw):
    dasar = {"dataset_type": "X", "title": "X", "name": "X",
             "origin": rs.ORIGIN_BUILTIN, "active": True, "institution": "",
             "year": "", "source_type": "", "authors": "", "paper_title": "",
             "scope": "", "dataset_name": "", "dataset_attribution": "",
             "dataset_note": "", "file_format": "", "extensions": [],
             "label_column": "", "expected_columns": [], "algorithms": 0,
             "experiments": 0, "created_at": "", "updated_at": "",
             "updated_by": "", "edited": False}
    dasar.update(kw)
    return dasar


# ── 1. Sumbernya: SELURUH research, bukan pengajuan ──────────────────────

def test_the_catalog_shows_the_builtin_research_too(db):
    """Inti keluhannya: HIKARI2021 dan EVE_SURICATA tidak pernah tampil."""
    from orchestrator.research_registry import all_dataset_types

    rows = rs.research_catalog(db)
    tipe = [r["dataset_type"] for r in rows]

    assert "HIKARI2021" in tipe
    assert "EVE_SURICATA" in tipe
    assert tipe == list(all_dataset_types(db))


def test_a_row_is_one_research_not_one_algorithm_version(db):
    """`registered_pipelines` memuat versi algoritma; halaman ini tidak."""
    rows = rs.research_catalog(db)
    hikari = next(r for r in rows if r["dataset_type"] == "HIKARI2021")

    assert len(rows) == len({r["dataset_type"] for r in rows})
    assert hikari["algorithms"] == 6           # enam algoritma, SATU baris


def test_the_catalog_never_reads_the_submission_table():
    """Antrean tinjauan bukan katalog — memakainya sebagai sumber adalah
    justru cacat yang diperbaiki di sini."""
    import ast

    source = Path(rs.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "research_catalog")
    body = ast.get_source_segment(source, fn)

    assert "submissions" not in body
    assert "list_submissions" not in body
    assert "all_dataset_types" in body


def test_an_inactive_contributed_research_is_still_listed(db, admin):
    """Yang dinonaktifkan tidak boleh hilang dari halaman pengelolaan — di
    sanalah satu-satunya tempat ia dapat dihidupkan kembali."""
    from orchestrator.research_registry import register_research

    register_research(dataset_type="uploaded:mati", name="Mati",
                      schema={"label_column": "y"}, registered_by="bos",
                      db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE research_pipelines SET active = 0 "
                     "WHERE dataset_type = ?", ("uploaded:mati",))
        conn.commit()

    rows = rs.research_catalog(db)
    mati = [r for r in rows if r["dataset_type"] == "uploaded:mati"]

    assert mati and mati[0]["active"] is False


# ── 2. Cari, saring, urut ────────────────────────────────────────────────

@pytest.mark.parametrize("query, cocok", [
    ("hikari", "HIKARI2021"),
    ("RAYYAN", "HIKARI2021"),                 # penulis, beda huruf
    ("2024", "HIKARI2021"),                   # tahun
])
def test_the_search_reaches_the_fields_that_matter(db, query, cocok):
    rows = rs.research_catalog(db)
    hasil = [r["dataset_type"] for r in rs.filter_rows(rows, query)]

    assert cocok in hasil


def test_an_empty_query_hides_nothing(db):
    rows = rs.research_catalog(db)
    assert rs.filter_rows(rows, "") == rows
    assert rs.filter_rows(rows, "   ") == rows


def test_the_filters_narrow_by_status_and_origin():
    rows = [_row(dataset_type="A", origin=rs.ORIGIN_BUILTIN, active=True),
            _row(dataset_type="B", origin=rs.ORIGIN_UPLOADED, active=False)]

    assert [r["dataset_type"] for r in
            rs.filter_rows(rows, origin=rs.ORIGIN_UPLOADED)] == ["B"]
    assert [r["dataset_type"] for r in
            rs.filter_rows(rows, status=True)] == ["A"]
    assert rs.filter_rows(rows) == rows        # tanpa penyaring: utuh


def test_sorting_by_name_and_year():
    rows = [_row(dataset_type="B", title="Beta", year="2020"),
            _row(dataset_type="A", title="Alfa", year="2026")]

    assert [r["title"] for r in rs.sort_rows(rows, rs.SORT_NAME)] == \
        ["Alfa", "Beta"]
    assert [r["year"] for r in rs.sort_rows(rows, rs.SORT_YEAR)] == \
        ["2020", "2026"]


def test_rows_without_a_timestamp_sort_last_not_first():
    """Ketiadaan tanggal bukan "paling lama diperbarui"."""
    rows = [_row(dataset_type="kosong"),
            _row(dataset_type="ada", updated_at="2026-09-06T10:00:00")]

    assert [r["dataset_type"] for r in
            rs.sort_rows(rows, rs.SORT_UPDATED)] == ["ada", "kosong"]


# ── 3. Cap waktu: dipakai bila ada, tidak dikarang bila tidak ────────────

def test_a_builtin_research_has_no_timestamp_and_says_so(db):
    rows = rs.research_catalog(db)
    hikari = next(r for r in rows if r["dataset_type"] == "HIKARI2021")

    assert hikari["created_at"] == ""
    assert hikari["updated_at"] == ""
    assert rs.last_touched(hikari) == ""
    assert "git" in rs.detail_line(hikari).lower()


def test_a_contributed_research_shows_the_timestamp_it_really_has(db):
    from orchestrator.research_registry import register_research

    register_research(dataset_type="uploaded:baru", name="Baru",
                      schema={"label_column": "y"}, registered_by="bos",
                      db_path=db)
    baris = next(r for r in rs.research_catalog(db)
                 if r["dataset_type"] == "uploaded:baru")

    assert baris["created_at"]
    assert baris["updated_at"] == ""           # belum pernah disunting
    assert rs.last_touched(baris) == baris["created_at"]


def test_the_stamp_is_readable_and_never_invented():
    assert rs.format_stamp("2026-09-06T21:42:11+00:00") == "6 Sep 2026, 21:42"
    assert rs.format_stamp("") == ""
    assert rs.format_stamp(None) == ""


# ── 4. Keadaan selalu lewat i18n ─────────────────────────────────────────

def test_the_status_word_is_translated_not_hardcoded():
    from ui.i18n.core import lookup

    assert lookup("rs.status_active", "id") == "Aktif"
    assert lookup("rs.status_active", "en") == "Active"
    assert lookup("rs.status_inactive", "id") == "Tidak aktif"
    assert lookup("rs.status_inactive", "en") == "Inactive"


def test_no_english_status_literal_lives_in_the_component():
    source = Path(rs.__file__).read_text(encoding="utf-8")
    kode = "\n".join(baris for baris in source.splitlines()
                     if not baris.strip().startswith("#"))

    assert '"Active"' not in kode and '"Inactive"' not in kode
    assert 'rs.status_active' in kode


@pytest.mark.parametrize("key", [
    "rs.sec_manage", "rs.search", "rs.lbl_status", "rs.lbl_origin",
    "rs.lbl_sort", "rs.status_active", "rs.status_inactive", "rs.count",
    "rs.btn_edit", "rs.btn_save", "rs.btn_cancel", "rs.btn_revert",
    "rs.no_timestamp", "rs.warn_contract", "rs.msg_saved",
    "rs.builtin_always_on", "err.research_not_builtin", "mp.exp_versions",
])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── 5. Menyunting research BAWAAN tanpa menyentuh berkas definisinya ─────

def test_editing_a_builtin_changes_what_readers_see(db, admin):
    from orchestrator.research_registry import attribution_for, update_research

    sebelum = attribution_for("HIKARI2021", db)
    baru = dict(sebelum)
    baru["pipeline_source"] = {**(sebelum.get("pipeline_source") or {}),
                               "institution": "Universitas Hasanuddin"}
    update_research("HIKARI2021", name="HIKARI2021", attribution=baru,
                    actor=admin, db_path=db)

    sesudah = attribution_for("HIKARI2021", db)
    assert sesudah["pipeline_source"]["institution"] == "Universitas Hasanuddin"


def test_fields_left_alone_still_come_from_git(db, admin):
    """Suntingan adalah LAPISAN di atas definisi bawaan, bukan penggantinya."""
    from orchestrator.research_registry import attribution_for, update_research

    asli = attribution_for("HIKARI2021", db)
    judul_asli = asli["pipeline_source"]["title"]
    update_research("HIKARI2021", name="HIKARI2021",
                    attribution={**asli, "pipeline_source": {
                        **asli["pipeline_source"],
                        "institution": "UNHAS"}},
                    actor=admin, db_path=db)

    assert attribution_for("HIKARI2021", db)["pipeline_source"]["title"] == \
        judul_asli


def test_no_definition_file_is_touched(db, admin):
    """`contracts/` dan `config/` adalah area terlarang — dan tidak perlu
    disentuh: suntingannya hidup sebagai baris timpaan."""
    from orchestrator.research_registry import update_research

    berkas = [REPO_ROOT / "contracts" / "dataset_schemas.py",
              REPO_ROOT / "config" / "research_attribution.py"]
    sebelum = [f.read_bytes() for f in berkas]

    update_research("HIKARI2021", name="HIKARI2021",
                    attribution={"scope": "diubah"}, actor=admin, db_path=db)

    assert [f.read_bytes() for f in berkas] == sebelum


def test_the_edit_is_recorded_with_who_and_when(db, admin):
    from orchestrator.research_registry import research_override, update_research

    update_research("HIKARI2021", name="HIKARI2021",
                    attribution={"scope": "x"}, actor=admin, db_path=db)
    row = research_override("HIKARI2021", db)

    assert row["updated_by"] == admin["username"]
    assert row["updated_at"]


def test_editing_the_contract_changes_how_datasets_are_checked(db, admin):
    from orchestrator.research_registry import schema_for, update_research

    assert schema_for("HIKARI2021", db)["label_column"] == "Label"
    update_research("HIKARI2021", name="HIKARI2021",
                    schema={"label_column": "target_baru",
                            "expected_columns": ["a", "b"]},
                    actor=admin, db_path=db)

    assert schema_for("HIKARI2021", db)["label_column"] == "target_baru"


def test_a_smuggled_row_does_not_override_a_builtin(db):
    """Yang membuat bawaan dapat disunting adalah SUNTINGAN yang disengaja —
    bukan keberadaan baris bernama sama.

    Sebuah baris yang disisipkan langsung ke basis data dengan nama bawaan
    tidak melewati `update_research`, jadi ia tidak punya `updated_at`. Tanpa
    pembeda itu, membuka penyuntingan berarti membuka pula jalan menimpa
    definisi bawaan dari luar.
    """
    from orchestrator.research_registry import schema_for

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO research_pipelines (dataset_type, name, schema_json,"
            " registered_by, registered_at, active) VALUES (?,?,?,?,?,1)",
            ("HIKARI2021", "penyusup", json.dumps({"label_column": "x"}),
             "penyusup", "2026-01-01T00:00:00"))
        conn.commit()

    assert schema_for("HIKARI2021", db)["label_column"] == "Label"


def test_a_deliberate_edit_does_override_it(db, admin):
    from orchestrator.research_registry import schema_for, update_research

    update_research("HIKARI2021", name="HIKARI2021",
                    schema={"label_column": "target_baru",
                            "expected_columns": []},
                    actor=admin, db_path=db)

    assert schema_for("HIKARI2021", db)["label_column"] == "target_baru"


def test_reverting_restores_the_git_definition(db, admin):
    from orchestrator.research_registry import (
        attribution_for, revert_research, schema_for, update_research,
    )

    asli_label = schema_for("HIKARI2021", db)["label_column"]
    asli_inst = attribution_for("HIKARI2021", db)["pipeline_source"]["institution"]
    update_research("HIKARI2021", name="HIKARI2021",
                    attribution={"pipeline_source": {"institution": "Lain"}},
                    schema={"label_column": "z", "expected_columns": []},
                    actor=admin, db_path=db)

    assert revert_research("HIKARI2021", actor=admin, db_path=db) is True
    assert schema_for("HIKARI2021", db)["label_column"] == asli_label
    assert attribution_for("HIKARI2021", db)["pipeline_source"]["institution"] \
        == asli_inst


def test_a_contributed_research_cannot_be_reverted(db, admin):
    """Barisnya bukan lapisan di atas apa pun — ia satu-satunya tempat
    identitasnya hidup, jadi membuangnya berarti kehilangan."""
    from orchestrator.research_registry import (
        ResearchRegistryError, register_research, revert_research,
    )

    register_research(dataset_type="uploaded:punyaku", name="Punyaku",
                      schema={"label_column": "y"}, registered_by="bos",
                      db_path=db)

    with pytest.raises(ResearchRegistryError) as excinfo:
        revert_research("uploaded:punyaku", actor=admin, db_path=db)
    assert excinfo.value.key == "err.research_not_builtin"


def test_editing_needs_the_research_admin_role(db):
    from orchestrator.research_registry import update_research

    for peran in ("visitor", "contributor"):
        with pytest.raises(Exception):
            update_research("HIKARI2021", name="X", attribution={},
                            actor={"username": "x", "role": peran}, db_path=db)


def test_the_dataset_type_is_never_offered_for_editing():
    """Ia identitas research ini, dan baris `experiments` menunjuk padanya."""
    source = Path(rs.__file__).read_text(encoding="utf-8")
    form = source.split("def _render_edit_form(")[1].split("\ndef ")[0]

    assert "rs_f_dataset_type" not in form
    assert "dataset_type=" not in form


def test_an_unknown_research_is_refused(db, admin):
    from orchestrator.research_registry import (
        ResearchRegistryError, update_research,
    )

    with pytest.raises(ResearchRegistryError) as excinfo:
        update_research("TIDAK_ADA", name="x", attribution={}, actor=admin,
                        db_path=db)
    assert excinfo.value.key == "err.research_not_found"


# ── 6. Migrasi ada di KEDUA jalur pembuatan ──────────────────────────────

def test_the_columns_exist_on_a_freshly_created_database(db):
    with sqlite3.connect(db) as conn:
        kolom = {r[1] for r in conn.execute(
            "PRAGMA table_info(research_pipelines)")}

    assert {"updated_at", "updated_by"} <= kolom


def test_the_columns_arrive_by_migration_too(tmp_path):
    from database.migration import apply_migrations
    from database.models import CREATE_RESEARCH_PIPELINES_TABLE

    path = str(tmp_path / "lama.db")
    lama = CREATE_RESEARCH_PIPELINES_TABLE
    for baris in ("    updated_at     TEXT,\n", "    updated_by     TEXT\n"):
        lama = lama.replace(baris, "")
    lama = lama.replace("dataset_json   TEXT,", "dataset_json   TEXT")
    assert "updated_at" not in lama
    with sqlite3.connect(path) as conn:
        conn.execute(lama)
        conn.commit()
    apply_migrations(path)

    with sqlite3.connect(path) as conn:
        kolom = {r[1] for r in conn.execute(
            "PRAGMA table_info(research_pipelines)")}
    assert {"updated_at", "updated_by"} <= kolom


def test_an_old_row_without_the_columns_still_reads(db, admin):
    """Baris yang lahir sebelum kolomnya ada tidak punya waktu suntingan —
    keadaan yang sah, bukan galat."""
    from orchestrator.research_registry import register_research

    register_research(dataset_type="uploaded:lawas", name="Lawas",
                      schema={"label_column": "y"}, registered_by="bos",
                      db_path=db)
    baris = next(r for r in rs.research_catalog(db)
                 if r["dataset_type"] == "uploaded:lawas")

    assert baris["updated_at"] == ""
    assert rs.detail_line(baris)               # tetap dapat digambar
