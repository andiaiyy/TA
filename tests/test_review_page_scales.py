"""Halaman peninjauan tidak lagi tumbuh mengikuti jumlah berkas.

Terukur sebelum perubahan ini, dengan menggambar halaman detail untuk paket
berisi 1, 2, 5, dan 10 berkas:

    berkas   markdown   karakter   blok kode   unduh
         1         19      1.716           1       1
         2         28      2.567           2       2
         5         55      5.120           5       5
        10        100      9.379          10      10

**+9 blok markdown, +851 karakter, +1 blok kode setinggi 320px, dan +1 tombol
unduh — per berkas.** Dari sembilan blok itu, enam adalah daftar pemeriksaan,
dan LIMA di antaranya bertuliskan "lolos": baris yang memberi tahu bahwa tidak
ada yang salah, sepuluh kali.

Dua perubahan, dan keduanya harus ada:

* **yang lolos jadi satu angka** — jumlahnya tetap disebut, perinciannya tidak;
* **daftar berkas jadi TABEL** yang barisnya dipilih, lalu satu berkas dibaca.

Yang kedua bukan expander yang dahulu dibuang: expander menyembunyikan hasil
periksa sampai tiap berkas dibuka satu per satu, sedangkan tabel menampilkan
hasil SELURUH berkas sekaligus dalam satu kolom berwarna.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import tests.grid_probe as grid_probe
from database.migration import apply_migrations
from database.models import KIND_PIPELINE, SUBMISSION_PENDING
from ui.components import submission_review as sr

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")

PKG = '''
from pipelines.base import BasePipeline


class Demo%dPipeline(BasePipeline):
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


def _render(tmp_path, n_files: int):
    """Halaman detail sebuah pengajuan berisi ``n_files`` berkas.

    Hash-nya dibuat UNIK per pemanggilan: `_reviewed_package` di-cache dengan
    kunci (id, file_hash) dan cache-nya milik PROSES, bukan milik test. Hash
    yang sama membuat dua pengukuran memakai hasil yang sama — dan hash
    berpola sederhana bertabrakan dengan berkas test lain yang memakai pola
    serupa, sehingga test ini lulus sendirian tetapi gagal di suite penuh.
    """
    import uuid
    from streamlit.testing.v1 import AppTest

    import config.settings as settings
    import database.db as dbmod

    db = tmp_path / f"s{n_files}.db"
    apply_migrations(str(db))
    folder = tmp_path / f"pkg{n_files}"
    folder.mkdir()
    for i in range(n_files):
        (folder / f"f{i}.py").write_text(PKG % i, encoding="utf-8")
    meta = {"entry_filename": "f0.py", "class_name": "Demo0Pipeline",
            "name": "Demo",
            "declared_schema": {"label_column": "a", "expected_columns": ["a"],
                                "file_format": "csv"}}
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json,
                validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (KIND_PIPELINE, SUBMISSION_PENDING, "andi", "2026-01-01", "f0.py",
             str(folder), uuid.uuid4().hex * 2, 100, json.dumps(meta),
             json.dumps({"valid": True})))
        conn.commit()
    finally:
        conn.close()

    saved = (dbmod.DB_PATH, settings.DB_PATH)
    try:
        script = tmp_path / f"app{n_files}.py"
        script.write_text(
            _APP.format(repo=str(REPO_ROOT), db=str(db), admin=ADMIN),
            encoding="utf-8")
        at = AppTest.from_file(str(script), default_timeout=900)
        at.run()
        assert at.exception is None or not at.exception, at.exception
        return at
    finally:
        dbmod.DB_PATH, settings.DB_PATH = saved


def _weight(at) -> dict:
    """Seberapa "berat" halaman ini — dalam satuan yang benar-benar dibaca."""
    md = [m.value for m in at.markdown]
    return {
        "markdown": len(md),
        "karakter": sum(len(x) for x in md
                        if not x.lstrip().startswith("<style")),
        "kode": len(at.get("code")),
        "unduh": len(at.get("download_button")),
    }


# ── Pertumbuhannya datar ─────────────────────────────────────────────────

def test_ten_files_weigh_about_the_same_as_one(tmp_path):
    """Inti perubahan ini, diukur — bukan diperkirakan."""
    one = _weight(_render(tmp_path, 1))
    ten = _weight(_render(tmp_path, 10))

    assert ten["kode"] == one["kode"] == 1
    assert ten["unduh"] == one["unduh"] == 1
    assert ten["markdown"] == one["markdown"]
    # Selisih karakternya hanya angka jumlah berkas ("1" menjadi "10").
    assert ten["karakter"] - one["karakter"] < 20, (one, ten)


@pytest.mark.parametrize("n_files", [1, 2, 5, 10])
def test_every_file_still_appears_in_the_table(tmp_path, n_files):
    """Ringkas TIDAK boleh berarti ada berkas yang hilang."""
    at = _render(tmp_path, n_files)
    assert grid_probe.count(at) == 1
    assert len(grid_probe.rows(at)) == n_files


def test_the_table_shows_each_files_check_result(tmp_path):
    """Justru inilah yang tidak dapat dilakukan expander: hasil SELURUH berkas
    terbaca sekaligus, tanpa membuka satu pun."""
    at = _render(tmp_path, 5)
    rows = grid_probe.rows(at)
    assert all(r["Hasil periksa"] for r in rows)
    assert all("pemeriksaan" in r["Hasil periksa"] for r in rows)


def test_the_check_result_column_is_coloured(tmp_path):
    at = _render(tmp_path, 3)
    options = grid_probe.options(at)
    column = next(c for c in options["columnDefs"]
                  if c["field"] == "Hasil periksa")
    assert "cellStyle" in column


# ── Yang lolos jadi satu angka ───────────────────────────────────────────

def _entry(*statuses):
    return {"report": {"checks": [{"status": s, "name": f"c{i}",
                                   "message": "m"}
                                  for i, s in enumerate(statuses)]}}


def test_the_tally_counts_what_ran():
    got = sr.check_tally(_entry("pass", "pass", "warn", "fail"))
    assert got == {"total": 4, "passed": 2, "warned": 1, "failed": 1}


def test_an_entry_without_a_report_counts_zero():
    assert sr.check_tally({}) == {"total": 0, "passed": 0, "warned": 0,
                                  "failed": 0}
    assert sr.check_tally(None)["total"] == 0


def test_only_the_notable_checks_are_listed():
    notable = sr.notable_checks(_entry("pass", "warn", "pass", "fail"))
    assert [c["status"] for c in notable] == ["fail", "warn"]


def test_failures_come_before_warnings():
    """Kegagalan menentukan boleh-tidaknya disetujui; peringatan hanya perlu
    dibaca."""
    notable = sr.notable_checks(_entry("warn", "fail", "warn"))
    assert notable[0]["status"] == "fail"


def test_a_clean_file_lists_nothing():
    assert sr.notable_checks(_entry("pass", "pass")) == []


def test_the_count_is_still_stated(tmp_path):
    """Menyembunyikan perinciannya tanpa menyebut berapa yang berjalan akan
    terbaca seperti tidak diperiksa sama sekali."""
    at = _render(tmp_path, 1)
    text = " ".join(m.value for m in at.markdown)
    assert "pemeriksaan" in text
    assert "6 pemeriksaan" in text          # jumlah nyata, bukan kata "beberapa"


def test_the_passing_checks_are_no_longer_listed_one_by_one(tmp_path):
    at = _render(tmp_path, 1)
    text = " ".join(m.value for m in at.markdown)
    assert "sintaks Python" not in text     # lolos: tidak dirinci…
    assert "get_info() mengembalikan dict" in text   # …peringatan: dirinci


def test_the_upload_flow_keeps_its_own_full_listing():
    """Yang diubah HANYA kartu peninjauan. Di alur unggah daftar lengkapnya
    tinggal di dalam expander, tempat kontributor memeriksa berkasnya sendiri —
    dan di sana ia tidak menumpuk sepuluh kali."""
    body = CONTRIB_SRC.split("def _render_group(")[1].split(chr(10) + "def ")[0]
    assert "for c in checks:" in body       # masih mencetak SELURUHNYA


# ── Tiga zona ────────────────────────────────────────────────────────────

def test_the_page_has_three_zones_in_reading_order(tmp_path):
    at = _render(tmp_path, 2)
    text = " ".join(m.value for m in at.markdown)
    for zone in ("ids-zone-read", "ids-zone-test", "ids-zone-work"):
        assert zone in text, zone
    assert text.index("ids-zone-read") < text.index("ids-zone-test") \
        < text.index("ids-zone-work")


def test_the_trial_moved_out_of_the_decision_zone():
    """Menjalankan uji dan memutuskan adalah dua pekerjaan berbeda, dan judul
    zonanya dahulu hanya menyebut yang kedua."""
    card = CONTRIB_SRC.split("def _render_submission_review_card(")[1].split(
        chr(10) + "def ")[0]
    testing = card.split('t("ap.zone_testing")')[1].split(
        't("ap.zone_decision")')[0]
    assert "_render_trial_step(item, user, latest)" in testing

    decision = card.split('t("ap.zone_decision")')[1]
    assert "_render_trial_step" not in decision
    assert "action.approve" in decision or "Setujui" in decision


def test_the_decision_zone_is_marked_as_the_irreversible_one():
    """Uji coba boleh diulang; menyetujui tidak. Gayanya mengikuti akibatnya."""
    theme = (REPO_ROOT / "ui" / "components" / "theme.py").read_text(
        encoding="utf-8")
    work = theme.split(".ids-zone-work {{")[1].split("}}")[0]
    test = theme.split(".ids-zone-test {{")[1].split("}}")[0]
    assert "border-bottom-width: 2px" in work
    assert "border-bottom-width" not in test


@pytest.mark.parametrize("key", ["ap.zone_testing", "ap.zone_decision",
                                 "ap.zone_examined", "sr.checks_tally",
                                 "sr.checks_clean", "sr.checks_warned",
                                 "sr.checks_failed", "sr.col_file",
                                 "sr.col_role", "sr.col_size"])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── Berkas yang dibaca ───────────────────────────────────────────────────

def test_the_entry_point_is_read_first(tmp_path):
    """Berkas yang paling menentukan, dan halaman tanpa isi apa pun di bawah
    tabelnya terbaca seperti sesuatu yang gagal dimuat."""
    at = _render(tmp_path, 5)
    text = " ".join(m.value for m in at.markdown)
    assert "f0.py" in text


def test_the_file_state_follows_the_worst_finding():
    assert sr.file_state({"tally": {"total": 3, "failed": 1, "warned": 1}}) == "bad"
    assert sr.file_state({"tally": {"total": 3, "failed": 0, "warned": 2}}) == "warn"
    assert sr.file_state({"tally": {"total": 3, "failed": 0, "warned": 0}}) == "ok"


def test_a_file_with_no_checks_is_not_called_clean():
    """Tidak ada pemeriksaan bukan berarti bersih — itu berarti tidak tahu."""
    assert sr.file_state({"tally": {"total": 0}}) == "warn"
    assert sr.file_state({}) == "warn"
