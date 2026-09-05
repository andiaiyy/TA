"""Panel kelola research pipeline di halaman Jalankan Eksperimen.

Halaman itu adalah tempat seseorang MELIHAT sebuah research pipeline dan
algoritmanya. Sampai perubahan ini, mematikan salah satunya berarti pergi ke
halaman lain, mencari pipeline yang sama di daftar berbeda, lalu kembali —
perjalanan yang tidak menambah pengaman apa pun.

Yang dijaga di sini adalah lapis TAMPILAN-nya: siapa yang melihatnya, apa yang
ditawarkan, dan — yang terpenting — bahwa menyembunyikan tombol tidak pernah
menjadi satu-satunya penghalang.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ui.components import research_admin_panel as panel

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_SRC = (REPO_ROOT / "ui" / "components"
             / "research_admin_panel.py").read_text(encoding="utf-8")
PAGE_SRC = (REPO_ROOT / "ui" / "views"
            / "run_experiment.py").read_text(encoding="utf-8")


# ── Label satu algoritma ─────────────────────────────────────────────────

def test_the_label_names_the_algorithm_its_version_and_its_state():
    label = panel.algorithm_label({"algorithm": "Random Forest", "version": 2,
                                   "active": True})
    assert "Random Forest" in label
    assert "v2" in label


def test_an_inactive_algorithm_reads_differently_from_an_active_one():
    """Keliru membaca "mati" sebagai "hidup" berakibat nyata: yang mati tidak
    dapat dipilih untuk eksperimen baru."""
    common = {"algorithm": "RF", "version": 1}
    assert (panel.algorithm_label({**common, "active": True})
            != panel.algorithm_label({**common, "active": False}))


def test_the_label_falls_back_to_the_package_name():
    label = panel.algorithm_label({"name": "paket", "version": 1,
                                   "active": True})
    assert "paket" in label


def test_building_a_label_reads_nothing(monkeypatch):
    """Ia dipanggil sekali per algoritma pada SETIAP penggambaran."""
    import sqlite3

    def _boom(*a, **k):
        raise AssertionError("label membuka basis data")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    panel.algorithm_label({"algorithm": "RF", "version": 1, "active": True})


# ── Siapa yang melihatnya ────────────────────────────────────────────────

def test_the_panel_is_drawn_only_for_a_research_admin():
    body = PANEL_SRC.split("def render(")[1].split(chr(10) + "def ")[0]
    assert "if not can_approve(user):" in body
    assert body.index("can_approve") < body.index("render_section")


def test_a_builtin_research_pipeline_offers_nothing_but_says_why():
    """Halaman yang diam-diam tidak menawarkan apa pun membuat orang mengira
    platformnya rusak."""
    body = PANEL_SRC.split("def _readonly_note(")[1].split(chr(10) + "def ")[0]
    assert "is_uploaded_research(dataset_type)" in body
    assert "re.msg_builtin_readonly" in body

    render = PANEL_SRC.split("def render(")[1].split(chr(10) + "def ")[0]
    assert "if _readonly_note(dataset_type):" in render
    assert "return" in render.split("_readonly_note(dataset_type):")[1][:40]


# ── Dua tingkat yang dibedakan ───────────────────────────────────────────

def test_both_levels_are_offered_and_they_are_different_buttons():
    assert "re.btn_research_off" in PANEL_SRC      # seluruh keluarga
    assert "re.btn_algorithm_off" in PANEL_SRC     # satu algoritma
    switch = PANEL_SRC.split("def _render_research_switch(")[1].split(
        chr(10) + "def ")[0]
    assert "dr.set_research_active(" in switch
    one = PANEL_SRC.split("def _render_algorithm(")[1].split(chr(10) + "def ")[0]
    assert "dr.set_pipeline_active(" in one


def test_the_last_live_algorithm_button_is_disabled_with_its_reason():
    """Alasan tombol nonaktif SELALU dinyatakan — tombol mati tanpa keterangan
    membuat pengguna menebak apa yang kurang."""
    one = PANEL_SRC.split("def _render_algorithm(")[1].split(chr(10) + "def ")[0]
    assert "last_active_algorithm_blocker" in one
    assert "disabled=bool(blocked)" in one
    assert "help=t(blocked) if blocked else None" in one


def test_deleting_is_confirmed_before_it_happens():
    """Menghapus membuang baris registry DAN berkasnya."""
    one = PANEL_SRC.split("def _render_algorithm(")[1].split(chr(10) + "def ")[0]
    assert "delete_blocker" in one                 # dan alasannya bila ditolak
    confirm = PANEL_SRC.split("def _render_delete_confirm(")[1].split(
        chr(10) + "def ")[0]
    assert "mp.delete_confirm" in confirm
    assert "delete_version(" in confirm


def test_an_unreadable_blocker_closes_the_gate_rather_than_opening_it():
    """"Tidak tahu apakah boleh" tidak pernah berarti "boleh"."""
    assert panel._safe(lambda _pid: (_ for _ in ()).throw(RuntimeError()),
                       "x") == "ap.err_gate_unreadable"
    assert panel._safe(lambda _pid: "", "x") == ""


# ── Tempatnya di halaman ─────────────────────────────────────────────────

def test_the_page_mounts_the_panel_for_the_selected_research():
    assert "from ui.components import research_admin_panel" in PAGE_SRC
    assert "research_admin_panel.render(" in PAGE_SRC


def test_the_panel_sits_between_the_read_only_facts_and_the_picker():
    """Urutan membacanya: kenali dulu, baru ubah, baru jalankan."""
    mount = PAGE_SRC.index("research_admin_panel.render(")
    facts = PAGE_SRC.index('"Tentang Research Pipeline (Read-Only)"')
    picker = PAGE_SRC.index('t("re.sec_algorithm")')
    assert facts < mount < picker


def test_the_page_never_calls_the_registry_writers_itself():
    """Aksinya tinggal di panel; halaman ini tetap tentang MENJALANKAN."""
    for writer in ("set_research_active(", "set_pipeline_active(",
                   "delete_version("):
        assert writer not in PAGE_SRC, writer


@pytest.mark.parametrize("key", ["re.sec_manage", "re.help_manage",
                                 "re.btn_research_off", "re.btn_research_on",
                                 "re.btn_algorithm_off", "re.btn_algorithm_on",
                                 "re.btn_delete_algorithm",
                                 "re.msg_builtin_readonly",
                                 "re.msg_edit_elsewhere",
                                 "re.lbl_algorithm_state"])
def test_every_panel_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


def test_the_panel_points_at_where_the_code_editor_actually_lives():
    """Menyunting kode menghasilkan VERSI BARU dan punya alur pemeriksaannya
    sendiri; menyalinnya ke sini akan melahirkan dua penyunting yang dapat
    berbeda perilaku."""
    from ui.i18n.core import lookup

    note = lookup("re.msg_edit_elsewhere", "id")
    assert "Add Pipeline & Dataset" in note
    assert "re.msg_edit_elsewhere" in PANEL_SRC
