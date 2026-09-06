"""Tiga isian jadi pemilih berisi, dan antrean yang warnanya berarti.

**Isian.** "Algoritma", "Kolom label", dan "Kolom wajib" dahulu diketik bebas.
Salah ketik satu huruf pada nama kolom membuat kontrak dataset tidak cocok
dengan datasetnya — dan tidak ada yang memberi tahu sampai uji coba dijalankan.
Sekarang ketiganya ``st.multiselect``: nama kolom ditawarkan dari header
dataset yang dilampirkan, algoritma dari yang terbaca di berkas terunggah.
``accept_new_options`` menjaga jalur mengetik sendiri tetap terbuka — tanpa
dataset, memang tidak ada yang dapat ditawarkan.

**Warna.** Kolom "Hasil periksa" pada antrean diwarnai menurut hasilnya, dengan
hijau/kuning/merah yang SAMA dengan halaman detailnya, diff versi, dan chip
katalog. Dua sifat yang dijaga: warnanya dibaca dari KEADAAN (pengenal), bukan
dari kalimat berbahasa yang tampil; dan warna tidak pernah menjadi satu-satunya
pembawa keterangan.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ui.components import grid
from ui.components import submission_review as sr

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")


class _Upload:
    """Pengganti berkas unggahan Streamlit — hanya dua hal yang dipakai."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


# ── Membaca header dataset ───────────────────────────────────────────────

def _columns_with(monkeypatch, upload):
    import ui.views.contribute as c

    monkeypatch.setitem(c.st.session_state, c._TRIAL_DATASET_KEY, upload)
    return c._attached_dataset_columns()


def test_csv_columns_are_offered(monkeypatch):
    upload = _Upload("d.csv", b"f1,f2,attack\n1,2,0\n3,4,1\n")
    assert _columns_with(monkeypatch, upload) == ["f1", "f2", "attack"]


def test_only_the_header_row_is_read(monkeypatch):
    """Dataset kontribusi dapat berukuran besar; yang dibutuhkan cuma namanya."""
    import pandas as pd

    seen = {}
    original = pd.read_csv

    def _spy(buf, **kwargs):
        seen.update(kwargs)
        return original(buf, **kwargs)

    monkeypatch.setattr(pd, "read_csv", _spy)
    _columns_with(monkeypatch, _Upload("d.csv", b"a,b\n1,2\n"))
    assert seen.get("nrows") == 0


def test_ndjson_columns_come_from_the_first_record(monkeypatch):
    data = (json.dumps({"src": 1, "dst": 2, "attack": 0}) + "\n"
            + json.dumps({"src": 3, "dst": 4, "attack": 1}) + "\n")
    assert _columns_with(monkeypatch, _Upload("d.ndjson", data.encode())) == \
        ["src", "dst", "attack"]


def test_nothing_attached_offers_nothing(monkeypatch):
    import ui.views.contribute as c

    monkeypatch.setitem(c.st.session_state, c._TRIAL_DATASET_KEY, None)
    assert c._attached_dataset_columns() == []


@pytest.mark.parametrize("payload", [b"", b"\x00\x01\x02", b"{bukan json"])
def test_an_unreadable_dataset_empties_the_list_instead_of_crashing(
        monkeypatch, payload):
    """Berkas yang belum lengkap terunggah tetap boleh terjadi; pengunggah
    tetap dapat mengetik sendiri."""
    assert _columns_with(monkeypatch, _Upload("d.ndjson", payload)) == []


def test_a_file_without_a_real_header_offers_nothing(monkeypatch):
    """pandas menamai kolom tanpa judul "Unnamed: 0". Menawarkannya berarti
    menawarkan sesuatu yang bukan nama kolom — dan yang dipilih akan masuk ke
    kontrak dataset sebagai fakta."""
    assert _columns_with(monkeypatch, _Upload("d.csv", b",,\n1,2,3\n")) == []


# ── Algoritma yang terbaca ───────────────────────────────────────────────

_PKG = '''
from pipelines.base import BasePipeline


class P(BasePipeline):
    def run(self, pipeline_input, progress=None):
        pass

    def get_info(self):
        return {"algorithm": "%s"}
'''


