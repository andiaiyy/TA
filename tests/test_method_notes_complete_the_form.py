"""Formulir Add Pipeline melengkapi apa yang platform TAMPILKAN.

Pipeline BAWAAN menulis sepuluh kunci di dalam ``get_info()``; validator hanya
mewajibkan enam. Selisih empat kunci itu — ``app``, ``anti_leakage``,
``metrics_policy``, ``dataset`` — dipakai di empat tempat: dua baris pada modal
katalog, dua bagian yang dapat dilipat pada modal itu, dan tiga baris kelompok
"Cakupan & metode" pada panel Tentang Research Pipeline. Paket kontribusi
hampir tidak pernah memuatnya, jadi keempat tempat itu kosong — bukan karena
kontributornya lalai, melainkan karena tidak pernah ada yang menanyakannya.

Formulir kini menanyakannya. Arah presedennya tidak boleh terbalik: **kode
menang**. Yang ditulis pipeline adalah kebenaran tentang apa yang benar-benar
dijalankan; isian formulir hanya mengisi kunci yang kodenya tidak menyebutkan.

Ke mana jawabannya disimpan dijaga [test_method_notes_are_editable.py]: research
yang berdiri sendiri menyimpannya di baris researchnya supaya dapat disunting,
paket yang menumpang jenis bawaan tetap menyimpannya di potret. Berkas INI
menjaga pertanyaannya — bahwa formulirnya benar-benar menanyakan keenamnya —
dan aturan penggabungannya.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.dynamic_registry import merge_info
from orchestrator.submission_service import info_extra_of

ISIAN = {"info_app": "TLS",
         "info_metrics_policy": "metrik kelas serangan pada holdout apa adanya",
         "info_dataset": "trafik kampus Januari 2026",
         "info_anti_leakage": "scaler di-fit pada data latih\npenyeimbangan sesudah split"}


# ── Preseden: kode menang, formulir mengisi yang kosong ──────────────────

def test_the_code_wins_when_both_state_the_same_key():
    """Bila formulir boleh menimpa kode, keterangan yang dibaca peninjau dapat
    berbeda dari yang dieksekusi — dan seluruh klaim ketertelusuran bertumpu
    pada keduanya tidak pernah berbeda."""
    gabung = merge_info({"app": "TLS"}, {"app": "HTTP"})

    assert gabung["app"] == "TLS"


def test_the_form_fills_only_what_the_code_left_out():
    gabung = merge_info({"algorithm": "RF"}, {"app": "TLS"})

    assert gabung == {"algorithm": "RF", "app": "TLS"}


def test_an_empty_form_field_is_not_an_instruction_to_blank_it():
    gabung = merge_info({"app": "TLS"}, {"app": "", "metrics_policy": []})

    assert gabung == {"app": "TLS"}


def test_no_form_notes_leaves_the_snapshot_exactly_as_it_was():
    """Paket lama harus menghasilkan potret yang sama persis seperti dulu."""
    asli = {"algorithm": "RF", "fixed_params": {"n": 1}}

    assert merge_info(asli, None) is asli
    assert merge_info(asli, {}) is asli


def test_a_missing_snapshot_still_gains_the_declared_notes():
    """`get_info()` yang gagal dipotret tidak boleh membuang isian formulir."""
    assert merge_info(None, {"app": "TLS"}) == {"app": "TLS"}


# ── Bentuk isian → bentuk yang dipakai penyaji ───────────────────────────

def test_the_anti_leakage_lines_become_a_list():
    """Penyajinya menggabungkan DAFTAR menjadi satu kalimat; satu tindakan per
    baris adalah cara menulisnya, bukan cara menyimpannya."""
    keluar = info_extra_of(ISIAN)

    assert keluar["anti_leakage"] == ["scaler di-fit pada data latih",
                                      "penyeimbangan sesudah split"]


def test_the_three_single_line_notes_pass_through():
    keluar = info_extra_of(ISIAN)

    assert keluar["app"] == "TLS"
    assert keluar["dataset"] == "trafik kampus Januari 2026"
    assert "holdout" in keluar["metrics_policy"]


def test_nothing_declared_yields_nothing():
    assert info_extra_of({}) == {}
    assert info_extra_of(None) == {}
    assert info_extra_of({"info_app": "   ", "info_anti_leakage": "\n\n"}) == {}


# ── Formulir benar-benar menanyakan keenamnya ────────────────────────────

@pytest.mark.parametrize("kunci", [
    "contrib_info_app", "contrib_info_metrics", "contrib_info_dataset",
    "contrib_info_anti", "contrib_sample_values", "contrib_ignored_cols",
])
def test_the_upload_form_asks_for_it(kunci):
    import ui.views.contribute as contrib

    assert kunci in Path(contrib.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("meta", [
    "info_app", "info_metrics_policy", "info_dataset", "info_anti_leakage",
    "dataset_sample_values", "dataset_ignored_columns",
])
def test_the_answer_reaches_the_submission_metadata(meta):
    import ui.views.contribute as contrib

    src = Path(contrib.__file__).read_text(encoding="utf-8")
    form = src.split("    form = {")[1].split(chr(10) + "    }")[0]

    assert meta in form, meta


def test_the_answer_is_kept_where_it_can_still_be_corrected():
    """Dahulu tes ini memeriksa satu baris harfiah — ``info_extra=…`` — pada
    kode pendaftaran. Baris itu memang benar ada, tetapi ia bukan yang
    dijanjikan kepada kontributor: yang dijanjikan adalah jawabannya TERSIMPAN.
    Sejak jawaban itu pindah ke baris research supaya dapat disunting, teks
    harfiahnya berubah sementara janjinya tidak. Yang dijaga sekarang janjinya.
    """
    from orchestrator.submission_service import research_attribution_of

    tersimpan = research_attribution_of({"metadata": ISIAN}, "Demo")

    assert tersimpan["method_notes"] == info_extra_of(ISIAN)


def test_a_package_riding_a_builtin_type_still_gets_its_notes():
    """Paket yang tidak membawa kontrak datasetnya sendiri tidak punya baris
    research yang memilikinya. Bagi mereka potret tetap satu-satunya rumah,
    dan pendaftarannya harus tetap menitipkannya ke sana."""
    import orchestrator.submission_service as ss

    src = Path(ss.__file__).read_text(encoding="utf-8")
    blok = src.split("def _register_approved_pipeline(")[1].split(
        chr(10) + "def ")[0]

    assert "is_standalone(item)" in blok
    assert "info_extra_of(metadata)" in blok


# ── Dua bidang persyaratan terakhir ──────────────────────────────────────

def test_the_ignored_columns_row_appears_only_when_declared():
    from ui.views.run_experiment import declared_requirement_rows

    skema = {"label_column": "y", "expected_columns": ["a"]}
    dengan = declared_requirement_rows(skema, "`.csv`", "y",
                                       {"ignored_columns": "uid, timestamp"})
    tanpa = declared_requirement_rows(skema, "`.csv`", "y", {})

    assert any("uid" in nilai for _a, nilai in dengan)
    assert len(tanpa) == len(dengan) - 1


def test_the_sample_block_gains_a_value_line_when_declared():
    from ui.views.run_experiment import declared_sample_block

    hanya_nama = declared_sample_block(["durasi", "byte_masuk"])
    dengan_nilai = declared_sample_block(["durasi", "byte_masuk"],
                                         "durasi = 0.523")

    assert chr(10) not in hanya_nama
    assert dengan_nilai.splitlines()[0] == "durasi,byte_masuk"
    # Kolom yang tidak disebutkan diisi "…", bukan nilai karangan.
    assert dengan_nilai.splitlines()[1] == "0.523,…"


def test_a_malformed_sample_line_is_ignored_not_crashed():
    from ui.views.run_experiment import declared_sample_block

    assert declared_sample_block(["a"], "tanpa tanda sama dengan") == "a"


def test_the_two_dataset_fields_stay_editable():
    """Penjagaan yang sama: `_clean` membuang bidang kosong, jadi keduanya
    harus ikut ditulis setiap kali formulir sunting menyimpan."""
    from ui.components import research_manage as rs

    src = Path(rs.__file__).read_text(encoding="utf-8")
    form = src.split("def _render_edit_form(")[1].split(chr(10) + "def ")[0]
    simpan = form.split('atribusi["dataset_source"]')[1][:500]

    for kunci in ("sample_values", "ignored_columns"):
        assert kunci in simpan, kunci
    for key in ("rs_f_dssample_", "rs_f_dsignore_"):
        assert key in form, key


@pytest.mark.parametrize("key", [
    "ap.sec_method_notes", "ap.help_method_notes", "ap.lbl_info_app",
    "ap.lbl_info_metrics", "ap.lbl_info_dataset", "ap.lbl_info_anti_leakage",
    "ap.help_info_anti_leakage", "ap.lbl_sample_values",
    "ap.help_sample_values", "ap.lbl_ignored_columns",
    "ap.help_ignored_columns", "re.req_row_sample_values", "re.req_row_ignored",
])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)
