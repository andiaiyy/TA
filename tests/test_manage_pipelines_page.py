"""Sub-tampilan "Peninjauan Pengajuan" + pemuatan di sisi worker.

Pengelolaan pipeline kontribusi TIDAK berupa halaman tersendiri: ia hidup di
dalam sub-tampilan "Peninjauan Pengajuan" pada halaman "Add Pipeline &
Dataset", memakai mekanisme sub-tampilan yang sama dengan jalur unggah
(penanda mode di ``session_state`` + tombol kembali).

Dua hal yang diperiksa di sini:

* sub-tampilan itu menyajikan tiga bagian yang diminta — dengan MEMANGGIL
  penyaji yang sudah ada, bukan menyalinnya — dan tidak pernah menjalankan
  kode kontribusi untuk meninjau;
* pipeline kontribusi benar-benar dapat dimuat oleh WORKER — dengan verifikasi
  hash — dan kegagalan satu pipeline tidak merusak daftar pipeline lainnya.
"""
import sqlite3
from pathlib import Path

import pytest

from config.pipeline_registry import PIPELINE_REGISTRY
from database.db import init_db
from database.models import UPLOADED_PREFIX
from ui.i18n.core import lookup
from orchestrator.dynamic_registry import (
    DynamicRegistryError, get_all_pipelines, get_pipeline_instance_merged,
    register_pipeline,
)
from ui.views import manage_pipelines as mp

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_SRC = (REPO_ROOT / "ui" / "views"
            / "manage_pipelines.py").read_text(encoding="utf-8")
CONTRIB_SRC = (REPO_ROOT / "ui" / "views"
               / "contribute.py").read_text(encoding="utf-8")
REVIEW_BODY = CONTRIB_SRC.split("def _render_review_flow()")[1].split(
    chr(10) + "def ")[0]

ADMIN = {"username": "boss", "role": "research_admin"}

