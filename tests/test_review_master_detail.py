"""Antrean peninjauan berbentuk master-detail: daftar, lalu SATU pengajuan.

Yang dijaga di sini bukan tata letaknya, melainkan sifat yang membuat bentuk
ini dipilih: **daftar dan detail tidak pernah tergambar bersamaan**. Selama
tiap pengajuan punya kartunya sendiri, tiap pengajuan membaca berkas paketnya
pada SETIAP penggambaran ulang — expander Streamlit selalu merender isinya dan
tidak mengekspos status terbuka. Biaya seperti itu tumbuh mengikuti panjang
antrean, dan antrean adalah hal yang memang bertambah panjang.

Menyaring, mengurutkan, dan memenggal diuji pada lapis MURNI
(`ui/components/submission_review.py`): ketiganya bekerja atas kolom baris
pengajuan apa adanya dan tidak boleh membuka berkas apa pun.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from database.migration import apply_migrations
from database.models import KIND_PIPELINE, SUBMISSION_PENDING
from ui.components import submission_review as sr

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

PKG = '''
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"dataset_type": "HIKARI2021", "algorithm": "Demo"}
'''


def _item(sid, name, who="andi", when="2026-01-01"):
    return {"id": sid, "submitted_by": who, "submitted_at": when,
            "original_filename": f"{name}.py",
            "metadata": {"name": name}}


# ── Lapis murni: menyaring ────────────────────────────────────────────────

def test_an_empty_query_keeps_everything():
    items = [_item(1, "alpha"), _item(2, "beta")]
    assert sr.filter_pending(items, "") == items
    assert sr.filter_pending(items, "   ") == items


def test_the_query_matches_name_submitter_and_number():
    items = [_item(1, "alpha", who="andi"), _item(2, "beta", who="siti")]
    assert [i["id"] for i in sr.filter_pending(items, "alpha")] == [1]
    assert [i["id"] for i in sr.filter_pending(items, "siti")] == [2]
    assert [i["id"] for i in sr.filter_pending(items, "#2")] == [2]


def test_the_query_ignores_letter_case():
    items = [_item(1, "AlPhA")]
    assert len(sr.filter_pending(items, "alpha")) == 1


def test_every_word_must_match():
    """Kata yang tidak cocok MENYEMPITKAN hasil — bukan melebarkannya."""
    items = [_item(1, "alpha", who="andi"), _item(2, "beta", who="andi")]
    assert [i["id"] for i in sr.filter_pending(items, "andi alpha")] == [1]
    assert sr.filter_pending(items, "andi zulu") == []


def test_filtering_never_opens_a_package_file(monkeypatch):
    """Penyaring bekerja atas kolom baris pengajuan, bukan atas berkasnya."""
    import orchestrator.submission_service as svc

    def _boom(*a, **k):
        raise AssertionError("penyaring membuka berkas paket")

    monkeypatch.setattr(svc, "read_submission_sources", _boom)
    items = [_item(i, f"p{i}") for i in range(20)]
    sr.filter_pending(items, "p1")
    sr.order_pending(items, sr.SORT_NEWEST)
    sr.page_slice(items, 2)


# ── Lapis murni: mengurutkan ──────────────────────────────────────────────

def test_the_default_order_is_still_longest_waiting_first():
    items = [_item(2, "b", when="2026-02-01"), _item(1, "a", when="2026-01-01")]
    assert [i["id"] for i in sr.order_pending(items)] == [1, 2]
    # …dan itu persis urutan `sort_pending` yang sudah ada.
    assert sr.order_pending(items) == sr.sort_pending(items)


def test_the_newest_order_is_the_exact_reverse():
    items = [_item(1, "a", when="2026-01-01"), _item(2, "b", when="2026-02-01"),
             _item(3, "c", when="2026-03-01")]
    assert [i["id"] for i in sr.order_pending(items, sr.SORT_NEWEST)] == [3, 2, 1]


def test_an_unknown_sort_falls_back_to_the_default():
    items = [_item(2, "b", when="2026-02-01"), _item(1, "a", when="2026-01-01")]
    assert sr.order_pending(items, "entah") == sr.order_pending(items)


# ── Lapis murni: memenggal ────────────────────────────────────────────────

def test_a_page_holds_at_most_the_page_size():
    items = [_item(i, f"p{i}") for i in range(25)]
    assert len(sr.page_slice(items, 1)) == sr.PAGE_SIZE
    assert len(sr.page_slice(items, 3)) == 5


def test_the_page_count_never_drops_below_one():
    assert sr.page_count(0) == 1
    assert sr.page_count(1) == 1
    assert sr.page_count(sr.PAGE_SIZE) == 1
    assert sr.page_count(sr.PAGE_SIZE + 1) == 2


def test_a_page_beyond_the_end_is_clamped_not_emptied():
    """Antrean yang menyusut tidak boleh mendamparkan pengguna di halaman
    kosong yang tidak dapat ia tinggalkan."""
    items = [_item(i, f"p{i}") for i in range(12)]
    assert sr.page_slice(items, 99) == sr.page_slice(items, 2)
    assert sr.page_slice(items, 0) == sr.page_slice(items, 1)


def test_the_result_note_reports_shown_and_total():
    assert sr.result_note(10, 42) == (10, 42)


# ── Tampilan: daftar dan detail tidak pernah bersamaan ───────────────────

_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
import database.db as dbmod
import config.settings as settings
dbmod.DB_PATH = settings.DB_PATH = r"{db}"
from ui.components import theme
theme.inject()
st.session_state["_current_page"] = "Add Pipeline & Dataset"
st.session_state["_contrib_mode"] = "review"
st.session_state["auth_user"] = {admin!r}
{extra}
import ui.views.contribute as c
c.render()
'''


def _seed(tmp_path, n: int) -> str:
    db = tmp_path / "rev.db"
    apply_migrations(str(db))
    conn = sqlite3.connect(str(db))
    try:
        for i in range(n):
            folder = tmp_path / f"pkg_{i}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "p.py").write_text(PKG, encoding="utf-8")
            meta = {"entry_filename": "p.py", "class_name": "DemoPipeline",
                    "name": f"pipeline{i}", "dataset_type": "HIKARI2021"}
            conn.execute(
                """INSERT INTO submissions
                   (kind, status, submitted_by, submitted_at, original_filename,
                    stored_path, file_hash, file_size, metadata_json,
                    validation_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (KIND_PIPELINE, SUBMISSION_PENDING, "andi",
                 f"2026-01-{(i % 28) + 1:02d}", "p.py", str(folder),
                 f"{i:064d}", 100, json.dumps(meta),
                 json.dumps({"valid": True})))
        conn.commit()
    finally:
        conn.close()
    return str(db)


