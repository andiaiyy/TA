"""Fase progres pipeline terunggah sampai ke layar.

Pipeline terunggah SUDAH memancarkan fasenya saat berjalan — panggilan
``_emit_progress()`` di kodenya berjalan seperti pada pipeline bawaan. Yang
tidak ada adalah tempat menyimpannya, sehingga bar progresnya berjalan tanpa
nama fase. Terkunci tiga lapis, dan ketiganya harus dibuka bersama:

1. **dibuang saat diajukan** — ``extract_registry_metadata`` sudah membacanya,
   lalu hanya nama berkas, kelas, dan algoritma yang disimpan;
2. **tidak ada kolomnya** di ``registered_pipelines``;
3. **pembacanya salah sumber** — ``progress_util._stages_for`` dan halaman
   Jalankan Eksperimen membaca registry STATIS, yang tidak pernah memuat
   pipeline terunggah.

Yang dijaga di sini bukan "fasenya tidak kosong" melainkan yang jauh lebih
tajam: fase yang DIPANCARKAN saat berjalan sama persis dengan fase yang
DILIHAT pelacak progres. Daftar yang tidak kosong tetapi salah isi justru
menyesatkan — bar progres akan menghitung fase yang tidak pernah terjadi.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from database.migration import apply_migrations
from orchestrator import dynamic_registry as dr

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

#: Tiga fase, dan salah satunya di dalam PERCABANGAN — pembacaan statis memberi
#: urutan kemunculan di berkas, dan test ini menyatakan urutan itu apa adanya
#: alih-alih berpura-pura ia selalu sama dengan urutan saat berjalan.
SOURCE = '''
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        self._emit_progress(progress, "Preprocessing")
        self._emit_progress(progress, "Training")
        if len(pipeline_input.df) > 0:
            self._emit_progress(progress, "Evaluating")
        raise NotImplementedError

    def get_info(self):
        return {"algorithm": "Demo"}
'''

SILENT = '''
from pipelines.base import BasePipeline


class QuietPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"algorithm": "Quiet"}
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "stages.db"
    apply_migrations(str(db))
    monkeypatch.setattr("database.db.DB_PATH", str(db), raising=False)
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    return {"db": str(db), "tmp": tmp_path}


def _register(env, source: str, *, name: str, stages=None):
    entry = env["tmp"] / f"{name}.py"
    entry.write_text(source, encoding="utf-8")
    return dr.register_pipeline(
        name=name, dataset_type="uploaded:demo", entry_class="DemoPipeline",
        entry_file=str(entry), registered_by="boss", stages=stages,
        db_path=env["db"])


# ── Membaca fase dari kode ───────────────────────────────────────────────

def test_the_phases_are_read_from_the_code_in_order():
    from ui.components.pipeline_upload import extract_registry_metadata

    meta = extract_registry_metadata(SOURCE, "demo.py")
    assert meta["stages"] == ["Preprocessing", "Training", "Evaluating"]


def test_a_package_that_emits_nothing_yields_no_phases():
    """Keadaan yang SAH, bukan isian terlewat."""
    from ui.components.pipeline_upload import extract_registry_metadata

    assert extract_registry_metadata(SILENT, "quiet.py")["stages"] == []


# ── Fase ikut tersimpan ──────────────────────────────────────────────────

def test_the_submission_keeps_the_phases_it_already_read():
    """Sudah terlanjur dihitung saat validasi; membuangnya berarti menghitung
    ulang atau kehilangannya sama sekali."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    body = src.split("algorithms.append({")[1].split("})")[0]
    assert '"stages": list(found.get("stages") or [])' in body


def test_approval_passes_the_phases_of_that_file(env):
    """Fase milik BERKAS, bukan milik paket: satu paket boleh memuat beberapa
    algoritma dengan urutan fase yang berbeda."""
    service = (REPO_ROOT / "orchestrator" / "submission_service.py").read_text(
        encoding="utf-8")
    body = service.split("def _register_approved_pipeline(")[1].split(
        chr(10) + "def ")[0]
    assert 'stages=entry.get("stages") or None' in body


def test_the_registry_row_carries_the_phases(env):
    row = _register(env, SOURCE, name="berfase",
                    stages=["Preprocessing", "Training"])
    assert json.loads(row["stages_json"]) == ["Preprocessing", "Training"]


def test_a_row_without_phases_stays_null(env):
    """Kolom NULLABLE: paket yang tidak memancarkan fase memang tidak punya."""
    assert _register(env, SILENT, name="sunyi")["stages_json"] is None


# ── Entri registry gabungan ──────────────────────────────────────────────

def test_the_merged_entry_exposes_the_phases(env):
    _register(env, SOURCE, name="berfase", stages=["A", "B", "C"])
    entry = next(v for k, v in dr.get_all_pipelines(env["db"]).items()
                 if k.startswith("uploaded."))
    assert entry["stages"] == ["A", "B", "C"]


