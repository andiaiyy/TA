"""Empat keterangan halaman Run Experiment berkumpul di satu modal ber-tab.

Dataset, research pipeline, algoritma, dan berkas konfigurasi masing-masing
punya expander sendiri di sepanjang halaman, dan DUA di antaranya terbuka
otomatis. Akibatnya alur pilih dataset → pilih research → pilih algoritma →
jalankan terus terputus oleh blok keterangan yang hanya dibaca sesekali.

Keempatnya pindah ke satu modal dengan empat tab, dibuka oleh satu tombol hitam
di judul halaman. Yang dijaga berkas ini ada tiga, dan ketiganya harus benar
sekaligus: **halamannya menjadi alur**, **tidak satu baris pun hilang**, dan
**tab yang belum dapat diisi tetap ada** sambil menyebut apa yang harus dipilih
lebih dulu. Tab yang hilang-timbul memindahkan posisi tab lain setiap kali
pengguna maju satu langkah.

Tampilan KATALOG sengaja tidak mendapat tombol itu: tiap blok research di sana
sudah punya tombol "Detail" sendiri.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import ui.views.run_experiment as rx
from ui.components import dialogs as dlg, theme

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_SRC = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
    encoding="utf-8")


def _script(preset: dict) -> str:
    return (
        "import os, sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        f"os.chdir(r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        + "".join(f"st.session_state[{k!r}] = {v!r}\n" for k, v in preset.items())
        + "from ui.views.run_experiment import render\nrender()\n"
    )


def _run(tmp_path, preset):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "run_page.py"
    script.write_text(_script(preset), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    at.run()
    return at


def _teks(at) -> list[str]:
    keluar: list[str] = []
    for grup in (at.markdown, at.caption, at.code, at.info, at.success,
                 at.warning, at.error):
        keluar += [e.value for e in grup]
    keluar += [str(e.proto.body) for e in at.get("html")]
    return keluar


def _small_dataset() -> str:
    kecil = [p for p, _ in rx._all_dataset_options() if "trafik_kampus" in p]
    if not kecil:
        pytest.skip("dataset kontribusi kecil tidak tersedia")
    return kecil[0]


def _execute_preset(with_dataset: bool = True) -> dict:
    preset = {"_current_page": "Run Experiment", "_run_view": "execute"}
    if with_dataset:
        preset["dataset_select"] = _small_dataset()
    return preset


# ── Halamannya menjadi alur ──────────────────────────────────────────────

@pytest.mark.parametrize("expander", [
    't("re.dlg_dataset_detail")',
    '"Tentang Research Pipeline (Read-Only)"',
    '"Pipeline Detail (Read-Only)"',
    '"Pipeline Config Viewer',
])
def test_the_four_expanders_are_gone_from_the_page(expander):
    assert f"st.expander({expander}" not in RUN_SRC, expander


def test_the_page_is_far_shorter_than_it_was(tmp_path):
    """Dahulu 26 elemen tergambar sebelum pengguna menyentuh apa pun."""
    at = _run(tmp_path, _execute_preset())

    assert at.exception is None or not at.exception
    assert len(_teks(at)) <= 8, _teks(at)


def test_the_button_lives_beside_the_page_title():
    kepala = RUN_SRC.split("def render():")[1].split(chr(10) + "def ")[0]

    assert 'key="run_info"' in kepala
    assert 't("ap.btn_info")' in kepala
    assert "_request_run_info()" in kepala


def test_the_catalog_view_gets_no_second_detail_button(tmp_path):
    """Tiap blok research di katalog sudah punya tombol "Detail" sendiri."""
    at = _run(tmp_path, {"_current_page": "Run Experiment"})

    assert at.exception is None or not at.exception
    assert not [b for b in at.button if b.key == "run_info"]


def test_the_execute_view_does_get_it(tmp_path):
    at = _run(tmp_path, _execute_preset(with_dataset=False))

    assert [b for b in at.button if b.key == "run_info"]


# ── Satu modal, empat tab ────────────────────────────────────────────────

def test_the_modal_has_four_tabs_in_a_fixed_order(tmp_path):
    from ui.i18n.core import lookup

    at = _run(tmp_path, _execute_preset())
    at = at.button(key="run_info").click().run()

    label = [tab.label for tab in at.get("tab")]
    urutan = [lookup(k, "id") for k in ("re.tab_dataset", "re.tab_research",
                                        "re.tab_algorithm", "re.tab_files")]
    assert label[:4] == urutan, label


def test_every_tab_stays_visible_before_its_choice_is_made(tmp_path):
    """Tab yang disembunyikan memindahkan posisi tab lain saat pengguna maju."""
    at = _run(tmp_path, _execute_preset(with_dataset=False))
    at = at.button(key="run_info").click().run()

    assert len(at.get("tab")) == 4


@pytest.mark.parametrize("key", ["re.detail_pick_dataset_first",
                                 "re.detail_pick_research_first",
                                 "re.detail_pick_algorithm_first"])
def test_an_unfilled_tab_says_what_to_choose_first(tmp_path, key):
    from ui.i18n.core import lookup

    at = _run(tmp_path, _execute_preset(with_dataset=False))
    at = at.button(key="run_info").click().run()

    assert lookup(key, "id") in " ".join(_teks(at))


# ── Tidak satu baris pun hilang ──────────────────────────────────────────

@pytest.mark.parametrize("penanda", [
    "Preview (beberapa baris pertama):",        # tab Dataset
    "Penelitian sumber",                        # tab Research Pipeline
    "Persyaratan Dataset",                      # sub-blok di tab Research
])
def test_the_modal_carries_what_the_expanders_carried(tmp_path, penanda):
    at = _run(tmp_path, _execute_preset())
    at = at.button(key="run_info").click().run()

    assert penanda in " ".join(_teks(at)), penanda


@pytest.mark.parametrize("nama, penanda", [
    ("_detail_dataset", "_dataset_preview("),
    ("_detail_research", "research_about_groups("),
    ("_detail_algorithm", 'st.json(info["fixed_params"])'),
    ("_detail_files", "render_file_browser("),
])
def test_no_tab_became_an_empty_shell(nama, penanda):
    badan = RUN_SRC.split(f"def {nama}(")[1].split(chr(10) + "def ")[0]

    assert penanda in badan, nama


def test_the_navigation_hint_points_at_the_tab_not_at_a_row_below():
    """Kalimat lama berbunyi "Pilih algoritma DI BAWAH…" — benar ketika ia
    expander di halaman, keliru di dalam modal. Isinya dipertahankan, arahnya
    dibetulkan."""
    from ui.i18n.core import lookup

    assert "di bawah" not in lookup("re.detail_see_algorithm_tab", "id").lower()
    assert "Algoritma" in lookup("re.detail_see_algorithm_tab", "id")
    assert "re.detail_see_algorithm_tab" in RUN_SRC


# ── Siklus hidup & gaya ──────────────────────────────────────────────────

def test_the_flag_is_registered_so_page_changes_clear_it():
    assert dlg.RUN_INFO_KEY in dlg.DIALOG_KEYS
    assert len(set(dlg.DIALOG_KEYS)) == len(dlg.DIALOG_KEYS)


def test_the_body_is_decorated_once_at_module_level():
    assert hasattr(rx, "_run_info_dialog")
    assert "dlg.RUN_INFO_KEY" in RUN_SRC


def test_the_dialog_is_called_from_the_main_flow_only():
    penjaga = RUN_SRC.split("def _maybe_render_run_info(")[1].split(
        chr(10) + "def ")[0]
    assert "_run_info_dialog()" in penjaga

    panggilan = [b for b in RUN_SRC.splitlines()
                 if "_run_info_dialog()" in b
                 and not b.lstrip().startswith("def ")]
    assert len(panggilan) == 1, panggilan


def test_the_opener_follows_the_request_convention():
    """Aturan `dialogs.py`: pembuka yang dibungkus fungsi sendiri harus bernama
    `request_*`, supaya pemeriksa "flag tidak di-set di luar blok tombol" dapat
    mengenalinya."""
    assert "def _request_run_info(" in RUN_SRC
    assert "def _open_run_info(" not in RUN_SRC


def test_closing_clears_the_flag(monkeypatch):
    state = {dlg.RUN_INFO_KEY: True}
    monkeypatch.setattr(dlg.st, "session_state", state, raising=False)
    monkeypatch.setattr(rx.st, "rerun", lambda: None)

    rx._close_run_info()

    assert dlg.RUN_INFO_KEY not in state


def test_the_button_is_painted_black_by_the_shared_rule():
    assert "run_info" in theme.DARK_BTN_SCOPES
    assert ('[class*="st-key-run_info"] .stButton > button'
            in theme.stylesheet())


@pytest.mark.parametrize("key", ["re.dlg_details", "re.tab_dataset",
                                 "re.tab_research", "re.tab_algorithm",
                                 "re.tab_files", "re.detail_pick_dataset_first",
                                 "re.detail_pick_research_first",
                                 "re.detail_pick_algorithm_first",
                                 "re.detail_no_info",
                                 "re.detail_see_algorithm_tab"])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


@pytest.mark.parametrize("key", ["re.tab_dataset", "re.tab_research",
                                 "re.tab_algorithm", "re.tab_files"])
def test_the_tab_labels_stay_short_single_line_phrases(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        label = lookup(key, lang)
        assert chr(10) not in label
        assert len(label) <= 20, (key, lang, label)
