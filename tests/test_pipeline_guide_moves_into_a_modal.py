"""Panduan unggah pipeline pindah ke modal, dan tidak kehilangan apa pun.

Panduannya panjang dengan sendirinya — diagram alur, tabel kontrak, dua daftar
modul (27 diizinkan, 25 ditolak), kerangka kode 19 baris, lima tab kontrak,
lima kesalahan umum, dan satu expander persyaratan lengkap. Seluruhnya berdiri
di ANTARA judul halaman dan pengunggah berkasnya, sehingga kontrol yang dicari
pengunggah selalu berada di bawah sepuluh ribu karakter keterangan.

Sekarang ia dibuka lewat satu tombol. Yang dijaga berkas ini ada dua, dan
keduanya harus benar sekaligus: **halamannya menjadi ringkas** dan **tidak satu
baris panduan pun hilang**. Memindahkan sambil diam-diam meringkas akan lolos
dari tes pertama dan justru itulah kegagalan yang paling mahal — panduan yang
hilang tidak terlihat hilang.

Ditambah siklus hidup modalnya. Bug "modal muncul sendiri" sudah dua kali
terjadi di aplikasi ini, dan sebabnya selalu sama: flag yang tidak dibersihkan.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import ui.components.instructions as ins
import ui.views.contribute as contrib
from ui.components import dialogs as dlg

CONTRIB_SRC = Path(contrib.__file__).read_text(encoding="utf-8")
THEME_SRC = Path(
    Path(contrib.__file__).resolve().parents[1] / "components" / "theme.py"
).read_text(encoding="utf-8")


def _flow() -> str:
    return CONTRIB_SRC.split("def _render_pipeline_flow(")[1].split(
        chr(10) + "def ")[0]


def _body() -> str:
    return CONTRIB_SRC.split("def _pipeline_info_body(")[1].split(
        chr(10) + "def ")[0]


class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Sink:
    """Menangkap teks; satu objek melayani `st` dan setiap kolomnya."""

    def __init__(self):
        self.teks: list[str] = []

    def markdown(self, s=None, **k): self.teks.append(str(s))
    def caption(self, s=None, **k): self.teks.append(str(s))
    def code(self, s=None, **k): self.teks.append(str(s))
    def write(self, s=None, **k): self.teks.append(str(s))
    def subheader(self, s=None, **k): self.teks.append(str(s))
    def button(self, label, **k):
        self.teks.append(str(label))
        return False

    def expander(self, *a, **k): return _Ctx()
    def container(self, **k): return _Ctx()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def tabs(self, labels, **k): return [_Ctx() for _ in labels]
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(n)]
    def divider(self, *a, **k): return None


def _rendered_panel() -> list[str]:
    """Seluruh teks yang digambar panel panduan, dipanggil langsung."""
    sink = _Sink()
    with patch.object(ins, "st", sink):
        ins.render_pipeline_instructions()
    return sink.teks


def _rendered_modal() -> list[str]:
    """Seluruh teks yang digambar BADAN MODAL."""
    sink = _Sink()
    with patch.object(ins, "st", sink), patch.object(contrib, "st", sink):
        contrib._pipeline_info_body()
    return sink.teks


# ── Halamannya menjadi ringkas ───────────────────────────────────────────

def test_the_page_no_longer_draws_the_guide_inline():
    flow = _flow()

    assert "_render_pipeline_requirements()" not in flow
    assert "render_pipeline_instructions" not in flow


def test_the_uploader_comes_before_anything_that_explains_it():
    """Yang dicari pengunggah adalah kontrolnya. Apa pun yang menerangkan
    boleh ada, asal tidak berdiri di depannya."""
    flow = _flow()
    sebelum = flow.split("st.file_uploader(")[0]

    for penjelas in ("_render_pipeline_requirements", "render_flow(",
                     "render_contract_docs", "render_mistakes",
                     "ap.note_metadata"):
        assert penjelas not in sebelum, penjelas


def test_the_page_offers_an_info_button():
    flow = _flow()

    assert 'key="contrib_info_pipeline"' in flow
    assert 't("ap.btn_info")' in flow
    assert "_request_pipeline_info()" in flow


def test_the_metadata_note_travelled_with_the_guide():
    assert 'st.markdown(t("ap.note_metadata"))' not in _flow()
    assert 'ap.note_metadata' in _body()


# ── Siklus hidup modalnya ────────────────────────────────────────────────

def test_the_flag_is_registered_so_page_changes_clear_it():
    assert dlg.PIPELINE_INFO_KEY in dlg.DIALOG_KEYS
    assert len(set(dlg.DIALOG_KEYS)) == len(dlg.DIALOG_KEYS)


def test_the_body_is_decorated_once_at_module_level():
    """`st.dialog` hanya ada di modul `st`, bukan pada hasil `st.columns()`."""
    assert hasattr(contrib, "_pipeline_info_dialog")
    assert "dlg.dialog_decorator(" in CONTRIB_SRC
    assert "dlg.PIPELINE_INFO_KEY" in CONTRIB_SRC
    # `dialog_decorator` SELALU memasang on_dismiss — itulah jalur keluar X/Esc
    # /klik-di-luar, yang paling sering terlupa bila `st.dialog` dipakai polos.
    assert "st.dialog(" not in CONTRIB_SRC


def test_the_dialog_is_called_from_the_main_flow_only():
    """Bukan dari dalam blok tombol, bukan dari dalam kolom — keduanya konteks
    yang tidak sah untuk membuka dialog."""
    penjaga = CONTRIB_SRC.split("def _maybe_render_pipeline_info(")[1].split(
        chr(10) + "def ")[0]
    assert "_pipeline_info_dialog()" in penjaga

    # Tidak dipanggil dari alur halaman — di sana ia berada di dalam kolom.
    assert "_pipeline_info_dialog()" not in _flow()
    # Dan tepat SATU panggilan di seluruh modul. Baris `def` jalur cadangan
    # Streamlit lama bukan panggilan, jadi ia tidak ikut dihitung.
    panggilan = [baris for baris in CONTRIB_SRC.splitlines()
                 if "_pipeline_info_dialog()" in baris
                 and not baris.lstrip().startswith("def ")]
    assert len(panggilan) == 1, panggilan


def test_the_button_only_writes_the_flag(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(dlg.st, "session_state", state, raising=False)

    contrib._request_pipeline_info()

    assert state[dlg.PIPELINE_INFO_KEY] is True


def test_closing_clears_the_flag(monkeypatch):
    state = {dlg.PIPELINE_INFO_KEY: True}
    monkeypatch.setattr(dlg.st, "session_state", state, raising=False)
    monkeypatch.setattr(contrib.st, "rerun", lambda: None)

    contrib._close_pipeline_info()

    assert dlg.PIPELINE_INFO_KEY not in state


def test_the_modal_carries_its_own_close_button():
    assert 'ap.btn_close_info' in _body()
    assert "_close_pipeline_info()" in _body()


def test_nothing_is_drawn_while_the_flag_is_down(monkeypatch):
    monkeypatch.setattr(dlg.st, "session_state", {}, raising=False)
    dipanggil = {"n": 0}
    monkeypatch.setattr(contrib, "_pipeline_info_dialog",
                        lambda: dipanggil.__setitem__("n", dipanggil["n"] + 1))

    contrib._maybe_render_pipeline_info()

    assert dipanggil["n"] == 0


def test_it_is_drawn_when_the_flag_is_up(monkeypatch):
    monkeypatch.setattr(dlg.st, "session_state",
                        {dlg.PIPELINE_INFO_KEY: True}, raising=False)
    dipanggil = {"n": 0}
    monkeypatch.setattr(contrib, "_pipeline_info_dialog",
                        lambda: dipanggil.__setitem__("n", dipanggil["n"] + 1))

    contrib._maybe_render_pipeline_info()

    assert dipanggil["n"] == 1


# ── Tidak satu baris pun hilang ──────────────────────────────────────────

def test_the_modal_loses_no_line_of_the_guide():
    """Pemindahan, bukan penyuntingan. Setiap baris yang dahulu tergambar di
    halaman harus tergambar di dalam modal — dibandingkan sebagai HIMPUNAN,
    bukan sekadar dihitung."""
    panel = _rendered_panel()
    modal = _rendered_modal()

    hilang = [baris for baris in panel if baris not in modal]

    assert hilang == [], hilang
    assert len(panel) >= 25          # panelnya memang sebesar itu


def test_the_modal_adds_the_note_and_the_close_button():
    panel = set(_rendered_panel())
    tambahan = [b for b in _rendered_modal() if b not in panel]

    from ui.i18n import t
    assert t("ap.note_metadata") in tambahan
    assert t("ap.btn_close_info") in tambahan


@pytest.mark.parametrize("bagian", [
    "ins.col_aspect",          # tabel kontrak
    "ins.static_check_note",   # catatan pemeriksaan statis
    "ins.expected_shape",      # kerangka
    "ins.contract_intro",      # dokumen kontrak (lima tab)
    "ins.mistakes_pipeline_title",
    "ins.modules_reasonable",  # expander persyaratan lengkap
])
def test_every_named_part_reaches_the_modal(bagian):
    from ui.i18n import t

    teks = " ".join(_rendered_modal())
    potongan = t(bagian).split("{")[0].strip()

    assert potongan and potongan in teks, bagian


def test_the_module_lists_still_come_from_the_validator():
    """Angkanya tidak boleh dipaku: panduan yang menyimpang dari aturan yang
    benar-benar ditegakkan lebih buruk daripada tidak ada panduan."""
    from orchestrator.pipeline_validator import (ALLOWED_MODULES,
                                                 FORBIDDEN_CALLS,
                                                 FORBIDDEN_MODULES)

    teks = " ".join(_rendered_modal())

    assert str(len(ALLOWED_MODULES)) in teks
    assert str(len(FORBIDDEN_MODULES)) in teks
    for modul in sorted(ALLOWED_MODULES)[:3]:
        assert modul in teks, modul
    for panggilan in sorted(FORBIDDEN_CALLS)[:3]:
        assert panggilan in teks, panggilan


# ── Tombolnya hitam, dan tetap terbaca ───────────────────────────────────

def test_the_button_is_black_with_its_own_contrast():
    """Aturan berkas tema adalah "tidak ada heksa", dan alasannya kontras yang
    hilang saat tema berganti. Tombol ini menetapkan latar DAN teksnya
    bersama-sama, jadi kontrasnya tidak bergantung latar halaman."""
    from ui.components import theme

    # Diperiksa pada stylesheet yang DIHASILKAN, bukan pada sumbernya:
    # selektornya kini dirakit dari `theme.DARK_BTN_SCOPES`, jadi sumbernya
    # tidak lagi memuat teks selektornya. Yang sampai ke peramban inilah yang
    # menentukan tombolnya terbaca atau tidak.
    css = theme.stylesheet()
    aturan = css.split("background-color: #111418")[1][:200]

    assert "color: #ffffff" in aturan
    assert "border" in aturan


def test_the_exception_is_written_down_where_the_rule_is():
    """Perkecualian yang tidak dicatat di sebelah aturannya akan dibaca sebagai
    izin umum memakai heksa."""
    kepala = THEME_SRC.split('"""')[1]

    assert "perkecualian" in kepala.lower()
    assert "Info" in kepala


def test_the_style_is_scoped_to_that_one_button():
    from ui.components import theme

    assert "contrib_info_" in theme.DARK_BTN_SCOPES
    assert ('[class*="st-key-contrib_info_"] .stButton > button'
            in theme.stylesheet())


# ── Aturan tampilan yang berlaku umum ────────────────────────────────────

def test_the_small_text_quota_still_holds():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import small_text_audit as audit

    assert len(audit.audit("Add Pipeline & Dataset")) <= audit.QUOTA


def test_the_modal_body_is_not_counted_as_the_main_view():
    """Badan modal bukan tampilan utama — audit teks kecil sudah tahu polanya,
    dan pola itulah yang dipakai di sini."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import small_text_audit as audit

    module = audit._load("ui/views/contribute.py")
    assert "_pipeline_info_body" in audit.dialog_bodies(module)


@pytest.mark.parametrize("key", ["ap.btn_info", "ap.btn_close_info",
                                 "ap.dlg_pipeline_info"])
def test_the_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


@pytest.mark.parametrize("key", ["ap.btn_info", "ap.btn_close_info"])
def test_the_labels_stay_short_single_line_phrases(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        label = lookup(key, lang)
        assert chr(10) not in label
        assert len(label) <= 24, (key, lang, label)