def test_every_entry_point_contributes_its_algorithm():
    """Satu paket boleh membawa beberapa entry point, dan tiap entry point
    adalah satu algoritma — itulah sebabnya isian ini jamak."""
    from ui.views.contribute import _detected_algorithms

    uploads = [_Upload("rf.py", (_PKG % "Random Forest").encode()),
               _Upload("svm.py", (_PKG % "SVM").encode())]
    assert _detected_algorithms(uploads) == ["Random Forest", "SVM"]


def test_the_same_algorithm_twice_is_listed_once():
    from ui.views.contribute import _detected_algorithms

    uploads = [_Upload("a.py", (_PKG % "RF").encode()),
               _Upload("b.py", (_PKG % "RF").encode())]
    assert _detected_algorithms(uploads) == ["RF"]


def test_a_file_that_declares_nothing_is_skipped_quietly():
    from ui.views.contribute import _detected_algorithms

    assert _detected_algorithms([_Upload("x.py", b"X = 1")]) == []
    assert _detected_algorithms([]) == []
    assert _detected_algorithms(None) == []


# ── Bentuk isiannya ──────────────────────────────────────────────────────

def _flow() -> str:
    return CONTRIB_SRC.split("def _render_pipeline_flow(")[1].split(
        chr(10) + "def ")[0]


@pytest.mark.parametrize("key,expected", [
    ("contrib_meta_algo", "multiselect"),
    ("contrib_schema_label", "multiselect"),
    ("contrib_schema_cols", "multiselect"),
])
def test_the_three_fields_are_pickers_now(key, expected):
    flow = _flow()
    before = flow.split(f'key="{key}"')[0]
    assert before.rstrip().rsplit(expected, 1)[-1].count("text_input") == 0
    assert expected in before.rsplit("(", 2)[0][-400:], key


def test_typing_your_own_value_is_still_possible():
    """Tanpa dataset yang dilampirkan, mengetik sendiri adalah satu-satunya
    jalan — daftar yang mengunci akan menutupnya."""
    assert _flow().count("accept_new_options=True") == 3


def test_the_label_column_takes_exactly_one():
    """Sebuah dataset punya SATU kolom label; membiarkan dua terpilih berarti
    menyimpan kontrak yang tidak dapat dipakai."""
    flow = _flow()
    block = flow.split('key="contrib_schema_label"')[0][-400:]
    assert "max_selections=1" in block


def test_the_stored_contract_did_not_change_shape():
    """Validator, uji coba, dan `schema_for` membaca bentuk ini apa adanya."""
    flow = _flow()
    assert '"label_column": (label_column or "").strip()' in flow
    assert '"expected_columns": [str(c).strip() for c in columns' in flow
    assert '"file_format": file_format' in flow


def test_the_algorithm_is_still_stored_as_one_sentence():
    """Nilai ini hanya CADANGAN bagi entri registry ketika kode paketnya
    sendiri tidak menyebut algoritmanya — bentuknya tidak berubah."""
    flow = _flow()
    assert 'algorithm = ", ".join(' in flow
    assert '"algorithm": algorithm,' in flow


# ── Kalimat kontrak dataset ──────────────────────────────────────────────

def test_the_contract_note_states_what_is_true_now():
    """"Jenis datasetnya belum terdaftar" membingkai ini sebagai perkecualian,
    padahal setiap unggahan berdiri sendiri — itu satu-satunya jalur."""
    from ui.i18n.core import lookup

    text = lookup("ap.help_declare_schema", "id")
    assert "belum terdaftar" not in text
    assert "berdiri sendiri" in text
    assert "belum terdaftar" not in lookup("ap.help_declare_schema", "en")


# ── Warna antrean ────────────────────────────────────────────────────────

def test_the_verdict_decides_the_state():
    assert sr.verdict_state({"verdict": sr.VERDICT_CLEAN}) == "ok"
    assert sr.verdict_state({"verdict": sr.VERDICT_WARN}) == "warn"
    assert sr.verdict_state({"verdict": sr.VERDICT_PROBLEM}) == "bad"