VALID = '''
from pipelines.base import BasePipeline


class UploadedPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return "ok"

    def get_info(self):
        return {"paper": "Uploaded (2026)", "algorithm": "Uploaded RF"}
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "page.db")
    init_db(db_path)

    def _conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    for module in ("database.db", "orchestrator.dynamic_registry",
                   "orchestrator.pipeline_versions"):
        monkeypatch.setattr(f"{module}.get_connection", _conn)

    entry = tmp_path / "approved" / "uploaded_pipeline.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(VALID, encoding="utf-8")
    row = register_pipeline(
        name="contoh", dataset_type="HIKARI2021",
        entry_class="UploadedPipeline", entry_file=entry,
        registered_by="boss", db_path=db_path,
    )
    return {"db": db_path, "row": row, "entry": entry}


# ── Struktur halaman: tiga bagian ────────────────────────────────────────

def test_the_review_subview_assembles_the_three_sections():
    """Menunggu tinjauan (milik contribute) + Aktif & Riwayat versi (dipanggil
    dari modul penyaji)."""
    assert 's["kind"] == KIND_PIPELINE' in REVIEW_BODY   # menunggu tinjauan
    assert "mp.render_active(user)" in REVIEW_BODY       # aktif
    assert "mp.render_history()" in REVIEW_BODY          # riwayat versi
    # Penyunting kini dibuka DARI DALAM bagian "Aktif" sebagai tampilan
    # tersendiri, jadi ia tidak lagi dipanggil sejajar ketiga bagian.
    assert "render_editor(user)" in PAGE_SRC

    # Bagian Aktif & Riwayat memakai pola bagian yang dibakukan.
    for section in ("Aktif", "Riwayat versi"):
        assert f'render_section("{section}"' in PAGE_SRC


def test_the_renderers_are_called_not_copied():
    """Isi tiga bagian TIDAK disalin ke contribute.py."""
    for marker in ("def render_active(", "def render_history(",
                   "def render_editor(", "history_table("):
        assert marker not in CONTRIB_SRC, marker
    # …dan memang didefinisikan sekali, di modul penyaji.
    for marker in ("def render_active(", "def render_history(",
                   "def render_editor("):
        assert PAGE_SRC.count(marker) == 1, marker


def test_the_pending_section_still_offers_review_actions():
    """Kartu tinjauan milik contribute dipertahankan — di situlah keputusan
    setujui/tolak benar-benar diambil."""
    body = CONTRIB_SRC.split("def _render_submission_review_card(")[1].split(
        chr(10) + "def ")[0]
    assert "approve_submission(" in body
    assert "reject_submission(" in body
    # Yang dijaga kini KEBALIKANNYA: peninjau tidak lagi menyodorkan
    # `dataset_type`, karena pengenalnya berasal dari pengajuannya sendiri.
    assert "dataset_type=" not in body
    assert "approval_identity_blocker(item)" in body

    # Sumbernya kini dibaca lewat `submission_review`, satu lapis di bawah —
    # jaminannya tetap: TEKS, tidak pernah di-import maupun dijalankan.
    helper = (REPO_ROOT / "ui" / "components"
              / "submission_review.py").read_text(encoding="utf-8")
    assert "read_submission_sources" in helper
    # Kartu memanggil pembungkus ber-cache; pembungkusnya yang memanggil
    # pemeriksa statis. Keduanya diperiksa supaya rantainya utuh.
    assert "_reviewed_package(" in body
    assert "sr.review_stored_package(" in CONTRIB_SRC


def test_the_active_section_offers_edit_deactivate_and_history():
    """Aksinya kini dirender helper tersendiri; jaminannya tidak berubah."""
    body = PAGE_SRC.split("def _render_pipeline_actions(")[1].split(
        chr(10) + "def ")[0]
    for label in ('t("action.edit")', 't("ap.btn_deactivate")',
                  't("ap.btn_history")', 't("ap.btn_reactivate")'):
        assert label in body, label
    assert "set_pipeline_active(" in body


def test_the_active_row_shows_version_hash_dataset_and_usage(env):
    rows = mp.active_rows()
    assert rows
    row = rows[0]
    for field in ("name", "pipeline_id", "version", "dataset_type",
                  "file_hash", "registered_by", "experiments", "running",
                  "versions", "is_active", "state", "version_count"):
        assert field in row, field


def test_the_history_table_carries_the_traceability_columns(env):
    from orchestrator.pipeline_versions import experiment_counts, version_history
    from ui.components import registry_view as rv

    rows = rv.history_rows(version_history("contoh", db_path=env["db"]),
                           experiment_counts(db_path=env["db"]))
    table = mp.history_table(rows)
    for column in ("Versi", "Hash", "Oleh", "Waktu", "Catatan", "Status",
                   "Eksperimen"):
        assert column in table, column
    assert env["row"]["file_hash"][:12] in table
    # Hash PENUH tetap dapat diakses lewat tooltip.
    assert env["row"]["file_hash"] in table


def test_the_editor_states_the_note_that_belongs_to_it():
    """Satu kalimat, satu baris, dan di tempat yang tepat.

    Yang tentang pemeriksaan statis dibuang dari halaman peninjauan atas
    permintaan; yang tentang versi baru bertahan DI PENYUNTING, karena di sana
    ia menjelaskan akibat dari tombol yang sedang akan ditekan.
    """
    assert "versi baru" in mp.NEW_VERSION_NOTE
    assert "tidak berubah" in mp.NEW_VERSION_NOTE
    assert chr(10) not in mp.NEW_VERSION_NOTE
    assert not hasattr(mp, "STATIC_CHECK_NOTE")

    editor = PAGE_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    assert "NEW_VERSION_NOTE" in editor


def test_the_save_button_is_disabled_until_the_check_passes():
    """Tombol terikat ke ``save_blocker`` — dan alasannya SELALU dinyatakan.

    Diperiksa dari PERILAKU ``save_blocker`` (fungsi murni), bukan dari teks
    sumber, supaya penataan ulang tidak lolos hanya karena kalimatnya pindah.
    """
    body = PAGE_SRC.split("def render_editor(")[1].split("\ndef ")[0]
    assert 't("ap.btn_save_version")' in body
    assert "disabled=bool(blocked)" in body
    assert "blocked = save_blocker(" in body
    # Tombol mati tidak pernah diam: alasannya ikut ditampilkan.
    assert "Tombol simpan nonaktif" in body

    files = {"uploaded_pipeline.py": VALID}
    good = mp.validate_package(files)
    fp = mp.package_fingerprint(files)
    assert good.get("valid"), good

    # Belum diperiksa → terkunci, dengan alasan.
    assert mp.save_blocker(files, None, "", "catatan").strip()
    # Lolos + catatan → terbuka.
    assert mp.save_blocker(files, good, fp, "catatan") == ""
    # Gagal validasi → terkunci, dan alasannya menyebut sebabnya.
    bad = {"uploaded_pipeline.py": "import subprocess\n" + VALID}
    report = mp.validate_package(bad)
    reason = mp.save_blocker(bad, report, mp.package_fingerprint(bad), "catatan")
    assert "subprocess" in reason


def test_the_editor_shows_context_and_a_running_warning():
    body = PAGE_SRC.split("def render_editor(")[1].split("\ndef ")[0]
    assert "Versi aktif" in body
    assert "Hash aktif" in body
    assert "running_experiments(" in body
    assert "sedang BERJALAN" in body
    # Peringatannya menjelaskan bahwa eksekusi berjalan TIDAK ikut berubah.
    assert "versi lama" in body


def test_the_editor_uses_a_tall_scrollable_text_area():
    body = PAGE_SRC.split("def render_editor(")[1].split("\ndef ")[0]
    assert "st.text_area(" in body
    height = int(body.split("height=")[1].split(",")[0])
    assert height >= 400, height


def test_the_change_note_is_required_before_saving():
    body = PAGE_SRC.split("def render_editor(")[1].split("\ndef ")[0]
    assert 't("ap.lbl_change_note")' in body

    files = {"uploaded_pipeline.py": VALID}
    good = mp.validate_package(files)
    fp = mp.package_fingerprint(files)
    # Kode lolos, tetapi catatan kosong → tetap terkunci.
    for blank in ("", "   "):
        assert mp.save_blocker(files, good, fp, blank) == "Isi catatan perubahan dulu."
    assert mp.save_blocker(files, good, fp, "menyesuaikan ambang") == ""


def test_the_subview_never_enforces_permission_by_hiding_alone():
    """Sub-tampilan boleh menyembunyikan, tetapi penolakannya ada di FUNGSI."""
    assert "can_approve(user)" in REVIEW_BODY          # menyembunyikan
    # …dan fungsi aksinya sendiri yang menolak.
    versions = (REPO_ROOT / "orchestrator"
                / "pipeline_versions.py").read_text(encoding="utf-8")
    assert "require_approve(" in versions


# ── Halaman terender untuk tiap identitas ────────────────────────────────

IDENTITIES = {
    "pengunjung": None,
    "kontributor": {"username": "rina", "role": "contributor", "status": "active"},
    "research_admin": {"username": "ai", "role": "research_admin",
                       "status": "active"},
}


@pytest.mark.parametrize("who", sorted(IDENTITIES))
def test_the_review_subview_renders_for_every_identity(tmp_path, who):
    """Halaman Add Pipeline & Dataset dengan mode `review` aktif."""
    from streamlit.testing.v1 import AppTest

    from ui.views import login

    script = tmp_path / "page.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        "st.session_state['_current_page'] = 'Add Pipeline & Dataset'\n"
        "st.session_state['_contrib_mode'] = 'review'\n"
        "from ui.views.contribute import render\n"
        "render()\n",
        encoding="utf-8")

    at = AppTest.from_file(str(script), default_timeout=900)
    if IDENTITIES[who]:
        at.session_state[login.SESSION_USER_KEY] = IDENTITIES[who]
    at.run()
    assert at.exception is None or not at.exception, (who, at.exception)

    refused = any("Hanya Research Admin" in e.value for e in at.error)
    assert refused is (IDENTITIES[who] is None
                       or IDENTITIES[who]["role"] != "research_admin")


def test_the_subview_uses_the_same_mode_mechanism_as_the_upload_paths():
    """Bukan mekanisme baru: penanda mode di session_state + tombol kembali,
    persis seperti jalur unggah pipeline/dataset."""
    render_body = CONTRIB_SRC.split(chr(10) + "def render()")[1]
    assert '_MODE_KEY = "_contrib_mode"' in CONTRIB_SRC
    assert 'mode not in ("pipeline", "dataset", "users", "review")' in render_body
    assert 'elif mode == "review":' in render_body
    assert "_render_review_flow()" in render_body
    # Tombol kembali dipakai bersama oleh SEMUA sub-tampilan, termasuk review.
    assert 'st.button(t("ap.btn_back"), key="contrib_back")' in render_body
    back_at = render_body.index('t("ap.btn_back")')
    review_at = render_body.index('elif mode == "review":')
    assert back_at < review_at


def test_the_review_card_stays_visible_to_everyone():
    """Kartu tidak disembunyikan; hanya aksinya yang nonaktif bagi yang tak
    berhak."""
    cards = (REPO_ROOT / "ui" / "components"
             / "upload_cards.py").read_text(encoding="utf-8")
    assert '"mode": "review"' in cards
    # Judul kartu kini kunci katalog; kalimatnya diperiksa lewat katalog.
    assert '"title": "ap.card_review_title"' in cards
    assert lookup("ap.card_review_title", "id") == "Peninjauan Pengajuan"
    # Kelayakan hanya mematikan tombol.
    assert "may_approve" in cards


# ── Pemuatan di sisi worker ──────────────────────────────────────────────

def test_the_worker_loads_contributed_pipelines_through_the_verified_path():
    """Worker masuk lewat `execute_pipeline`, yang memakai loader
    ber-verifikasi hash yang sama dengan UI."""
    worker = (REPO_ROOT / "workers" / "celery_worker.py").read_text(encoding="utf-8")
    execution = (REPO_ROOT / "orchestrator"
                 / "execution_service.py").read_text(encoding="utf-8")
    assert "execute_pipeline(" in worker
    assert "get_pipeline_instance_merged(" in execution
    # Kegagalan memuat menjadi ValueError -> eksperimen FAILED dengan pesan,
    # bukan menggantung.
    assert "except DynamicRegistryError" in execution
    assert "raise ValueError(" in execution


def test_a_tampered_file_is_refused_before_its_code_runs(env):
    """Hash tidak cocok -> ditolak SEBELUM kodenya dieksekusi."""
    env["entry"].write_text(VALID.replace('"ok"', '"diubah"'), encoding="utf-8")
    with pytest.raises(DynamicRegistryError, match="[Hh]ash"):
        get_pipeline_instance_merged(env["row"]["pipeline_id"],
                                     db_path=env["db"])


def test_one_broken_pipeline_does_not_break_the_whole_list(env, tmp_path):
    """Daftar pipeline harus tetap terbaca walau satu entri rusak."""
    broken = tmp_path / "approved" / "broken.py"
    broken.write_text(VALID, encoding="utf-8")
    register_pipeline(name="rusak", dataset_type="HIKARI2021",
                      entry_class="UploadedPipeline", entry_file=broken,
                      registered_by="boss", db_path=env["db"])
    broken.write_text("bukan python yang sama", encoding="utf-8")  # hash beda

    merged = get_all_pipelines(db_path=env["db"])
    # Pipeline bawaan tetap lengkap, dan yang sehat tetap ada.
    for pipeline_id in PIPELINE_REGISTRY:
        assert pipeline_id in merged
    assert env["row"]["pipeline_id"] in merged


def test_built_in_pipelines_always_come_from_the_static_registry(env):
    merged = get_all_pipelines(db_path=env["db"])
    for pipeline_id, entry in PIPELINE_REGISTRY.items():
        assert merged[pipeline_id]["class"] is entry["class"]
        assert not pipeline_id.startswith(UPLOADED_PREFIX)


# ── Ketiga bagian harus SALING MENIADAKAN ────────────────────────────────
# Klaim "SATU bagian tampil pada satu waktu" dulu hanya berlaku untuk dua
# bagian: jalur "Menunggu tinjauan" tidak berhenti setelah antreannya,
# melainkan memanggil `render_active` dan `render_history` sekali lagi di
# bawahnya — sehingga bagian itu memuat SEMUANYA sekaligus.

def test_the_pending_path_never_falls_through_into_the_other_sections():
    """Penjaga STRUKTURAL atas cacatnya, dibaca dari pohon sintaks.

    Aturannya: setelah antrean digambar, tidak boleh ada lagi pemanggilan
    penyaji bagian lain — itulah bentuk persis kebocoran yang diperbaiki.
    Ditulis atas AST, bukan atas potongan teks, supaya penataan ulang kode
    tidak diam-diam melewatinya.
    """
    import ast

    tree = ast.parse(CONTRIB_SRC)
    flow = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "_render_review_flow")

    def call_name(node):
        fn = getattr(node, "func", None)
        return getattr(fn, "attr", None) or getattr(fn, "id", None)

    # Baris tempat antrean digambar — segala sesudahnya milik bagian itu.
    pending_line = min(
        n.lineno for n in ast.walk(flow)
        if isinstance(n, ast.Call) and call_name(n) == "_render_pending_section")

    leaked = sorted(
        (call_name(n), n.lineno) for n in ast.walk(flow)
        if isinstance(n, ast.Call)
        and call_name(n) in ("render_active", "render_history")
        and n.lineno > pending_line)

    assert not leaked, (
        "bagian lain ikut tergambar pada jalur 'Menunggu tinjauan': "
        f"{leaked}")


def test_each_section_renderer_is_reached_by_exactly_one_branch():
    """Penjaga anti-hampa: ketiga penyaji tetap benar-benar dipanggil."""
    import ast

    tree = ast.parse(CONTRIB_SRC)
    flow = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "_render_review_flow")

    def call_name(node):
        fn = getattr(node, "func", None)
        return getattr(fn, "attr", None) or getattr(fn, "id", None)

    names = [call_name(n) for n in ast.walk(flow) if isinstance(n, ast.Call)]
    for renderer in ("render_active", "render_history",
                     "_render_pending_section"):
        assert names.count(renderer) == 1, (renderer, names.count(renderer))


def test_the_submission_history_left_the_pending_section():
    """Antrean adalah tempat MEMUTUSKAN; yang sudah diputuskan pindah ke tab
    "Riwayat versi", bersama riwayat lain. Sisa pengajuan dataset lama TETAP
    di sini — itu pekerjaan yang belum selesai, bukan riwayat."""
    import ast

    tree = ast.parse(CONTRIB_SRC)
    flow = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)
                and n.name == "_render_review_flow")
    body = ast.unparse(flow)
    assert "ap.review_history_heading" not in body
    assert "ap.msg_legacy_dataset_submission" in body      # sisa dataset lama

    manage = (REPO_ROOT / "ui" / "views" / "manage_pipelines.py").read_text(
        encoding="utf-8")
    assert "ap.review_history_heading" in manage
