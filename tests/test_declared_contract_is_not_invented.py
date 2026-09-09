"""Kontrak research kontribusi: yang ditampilkan hanya yang DINYATAKAN.

Research bawaan punya entri persyaratan yang ditulis platform
(``_DATASET_REQUIREMENTS``). Research kontribusi tidak — yang ia punya hanyalah
kontrak yang dideklarasikan pengunggahnya di formulir pengajuan: format berkas,
nama kolom label, kolom wajib, dan (untuk NDJSON) kunci JSON tingkat atas.

Sebelum berkas ini ada, dua penyaji membaca skema STATIS yang tidak mengenal
jenis kontribusi sama sekali, lalu mengisi kekosongannya dengan karangan:

* panel "Persyaratan Dataset" menyebut kolom label ``label`` — nilai bawaan
  sebuah ``.get()`` — padahal keterangan dataset TIGA BARIS di atasnya, pada
  panel yang sama, menyebut ``serangan``. Dua kalimat yang bertentangan dalam
  satu tampilan;
* checklist "Dataset Anda cocok jika…" menyatakan tiga hal yang tidak pernah
  dideklarasikan siapa pun: "satu baris per flow", kolom label bernama "`?`"
  berisi "`0`/`1`", dan "dua kelas: benign dan malicious".
"""
from __future__ import annotations

import pytest

from ui.views.run_experiment import declared_checklist, declared_requirement_rows

KONTRAK = {"label_column": "serangan", "file_format": "csv",
           "expected_columns": ["durasi", "byte_masuk", "serangan"]}
NDJSON = {"label_column": "target", "file_format": "ndjson",
          "expected_columns": ["a", "b"],
          "expected_top_level_keys": ["timestamp", "event_type"]}


# ── Yang dinyatakan, ditampilkan ─────────────────────────────────────────

def test_the_declared_label_column_is_the_one_shown():
    aspek = dict(declared_requirement_rows(KONTRAK, "`.csv`", "serangan"))

    assert any("serangan" in nilai for nilai in aspek.values())
    assert not any("`label`" in nilai for nilai in aspek.values())


def test_the_required_columns_are_named_not_counted():
    """Justru di sinilah orang mencocokkan berkasnya sendiri; "5 kolom" tidak
    dapat dicocokkan dengan apa pun."""
    nilai = " ".join(dict(declared_requirement_rows(
        KONTRAK, "`.csv`", "serangan")).values())

    for kolom in KONTRAK["expected_columns"]:
        assert f"`{kolom}`" in nilai, kolom


def test_the_top_level_json_keys_finally_appear():
    """Dideklarasikan di formulir unggah sejak awal, tidak pernah ditampilkan."""
    nilai = " ".join(dict(declared_requirement_rows(
        NDJSON, "`.ndjson`", "target")).values())

    assert "`timestamp`" in nilai and "`event_type`" in nilai


def test_top_level_keys_are_not_repeated_when_identical_to_columns():
    schema = {"expected_columns": ["a"], "expected_top_level_keys": ["a"]}
    baris = declared_requirement_rows(schema, "`.ndjson`", "y")

    assert len(baris) == len({aspek for aspek, _ in baris})
    assert sum(1 for _aspek, nilai in baris if "`a`" in nilai) == 1


def test_a_contract_without_a_label_column_says_nothing_about_one():
    aspek = dict(declared_requirement_rows({"expected_columns": ["a"]},
                                           "`.csv`", ""))

    assert not any("label" in a.lower() for a in aspek)


# ── Yang TIDAK dinyatakan, tidak ditampilkan ─────────────────────────────

@pytest.mark.parametrize("karangan", [
    "flow",          # satuan baris tidak pernah dinyatakan
    "0`/`1",         # arti nilai label tidak pernah dinyatakan
    "dua kelas",     # jumlah kelas tidak pernah dinyatakan
    "numerik",       # sifat fitur tidak pernah dinyatakan
    "?",             # kolom label yang tidak diketahui
])
def test_the_checklist_invents_nothing(karangan):
    teks = " ".join(declared_checklist(KONTRAK, "`.csv`", "serangan"))

    assert karangan not in teks, karangan