def test_an_old_row_without_the_column_answers_empty(env):
    """Baris LAMA tidak punya kolomnya sama sekali — jawabannya sama dengan
    "paket ini tidak memancarkan fase", bukan sebuah kesalahan."""
    assert dr._stages_of({"pipeline_id": "x"}) == []
    assert dr._stages_of({"pipeline_id": "x", "stages_json": None}) == []


def test_a_corrupt_value_does_not_break_the_listing(env):
    """Menggambar daftar tidak boleh jatuh karena satu baris rusak."""
    assert dr._stages_of({"pipeline_id": "x", "stages_json": "{bukan json"}) == []
    assert dr._stages_of({"pipeline_id": "x", "stages_json": '"bukan daftar"'}) == []


def test_reading_the_phases_costs_no_extra_query(env):
    """Ia dibaca dari BARIS registry, bukan dengan menengok pengajuannya —
    yang berarti satu kueri tambahan untuk setiap pipeline pada setiap
    penggambaran halaman."""
    body = (REPO_ROOT / "orchestrator" / "dynamic_registry.py").read_text(
        encoding="utf-8").split("def _stages_of(")[1].split(chr(10) + "def ")[0]
    assert "get_connection" not in body
    assert "get_submission" not in body


# ── Pembacanya ───────────────────────────────────────────────────────────

def test_the_progress_tracker_sees_an_uploaded_pipelines_phases(env, monkeypatch):
    """Inti perubahan ini: dahulu SELALU [] untuk pipeline terunggah."""
    import config.settings as settings

    row = _register(env, SOURCE, name="berfase",
                    stages=["Preprocessing", "Training", "Evaluating"])
    monkeypatch.setattr(settings, "DB_PATH", env["db"], raising=False)

    from workers.progress_util import _stages_for

    assert _stages_for(row["pipeline_id"]) == ["Preprocessing", "Training",
                                               "Evaluating"]


def test_the_builtin_pipelines_are_unchanged():
    """Penjaga anti-hampa: mengalihkan sumbernya tidak boleh menghilangkan
    fase pipeline bawaan."""
    from workers.progress_util import _stages_for

    stages = _stages_for("hikari2021.rfc_pipeline")
    assert stages[0] == "Preprocessing"
    assert len(stages) == 4


def test_both_readers_use_the_merged_registry():
    """Satu saja yang tertinggal berarti fase muncul di satu tempat dan hilang
    di tempat lain — lebih membingungkan daripada tidak muncul sama sekali."""
    tracker = (REPO_ROOT / "workers" / "progress_util.py").read_text(
        encoding="utf-8").split("def _stages_for(")[1].split(chr(10) + "def ")[0]
    assert "get_all_pipelines" in tracker
    assert "config.pipeline_registry" not in tracker

    page = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
        encoding="utf-8")
    block = page.split('_stages_list = _reg_entry.get("stages"')[0][-500:]
    assert "get_all_pipelines" in block


# ── Yang dipancarkan == yang dilihat ─────────────────────────────────────

def test_what_is_emitted_is_what_the_tracker_sees(env, monkeypatch):
    """Penjaga yang sesungguhnya.

    Daftar yang tidak kosong tetapi salah isi lebih menyesatkan daripada daftar
    kosong: bar progres akan menghitung fase yang tidak pernah terjadi. Jadi
    yang dibandingkan adalah fase yang benar-benar DIPANCARKAN sebuah eksekusi
    dengan fase yang DILIHAT pelacaknya.
    """
    import config.settings as settings
    from ui.components.pipeline_upload import extract_registry_metadata

    runnable = SOURCE.replace("raise NotImplementedError", "return None")
    detected = extract_registry_metadata(runnable, "demo.py")["stages"]
    row = _register(env, runnable, name="cocok", stages=detected)
    monkeypatch.setattr(settings, "DB_PATH", env["db"], raising=False)

    # Jalankan kelasnya apa adanya dan catat apa yang benar-benar dipancarkan.
    emitted = []
    cls = dr.load_pipeline_class(row["entry_file"], "DemoPipeline",
                                 row["file_hash"])

    class _Input:
        df = [1]                             # cukup untuk melewati percabangan

    cls().run(_Input(), progress=emitted.append)

    from workers.progress_util import _stages_for

    assert emitted == _stages_for(row["pipeline_id"])


# ── Formulir unggah ──────────────────────────────────────────────────────

def test_the_form_shows_the_phases_instead_of_asking_for_them():
    """Meminta pengunggah mengetik ulang urutannya melahirkan sumber kebenaran
    kedua yang dapat berbeda dari kode yang benar-benar berjalan."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    body = src.split("def _render_detected_stages(")[1].split(chr(10) + "def ")[0]
    assert "ap.detected_stages" in body
    assert "text_input" not in body and "selectbox" not in body


def test_the_phase_note_asks_the_uploader_to_check_the_order():
    """Pembacaan statis memberi urutan KEMUNCULAN — fase di dalam percabangan
    atau perulangan dapat menipu."""
    from ui.i18n.core import lookup

    assert "periksa" in lookup("ap.detected_stages", "id").lower()
    assert "check" in lookup("ap.detected_stages", "en").lower()
