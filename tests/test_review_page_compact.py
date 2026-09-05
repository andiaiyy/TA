"""Halaman peninjauan satu pengajuan: padat, dan warnanya berarti.

Sebelum perubahan ini halaman itu memuat, terukur: 16 blok markdown, 6 tombol
— **dua di antaranya tombol kembali** — 3 expander bersarang, dan dua paragraf
peringatan, semuanya berselang-seling. Tidak ada tempat yang jelas untuk
memulai maupun mengakhiri.

Yang dijaga di sini bukan angkanya melainkan sifat-sifat yang membuat bentuk
ini dipilih:

* **satu tombol kembali**, dan selalu yang paling dalam;
* **tanpa expander** — sebuah expander per berkas berarti peninjau membuka satu
  per satu untuk tahu ada temuan atau tidak, padahal justru itu yang ia cari;
* **dua zona yang terbedakan** — yang dibaca, dan yang dikerjakan;
* **warna menandai keadaan, bukan menghias** — dan tidak pernah menjadi
  satu-satunya pembawa keterangan.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from database.migration import apply_migrations
from database.models import KIND_PIPELINE, SUBMISSION_PENDING
from ui.components import review_style as rp

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")
THEME_SRC = (REPO_ROOT / "ui" / "components" / "theme.py").read_text(
    encoding="utf-8")

PKG = '''
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"dataset_type": "HIKARI2021", "algorithm": "Demo"}
'''

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
st.session_state["_contrib_review_open"] = 1
import ui.views.contribute as c
c.render()
'''


def _render(tmp_path):
    from streamlit.testing.v1 import AppTest

    import config.settings as settings
    import database.db as dbmod

    db = tmp_path / "rev.db"
    apply_migrations(str(db))
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "p.py").write_text(PKG, encoding="utf-8")
    (folder / "helper.py").write_text("X = 1\n", encoding="utf-8")
    meta = {"entry_filename": "p.py", "class_name": "DemoPipeline",
            "name": "Demo",
            "declared_schema": {"label_column": "attack",
                                "expected_columns": ["a", "b"],
                                "file_format": "csv"}}
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json,
                validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (KIND_PIPELINE, SUBMISSION_PENDING, "andi", "2026-01-01", "p.py",
             str(folder), "a" * 64, 100, json.dumps(meta),
             json.dumps({"valid": True})))
        conn.commit()
    finally:
        conn.close()

    saved = (dbmod.DB_PATH, settings.DB_PATH)
    try:
        script = tmp_path / "app.py"
        script.write_text(
            _APP.format(repo=str(REPO_ROOT), db=str(db), admin=ADMIN),
            encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        dbmod.DB_PATH, settings.DB_PATH = saved


def _markup(at) -> str:
    return " ".join(m.value for m in at.markdown)


# ── Satu tombol kembali ──────────────────────────────────────────────────

def test_the_detail_page_has_exactly_one_back_button(tmp_path):
    """Dua tombol kembali bertumpuk dengan tujuan berbeda tidak memberi tahu
    pembacanya yang mana yang ia maksud."""
    at = _render(tmp_path)
    backs = [b.label for b in at.button if "kembali" in b.label.lower()]
    assert len(backs) == 1, backs


def test_the_outer_back_button_returns_when_no_detail_is_open():
    """Penjaga anti-hampa: tombol luar tidak dibuang, hanya ditahan selagi ada
    tampilan yang lebih dalam."""
    body = CONTRIB_SRC.split("def render()")[1]
    assert "if not _detail_is_open():" in body
    assert 't("ap.btn_back")' in body


def test_both_owners_are_asked_about_their_own_state():
    """Tidak ada daftar nama kunci kedua yang bisa ketinggalan."""
    body = CONTRIB_SRC.split("def _detail_is_open(")[1].split(chr(10) + "def ")[0]
    assert "_OPEN_KEY" in body
    assert "mp.detail_open()" in body

    manage = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    owner = manage.split("def detail_open(")[1].split(chr(10) + "def ")[0]
    for key in ("_OPEN_PIPELINE_KEY", "_EDIT_KEY", "_COMPARE_KEY"):
        assert key in owner, key


# ── Tanpa expander ───────────────────────────────────────────────────────

def test_the_detail_page_draws_no_expander(tmp_path):
    at = _render(tmp_path)
    assert not at.get("expander"), [e for e in at.get("expander")]


def test_the_findings_are_visible_without_opening_anything(tmp_path):
    """Justru temuan itulah yang dicari peninjau — menyembunyikannya di balik
    expander membuat ia membuka setiap berkas satu per satu."""
    at = _render(tmp_path)
    text = _markup(at)
    assert "get_info() mengembalikan dict" in text        # temuan WARN
    assert "Temuan ada di baris" in text


def test_the_code_of_every_file_is_still_shown(tmp_path):
    """Dua berkas diunggah; keduanya harus terbaca."""
    at = _render(tmp_path)
    assert len(at.get("code")) == 2


# ── Dua kalimat yang dibuang ─────────────────────────────────────────────

def test_the_two_standing_notes_are_gone(tmp_path):
    at = _render(tmp_path)
    text = _markup(at)
    assert "Pemeriksaan bersifat" not in text
    assert "Menyunting membuat" not in text
    assert "STATIC_CHECK_NOTE_KEY" not in CONTRIB_SRC
    assert "NEW_VERSION_NOTE_KEY" not in CONTRIB_SRC


def test_the_consequence_of_approving_is_still_stated(tmp_path):
    """Yang dibuang dua kalimat itu — BUKAN kejujuran tentang akibat menyetujui,
    yang justru dibaca tepat sebelum tombolnya ditekan."""
    at = _render(tmp_path)
    assert "langsung dapat dijalankan" in _markup(at)


# ── Dua zona ─────────────────────────────────────────────────────────────

def test_the_page_separates_what_is_read_from_what_is_done(tmp_path):
    at = _render(tmp_path)
    text = _markup(at)
    assert "ids-zone-read" in text
    assert "ids-zone-work" in text
    assert text.index("ids-zone-read") < text.index("ids-zone-work")


def test_the_decision_zone_holds_the_controls_that_change_things(tmp_path):
    at = _render(tmp_path)
    labels = {b.label for b in at.button}
    assert {"Setujui", "Tolak"} <= labels
    assert at.selectbox                       # dataset uji
    assert at.text_input                      # catatan tinjauan


def test_an_unknown_zone_is_still_drawn():
    """Judul yang lenyap lebih membingungkan daripada judul tanpa gaya."""
    import streamlit as st

    seen = []
    original = st.markdown
    st.markdown = lambda html, **k: seen.append(str(html))
    try:
        rp.zone_heading("entah", "Judulnya")
    finally:
        st.markdown = original
    assert seen and "Judulnya" in seen[0]


# ── Warna yang berarti ───────────────────────────────────────────────────

def test_the_verdict_decides_the_state(tmp_path):
    assert rp.verdict_state("bersih") == "ok"
    assert rp.verdict_state("peringatan") == "warn"
    assert rp.verdict_state("bermasalah") == "bad"


def test_an_unknown_verdict_is_never_treated_as_clean():
    """Menganggap yang tak dikenal sebagai bersih adalah kesalahan yang
    menutupi masalah."""
    assert rp.verdict_state("entah") == "warn"
    assert rp.verdict_state("") == "warn"
    assert rp.verdict_state(None) == "warn"


def test_the_header_carries_the_state_into_the_markup(tmp_path):
    at = _render(tmp_path)
    text = _markup(at)
    assert "ids-rv-head" in text
    assert "ids-rv-warn" in text              # paket ini lolos DENGAN peringatan


def test_colour_is_never_the_only_carrier_of_meaning(tmp_path):
    """Halaman harus tetap terbaca tanpa melihat warna sama sekali."""
    at = _render(tmp_path)
    text = _markup(at)
    assert "lolos dengan peringatan" in text  # keadaannya TERTULIS, bukan cuma
                                              # ditandai warna


@pytest.mark.parametrize("state", ["ok", "warn", "bad"])
def test_every_state_has_a_style(state):
    assert f".ids-rv-{state}" in THEME_SRC


def test_the_states_reuse_the_colours_already_in_use():
    """"Merah" harus berarti hal yang sama di seluruh aplikasi."""
    assert "rgba(46,160,67" in THEME_SRC      # hijau, sama dengan diff-add
    assert "rgba(200,70,70" in THEME_SRC      # merah, sama dengan chip rusak
    assert "rgba(200,150,60" in THEME_SRC     # kuning, sama dengan chip warn


def test_the_tints_are_translucent_so_both_themes_work():
    """Rona beralfa rendah menjadi pastel di tema terang dan rona tipis di tema
    gelap — satu definisi, bukan dua."""
    block = THEME_SRC.split(".ids-rv-ok")[1].split(".ids-zone")[0]
    assert "rgba(" in block
    assert "#" not in block                   # tidak ada warna pekat
