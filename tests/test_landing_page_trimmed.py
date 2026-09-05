"""Halaman muka "Tambah Pipeline & Dataset" berhenti mengulang dirinya.

Dua hal dibuang dari sana:

* **tabel "Pengajuan saya"** — daftar berkolom penuh di kaki halaman yang
  memilih jalur, jauh dari apa pun yang sedang dikerjakan pembacanya;
* **baris "{n} pengajuan menunggu tinjauan"** pada kartu peninjauan — angka
  yang sudah tampak begitu bagian peninjauan dibuka, ditebus dengan satu kueri
  basis data pada setiap penggambaran halaman muka.

Satu hal TIDAK ikut dibuang: **catatan peninjau pada pengajuan yang ditolak**.
Itu satu-satunya umpan balik yang pernah diterima kontributor; tanpanya ia
mengunggah ulang kesalahan yang sama tanpa pernah tahu apa yang salah. Ia
pindah ke ringkasan pasca-unggah, tempat status pengajuannya memang dibaca.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ui.components import contribute_context as ctx

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")
CARDS_SRC = (REPO_ROOT / "ui" / "components" / "upload_cards.py").read_text(
    encoding="utf-8")


# ── Yang dibuang ─────────────────────────────────────────────────────────

def test_the_my_submissions_table_is_gone():
    for gone in ("_render_my_submissions", "_my_submission_columns",
                 "Pengajuan saya"):
        assert gone not in CONTRIB_SRC, gone


def test_the_pending_count_note_is_gone():
    assert "_admin_queue_notes" not in CONTRIB_SRC
    assert "ap.review_pending_count" not in CONTRIB_SRC


def test_the_cards_no_longer_accept_a_counts_argument():
    """Parameter yang tidak punya pemberi nilai adalah jebakan: ia terlihat
    seperti kemampuan yang masih ada."""
    assert "counts" not in CARDS_SRC


def test_the_cards_still_say_why_a_button_is_dead():
    """Yang dibuang hanya baris jumlah — sebab tombol mati TETAP dinyatakan."""
    assert "card['denied']" in CARDS_SRC
    assert "ap.card_denied_hint" in CARDS_SRC


def test_the_landing_view_no_longer_queries_for_a_count():
    """Halaman muka digambar untuk setiap pengunjung; kueri yang hasilnya
    belum tentu dibaca adalah biaya yang ditanggung semua orang."""
    body = CONTRIB_SRC.split("def _render_choice_boxes(")[1].split(
        chr(10) + "def ")[0]
    assert "list_submissions(" not in body


@pytest.mark.parametrize("key", ["ap.review_pending_count", "ap.col_file",
                                 "ap.col_kind", "ap.col_status", "ap.col_time",
                                 "ap.my_submissions_empty"])
def test_the_orphaned_keys_left_the_catalog(key):
    """Kunci tanpa pemakai menyesatkan pembaca katalog berikutnya."""
    from ui.i18n.catalog import CATALOG

    assert key not in CATALOG


# ── Yang DIPERTAHANKAN ───────────────────────────────────────────────────

def _item(sid, status, note=""):
    return {"id": sid, "status": status, "review_note": note}


def test_only_rejected_submissions_carry_a_note_forward():
    """Yang disetujui sudah menjelaskan dirinya lewat pipeline yang muncul di
    daftar; yang ditolak tidak meninggalkan jejak apa pun selain catatan ini."""
    items = [_item(1, "rejected", "kolom label tidak ada"),
             _item(2, "approved", "bagus"),
             _item(3, "pending", "")]
    assert ctx.rejection_notes(items) == [(1, "kolom label tidak ada")]


def test_a_rejection_without_a_note_is_not_announced_as_empty():
    """Baris "Pengajuan #2 ditolak — " tanpa isi lebih buruk daripada diam."""
    assert ctx.rejection_notes([_item(2, "rejected", "   ")]) == []
    assert ctx.rejection_notes([_item(2, "rejected")]) == []


def test_every_rejection_is_carried_not_just_the_latest():
    items = [_item(1, "rejected", "a"), _item(2, "rejected", "b")]
    assert ctx.rejection_notes(items) == [(1, "a"), (2, "b")]


def test_reading_the_notes_is_pure(monkeypatch):
    """Fungsi MURNI: dipisah dari perenderannya supaya dapat diperiksa tanpa
    menjalankan halaman."""
    import sqlite3

    def _boom(*a, **k):
        raise AssertionError("penyusun catatan membuka basis data")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    assert ctx.rejection_notes([]) == []
    assert ctx.rejection_notes(None) == []


def test_the_note_is_rendered_after_the_status_summary():
    """Tempatnya mengikuti bacaannya: berapa banyak dulu, baru kenapa."""
    src = (REPO_ROOT / "ui" / "components"
           / "contribute_context.py").read_text(encoding="utf-8")
    body = src.split("def render_after_upload(")[1].split(chr(10) + "def ")[0]
    assert "ap.sub_yours" in body
    assert "_render_rejection_notes(user)" in body
    assert body.index("ap.sub_yours") < body.index("_render_rejection_notes")


def test_the_note_text_names_the_submission_and_the_reason():
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        text = lookup("ap.rejection_note", lang)
        assert "{id}" in text and "{note}" in text, lang
