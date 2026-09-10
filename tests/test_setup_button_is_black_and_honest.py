"""Tombol yang MENYIAPKAN dan tombol yang MENJALANKAN tidak lagi menyaru.

Empat tombol merah berdiri di jalur eksperimen, dan tiga di antaranya tidak
menjalankan apa pun: satu membuka modal pilih dataset, satu berpindah ke layar
eksekusi dari modal detail, satu berpindah ke layar eksekusi dari atas katalog.
Ketiganya berbunyi "Jalankan", sehingga janjinya lebih besar daripada yang
benar-benar terjadi. Yang keempat memanggil ``_run_with_status()`` dan memang
menjalankan pipelinenya.

Ketiganya kini hitam dan berbunyi "Siapkan Eksperimen". Yang keempat sengaja
TIDAK ikut: ia tetap merah dan tetap berkata menjalankan, karena warnanya ikut
memberi tahu bahwa yang berikutnya terjadi memakan waktu dan menulis hasil.
Sebuah tombol eksekusi yang berbunyi "siapkan" adalah label yang berbohong, dan
itu lebih buruk daripada label yang membosankan.

Dahulu ketiga-empatnya berbagi SATU kunci kamus, jadi mengganti kalimatnya
sekali akan ikut mengubah tombol eksekusi. Kuncinya dipecah, dan berkas ini
yang menjaga agar tidak menyatu lagi.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from ui.components import theme
from ui.i18n.core import lookup

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG_SRC = (REPO_ROOT / "ui" / "components" / "pipeline_catalog.py").read_text(
    encoding="utf-8")
RUN_SRC = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
    encoding="utf-8")
CSS = theme.stylesheet()

RUN_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
for key, value in (st.session_state.pop("_preset", None) or {{}}).items():
    st.session_state[key] = value
from ui.views.run_experiment import render
render()
'''


def _run_page(tmp_path, preset=None):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "run_page.py"
    script.write_text(RUN_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=600)
    if preset:
        at.session_state["_preset"] = preset
    at.run()
    return at


# ── Dua kunci, dua janji ─────────────────────────────────────────────────

def test_the_two_promises_have_two_keys():
    assert lookup("re.btn_setup", "id") != lookup("re.btn_run", "id")
    assert lookup("re.btn_setup", "en") != lookup("re.btn_run", "en")


@pytest.mark.parametrize("lang, teks", [("id", "Siapkan Eksperimen"),
                                        ("en", "Set up experiment")])
def test_the_setup_label_says_what_it_does(lang, teks):
    assert lookup("re.btn_setup", lang) == teks


@pytest.mark.parametrize("lang, teks", [("id", "Jalankan Eksperimen"),
                                        ("en", "Run Experiment")])
def test_the_run_label_is_left_alone(lang, teks):
    """Ia satu-satunya tombol yang benar-benar mengeksekusi."""
    assert lookup("re.btn_run", lang) == teks


@pytest.mark.parametrize("lang", ["id", "en"])
def test_the_new_label_is_a_short_single_line_phrase(lang):
    label = lookup("re.btn_setup", lang)

    assert chr(10) not in label
    assert len(label) <= 24, label


# ── Tombol mana memakai yang mana ────────────────────────────────────────

def test_the_three_setup_buttons_use_the_setup_key():
    """Blok katalog, modal detail, dan tombol di atas katalog."""
    blok = CATALOG_SRC.split('key=f"cat_run_{group[\'dataset_type\']}"')[0][-200:]
    assert 't("re.btn_setup")' in blok

    for kunci in ('key="_catalog_run"', 'key="_run_go"'):
        potongan = RUN_SRC.split(kunci)[0][-260:]
        assert 't("re.btn_setup")' in potongan, kunci


def test_the_execute_button_still_promises_execution():
    """Dijaga lewat apa yang DIPANGGILNYA, bukan lewat tempatnya di berkas."""
    blok = RUN_SRC.split('st.button(t("re.btn_run"), type="primary"')[1][:320]

    assert "_run_with_status(" in blok


def test_only_one_button_in_the_whole_app_runs_an_experiment():
    assert RUN_SRC.count('st.button(t("re.btn_run"), type="primary"') == 1
    assert CATALOG_SRC.count('re.btn_run"') == 0


# ── Hitam, dan hanya yang menyiapkan ─────────────────────────────────────

@pytest.mark.parametrize("scope", ["cat_run_", "_catalog_run", "_run_go"])
def test_every_setup_button_is_in_the_dark_scope(scope):
    assert scope in theme.DARK_BTN_SCOPES


def test_the_dark_rule_is_built_from_the_one_list():
    """Dua aturan kembar yang harus diingat untuk diubah bersama pasti berbeda
    sendiri suatu saat."""
    for scope in theme.DARK_BTN_SCOPES:
        assert f'[class*="st-key-{scope}"] .stButton > button' in CSS, scope
    # Satu deklarasi latar, bukan satu per cakupan.
    assert CSS.count("background-color: #111418") == 1


def test_the_dark_rule_sets_background_and_text_together():
    """Kontras yang berdiri sendiri: itulah sebab heksa boleh di sini."""
    blok = CSS.split("background-color: #111418")[1][:200]

    assert "color: #ffffff" in blok
    assert "border" in blok


def test_the_dark_hover_leaves_disabled_buttons_alone():
    sorot = [l for l in CSS.splitlines()
             if ":hover" in l and "st-key-" in l and ".stButton" in l]

    assert sorot
    for baris in sorot:
        assert ":not(:disabled)" in baris, baris


def test_the_button_that_runs_is_not_painted_black():
    """Merah pada aksi yang memakan waktu dan menulis hasil adalah keterangan,
    bukan sekadar gaya."""
    blok = RUN_SRC.split('st.button(t("re.btn_run"), type="primary"')[1][:320]
    kunci = re.findall(r'key="([^"]+)"', blok)

    for k in kunci:
        assert not any(k.startswith(s) for s in theme.DARK_BTN_SCOPES), k


# ── Lebarnya cukup untuk satu baris ──────────────────────────────────────

def test_the_catalog_button_is_wide_enough_for_the_new_label():
    lebar = float(theme.CATALOG_BTN_W.rstrip("rem"))

    assert theme.CATALOG_BTN_W.endswith("rem")
    assert lebar >= 11, theme.CATALOG_BTN_W


def test_the_two_catalog_action_columns_stay_equal():
    """Tinggi keduanya hanya sama bila lebarnya sama.

    Yang dibaca adalah `st.columns` TEPAT SEBELUM tombol blok katalog, bukan
    yang pertama di berkas: modul ini punya beberapa baris kolom lain.
    """
    sebelum = CATALOG_SRC.split('key=f"cat_run_{group[\'dataset_type\']}"')[0]
    rasio = sebelum.rsplit("st.columns([", 1)[1].split("])")[0]
    bagian = [b.strip() for b in rasio.split(",")]

    assert bagian[0] == bagian[1], rasio


# ── Yang benar-benar tergambar ───────────────────────────────────────────

def test_the_catalog_shows_the_setup_label(tmp_path):
    at = _run_page(tmp_path)
    label = [b.label for b in at.button]

    assert lookup("re.btn_setup", "id") in label
    assert lookup("re.btn_run", "id") not in label


def test_the_setup_label_does_not_follow_you_into_the_execute_view(tmp_path):
    """Sesudah berpindah, tidak ada lagi yang menawarkan "siapkan": yang
    tersisa di layar itu adalah menjalankan.

    Tombol jalankannya sendiri baru tergambar setelah dataset dipilih, jadi
    kontraknya dijaga `test_the_execute_button_still_promises_execution`, yang
    memeriksa apa yang DIPANGGIL tombol itu."""
    at = _run_page(tmp_path, {"_run_view": "execute"})
    label = [b.label for b in at.button]

    assert lookup("re.btn_setup", "id") not in label


def test_pressing_setup_moves_to_the_execute_view(tmp_path):
    import ui.views.run_experiment as rx

    at = _run_page(tmp_path)
    at.button(key="_run_go").click().run()

    assert at.exception is None or not at.exception
    assert at.session_state.filtered_state.get(rx._VIEW_KEY) == rx.VIEW_EXECUTE