def test_the_checklist_states_what_was_declared():
    teks = " ".join(declared_checklist(KONTRAK, "`.csv`", "serangan"))

    assert "`.csv`" in teks
    assert "`serangan`" in teks
    assert "3" in teks                      # tiga kolom wajib


# ── Kedua penyaji sepakat, dan bawaan tidak berubah ──────────────────────

def test_both_surfaces_now_name_the_same_label_column():
    """Inti cacatnya: satu panel, dua jawaban."""
    from ui.components.instructions import dataset_contract_rows
    from ui.views.run_experiment import _dataset_extensions, _schema_of

    dtype = "uploaded:deteksi_trafik_kampus"
    schema = _schema_of(dtype)
    if not schema:
        pytest.skip("research kontribusi tidak ada pada basis data uji")

    kolom = schema.get("label_column")
    panel = " ".join(dict(declared_requirement_rows(
        schema, " / ".join(f"`{e}`" for e in _dataset_extensions(dtype)),
        kolom)).values())
    halaman = " ".join(nilai for _a, nilai in dataset_contract_rows(dtype))

    assert f"`{kolom}`" in panel
    assert f"`{kolom}`" in halaman


def test_the_checklist_of_a_contributed_type_uses_the_declared_branch():
    from ui.components.instructions import dataset_checklist
    from ui.views.run_experiment import _schema_of

    dtype = "uploaded:deteksi_trafik_kampus"
    schema = _schema_of(dtype)
    if not schema:
        pytest.skip("research kontribusi tidak ada pada basis data uji")

    butir = dataset_checklist(dtype)

    assert butir == declared_checklist(
        schema, "`.csv`", schema.get("label_column") or "")


def test_the_sample_shows_the_declared_column_names():
    from ui.components.instructions import dataset_sample_snippet
    from ui.views.run_experiment import _schema_of

    dtype = "uploaded:deteksi_trafik_kampus"
    schema = _schema_of(dtype)
    if not schema:
        pytest.skip("research kontribusi tidak ada pada basis data uji")

    contoh = dataset_sample_snippet(dtype)

    assert contoh == ",".join(schema.get("expected_columns") or [])
    assert chr(10) not in contoh            # header saja, tanpa baris nilai


@pytest.mark.parametrize("dtype", ["HIKARI2021", "EVE_SURICATA"])
def test_the_builtin_types_are_untouched(dtype):
    """Perbaikan ini hanya menyentuh cabang yang dahulu mengarang."""
    from ui.components.instructions import dataset_checklist
    from ui.views.run_experiment import _DATASET_REQUIREMENTS

    assert dtype in _DATASET_REQUIREMENTS
    butir = dataset_checklist(dtype)

    assert len(butir) == 4
    assert any("kelas" in b.lower() or "class" in b.lower() or
               "alert" in b.lower() for b in butir)


@pytest.mark.parametrize("key", [
    "re.req_row_columns", "re.req_row_top_keys", "re.req_declared_note",
    "re.req_sample_declared_note", "re.dschk_declared_format",
    "re.dschk_declared_label", "re.dschk_declared_columns",
])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── Empat keterangan yang kini DAPAT dinyatakan pengunggah ───────────────
#
# Sebelumnya formulir unggah tidak pernah menanyakan keempatnya, sehingga
# panel persyaratan sebuah research kontribusi hanya dapat menyebut format
# dan nama kolom — dan penyaji lamanya menambal kekosongan itu dengan kalimat
# milik HIKARI2021.

FAKTA = {"row_unit": "satu baris per sesi trafik",
         "label_meaning": "0 = normal, 1 = serangan",
         "feature_nature": "kolom numerik hasil agregasi per sesi",
         "class_count": 2}


def test_the_row_unit_joins_the_file_format():
    baris = dict(declared_requirement_rows(KONTRAK, "`.csv`", "serangan", FAKTA))
    format_row = next(v for k, v in baris.items() if "ormat" in k)

    assert "satu baris per sesi trafik" in format_row


def test_the_label_meaning_replaces_the_generic_sentence():
    baris = dict(declared_requirement_rows(KONTRAK, "`.csv`", "serangan", FAKTA))
    label_row = next(v for k, v in baris.items() if "abel" in k)

    assert "0 = normal, 1 = serangan" in label_row
    assert "sesuai kontrak" not in label_row