def _render(tmp_path, n: int, *, open_id: int | None = None):
    from streamlit.testing.v1 import AppTest

    import config.settings as settings
    import database.db as dbmod

    db = _seed(tmp_path, n)
    saved = (dbmod.DB_PATH, settings.DB_PATH)
    try:
        extra = ("" if open_id is None
                 else f'st.session_state["_contrib_review_open"] = {open_id}')
        script = tmp_path / "app.py"
        script.write_text(
            _APP.format(repo=str(REPO_ROOT), db=db, admin=ADMIN, extra=extra),
            encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        dbmod.DB_PATH, settings.DB_PATH = saved


def test_the_list_shows_a_table_and_controls_but_no_submission_detail(tmp_path):
    at = _render(tmp_path, 12)

    tables = [e.proto.body for e in at.get("html") if "ids-tbl" in e.proto.body]
    assert tables, "tabel ikhtisar tidak tergambar"
    # Kontrol daftar ada…
    assert at.text_input, "kolom pencarian tidak ada"
    assert at.selectbox, "pemilih urutan/pembuka tidak ada"
    # …dan TIDAK ada satu pun isi detail.
    assert not at.get("code"), "kode berkas tergambar padahal belum dibuka"
    labels = {b.label for b in at.button}
    assert "Setujui" not in labels and "Tolak" not in labels


def test_opening_one_submission_replaces_the_list(tmp_path):
    at = _render(tmp_path, 12, open_id=1)

    # Detail tergambar…
    assert at.get("code"), "kode berkas tidak tergambar pada detail"
    labels = {b.label for b in at.button}
    assert "Setujui" in labels and "Tolak" in labels
    # …dan daftarnya TIDAK.
    tables = [e.proto.body for e in at.get("html") if "ids-tbl" in e.proto.body]
    assert not tables, "tabel antrean masih tergambar di tampilan detail"


def test_the_detail_offers_a_way_back_to_the_queue(tmp_path):
    at = _render(tmp_path, 12, open_id=1)
    labels = [b.label for b in at.button]
    assert any("antrean" in label.lower() for label in labels), labels


def test_an_open_submission_that_left_the_queue_falls_back_to_the_list(tmp_path):
    """Pengajuan yang baru saja diputuskan tidak boleh menyisakan halaman
    kosong yang tidak dapat ditinggalkan."""
    at = _render(tmp_path, 3, open_id=999)          # tidak ada di antrean
    tables = [e.proto.body for e in at.get("html") if "ids-tbl" in e.proto.body]
    assert tables, "tidak kembali ke daftar"


def test_the_queue_states_how_many_it_shows(tmp_path):
    at = _render(tmp_path, 25)
    captions = " ".join(c.value for c in at.caption)
    assert "25" in captions, captions          # totalnya dinyatakan
    assert str(sr.PAGE_SIZE) in captions       # dan berapa yang tampil


def test_the_honesty_notes_are_shown_on_both_the_list_and_the_detail(tmp_path):
    """Peringatan "pemeriksaannya statis, keputusannya manusia" paling perlu
    terbaca di tempat keputusan diambil — yaitu pada detailnya."""
    for open_id in (None, 1):
        at = _render(tmp_path, 3, open_id=open_id)
        text = " ".join(m.value for m in at.markdown)
        assert "statis" in text, open_id
