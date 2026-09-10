"""Panduan Tambah Dataset pindah ke modal — pemilih researchnya ikut.

Pola yang sama dengan jalur pipeline, dengan satu perbedaan yang menentukan:
panduan dataset membawa sebuah KONTROL, yaitu pemilih research pipeline. Ia
ikut masuk ke modal, dan itu bukan kelalaian — tugasnya semata memilih
*persyaratan siapa yang sedang dibaca*. Berkas yang diunggah diperiksa terhadap
SELURUH research, bukan terhadap satu yang dipilih, jadi meninggalkan pemilih
itu di halaman berarti menyisakan kontrol yang tampak menentukan sesuatu
padahal tidak mengubah apa pun di sana.

Karena ia kontrol, ada satu hal tambahan yang harus dibuktikan dan tidak cukup
dibaca dari sumber: pemilihnya benar-benar DAPAT DIPAKAI di dalam modal, dan
mengganti pilihannya mengganti isi persyaratannya tanpa menutup modalnya.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import ui.components.instructions as ins
import ui.views.contribute as contrib
from ui.components import dialogs as dlg

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = Path(contrib.__file__).read_text(encoding="utf-8")
THEME_SRC = (REPO_ROOT / "ui" / "components" / "theme.py").read_text(
    encoding="utf-8")

CONTRIB_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import ui.views.contribute as c
c.render()
'''


def _flow() -> str:
    return CONTRIB_SRC.split("def _render_dataset_flow(")[1].split(
        chr(10) + "def ")[0]


def _body() -> str:
    return CONTRIB_SRC.split("def _dataset_info_body(")[1].split(
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
    def subheader(self, s=None, **k): self.teks.append(str(s))
    def selectbox(self, label, options, **k):
        self.teks.append(str(label))
        return list(options)[0] if options else None

    def button(self, label, **k):
        self.teks.append(str(label))
        return False

    def expander(self, *a, **k): return _Ctx()
    def container(self, **k): return _Ctx()
    def tabs(self, labels, **k): return [_Ctx() for _ in labels]
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(n)]
    def divider(self, *a, **k): return None
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _rendered_panel() -> list[str]:
    sink = _Sink()
    with patch.object(ins, "st", sink):
        ins.render_dataset_instructions()
    return sink.teks


def _rendered_modal() -> list[str]:
    sink = _Sink()
    with patch.object(ins, "st", sink), patch.object(contrib, "st", sink):
        contrib._dataset_info_body()
    return sink.teks


def _run_page(tmp_path):
    from streamlit.testing.v1 import AppTest

    app = tmp_path / "contrib_app.py"
    app.write_text(CONTRIB_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(app), default_timeout=300)
    at.session_state["_contrib_mode"] = "dataset"
    at.run()
    return at


def _teks(at) -> str:
    return " ".join([m.value for m in at.markdown]
                    + [c.value for c in at.caption]
                    + [c.value for c in at.code])


# ── Halamannya menjadi tindakan ──────────────────────────────────────────

def test_the_page_no_longer_draws_the_guide_inline():
    flow = _flow()

    assert "_render_dataset_requirements_overview()" not in flow
    assert "render_dataset_instructions" not in flow
    assert "ap.note_checked_against_all" not in flow


def test_the_tabs_come_before_anything_that_explains_them():
    flow = _flow()
    sebelum = flow.split("st.tabs(")[0]

    for penjelas in ("_render_dataset_requirements_overview",
                     "render_dataset_instructions",
                     "ap.note_checked_against_all"):
        assert penjelas not in sebelum, penjelas


def test_the_page_offers_an_info_button():
    flow = _flow()

    assert 'key="contrib_info_dataset"' in flow
    assert 't("ap.btn_info")' in flow
    assert "_request_dataset_info()" in flow


def test_the_flow_still_has_no_research_dropdown_of_its_own():
    """Penjagaan lama yang tetap berlaku: halaman ini tidak pernah bertanya
    "untuk pipeline yang mana?" — platform yang menyimpulkan kecocokannya."""
    assert "selectbox" not in _flow()


# ── Siklus hidup modalnya ────────────────────────────────────────────────

def test_the_flag_is_registered_so_page_changes_clear_it():
    assert dlg.DATASET_INFO_KEY in dlg.DIALOG_KEYS
    assert len(set(dlg.DIALOG_KEYS)) == len(dlg.DIALOG_KEYS)
    # Dua panduan, dua flag berbeda — satu flag bersama akan membuat menekan
    # Info di satu halaman membuka modal halaman lain.
    assert dlg.DATASET_INFO_KEY != dlg.PIPELINE_INFO_KEY


def test_the_body_is_decorated_once_at_module_level():
    assert hasattr(contrib, "_dataset_info_dialog")
    assert "dlg.DATASET_INFO_KEY" in CONTRIB_SRC
    assert "st.dialog(" not in CONTRIB_SRC          # selalu lewat dekorator


def test_the_dialog_is_called_from_the_main_flow_only():
    penjaga = CONTRIB_SRC.split("def _maybe_render_dataset_info(")[1].split(
        chr(10) + "def ")[0]
    assert "_dataset_info_dialog()" in penjaga

    panggilan = [baris for baris in CONTRIB_SRC.splitlines()
                 if "_dataset_info_dialog()" in baris
                 and not baris.lstrip().startswith("def ")]
    assert len(panggilan) == 1, panggilan


def test_the_button_only_writes_the_flag(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(dlg.st, "session_state", state, raising=False)

    contrib._request_dataset_info()

    assert state[dlg.DATASET_INFO_KEY] is True


def test_closing_clears_the_flag(monkeypatch):
    state = {dlg.DATASET_INFO_KEY: True}
    monkeypatch.setattr(dlg.st, "session_state", state, raising=False)
    monkeypatch.setattr(contrib.st, "rerun", lambda: None)

    contrib._close_dataset_info()

    assert dlg.DATASET_INFO_KEY not in state


def test_the_modal_carries_its_own_close_button():
    assert "ap.btn_close_info" in _body()
    assert "_close_dataset_info()" in _body()


def test_nothing_is_drawn_while_the_flag_is_down(monkeypatch):
    monkeypatch.setattr(dlg.st, "session_state", {}, raising=False)
    dipanggil = {"n": 0}
    monkeypatch.setattr(contrib, "_dataset_info_dialog",
                        lambda: dipanggil.__setitem__("n", dipanggil["n"] + 1))

    contrib._maybe_render_dataset_info()

    assert dipanggil["n"] == 0


def test_it_is_drawn_when_the_flag_is_up(monkeypatch):
    monkeypatch.setattr(dlg.st, "session_state",
                        {dlg.DATASET_INFO_KEY: True}, raising=False)
    dipanggil = {"n": 0}
    monkeypatch.setattr(contrib, "_dataset_info_dialog",
                        lambda: dipanggil.__setitem__("n", dipanggil["n"] + 1))

    contrib._maybe_render_dataset_info()

    assert dipanggil["n"] == 1


# ── Tidak satu baris pun hilang ──────────────────────────────────────────

def test_the_modal_loses_no_line_of_the_guide():
    panel = _rendered_panel()
    modal = _rendered_modal()

    hilang = [baris for baris in panel if baris not in modal]

    assert hilang == [], hilang
    assert len(panel) >= 8


def test_the_modal_adds_the_note_and_the_close_button():
    from ui.i18n import t

    panel = set(_rendered_panel())
    tambahan = [b for b in _rendered_modal() if b not in panel]

    assert t("ap.note_checked_against_all") in tambahan
    assert t("ap.btn_close_info") in tambahan


@pytest.mark.parametrize("bagian", [
    "ins.lbl_research_pipeline",     # pemilih research
    "ins.col_aspect",                # tabel kontrak
    "ins.dataset_sample_note",       # catatan cuplikan
    "ins.mistakes_dataset_title",    # kesalahan umum
])
def test_every_named_part_reaches_the_modal(bagian):
    from ui.i18n import t

    teks = " ".join(_rendered_modal())
    potongan = t(bagian).split("{")[0].strip()

    assert potongan and potongan in teks, bagian


# ── Pemilihnya benar-benar dapat dipakai DI DALAM modal ──────────────────

def _kunci_pemilih(at) -> set[str]:
    return {s.key for s in at.selectbox}


def test_the_picker_lives_inside_the_modal(tmp_path):
    at = _run_page(tmp_path)

    # Halaman ini memang punya pemilih LAIN — berkas di server, pada tab
    # "Daftarkan dari server". Yang harus absen sebelum modal dibuka hanyalah
    # pemilih research.
    assert "ins_dataset_research" not in _kunci_pemilih(at)
    assert "contrib_server_dataset" in _kunci_pemilih(at)

    at = at.button(key="contrib_info_dataset").click().run()
    picker = at.selectbox(key="ins_dataset_research")

    assert picker
    assert not picker.proto.disabled
    assert len(picker.options) >= 2


def test_changing_the_research_changes_the_requirements(tmp_path):
    """Sebuah kontrol di dalam modal harus benar-benar berfungsi di sana.
    Mengganti pilihan memicu rerun; modalnya tetap terbuka karena flagnya masih
    hidup, jadi persyaratan research lain terbaca tanpa menutup apa pun."""
    at = _run_page(tmp_path)
    at = at.button(key="contrib_info_dataset").click().run()

    picker = at.selectbox(key="ins_dataset_research")
    semula = picker.value
    # `AppTest.run()` mengubah objeknya sendiri lalu mengembalikannya, jadi
    # teks "sebelum" harus disalin SEKARANG — membacanya sesudah `run()` berarti
    # membandingkan sesuatu dengan dirinya sendiri.
    sebelum = _teks(at)

    sesudah = picker.select_index(1).run()

    lain = sesudah.selectbox(key="ins_dataset_research")
    assert lain, "modalnya harus tetap terbuka sesudah pilihan berganti"
    assert lain.value != semula                # pilihannya benar-benar pindah
    assert _teks(sesudah) != sebelum           # dan isinya ikut berganti


def test_the_visitor_reads_the_contract_after_opening_it(tmp_path):
    at = _run_page(tmp_path)
    tombol = at.button(key="contrib_info_dataset")

    assert tombol and not tombol.proto.disabled
    sesudah = tombol.click().run()

    assert any("<svg" in m.value for m in sesudah.markdown)   # diagram alur
    assert "cuplikan" in _teks(sesudah).lower()               # catatan cuplikan


# ── Satu gaya untuk kedua tombol ─────────────────────────────────────────

def test_both_info_buttons_share_one_rule():
    """Dua aturan kembar yang harus diingat untuk diubah bersama pasti berbeda
    sendiri suatu saat. Satu awalan kunci, satu aturan."""
    from ui.components import theme

    css = theme.stylesheet()
    assert '[class*="st-key-contrib_info_"] .stButton > button' in css
    # Tidak ada selektor per-halaman: keduanya dilayani awalan yang sama.
    assert "st-key-contrib_info_pipeline" not in css
    assert "st-key-contrib_info_dataset" not in css

    for kunci in ('key="contrib_info_pipeline"', 'key="contrib_info_dataset"'):
        assert kunci in CONTRIB_SRC, kunci


def test_the_shared_rule_still_carries_its_own_contrast():
    from ui.components import theme

    aturan = theme.stylesheet().split("background-color: #111418")[1][:200]

    assert "color: #ffffff" in aturan
    assert "border" in aturan


# ── Aturan tampilan yang berlaku umum ────────────────────────────────────

def test_the_small_text_quota_still_holds():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import small_text_audit as audit

    assert len(audit.audit("Add Pipeline & Dataset")) <= audit.QUOTA


def test_both_modal_bodies_are_sheltered_from_the_main_view():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import small_text_audit as audit

    badan = audit.dialog_bodies(audit._load("ui/views/contribute.py"))

    assert {"_pipeline_info_body", "_dataset_info_body"} <= badan


def test_the_new_title_exists_in_both_languages():
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        judul = lookup("ap.dlg_dataset_info", lang)
        assert judul, lang
        assert chr(10) not in judul
