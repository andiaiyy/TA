"""
Jenis dataset uji coba: satu penentu, urutan yang jelas, gerbang yang rapat.

Dua cacat terpisah dijaga di sini.

**Cacat 1** — formulir menulis nilai kosong untuk pilihan "lainnya", lalu
penyaring nilai-benar pada pengiriman membuang kuncinya sama sekali. Akibatnya
`dataset_type` TIDAK ADA pada catatan pengajuan, diteruskan sebagai None, dan
gagal sebagai `NOT NULL constraint failed` — kesalahan basis data mentah, di
titik terjauh dari sebabnya.

**Cacat 2** — pasangan (jalur berkas, jenis) dibongkar TERBALIK pada penyusun
pilihan, sehingga daftar mengirim JENIS sebagai jalur berkas. Cacat ini tidak
pernah terlihat karena alurnya selalu gagal lebih dulu pada Cacat 1. Test
`test_the_option_pair_is_not_swapped` adalah penjaganya: pasangan seperti ini
tidak menampakkan diri sampai benar-benar dijalankan.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from database import trials as trial_db
from database.migration import apply_migrations
from database.models import KIND_PIPELINE, SUBMISSION_PENDING
from orchestrator import trial_service as ts

REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

#: Pipeline yang MENDEKLARASIKAN jenis datasetnya di get_info().
DECLARING_SOURCE = '''
from pipelines.base import BasePipeline


class DeclaringPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"dataset_type": "EVE_SURICATA", "algorithm": "Declared"}
'''

#: Pipeline yang TIDAK mendeklarasikan apa pun.
SILENT_SOURCE = '''
from pipelines.base import BasePipeline


class SilentPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"algorithm": "Silent"}
'''


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "dt.db"
    apply_migrations(str(path))
    monkeypatch.setattr("database.db.DB_PATH", str(path), raising=False)
    return str(path)


def _package(tmp_path, source, name="p.py"):
    folder = tmp_path / f"pkg_{abs(hash(source)) % 9999}"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(source, encoding="utf-8")
    return folder


def _submit(db_path, package_dir, *, dataset_type=None, entry="p.py") -> int:
    """Pengajuan; `dataset_type=None` meniru catatan LAMA tanpa kunci itu."""
    metadata = {"entry_filename": entry, "class_name": "X", "name": "demo"}
    if dataset_type is not None:
        metadata["dataset_type"] = dataset_type
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json,
                validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (KIND_PIPELINE, SUBMISSION_PENDING, "andi", "2026-01-01",
             entry, str(package_dir), "a" * 64, 100,
             json.dumps(metadata), json.dumps({"valid": True})))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _item(db_path, sid):
    from orchestrator.submission_service import get_submission

    return get_submission(sid, db_path)


@pytest.fixture
def platform_csv():
    """Berkas platform NYATA, supaya jenisnya benar-benar dapat ditentukan.

    Daftar dataset DI-CACHE. Test lain membuat & menghapus berkas fixture-nya
    sendiri, jadi cache yang tersisa dari test sebelumnya dapat memuat berkas
    yang sudah tidak ada — dan penjaga pasangan di bawah akan gagal karena
    alasan yang keliru. Cache dibersihkan di kedua ujung.
    """
    import pandas as pd

    from ui.views.run_experiment import _dataset_options_cached

    path = Path("storage/datasets/_dtype_fixture.csv")
    pd.DataFrame({"a": range(5), "Label": [0, 1, 0, 1, 0]}).to_csv(
        path, index=False)
    _dataset_options_cached.clear()
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        _dataset_options_cached.clear()


# ── Urutan penentuan ─────────────────────────────────────────────────────

def test_the_platform_file_type_wins(db, tmp_path, monkeypatch):
    """(i) berkas yang benar-benar dibaca mengalahkan deklarasi apa pun."""
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE),
                  dataset_type="HIKARI2021")
    monkeypatch.setattr(ts, "platform_dataset_type",
                        lambda path: "HIKARI2021" if path else "")
    resolved = ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_PLATFORM,
                                       "apa/pun.csv")
    # Pipeline mendeklarasikan EVE_SURICATA, tetapi BERKASnya HIKARI2021.
    assert resolved == "HIKARI2021"


def test_the_declared_type_is_used_when_no_file_type(db, tmp_path):
    """(ii) deklarasi pipeline dipakai bila berkasnya tidak memberi jawaban."""
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE), dataset_type=None)
    resolved = ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_PLATFORM,
                                       None)
    assert resolved == "EVE_SURICATA"


def test_the_submission_metadata_is_the_last_resort(db, tmp_path):
    """(iii) isian kontributor dipakai paling akhir."""
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE),
                  dataset_type="HIKARI2021")
    resolved = ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_PLATFORM,
                                       None)
    assert resolved == "HIKARI2021"


def test_an_attachment_uses_the_pipelines_declared_type(db, tmp_path):
    """Lampiran disediakan UNTUK pipeline itu, jadi jenisnya jenis pipeline."""
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE),
                  dataset_type="HIKARI2021")
    resolved = ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_ATTACHED,
                                       "tidak/dipakai.csv")
    # Jalur lampiran MELEWATI langkah (i) — jenisnya dari deklarasi pipeline.
    assert resolved == "EVE_SURICATA"


def test_an_attachment_falls_back_to_the_submission_metadata(db, tmp_path):
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE),
                  dataset_type="HIKARI2021")
    assert ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_ATTACHED,
                                   None) == "HIKARI2021"


def test_nothing_resolves_when_every_source_is_empty(db, tmp_path):
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE), dataset_type=None)
    assert ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_PLATFORM,
                                   None) == ""


def test_the_unregistered_marker_is_not_a_usable_type(db, tmp_path):
    """"Lainnya" adalah keterangan, bukan jenis yang dapat dipakai."""
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE),
                  dataset_type=ts.DATASET_TYPE_UNREGISTERED)
    assert ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_PLATFORM,
                                   None) == ""


def test_the_marker_is_stored_rather_than_an_empty_string():
    """Ia harus BERMAKNA — dapat dibedakan dari "tidak pernah diisi"."""
    assert ts.DATASET_TYPE_UNREGISTERED
    assert ts.DATASET_TYPE_UNREGISTERED.strip()


# ── Catatan LAMA tetap dapat diproses ────────────────────────────────────

def test_a_legacy_submission_without_the_key_still_resolves(db, tmp_path):
    """Pengajuan lama tidak punya kunci itu sama sekali — dan tetap jalan."""
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE), dataset_type=None)
    item = _item(db, sid)
    assert "dataset_type" not in (item.get("metadata") or {})
    assert ts.resolve_dataset_type(item, ts.SOURCE_PLATFORM, None) == \
        "EVE_SURICATA"


def test_a_legacy_submission_is_never_backfilled(db, tmp_path):
    """Membaca TIDAK menulis: catatan lama tetap apa adanya."""
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE), dataset_type=None)
    ts.resolve_dataset_type(_item(db, sid), ts.SOURCE_PLATFORM, None)
    assert "dataset_type" not in (_item(db, sid).get("metadata") or {})


# ── Penolakan dini, BUKAN kesalahan basis data ───────────────────────────

def test_an_unresolvable_type_is_refused_before_anything_is_written(
        db, tmp_path, monkeypatch):
    """Inilah cacat aslinya: dulu ia jatuh sebagai NOT NULL di basis data."""
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE), dataset_type=None)

    with pytest.raises(ts.TrialError) as excinfo:
        ts.run_trial(sid, dataset_path=None, actor=ADMIN, db_path=db)

    assert getattr(excinfo.value, "key", "") == "td.err_unknown_dataset_type"
    # TIDAK ada catatan setengah jadi.
    assert trial_db.list_trials(sid, db) == []


def test_the_failure_is_not_a_database_error(db, tmp_path, monkeypatch):
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE), dataset_type=None)
    with pytest.raises(ts.TrialError):
        ts.run_trial(sid, dataset_path=None, actor=ADMIN, db_path=db)
    # sqlite3.IntegrityError tidak boleh lagi menjadi wajah kegagalan ini.
    with pytest.raises(Exception) as excinfo:
        ts.run_trial(sid, dataset_path=None, actor=ADMIN, db_path=db)
    assert not isinstance(excinfo.value, sqlite3.Error)


# ── Cacat 2: pasangan jalur/jenis ────────────────────────────────────────

def test_the_option_pair_is_not_swapped(platform_csv):
    """PENJAGA cacat 2 — tertukar tidak terlihat sampai dijalankan.

    Yang dikunci: elemen pertama adalah JALUR berkas yang benar-benar ada,
    elemen kedua adalah JENIS dataset yang dikenal platform.
    """
    from orchestrator.dataset_diagnostics import supported_datasets
    from ui.views.contribute import _trial_dataset_options

    options = _trial_dataset_options()
    assert options, "tidak ada dataset platform untuk diuji"

    known = set(supported_datasets())
    for path, dtype in options:
        assert Path(path).is_file(), f"elemen pertama bukan berkas: {path!r}"
        assert dtype in known, f"elemen kedua bukan jenis dataset: {dtype!r}"


def test_the_upstream_reader_keeps_the_same_order(platform_csv):
    """Pasangan dari pembacanya sendiri berbentuk (jalur, jenis)."""
    from config.settings import DATASETS_DIR
    from orchestrator.dataset_diagnostics import supported_datasets
    from ui.views.run_experiment import _dataset_options_cached

    options, _sizes = _dataset_options_cached(0, str(DATASETS_DIR))
    known = set(supported_datasets())
    for path, dtype in options:
        assert Path(path).is_file(), path
        assert dtype in known, dtype


def test_the_platform_type_lookup_finds_a_real_file(platform_csv):
    """Penentu (i) benar-benar mengenali berkas platform."""
    resolved = ts.platform_dataset_type(str(platform_csv))
    from orchestrator.dataset_diagnostics import supported_datasets

    assert resolved in set(supported_datasets()), resolved


# ── Gerbang pada KEDUA jalur ─────────────────────────────────────────────

def test_the_gate_blocks_both_paths_when_the_type_is_unknown(db, tmp_path):
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE), dataset_type=None)
    item = _item(db, sid)
    for source in (ts.SOURCE_PLATFORM, ts.SOURCE_ATTACHED):
        assert ts.dataset_type_blocker(item, source, None) == \
            "td.err_unknown_dataset_type", source


def test_the_gate_opens_once_the_type_resolves(db, tmp_path):
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE), dataset_type=None)
    item = _item(db, sid)
    for source in (ts.SOURCE_PLATFORM, ts.SOURCE_ATTACHED):
        assert ts.dataset_type_blocker(item, source, None) == "", source


def test_the_view_disables_the_button_on_both_paths():
    """Gerbangnya dipasang di tampilan, bukan hanya di layanan."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "type_blocker = trial_service.dataset_type_blocker(" in src
    assert "disabled=blocked" in src
    assert 'help=t(type_blocker) if type_blocker else None' in src


def test_the_reason_is_always_stated():
    for lang in ("id", "en"):
        from ui.i18n.core import lookup

        assert lookup("td.err_unknown_dataset_type", lang)


# ── Satu penentu, bukan tersebar ─────────────────────────────────────────

def test_the_dataset_type_is_decided_in_exactly_one_place():
    """Penentuan tidak boleh tersebar — satu fungsi, dipakai semua jalur."""
    view = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    trial_step = view.split("def _render_trial_step(")[1].split("\ndef ")[0]
    # Tampilan TIDAK lagi mengambil jenis dari metadata sendiri.
    assert '(item.get("metadata") or {}).get("dataset_type")' not in trial_step
    assert "trial_service.resolve_dataset_type(" in trial_step


def test_run_trial_resolves_the_type_itself(db, tmp_path, monkeypatch):
    """Pemanggil tidak wajib memberi jenis; layanan menentukannya sendiri."""
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE), dataset_type=None)
    monkeypatch.setattr(
        ts, "_execute_trial",
        lambda **kw: {"success": True, "trial_id": kw["trial_id"],
                      "metrics": {}, "duration_s": 0.1, "rows_used": 3})

    out = ts.run_trial(sid, dataset_path="storage/datasets/x.csv",
                       actor=ADMIN, db_path=db)
    assert out["success"] is True
    trial = trial_db.latest_trial(sid, db)
    assert trial["dataset_type"] == "EVE_SURICATA"


