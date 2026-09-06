"""Pemilih research pipeline pada halaman Tambah Dataset.

Sederet tab tumbuh KE SAMPING. Dengan dua research bawaan ia masih rapi; setiap
research pipeline kontribusi yang disetujui menambah satu lagi, dan judul yang
panjang — "Contoh Kontributor (2026), Universitas Hasanuddin — Deteksi Trafik
Kampus" — terpotong atau membungkus ke baris kedua. Sebuah pemilih tidak
berubah tingginya berapa pun panjang daftarnya, dan namanya tampil utuh.

Yang berubah HANYA cara memilihnya. Isi persyaratannya, contoh datanya,
checklist-nya, dan panel persyaratan bersama tetap datang dari fungsi yang sama
seperti sebelumnya — tes di berkas ini menjaga agar tidak ada satu pun di
antaranya yang ikut hilang.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import ui.components.instructions as ins

MODULE = Path(ins.__file__).read_text(encoding="utf-8")


class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _render(pilihan=None):
    """Gambar halamannya, kembalikan (teks yang tergambar, jejak selectbox)."""
    keluar: list[str] = []
    jejak: dict = {}

    def _selectbox(label, options, **kw):
        jejak["label"] = label
        jejak["options"] = list(options)
        jejak["format_func"] = kw.get("format_func")
        jejak["key"] = kw.get("key")
        pilih = pilihan if pilihan is not None else (
            list(options)[0] if options else None)
        return pilih

    with patch.object(ins.st, "selectbox", _selectbox), \
         patch.object(ins.st, "container", lambda **kw: _Ctx()), \
         patch.object(ins.st, "expander", lambda *a, **kw: _Ctx()), \
         patch.object(ins.st, "tabs",
                      lambda labels, **kw: [_Ctx() for _ in labels]), \
         patch.object(ins.st, "markdown",
                      lambda s=None, **kw: keluar.append(str(s))), \
         patch.object(ins.st, "caption",
                      lambda s=None, **kw: keluar.append(str(s))), \
         patch.object(ins.st, "code",
                      lambda s=None, **kw: keluar.append(str(s))), \
         patch.object(ins.st, "divider", lambda *a, **kw: None):
        ins.render_dataset_instructions()
    return " ".join(keluar), jejak


# ── Bentuk pemilihnya ────────────────────────────────────────────────────

def test_the_tabs_are_gone_from_this_page():
    """Sumbernya diperiksa: `st.tabs` masih dipakai bagian LAIN halaman ini
    (kontrak masukan/keluaran pipeline), jadi yang dijaga adalah bahwa fungsi
    INI tidak lagi memakainya."""
    body = MODULE.split("def render_dataset_instructions(")[1].split(
        chr(10) + "def ")[0]

    assert "st.tabs" not in body
    assert "st.selectbox" in body


def test_the_picker_is_labelled_and_keyed():
    _teks, jejak = _render()

    assert jejak["label"] == "Research Pipeline"
    assert jejak["key"] == "ins_dataset_research"


def test_every_research_pipeline_is_offered():
    from orchestrator.research_registry import all_dataset_types

    _teks, jejak = _render()

    assert jejak["options"] == list(all_dataset_types())
    assert len(jejak["options"]) >= 2


def test_each_option_reads_as_its_research_credit():
    """Pengenal mentah (`uploaded:deteksi_trafik_kampus`) tidak menjelaskan apa
    pun; yang ditampilkan adalah nama beratribusinya."""
    from orchestrator.research_registry import short_label_for

    _teks, jejak = _render()
    tampil = [jejak["format_func"](k) for k in jejak["options"]]

    assert tampil == [short_label_for(k) for k in jejak["options"]]
    assert any("—" in label for label in tampil)      # "<kredit> — <nama>"
    assert all(label for label in tampil)


# ── Isinya tetap lengkap, dan hanya milik yang terpilih ──────────────────

@pytest.mark.parametrize("dtype", ["HIKARI2021", "EVE_SURICATA"])
def test_the_requirements_table_survives(dtype):
    from ui.components.instructions import dataset_contract_rows

    teks, _jejak = _render(dtype)

    for aspek, ketentuan in dataset_contract_rows(dtype):
        assert aspek in teks, aspek
        assert ketentuan in teks, ketentuan


@pytest.mark.parametrize("dtype", ["HIKARI2021", "EVE_SURICATA"])
def test_the_sample_and_checklist_survive(dtype):
    from ui.components.instructions import dataset_checklist, dataset_sample_snippet

    teks, _jejak = _render(dtype)

    assert dataset_sample_snippet(dtype) in teks
    for butir in dataset_checklist(dtype):
        assert butir in teks, butir


def test_only_the_selected_research_is_detailed():
    """Sebelumnya expander persyaratan menggambar SELURUH research sekaligus."""
    teks, _jejak = _render("HIKARI2021")

    assert "flow" in teks.lower()                     # HIKARI memang tampil
    # Kalimat khas EVE tidak boleh ikut terbawa.
    assert "satu objek JSON per baris" not in teks
    assert "alert Suricata" not in teks


def test_switching_swaps_every_research_specific_part():
    hikari, _ = _render("HIKARI2021")
    eve, _ = _render("EVE_SURICATA")

    assert hikari != eve
    assert "satu objek JSON per baris" in eve
    assert "satu objek JSON per baris" not in hikari
    assert "flow_duration" in hikari                  # contoh data HIKARI
    assert "flow_duration" not in eve


def test_the_page_still_carries_its_warnings():
    """Catatan cuplikan dan daftar kesalahan umum bukan bagian per-research —
    keduanya harus tetap tergambar."""
    teks, _jejak = _render()

    assert "cuplikan" in teks.lower()
    assert "tersimpan langsung" in teks.lower()


def test_the_shared_requirements_panel_is_still_reused():
    """Panel persyaratan halaman Run Experiment tetap dipakai apa adanya —
    yang berubah hanya BERAPA research yang dilewatkan kepadanya."""
    body = MODULE.split("def render_dataset_instructions(")[1].split(
        chr(10) + "def ")[0]

    assert "_render_dataset_requirements(dtype)" in body
    assert "for dtype in supported_datasets()" not in body


def test_an_empty_registry_does_not_crash():
    """Registry yang tidak mengembalikan apa pun berarti tidak ada yang dapat
    dipilih — halamannya berhenti, bukan jatuh."""
    with patch.object(ins.st, "selectbox", lambda *a, **kw: None), \
         patch.object(ins.st, "container", lambda **kw: _Ctx()), \
         patch.object(ins.st, "expander", lambda *a, **kw: _Ctx()), \
         patch.object(ins.st, "markdown", lambda *a, **kw: None), \
         patch.object(ins.st, "caption", lambda *a, **kw: None), \
         patch.object(ins.st, "code", lambda *a, **kw: None), \
         patch.object(ins.st, "divider", lambda *a, **kw: None):
        ins.render_dataset_instructions()          # tidak melempar


def test_the_label_exists_in_both_languages():
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup("ins.lbl_research_pipeline", lang), lang
