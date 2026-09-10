"""Halaman kontribusi dibaca sebagai ALUR, bukan sebagai bacaan.

Dua perubahan yang harus benar sekaligus.

**Em dash dicabut dari teks yang dibaca pengguna.** Ia memaksa pembaca menahan
satu klausa sambil membaca klausa berikutnya; pada kalimat instruksi itu
memperlambat orang yang sedang mencoba mengerjakan sesuatu. Yang dicabut hanya
tanda pisah bergaya. DUA pemakaian tetap, karena keduanya data dan bukan gaya
tulisan: pemisah kredit ``"<kredit> — <nama>"`` yang dipecah dan disusun ulang
`research_registry.short_label_from`, dan ``"—"`` sebagai penanda sel tanpa
nilai. Mencabut yang pertama merusak label setiap research beserta parsernya;
mencabut yang kedua membuat "tidak ada nilai" terbaca sebagai "lupa diisi".

**Keterangan yang berdiri sendiri menempel pada kontrolnya.** Paragraf yang
melayang di antara judul bagian dan kontrolnya harus dilewati setiap orang yang
sudah tahu isinya, setiap kali. Sebagai ``help=`` ia muncul tepat ketika
kontrolnya ditanyakan, dan tidak ada informasi yang hilang.

Yang TIDAK dipindah: status dan umpan balik. "Paket valid", "{n} kolom terbaca",
"belum ada berkas" mengabarkan apa yang baru terjadi. Itu bagian dari alurnya,
bukan keterangan yang melayang di atasnya.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")

EM = "—"

APP = '''
import sys
sys.path.insert(0, r"{repo}")
import ui.views.contribute as c
c.render()
'''


def _run(tmp_path, mode, buka=False):
    from streamlit.testing.v1 import AppTest

    app = tmp_path / "contrib_app.py"
    app.write_text(APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(app), default_timeout=300)
    at.session_state["_contrib_mode"] = mode
    at.run()
    if buka:
        at = at.button(key=f"contrib_info_{mode}").click().run()
    return at


def _teks(at) -> list[str]:
    keluar: list[str] = []
    for grup in (at.markdown, at.caption, at.code, at.info, at.success,
                 at.warning, at.error):
        keluar += [e.value for e in grup]
    return keluar


# ── Nol em dash pada yang benar-benar TERGAMBAR ──────────────────────────

@pytest.mark.parametrize("mode", ["pipeline", "dataset"])
@pytest.mark.parametrize("buka", [False, True], ids=["halaman", "modal"])
def test_no_em_dash_reaches_the_reader(tmp_path, mode, buka):
    """Dirender, bukan dibaca dari sumber: yang dijaga adalah apa yang sampai
    ke mata pengguna, termasuk kalimat yang dirakit saat berjalan."""
    kena = [b for b in _teks(_run(tmp_path, mode, buka)) if EM in b]

    assert kena == [], kena


def test_the_pages_still_say_something(tmp_path):
    """Penjagaan terhadap cara curang lulus tes di atas: halaman kosong juga
    tidak punya em dash."""
    assert len(_teks(_run(tmp_path, "pipeline", buka=True))) >= 20
    assert len(_teks(_run(tmp_path, "dataset", buka=True))) >= 8


# ── Dua pemakaian yang TETAP, karena keduanya data ───────────────────────

def test_the_credit_separator_survives_and_still_parses():
    """Ia bukan gaya tulisan: `short_label_from` MEMECAH pada tanda ini untuk
    mengambil kredit, lalu menyusunnya kembali."""
    from orchestrator.research_registry import short_label_from

    label = short_label_from("HIKARI2021",
                             {"display_name": "Rayyan (2024) — HIKARI2021",
                              "short_name": "HIKARI2021"})

    assert label == "Rayyan (2024) — HIKARI2021"
    assert label.split(EM)[0].strip() == "Rayyan (2024)"


def test_the_preview_shows_the_separator_it_will_actually_produce():
    """Pratinjau yang mencabut tanda pisahnya akan berbohong tentang bentuk
    label yang akan dihasilkan."""
    from ui.i18n import t

    for lang in ("id", "en"):
        from ui.i18n.core import lookup
        assert EM in lookup("ap.credit_preview", lang), lang
    assert EM in t("ap.credit_preview", credit="Budi (2026)", name="Deteksi X")


def test_the_empty_cell_marker_survives():
    """"Tidak ada nilai" harus terbaca sebagai jawaban, bukan sebagai kolom
    yang lupa diisi."""
    from ui.components.experiment_table import basename

    assert basename(None) == EM


# ── Kalimat pengganti tidak merusak maknanya ─────────────────────────────

@pytest.mark.parametrize("key, harus_ada", [
    ("ap.err_file_exists", "tidak menimpa dataset"),
    ("ap.msg_valid_not_active", "belum aktif"),
    ("ins.static_check_note", "tidak dijalankan"),
    ("ins.dataset_sample_note", "tersimpan langsung"),
    ("ins.mis_entry_point", "Titik masuk"),
])
def test_the_fact_survives_the_rewrite(key, harus_ada):
    from ui.i18n.core import lookup

    assert harus_ada in lookup(key, "id"), key


@pytest.mark.parametrize("key", [
    "ap.help_declare_schema", "ap.help_dataset_facts", "ap.help_method_notes",
    "ap.note_checked_against_all", "ins.static_check_note",
    "ins.dataset_sample_note", "ins.contract_intro", "ap.msg_valid_not_active",
])
def test_the_rewritten_sentences_carry_no_em_dash(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert EM not in lookup(key, lang), (key, lang)


def test_the_range_dash_is_not_collateral_damage():
    """"Langkah 2–3" memakai en dash sebagai RENTANG, bukan tanda pisah."""
    from ui.i18n.core import lookup

    assert "2–3" in lookup("ins.anti_leak_note", "id")


# ── Keterangan menempel pada kontrolnya ──────────────────────────────────

@pytest.mark.parametrize("kunci_teks, kunci_widget", [
    ("ap.help_declare_schema", "contrib_schema_label"),
    ("ap.help_dataset_facts", "contrib_schema_rowunit"),
    ("ap.help_method_notes", "contrib_info_app"),
])
def test_the_guidance_moved_onto_the_control_it_explains(kunci_teks,
                                                         kunci_widget):
    blok = CONTRIB_SRC.split(f'key="{kunci_widget}"')[1][:220]

    assert f't("{kunci_teks}")' in blok, kunci_widget
    # Dan tidak lagi berdiri sebagai paragraf lepas.
    assert f'prose(t("{kunci_teks}")' not in CONTRIB_SRC


def test_the_trial_dataset_note_moved_onto_its_uploader():
    blok = CONTRIB_SRC.split('key="contrib_trial_dataset"')[1][:320]

    assert 'td.intro' in blok
    assert 'td.limit_note' in blok
    assert 'st.caption(t("td.intro")' not in CONTRIB_SRC


@pytest.mark.parametrize("tetap", [
    'st.info(t("ap.msg_valid_not_active"))',       # status hasil validasi
    'ap.columns_from_dataset',                      # umpan balik: {n} kolom
    'ap.credit_preview',                            # pratinjau label
])
def test_status_and_feedback_stay_on_the_page(tetap):
    """Yang mengabarkan apa yang baru terjadi adalah bagian dari alurnya."""
    assert tetap in CONTRIB_SRC


# ── Aturan tampilan yang berlaku umum ────────────────────────────────────

def test_the_page_carries_less_small_text_than_before():
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import small_text_audit as audit

    jumlah = len(audit.audit("Add Pipeline & Dataset"))

    assert jumlah <= audit.QUOTA
    # Tiga adalah kuotanya; sesudah pemindahan ini halamannya di bawah kuota.
    assert jumlah < audit.QUOTA


def test_the_catalogue_is_complete_in_both_languages():
    from ui.i18n.catalog import CATALOG

    kurang = [k for k, v in CATALOG.items()
              if not str(v.get("id") or "").strip()
              or not str(v.get("en") or "").strip()]

    assert kurang == []
