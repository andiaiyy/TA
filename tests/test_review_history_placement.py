"""Riwayat tinjauan tinggal di tab "Riwayat versi" — dan HANYA di sana.

Sebelumnya ia digambar di ujung tab "Menunggu tinjauan". Itu tempat orang
datang untuk MEMUTUSKAN; yang sudah diputuskan hanya memanjangkan halaman di
sana, dan hilang dari tempat orang benar-benar mencarinya — yaitu bersama
riwayat versi, yang menjawab pertanyaan yang sama: "apa yang sudah terjadi".

Yang dijaga bukan tata letaknya melainkan dua sifat: riwayat tinjauan tergambar
di SATU tab saja, dan tab itu tetap menggambarnya walaupun belum ada satu pun
pipeline terdaftar — riwayat tinjauan berbicara tentang PENGAJUAN, bukan versi,
jadi ia tidak boleh ikut hilang ketika registry masih kosong.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from database.migration import apply_migrations
from database.models import (
    KIND_PIPELINE, SUBMISSION_APPROVED, SUBMISSION_PENDING,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

HEADING = "Riwayat tinjauan"

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
{extra}
import ui.views.contribute as c
c.render()
'''


def _seed(tmp_path, *, decided: int) -> str:
    """Basis data dengan `decided` pengajuan yang SUDAH diputuskan.

    Satu pengajuan pending selalu ada, supaya tab "Menunggu tinjauan" punya
    isi — kalau ia kosong, "riwayat tidak tergambar di sana" menjadi klaim
    yang benar karena alasan yang salah.
    """
    db = tmp_path / "hist.db"
    apply_migrations(str(db))
    conn = sqlite3.connect(str(db))
    try:
        rows = [(SUBMISSION_PENDING, "menunggu")]
        rows += [(SUBMISSION_APPROVED, f"sudah{i}") for i in range(decided)]
        for index, (status, name) in enumerate(rows):
            folder = tmp_path / f"pkg_{index}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "p.py").write_text(PKG, encoding="utf-8")
            meta = {"entry_filename": "p.py", "class_name": "DemoPipeline",
                    "name": name, "dataset_type": "HIKARI2021"}
            conn.execute(
                """INSERT INTO submissions
                   (kind, status, submitted_by, submitted_at, original_filename,
                    stored_path, file_hash, file_size, metadata_json,
                    validation_json, reviewed_by, reviewed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (KIND_PIPELINE, status, "andi", f"2026-01-{index + 1:02d}",
                 "p.py", str(folder), f"{index:064d}", 100, json.dumps(meta),
                 json.dumps({"valid": True}),
                 "boss" if status != SUBMISSION_PENDING else None,
                 "2026-02-01T00:00:00" if status != SUBMISSION_PENDING else None))
        conn.commit()
    finally:
        conn.close()
    return str(db)


def _render(tmp_path, section: str | None, *, decided: int = 2):
    from streamlit.testing.v1 import AppTest

    import config.settings as settings
    import database.db as dbmod

    db = _seed(tmp_path, decided=decided)
    saved = (dbmod.DB_PATH, settings.DB_PATH)
    try:
        extra = ("" if section is None
                 else f'st.session_state["_mp_section"] = {section!r}')
        script = tmp_path / f"app_{section or 'pending'}.py"
        script.write_text(
            _APP.format(repo=str(REPO_ROOT), db=db, admin=ADMIN, extra=extra),
            encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        dbmod.DB_PATH, settings.DB_PATH = saved


def _drawn(at) -> bool:
    text = " ".join(m.value for m in at.markdown)
    html = " ".join(e.proto.body for e in at.get("html"))
    return HEADING in text or HEADING in html


def test_the_review_history_lives_only_in_the_version_history_tab(tmp_path):
    seen = {name: _drawn(_render(tmp_path, name))
            for name in (None, "Aktif", "Riwayat versi")}
    assert seen == {None: False, "Aktif": False, "Riwayat versi": True}, seen


def test_the_queue_tab_still_shows_the_queue(tmp_path):
    """Penjaga anti-hampa: kalau tab antrean kosong, test di atas benar karena
    alasan yang salah."""
    import tests.grid_probe as grid_probe

    at = _render(tmp_path, None)
    assert grid_probe.count(at) == 1
    assert grid_probe.rows(at), "antrean tidak menggambar satu baris pun"


def test_the_review_history_survives_an_empty_registry(tmp_path):
    """Belum ada pipeline TERDAFTAR bukan berarti belum ada pengajuan yang
    diputuskan — keduanya hal yang berbeda, dan riwayat versi yang kosong tidak
    boleh ikut menelan riwayat tinjauan."""
    at = _render(tmp_path, "Riwayat versi")
    text = " ".join(m.value for m in at.markdown)
    assert HEADING in text, text[:300]


def test_the_history_table_names_the_decided_submissions(tmp_path):
    """Bukan sekadar judulnya yang muncul — isinya benar-benar tergambar."""
    at = _render(tmp_path, "Riwayat versi", decided=2)
    html = " ".join(e.proto.body for e in at.get("html"))
    assert "sudah0" in html and "sudah1" in html, html[:400]
    assert "menunggu" not in html, "yang belum diputuskan ikut masuk riwayat"


def test_the_comparison_view_replaces_the_whole_section(tmp_path):
    """Perbandingan versi MENGGANTIKAN isi tab, termasuk riwayat tinjauan —
    aturan "satu hal pada satu waktu" yang sama dengan bagian lain."""
    src = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    body = src.split("def render_history(")[1].split("\ndef ")[0]
    assert "_render_version_history()" in body
    assert "_render_review_history()" in body
    version = src.split("def _render_version_history(")[1].split("\ndef ")[0]
    assert "_render_compare(rows, name)\n        return True" in version


def test_the_status_labels_come_from_one_place():
    """Petanya tinggal di komponen, bukan di penyajinya.

    Ketika tabel "Pengajuan saya" masih ada, dua halaman memakainya. Tabel itu
    kini dibuang dan tinggal satu pemakai — tetapi tempatnya TIDAK ditarik
    kembali ke penyaji: `history_rows` menerimanya sebagai parameter, jadi di
    situlah ia memang bertempat.
    """
    contribute = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "_STATUS_LABEL_KEYS" not in contribute

    from ui.components import submission_review as sr

    assert set(sr.STATUS_LABEL_KEYS.values()) == {
        "ap.sub_pending", "ap.sub_approved", "ap.sub_rejected"}

    manage = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    assert "status_label=sr.status_label" in manage