# ── Formulir: wajib & bermakna ───────────────────────────────────────────

def test_the_upload_form_requires_a_target_dataset():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "disabled=not may_upload or dtype_choice is None" in src


def test_the_other_choice_is_stored_meaningfully():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "DATASET_TYPE_UNREGISTERED" in src
    assert '"dataset_type": "" if dtype_choice' not in src


def test_the_metadata_filter_never_drops_the_dataset_type():
    """Sebab teknis Cacat 1: kunci penting dibuang karena nilainya kosong."""
    from ui.views.contribute import _submission_metadata

    kept = _submission_metadata({"name": "x", "dataset_type": "",
                                 "algorithm": ""})
    assert "dataset_type" in kept
    assert "algorithm" not in kept          # yang lain tetap disaring


# ── Tidak ada jejak teknis mentah ────────────────────────────────────────

def test_the_trial_call_site_catches_unexpected_errors():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    step = src.split("def _render_trial_step(")[1].split("\ndef ")[0]
    assert "except Exception as e:" in step
    assert 'td.err_trial_failed' in step
    assert "logger.exception(" in step      # log pengembang tetap lengkap


def test_no_submission_handler_catches_only_part_of_the_errors():
    """Penangan yang hanya menangkap sebagian membiarkan sisanya lolos."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    for marker in ("except (TrialDatasetError, OSError) as exc:",
                   "except (AuthError, OSError) as e:",
                   "except (AuthError, PermissionDenied, OSError) as e:"):
        assert marker in src, marker
        tail = src.split(marker)[1][:600]
        assert "except Exception" in tail, marker


@pytest.mark.parametrize("key", ["td.err_trial_failed", "ap.err_unexpected"])
def test_the_fallback_messages_exist_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── Bacaan yang gagal: halaman tidak jatuh, gerbang MENUTUP ──────────────
# Sebelumnya dua pembacaan pada alur peninjauan sama sekali tidak berpenangan:
# riwayat uji terakhir dan gerbang persetujuan, keduanya membaca basis data.
# Sebuah `sqlite3.OperationalError` di sana lolos sebagai jejak teknis mentah.

def test_a_failed_read_returns_the_stated_fallback(caplog):
    import logging

    import ui.views.contribute as contrib

    def _boom():
        raise sqlite3.OperationalError("database is locked")

    with caplog.at_level(logging.ERROR):
        out = contrib._safe_read("riwayat", _boom, default="cadangan")
    assert out == "cadangan"


def test_a_failed_read_still_logs_the_full_detail(caplog):
    """Pengguna melihat kalimat; pengembang tetap melihat rinciannya."""
    import logging

    import ui.views.contribute as contrib

    def _boom():
        raise sqlite3.OperationalError("database is locked")

    with caplog.at_level(logging.ERROR):
        contrib._safe_read("gerbang persetujuan", _boom, default=None)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "gerbang persetujuan" in joined
    assert any(r.exc_info for r in caplog.records)   # traceback ikut tercatat


def test_a_successful_read_passes_its_arguments_through():
    import ui.views.contribute as contrib

    assert contrib._safe_read("x", lambda a, b=0: a + b, 2, b=3,
                              default=None) == 5


def test_an_unreadable_gate_closes_rather_than_opens():
    """Fail-closed: "tidak tahu apakah sudah diuji" bukan "boleh disetujui"."""
    import ui.views.contribute as contrib

    def _boom(_item):
        raise sqlite3.OperationalError("database is locked")

    gate = contrib._safe_read("gerbang persetujuan", _boom, {"id": 1},
                              default="ap.err_gate_unreadable")
    assert gate, "gerbang yang tidak terbaca harus MENUTUP"
    from ui.i18n.core import lookup
    for lang in ("id", "en"):
        assert lookup(gate, lang), (gate, lang)


def test_the_unreadable_marker_is_distinct_from_no_trial():
    """"Tidak ada uji" dan "tidak dapat dibaca" berbeda tindakannya."""
    import ui.views.contribute as contrib

    assert contrib._UNREADABLE is not None
    assert contrib._UNREADABLE is not False


# ── Penyisiran: setiap aksi berisiko punya penangan penutup ──────────────

#: Fungsi yang MENGUBAH keadaan (basis data dan/atau berkas). Kegagalannya
#: bukan hanya AuthError: OSError, kesalahan basis data, dan
#: DynamicRegistryError semuanya mungkin, dan tidak satu pun turunan AuthError.
_RISKY_CALLS = {
    "approve_submission", "reject_submission", "submit_pipeline",
    "submit_dataset", "run_trial", "save_dataset_upload",
    "attach_to_submission",
    # Penyunting versi dirender DI DALAM alur peninjauan yang sama, jadi
    # kebocoran di sana sampai ke peninjau lewat halaman yang sama.
    "save_new_version", "set_pipeline_active",
}

#: Berkas tampilan yang ikut disisir. Keduanya bagian dari satu alur.
_SWEPT_VIEWS = ("contribute.py", "manage_pipelines.py")


def _call_names(node) -> set:
    import ast

    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            fn = child.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name:
                found.add(name)
    return found


def _has_catch_all(handlers) -> bool:
    import ast

    for handler in handlers:
        if handler.type is None:
            return True
        names = {getattr(handler.type, "id", None)}
        if isinstance(handler.type, ast.Tuple):
            names |= {getattr(e, "id", None) for e in handler.type.elts}
        if names & {"Exception", "BaseException"}:
            return True
    return False


def test_every_risky_call_site_has_a_closing_handler():
    """Penjaga struktural, bukan daftar penanda.

    Aturan yang diuji: setiap `try` pada halaman kontribusi yang memanggil
    fungsi pengubah keadaan HARUS punya penangan penutup. Ditulis atas pohon
    sintaks, bukan atas potongan teks, supaya penangan baru yang hanya
    menangkap sebagian tetap tertangkap saat kode berubah.
    """
    import ast

    offenders = []
    seen = 0
    for filename in _SWEPT_VIEWS:
        src = (REPO_ROOT / "ui" / "views" / filename).read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        guarded_lines = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body = ast.Module(body=node.body, type_ignores=[])
            for call in ast.walk(body):
                if isinstance(call, ast.Call):
                    guarded_lines.add(call.lineno)
            risky = _call_names(body) & _RISKY_CALLS
            if risky:
                seen += 1
                if not _has_catch_all(node.handlers):
                    offenders.append((filename, sorted(risky), node.lineno))
        # Aksi berisiko yang tidak berada di dalam `try` sama sekali juga
        # bocor — dan itu tidak akan terlihat dari memeriksa penangan saja.
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "attr", None) or getattr(
                call.func, "id", None)
            if name in _RISKY_CALLS and call.lineno not in guarded_lines:
                offenders.append((filename, [name], call.lineno))

    assert seen >= 7, (
        "penjaga ini menjadi tanpa arti bila tidak menemukan aksi berisiko "
        f"apa pun — hanya {seen} ditemukan")
    assert not offenders, (
        "aksi berisiko tanpa penangan penutup — kesalahan sisanya akan "
        f"lolos mentah ke pengguna: {offenders}")


def test_the_approval_and_rejection_handlers_report_a_readable_sentence():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    card = src.split("def _render_submission_review_card(")[1].split(
        "\ndef ")[0]
    assert card.count("ap.err_unexpected") >= 2      # setujui DAN tolak
    assert card.count("logger.exception(") >= 2


@pytest.mark.parametrize("key", ["ap.err_gate_unreadable",
                                 "trial.err_history_unreadable"])
def test_the_new_fallback_messages_exist_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── Kegagalan tidak menyisakan catatan setengah jadi ─────────────────────

def test_an_environment_failure_still_closes_the_trial_record(
        db, tmp_path, monkeypatch, platform_csv):
    """`run_bounded` tidak melempar untuk kegagalan PIPELINE — tetapi ia masih
    dapat gagal karena sebab lingkungan (proses anak tidak dapat dijalankan).

    Tanpa penangan, catatan uji tertinggal pada QUEUED selamanya: sebuah
    catatan tanpa kesimpulan, yang justru merupakan keadaan setengah jadi yang
    harus dicegah.
    """
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE),
                  dataset_type="HIKARI2021")

    def _cannot_spawn(**kwargs):
        raise OSError("tidak dapat menjalankan proses anak")

    monkeypatch.setattr("workers.trial_runner.run_bounded", _cannot_spawn)
    out = ts.run_trial(sid, dataset_path=str(platform_csv), actor=ADMIN,
                       db_path=db)

    assert out["success"] is False
    rows = trial_db.list_trials(sid, db)
    assert len(rows) == 1
    # Berkesudahan: BUKAN QUEUED, dan sebabnya tercatat.
    assert rows[0]["status"] == trial_db.STATUS_FAILED
    assert rows[0]["finished_at"]
    assert rows[0]["error_kind"] == "OSError"


def test_no_trial_record_survives_a_refusal_before_execution(
        db, tmp_path, monkeypatch):
    """Penolakan sebelum eksekusi tidak menulis catatan MAUPUN berkas."""
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, SILENT_SOURCE), dataset_type=None)

    before = sorted(p.name for p in ts.TRIAL_ROOT.iterdir()) \
        if ts.TRIAL_ROOT.is_dir() else []
    with pytest.raises(ts.TrialError):
        ts.run_trial(sid, dataset_path=None, actor=ADMIN, db_path=db)
    after = sorted(p.name for p in ts.TRIAL_ROOT.iterdir()) \
        if ts.TRIAL_ROOT.is_dir() else []

    assert trial_db.list_trials(sid, db) == []
    assert before == after                   # tidak ada folder artefak baru


def test_every_recorded_trial_reaches_a_conclusion(db, tmp_path, monkeypatch,
                                                   platform_csv):
    """Sifat yang dijaga: catatan uji yang ADA selalu punya kesimpulan.

    Ini yang membuat "tidak ada catatan setengah jadi" dapat diperiksa, bukan
    sekadar dijanjikan.
    """
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE),
                  dataset_type="HIKARI2021")

    monkeypatch.setattr(
        "workers.trial_runner.run_bounded",
        lambda **kw: {"ok": False, "stage": "menjalankan pipeline",
                      "kind": "ValueError", "message": "gagal",
                      "rows_used": 10})
    ts.run_trial(sid, dataset_path=str(platform_csv), actor=ADMIN, db_path=db)

    for row in trial_db.list_trials(sid, db):
        assert row["status"] in (trial_db.STATUS_PASSED,
                                 trial_db.STATUS_FAILED), row["status"]
        assert row["finished_at"], "catatan tanpa waktu selesai"


def test_every_stage_name_a_trial_can_emit_is_translatable():
    """Nama tahap yang tidak terdaftar tampil APA ADANYA.

    Akibatnya satu kalimat Inggris memuat potongan Indonesia — cacat yang
    sudah pernah diperbaiki pada catatan kaki laporan PDF dan pada jalur uji
    coba. Penjaga ini menutupnya untuk SETIAP tahap, termasuk tahap baru.
    """
    from ui.components.validator_messages import TRIAL_STAGE_KEYS
    from ui.i18n.core import lookup
    from workers import trial_runner

    emitted = {value for name, value in vars(trial_runner).items()
               if name.startswith("STAGE_") and isinstance(value, str)}
    assert emitted, "tidak ada tahap yang ditemukan — penjaga jadi tanpa arti"

    for stage in sorted(emitted):
        key = TRIAL_STAGE_KEYS.get(stage)
        assert key, f"tahap tanpa kunci terjemahan: {stage!r}"
        for lang in ("id", "en"):
            assert lookup(key, lang), (stage, lang)


def test_the_setup_stage_is_reported_by_its_constant(db, tmp_path,
                                                     monkeypatch, platform_csv):
    """Kegagalan lingkungan memakai nama tahap dari konstanta, bukan teks."""
    from workers.trial_runner import STAGE_SETUP

    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    sid = _submit(db, _package(tmp_path, DECLARING_SOURCE),
                  dataset_type="HIKARI2021")

    def _cannot_spawn(**kwargs):
        raise OSError("tidak dapat menjalankan proses anak")

    monkeypatch.setattr("workers.trial_runner.run_bounded", _cannot_spawn)
    ts.run_trial(sid, dataset_path=str(platform_csv), actor=ADMIN, db_path=db)

    assert trial_db.list_trials(sid, db)[0]["error_stage"] == STAGE_SETUP