def test_an_unknown_verdict_is_never_treated_as_clean():
    """Menganggap yang tak dikenal sebagai bersih menutupi masalah."""
    assert sr.verdict_state({"verdict": "entah"}) == "warn"
    assert sr.verdict_state({}) == "warn"
    assert sr.verdict_state(None) == "warn"


def test_the_colour_is_read_from_the_state_not_the_sentence():
    """Kalimat yang tampil berbahasa; mewarnai berdasarkan kalimatnya akan
    berhenti bekerja begitu bahasanya berganti."""
    from ui.components import tables as tbl

    columns = (tbl.column("Hasil", "verdict_text", kind=tbl.KIND_STATUS),)
    rows = [{"id": 1, "verdict": sr.VERDICT_PROBLEM,
             "verdict_text": "ada masalah"}]
    df = grid.dataframe(columns, rows, id_key="id",
                        state_of=sr.verdict_state, state_column="verdict_text")
    assert df["Hasil" + grid.STATE_SUFFIX][0] == "bad"
    assert df["Hasil"][0] == "ada masalah"      # kalimatnya tetap ada


def test_only_one_state_column_is_carried():
    """Seluruh isi DataFrame menyeberang ke browser sebagai Arrow; kolom yang
    tidak dibaca siapa pun tetap menambah muatan tiap penggambaran."""
    from ui.components import tables as tbl

    columns = (tbl.column("Hasil", "verdict_text", kind=tbl.KIND_STATUS),
               tbl.column("Berkas", "file_count", kind=tbl.KIND_NUM))
    df = grid.dataframe(columns, [{"id": 1, "verdict": "bersih",
                                   "verdict_text": "lolos", "file_count": 2}],
                        id_key="id", state_of=sr.verdict_state,
                        state_column="verdict_text")
    assert [c for c in df.columns if c.endswith(grid.STATE_SUFFIX)] == \
        ["Hasil" + grid.STATE_SUFFIX]


def test_no_state_column_means_no_extra_payload():
    from ui.components import tables as tbl

    columns = (tbl.column("Hasil", "verdict_text", kind=tbl.KIND_STATUS),)
    df = grid.dataframe(columns, [{"id": 1, "verdict_text": "lolos"}],
                        id_key="id")
    assert not [c for c in df.columns if c.endswith(grid.STATE_SUFFIX)]


def test_the_tints_are_translucent_so_both_themes_work():
    """Warna pekat pada latar yang tidak diketahui adalah cara membuat teks
    hilang — dan tema gelap adalah latar yang tidak diketahui."""
    assert set(grid.STATE_TINT) == {"ok", "warn", "bad"}
    for value in grid.STATE_TINT.values():
        assert value.startswith("rgba("), value


def test_the_tints_reuse_the_colours_already_in_use():
    """"Merah" harus berarti hal yang sama di seluruh aplikasi."""
    theme = (REPO_ROOT / "ui" / "components" / "theme.py").read_text(
        encoding="utf-8")
    for rgb in ("46,160,67", "200,150,60", "200,70,70"):
        assert rgb in theme, rgb
        assert any(rgb in tint for tint in grid.STATE_TINT.values()), rgb


def test_an_unknown_state_is_left_uncoloured():
    """Mewarnai sesuatu yang tidak dipahami menyampaikan keterangan yang tidak
    dimiliki siapa pun."""
    code = str(grid.state_style("x" + grid.STATE_SUFFIX).js_code)
    assert "return bg ?" in code
    assert ": null" in code


def test_the_queue_asks_for_the_verdict_column():
    body = CONTRIB_SRC.split("def _render_queue_grid(")[1].split(
        chr(10) + "def ")[0]
    assert 'state_column="verdict_text"' in body
    assert "state_of=sr.verdict_state" in body


def test_the_other_two_tables_stay_uncoloured():
    """Warna dipakai di tempat ia BERARTI. Daftar pipeline terdaftar sudah
    punya kolom Status yang menyebut keadaannya, dan riwayat eksperimen
    berwarna menurut aturannya sendiri."""
    manage = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    assert "state_column=" not in manage
