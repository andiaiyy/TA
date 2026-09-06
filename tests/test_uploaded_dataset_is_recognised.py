"""Research pipeline kontribusi yang datasetnya ADA, tetapi dinyatakan tidak.

Sebuah paket kontribusi membawa datasetnya sendiri: ia terikat ke research
pipeline-nya, bukan diletakkan di ``storage/datasets/``. Semua yang menjalankan
sudah tahu itu — `_list_dataset_files` mengembalikannya, diagnosa meluluskannya,
`execute_pipeline` menyelesaikan skemanya lewat registry, dan pipelinenya
benar-benar berjalan.

Yang tidak tahu justru yang MENJELASKAN. Tiga tempat masih bertanya kepada
``contracts.dataset_schemas``, yang hanya mengenal jenis bawaan:

* katalog menyerah sebelum bertanya (`_has_dataset_for`), lalu menandai setiap
  algoritma kontribusi "belum ada dataset platform berjenis ini, jadi pipeline
  ini belum dapat dijalankan" — kalimat yang salah tentang pipeline yang sudah
  siap jalan;
* kartunya menggambarkan kontraknya sebagai ``Kolom label: `?` ``, padahal
  kontrak itu dideklarasikan saat pengunggahan dan tersimpan utuh;
* daftar ekstensinya jatuh ke ``.csv`` untuk paket apa pun, termasuk yang
  formatnya NDJSON.

Ketiganya cacat KETERBACAAN, bukan cacat eksekusi — dan justru itu yang membuat
pembacanya menyimpulkan datasetnya hilang.
"""
from __future__ import annotations

import pytest

UPLOADED = "uploaded:demo_kampus"
DECLARED = {"label_column": "serangan", "file_format": "csv",
            "expected_columns": ["durasi", "byte_masuk", "serangan"]}


@pytest.fixture
def declared(monkeypatch):
    """Sebuah jenis dataset kontribusi dengan kontrak terdeklarasi + berkasnya."""
    import ui.views.run_experiment as rx

    monkeypatch.setattr(rx, "get_schema", lambda dt: None)
    monkeypatch.setattr("orchestrator.research_registry.schema_for",
                        lambda dt, db_path=None: dict(DECLARED)
                        if dt == UPLOADED else None)
    monkeypatch.setattr(rx, "_list_dataset_files",
                        lambda dt: ["C:/x/trafik.csv"] if dt == UPLOADED else [])
    return rx


# ── Katalog berhenti menuduh dataset itu tidak ada ───────────────────────

def test_a_contributed_pipeline_with_its_own_dataset_is_runnable(declared):
    from ui.components import pipeline_catalog as pc

    state, reason = pc.entry_state(
        "uploaded.demo@v1", {"dataset_type": UPLOADED, "uploaded": True})

    assert state == pc.STATE_OK, reason
    assert reason == ""


def test_a_type_nobody_declared_is_still_reported_as_missing(declared):
    """Perbaikannya bukan "selalu bilang ada": jenis yang benar-benar asing
    tetap dinyatakan tidak punya dataset."""
    from ui.components import pipeline_catalog as pc

    state, reason = pc.entry_state(
        "uploaded.asing@v1", {"dataset_type": "uploaded:tak_terdaftar",
                              "uploaded": True})

    assert state == pc.STATE_NO_DATASET
    assert reason


def test_the_group_stops_listing_it_as_a_problem(declared):
    from ui.components import pipeline_catalog as pc

    groups = pc.build_catalog(
        registry_reader=lambda: {"uploaded.demo@v1": {
            "dataset_type": UPLOADED, "algorithm": "Random Forest",
            "name": "demo", "uploaded": True, "version": 1,
            "info": {"algorithm": "Random Forest"}}},
        info_reader=lambda _pid: {},
        name_reader=lambda dt: "Demo Kampus")

    assert pc.group_problems(groups[0]) == []


# ── Kartunya menyebut kontrak yang DIDEKLARASIKAN ────────────────────────

def test_the_card_states_the_declared_contract(declared):
    from ui.components.instructions import dataset_contract_rows

    rows = dict(dataset_contract_rows(UPLOADED))

    assert "`serangan`" in rows["Kolom label"]
    assert "?" not in rows["Kolom label"]
    assert "5 kolom" not in str(rows)          # kontraknya menyebut 3
    assert "3 kolom" in rows["Kolom wajib"]


def test_it_never_invents_what_the_contract_does_not_say(declared):
    """Kontrak kontribusi menyatakan NAMA kolom label, bukan arti nilainya.
    Menyalin "`0` = benign, `1` = malicious" ke sini mengarang semantik yang
    tidak pernah dinyatakan siapa pun — dan "Jumlah kelas: dua" bersamanya."""
    from ui.components.instructions import dataset_contract_rows

    rows = dict(dataset_contract_rows(UPLOADED))

    assert "benign" not in str(rows) and "malicious" not in str(rows)
    assert "Jumlah kelas" not in rows
    assert "Sifat fitur" not in rows           # tidak ada kalimat kurasinya
    assert "—" not in rows["Format berkas"]    # bekas isian kosong


@pytest.mark.parametrize("dtype", ["HIKARI2021", "EVE_SURICATA"])
def test_the_builtin_rows_are_untouched(dtype):
    from contracts.dataset_schemas import get_schema
    from ui.components.instructions import dataset_contract_rows

    rows = dict(dataset_contract_rows(dtype))

    assert get_schema(dtype)["label_column"] in rows["Kolom label"]
    assert rows["Sifat fitur"]
    assert "dua kelas" in rows["Jumlah kelas"]


# ── Ekstensi mengikuti format yang dinyatakan ────────────────────────────

def test_the_extensions_follow_the_declared_format(monkeypatch):
    """Sebuah paket NDJSON yang diumumkan menerima `.csv` adalah pernyataan
    yang SALAH, bukan sekadar tidak lengkap."""
    import ui.views.run_experiment as rx

    monkeypatch.setattr(rx, "get_schema", lambda dt: None)
    monkeypatch.setattr(
        "orchestrator.research_registry.schema_for",
        lambda dt, db_path=None: {"label_column": "y", "file_format": "ndjson"})

    assert rx._dataset_extensions(UPLOADED) == (".json", ".jsonl", ".ndjson")


def test_an_unknown_type_still_falls_back_to_csv(monkeypatch):
    import ui.views.run_experiment as rx

    monkeypatch.setattr(rx, "get_schema", lambda dt: None)
    monkeypatch.setattr("orchestrator.research_registry.schema_for",
                        lambda dt, db_path=None: None)

    assert rx._dataset_extensions("uploaded:kosong") == (".csv",)


def test_the_builtin_extension_map_still_wins():
    import ui.views.run_experiment as rx

    assert rx._dataset_extensions("EVE_SURICATA") == (".json", ".jsonl",
                                                      ".ndjson")
    assert rx._dataset_extensions("HIKARI2021") == (".csv",)
