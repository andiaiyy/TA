"""Panel pembuka halaman kontribusi berhenti berbicara sebelum ditanya.

Dahulu halaman ini dibuka tiga angka ringkas — jumlah research pipeline,
algoritma, dataset — lalu satu baris hak pengguna, keduanya berdiri di antara
pengguna dan empat kartu pilihan jalur yang ia datangi. Angka-angka itu
menerangkan platform, bukan menuntun tindakan; barisnya hak mengulangi apa yang
sudah dikatakan kontrol yang hidup atau mati di hadapannya.

Keduanya dicabut, beserta fungsinya dan tesnya: kode yang tidak menggambar apa
pun tetap dibaca sebagai fitur oleh siapa pun yang membuka berkasnya nanti.

DUA hal sengaja tidak ikut. **Ajakan masuk** tetap ada — tanpanya seorang
pengunjung melihat sederet kontrol mati tanpa keterangan apa pun mengapa. Dan
**kalimat kaitan halaman** tidak dihapus, hanya pindah ke dalam dropdown "Apa
yang terjadi setelah saya mengunggah?": ia menjawab pertanyaan yang sama, dan ia
menyatakan dua aturan yang BERBEDA — dataset tersimpan langsung, pipeline
menunggu persetujuan — yang bila disamakan membuat pengunggah dataset menunggu
sesuatu yang tidak pernah datang.
"""
from __future__ import annotations

import pathlib

import pytest

import ui.components.contribute_context as ctx

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CTX_SRC = pathlib.Path(ctx.__file__).read_text(encoding="utf-8")

VISITOR = None
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}

CONTRIB_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
for key, value in (st.session_state.pop("_preset", None) or {{}}).items():
    st.session_state[key] = value
import ui.views.contribute as c
c.render()
'''


def _run_page(tmp_path, user=None):
    from streamlit.testing.v1 import AppTest

    app = tmp_path / "ctx_app.py"
    app.write_text(CONTRIB_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(app), default_timeout=300)
    if user:
        at.session_state["_preset"] = {"auth_user": user}
    at.run()
    return at


def _teks(at) -> str:
    return " ".join([m.value for m in at.markdown]
                    + [c.value for c in at.caption]
                    + [i.value for i in at.info])


# ── Perekam bersarang: DI DALAM dropdown, atau di badan halaman? ─────────

class _Expander:
    def __init__(self, jejak):
        self.jejak = jejak

    def __enter__(self):
        self.jejak["dalam"] += 1
        return self

    def __exit__(self, *a):
        self.jejak["dalam"] -= 1
        return False


class _Panel:
    """`st` tiruan yang mencatat setiap teks BESERTA kedalamannya."""

    def __init__(self):
        self.jejak = {"dalam": 0}
        self.dicatat: list[tuple[str, bool]] = []
        self.judul_expander: list[str] = []

    def _catat(self, teks):
        self.dicatat.append((str(teks), self.jejak["dalam"] > 0))

    def markdown(self, s=None, **k): self._catat(s)
    def caption(self, s=None, **k): self._catat(s)
    def info(self, s=None, **k): self._catat(s)
    def code(self, s=None, **k): self._catat(s)

    def expander(self, label, **k):
        self.judul_expander.append(str(label))
        return _Expander(self.jejak)

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(n)]

    def container(self, **k): return _Expander({"dalam": 0})
    def divider(self, *a, **k): return None
    def button(self, label, **k): self._catat(label); return False
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _gambar(user):
    from unittest.mock import patch

    panel = _Panel()
    with patch.object(ctx, "st", panel):
        ctx.render_page_context(user)
    return panel


# ── Yang dicabut benar-benar hilang ──────────────────────────────────────

def test_the_three_numbers_are_gone(tmp_path):
    teks = _teks(_run_page(tmp_path, CONTRIBUTOR))

    for angka in ("research pipeline", "algoritma", "dataset"):
        assert f"ids-count" not in teks, angka
    assert "ids-count-n" not in teks


def test_the_rights_line_is_gone(tmp_path):
    """Frasa yang dahulu tergambar pada baris status. Kuncinya sendiri sudah
    dihapus dari kamus, jadi yang dicari adalah kalimatnya."""
    teks = _teks(_run_page(tmp_path, CONTRIBUTOR))

    assert "Kontributor" not in teks
    assert "mengajukan pipeline" not in teks


@pytest.mark.parametrize("nama", ["platform_stats", "render_platform_summary",
                                  "capability", "render_capability",
                                  "role_display"])
def test_the_dead_helpers_are_gone_from_the_module(nama):
    """Kode yang tidak menggambar apa pun tetap dibaca sebagai fitur."""
    assert not hasattr(ctx, nama), nama
    assert f"def {nama}(" not in CTX_SRC, nama


# ── Yang sengaja TIDAK ikut dicabut ──────────────────────────────────────

def test_a_visitor_is_still_told_how_to_get_in(tmp_path):
    """Tanpa ini halamannya menampilkan kontrol mati tanpa keterangan."""
    at = _run_page(tmp_path, VISITOR)

    assert any("Masuk" in i.value for i in at.info)


def test_a_signed_in_user_is_not_nagged_to_sign_in():
    panel = _gambar(CONTRIBUTOR)

    assert all("Masuk" not in teks for teks, _dalam in panel.dicatat)


# ── Kalimat kaitan halaman PINDAH, bukan hilang ──────────────────────────

def test_the_related_pages_line_lives_inside_the_dropdown():
    from ui.i18n import t

    panel = _gambar(CONTRIBUTOR)
    kalimat = t("ap.related_pages", page=t("page.run_experiment"))

    cocok = [dalam for teks, dalam in panel.dicatat if teks == kalimat]
    assert cocok, "kalimat kaitan halaman hilang sama sekali"
    assert all(cocok), "ia masih tergambar di badan halaman"


def test_the_dropdown_is_still_there_and_still_asks_the_question():
    from ui.i18n import t

    panel = _gambar(CONTRIBUTOR)

    assert panel.judul_expander == [t("ctx.after_upload_q")]


def test_nothing_but_the_invite_is_drawn_outside_the_dropdown():
    """Inilah maksud seluruh perubahan: halaman pembukanya diam sampai
    diketuk."""
    panel = _gambar(CONTRIBUTOR)
    luar = [teks for teks, dalam in panel.dicatat if not dalam]

    assert luar == [], luar


def test_the_two_different_rules_are_still_stated():
    """Dataset langsung, pipeline menunggu. Menyamakan keduanya pernah membuat
    pengunggah dataset menunggu sesuatu yang tidak pernah datang."""
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        kalimat = lookup("ap.related_pages", lang).lower()
        assert "research admin" in kalimat, lang
    assert "langsung" in lookup("ap.related_pages", "id").lower()
    assert "disetujui" in lookup("ap.related_pages", "id").lower()


def test_the_sentence_reaches_the_reader(tmp_path):
    """Dibuktikan pada halaman yang benar-benar dirender, bukan hanya pada
    fungsi yang dipanggil sendirian."""
    from ui.i18n.core import lookup

    teks = _teks(_run_page(tmp_path, CONTRIBUTOR)).lower()

    assert lookup("page.run_experiment", "id").lower() in teks
    assert "disetujui" in teks
