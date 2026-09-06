"""Rantai unggah → tinjau → aktif → jalankan, dan apa yang DIKATAKANNYA.

Mekanismenya sudah utuh dan terbukti: sebuah tes lain menjalankan seluruh
rantai sampai eksperimen sungguhan. Yang membuatnya terasa tidak sinkron bukan
alirannya, melainkan bahwa tidak ada satu pun titik yang mengatakan apa yang
baru saja terjadi:

1. **Konfirmasi yang tidak menuntun ke mana pun.** Setelah Setujui, kalimatnya
   menyebut pengenal mesin dan hash berkas. Keduanya benar; keduanya tidak
   menjawab "berhasil, lalu ada di mana?".

2. **Dua halaman, dua kebenaran.** Tabel "Aktif" menyebut sebuah pipeline
   `aktif`, sementara halaman Jalankan Eksperimen menyebutnya belum dapat
   dijalankan karena datasetnya tidak ada. Keduanya benar menurut ukurannya
   sendiri, dan pembacanya menyimpulkan sistemnya tidak sinkron.

3. **Jalan keluar yang mustahil.** Kalimat "belum ada dataset" menyuruh
   mengunggah lewat halaman Tambah Pipeline & Dataset. Untuk research pipeline
   KONTRIBUSI itu tidak akan pernah berhasil: ia hanya memakai dataset yang
   terikat pada paketnya, bukan isi ``storage/datasets/``.
"""
from __future__ import annotations

import pytest

from ui.components import registry_view as rv


#: Hash yang cocok dengan `_hash_ok` di bawah — versi yang SEHAT, sehingga
#: yang diuji memang kalimat tentang datasetnya, bukan "berkas hilang".
_HASH = "a" * 64


def _hash_ok(_path):
    return _HASH


def _versions(dataset_type="uploaded:demo", active=True, submission_id=7):
    return [{"pipeline_id": "uploaded.demo@v1", "version": 1,
             "dataset_type": dataset_type, "algorithm": "Random Forest",
             "entry_file": "x.py", "entry_class": "P", "file_hash": _HASH,
             "registered_by": "bos", "registered_at": "2026-09-06T00:00:00",
             "active": 1 if active else 0, "submission_id": submission_id}]


def _summary(dataset_reader, **kw):
    return rv.pipeline_summary("demo", _versions(**kw), {},
                               hash_reader=_hash_ok,
                               dataset_reader=dataset_reader)


# ── 1. Aktif belum tentu dapat dijalankan, dan itu dikatakan ─────────────

def test_the_summary_carries_whether_it_can_actually_run():
    summary = _summary(lambda _dt: False)

    assert summary["is_active"] is True
    assert summary["runnable"] is False


def test_the_status_column_stops_claiming_active_is_enough():
    rows = rv.active_table_rows([_summary(lambda _dt: False)])

    assert "aktif" in rows[0]["status_text"]
    assert "belum ada datasetnya" in rows[0]["status_text"]


def test_a_runnable_pipeline_says_nothing_extra():
    """Keterangan tambahan hanya muncul ketika ia berarti sesuatu."""
    rows = rv.active_table_rows([_summary(lambda _dt: True)])

    assert rows[0]["status_text"] == "aktif"


def test_an_inactive_pipeline_is_not_nagged_about_datasets():
    """Yang sengaja dimatikan tidak sedang menunggu dataset apa pun."""
    rows = rv.active_table_rows([_summary(lambda _dt: False, active=False)])

    assert "belum ada datasetnya" not in rows[0]["status_text"]


def test_a_doubtful_reader_never_accuses():
    """Pembaca yang melempar tidak boleh berubah menjadi tuduhan."""
    def broken(_dt):
        raise RuntimeError("registry tidak terbaca")

    assert _summary(broken)["runnable"] is True


def test_the_summary_remembers_which_submission_it_came_from():
    """Riwayat hidupnya dapat ditelusuri balik tanpa menebak dari nama."""
    assert _summary(lambda _dt: True, submission_id=42)["submission_id"] == 42


# ── 2. Jalan keluar yang benar untuk masing-masing jenis ─────────────────

def test_a_contributed_pipeline_is_not_told_to_do_the_impossible(monkeypatch):
    from ui.components import pipeline_catalog as pc

    monkeypatch.setattr(pc, "has_dataset_for", lambda _dt: False)
    _state, reason = pc.entry_state(
        "uploaded.demo@v1", {"uploaded": True,
                             "dataset_type": "uploaded:demo"})

    assert "Tambah Pipeline & Dataset" not in reason
    assert "Unggah dataset" not in reason
    # Yang benar: datasetnya datang dari paketnya sendiri.
    assert "dilampirkan" in reason or "terikat" in reason.lower()


def test_a_builtin_type_keeps_the_sentence_that_does_work(monkeypatch):
    from ui.components import pipeline_catalog as pc

    monkeypatch.setattr(pc, "has_dataset_for", lambda _dt: False)
    _state, reason = pc.entry_state(
        "uploaded.demo@v1", {"uploaded": True, "dataset_type": "HIKARI2021"})

    assert "Tambah Pipeline & Dataset" in reason


@pytest.mark.parametrize("key", [
    "re.cat_no_dataset_reason_uploaded", "rv.status_no_dataset",
    "ap.msg_approved_live", "ap.msg_approved_no_dataset",
])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


# ── 3. Konfirmasi persetujuan yang menuntun ──────────────────────────────

def test_the_confirmation_names_the_research_and_where_to_find_it(monkeypatch):
    import ui.views.contribute as contrib

    monkeypatch.setattr(
        "orchestrator.dynamic_registry.list_registered",
        lambda *a, **k: [dict(_versions()[0], submission_id=7),
                         dict(_versions()[0], submission_id=7,
                              pipeline_id="uploaded.demo_dt@v1")])
    monkeypatch.setattr("orchestrator.research_registry.display_name_for",
                        lambda dt, db_path=None: "Budi (2026) — Deteksi Anomali")
    monkeypatch.setattr("ui.components.pipeline_catalog.has_dataset_for",
                        lambda _dt: True)

    text = contrib._latest_registration({"id": 7})

    assert "Deteksi Anomali" in text
    assert "Jalankan Eksperimen" in text
    assert "2 algoritma" in text
    # Pengenal mesin & hash tidak lagi menjadi isi kalimatnya.
    assert "uploaded.demo@v1" not in text


def test_the_confirmation_admits_when_it_cannot_be_run(monkeypatch):
    """Kalau datasetnya justru tidak ada, peninjau tahu SEKARANG — bukan
    menemukannya sendiri nanti di halaman lain."""
    import ui.views.contribute as contrib

    monkeypatch.setattr("orchestrator.dynamic_registry.list_registered",
                        lambda *a, **k: _versions())
    monkeypatch.setattr("orchestrator.research_registry.display_name_for",
                        lambda dt, db_path=None: "Deteksi Anomali")
    monkeypatch.setattr("ui.components.pipeline_catalog.has_dataset_for",
                        lambda _dt: False)

    text = contrib._latest_registration({"id": 7})

    assert "belum dapat dijalankan" in text
    assert "Jalankan Eksperimen" not in text     # tidak menyuruh ke sana