@pytest.mark.parametrize("kunci, dicari", [
    ("feature_nature", "agregasi per sesi"),
    ("class_count", "2 kelas"),
])
def test_the_new_rows_appear_only_when_declared(kunci, dicari):
    dengan = " ".join(n for _a, n in declared_requirement_rows(
        KONTRAK, "`.csv`", "serangan", FAKTA))
    tanpa = " ".join(n for _a, n in declared_requirement_rows(
        KONTRAK, "`.csv`", "serangan", {k: v for k, v in FAKTA.items()
                                        if k != kunci}))

    assert dicari in dengan
    assert dicari not in tanpa


def test_nothing_declared_means_nothing_added():
    """Kosong tidak pernah menjadi baris bertanda "—"."""
    baris = declared_requirement_rows(KONTRAK, "`.csv`", "serangan", {})
    aspek = [a for a, _n in baris]

    assert not any("itur" in a or "kelas" in a.lower() for a in aspek)
    assert len(baris) == len(declared_requirement_rows(
        KONTRAK, "`.csv`", "serangan"))


def test_the_checklist_gains_the_class_count_when_declared():
    dengan = " ".join(declared_checklist(KONTRAK, "`.csv`", "serangan", FAKTA))
    tanpa = " ".join(declared_checklist(KONTRAK, "`.csv`", "serangan"))

    assert "2 kelas" in dengan
    assert "2 kelas" not in tanpa
    assert "satu baris per sesi trafik" in dengan


# ── Rantainya: formulir → metadata → atribusi → tampilan ─────────────────

def test_the_upload_form_asks_for_all_four():
    from pathlib import Path

    import ui.views.contribute as contrib

    src = Path(contrib.__file__).read_text(encoding="utf-8")
    for key in ("contrib_schema_rowunit", "contrib_schema_labelmeaning",
                "contrib_schema_features", "contrib_schema_classes"):
        assert key in src, key
    for meta in ("dataset_row_unit", "dataset_label_meaning",
                 "dataset_feature_nature", "dataset_class_count"):
        assert meta in src, meta


def test_the_submission_metadata_reaches_the_attribution():
    from orchestrator.submission_service import research_attribution_of

    item = {"metadata": {"dataset_row_unit": "satu baris per sesi trafik",
                         "dataset_label_meaning": "0 = normal, 1 = serangan",
                         "dataset_feature_nature": "kolom numerik",
                         "dataset_class_count": 2,
                         "researcher": "Budi", "year": "2026"}}
    sumber = research_attribution_of(item, "Deteksi X")["dataset_source"]

    assert sumber["row_unit"] == "satu baris per sesi trafik"
    assert sumber["label_meaning"] == "0 = normal, 1 = serangan"
    assert sumber["feature_nature"] == "kolom numerik"
    assert sumber["class_count"] == "2"


def test_an_empty_field_is_dropped_not_stored_as_a_dash():
    from orchestrator.submission_service import research_attribution_of

    item = {"metadata": {"dataset_name": "Trafik", "dataset_row_unit": "",
                         "dataset_class_count": ""}}
    sumber = research_attribution_of(item, "X")["dataset_source"]

    assert "row_unit" not in sumber and "class_count" not in sumber
    assert sumber["name"] == "Trafik"


def test_the_add_dataset_table_reads_the_same_declaration(monkeypatch):
    """Kedua halaman menyebut hal yang sama — itulah pangkal seluruh kerja ini."""
    from ui.components import instructions as ins
    from ui.views import run_experiment as rx

    monkeypatch.setattr(rx, "declared_dataset_facts", lambda _dt: FAKTA)
    dtype = "uploaded:deteksi_trafik_kampus"
    if not rx._schema_of(dtype):
        pytest.skip("research kontribusi tidak ada pada basis data uji")

    tabel = " ".join(n for _a, n in ins.dataset_contract_rows(dtype))

    assert "satu baris per sesi trafik" in tabel
    assert "0 = normal, 1 = serangan" in tabel
    assert "agregasi per sesi" in tabel
    assert "2 kelas" in tabel
