"""Paket yang ada di depan mata, dilaporkan hilang.

``submissions.stored_path`` dicatat sebagai jalur ABSOLUT saat pengajuannya
masuk. Platform ini dijalankan bergantian di dalam container
(``/app/storage/...``) dan langsung di host (``D:\\...\\storage\\...``), dengan
folder ``storage/`` yang SAMA dipasang ke keduanya — jadi jalur yang benar di
satu lingkungan salah di lingkungan lain.

Akibatnya bukan pesan galat, melainkan kekosongan yang meyakinkan: dua
pengajuan nyata terbaca **nol berkas**, salah satunya masih `pending`. Peninjau
membuka paketnya, melihatnya kosong, dan tidak punya cara mengetahui bahwa
berkasnya ada — beberapa sentimeter jauhnya di disk yang sama.

Yang tetap benar di kedua lingkungan adalah EKORNYA: bagian setelah
``uploaded_pipelines/``. Itulah yang ditambatkan ulang — dan hanya bila
hasilnya benar-benar ada, sehingga tidak ada letak yang pernah dikarang.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.submission_service import stored_location


@pytest.fixture
def roots(monkeypatch, tmp_path):
    """Akar unggahan yang berlaku SEKARANG, dengan satu paket di dalamnya."""
    from orchestrator import submission_service as ss

    pipelines = tmp_path / "uploaded_pipelines"
    datasets = tmp_path / "uploaded_datasets"
    package = pipelines / "approved" / "paket_saya"
    package.mkdir(parents=True)
    (package / "entry.py").write_text("x = 1", encoding="utf-8")
    datasets.mkdir(parents=True)

    monkeypatch.setattr(ss, "PIPELINE_ROOT", pipelines)
    monkeypatch.setattr(ss, "DATASET_ROOT", datasets)
    return {"pipelines": pipelines, "datasets": datasets, "package": package}


# ── Jalur dari lingkungan LAIN ───────────────────────────────────────────

def test_a_container_path_finds_the_package_on_the_host(roots):
    """Inilah keadaan dua pengajuan nyata di basis data ini."""
    assert stored_location(
        "/app/storage/uploaded_pipelines/approved/paket_saya") == roots["package"]


def test_a_windows_path_finds_the_package_in_the_container(roots):
    """Arah sebaliknya, yang terjadi begitu stack Docker dinyalakan lagi."""
    raw = "D:" + chr(92) + "kerja" + chr(92) + "storage" + chr(92) + \
        "uploaded_pipelines" + chr(92) + "approved" + chr(92) + "paket_saya"

    assert stored_location(raw) == roots["package"]


def test_a_dataset_path_uses_the_dataset_root(roots):
    berkas = roots["datasets"] / "pending" / "data.csv"
    berkas.parent.mkdir(parents=True)
    berkas.write_text("a,b", encoding="utf-8")

    assert stored_location(
        "/app/storage/uploaded_datasets/pending/data.csv") == berkas


# ── Yang TIDAK boleh berubah ─────────────────────────────────────────────

def test_a_path_that_exists_is_used_exactly_as_recorded(roots):
    """Selama jalurnya benar, tidak ada yang ditafsirkan ulang."""
    assert stored_location(str(roots["package"])) == roots["package"]


def test_it_never_invents_a_location(roots):
    """Ekor yang tidak ditemukan dikembalikan apa adanya — sebuah jalur yang
    tidak ada, yang akan dilaporkan pemanggilnya sebagai tidak ada. Menebak
    letak lain akan membuat paket yang SALAH terbuka atas nama pengajuan ini.
    """
    hilang = "/app/storage/uploaded_pipelines/approved/tidak_pernah_ada"

    assert stored_location(hilang) == Path(hilang)
    assert not stored_location(hilang).exists()


def test_a_path_outside_the_upload_areas_is_left_alone(roots):
    assert stored_location("/etc/passwd") == Path("/etc/passwd")
    assert stored_location("") == Path("")
    assert stored_location(None) == Path("")


def test_the_tail_starts_at_the_first_anchor_the_root_boundary(roots):
    """Kemunculan PERTAMA adalah batas akarnya; yang berikutnya bagian dari
    ekor. Sebuah folder yang kebetulan bernama sama dengan akarnya karena itu
    tetap utuh di dalam ekor, bukan memotongnya di tempat yang salah."""
    nested = roots["pipelines"] / "approved" / "uploaded_pipelines"
    nested.mkdir(parents=True)
    (nested / "x.py").write_text("x = 1", encoding="utf-8")

    got = stored_location(
        "/app/storage/uploaded_pipelines/approved/uploaded_pipelines")
    assert got == nested


# ── Berkas pipeline yang terdaftar ikut berpindah ────────────────────────
# `registered_pipelines.entry_file` menyimpan jalur absolut yang sama. Di
# lingkungan yang lain berkasnya tidak ditemukan, hash-nya karena itu kosong,
# dan katalog menandai pipeline yang berkasnya UTUH sebagai "bermasalah".

SOURCE = chr(10).join([
    "from pipelines.base import BasePipeline",
    "",
    "",
    "class DemoPipeline(BasePipeline):",
    "    def run(self, pipeline_input, progress=None):",
    "        return None",
    "",
    "    def get_info(self):",
    '        return {"algorithm": "Demo"}',
    "",
])


@pytest.fixture
def registered(roots):
    """Sebuah berkas pipeline yang ADA, dicatat dengan jalur lingkungan lain."""
    from orchestrator.dynamic_registry import file_sha256

    entry = roots["package"] / "demo_pipeline.py"
    entry.write_text(SOURCE, encoding="utf-8")
    return {"entry_file": ("/app/storage/uploaded_pipelines/approved/"
                           "paket_saya/demo_pipeline.py"),
            "entry_class": "DemoPipeline",
            "file_hash": file_sha256(entry),
            "path": entry}


def test_a_registered_pipeline_loads_from_the_other_environment(registered):
    from orchestrator.dynamic_registry import load_pipeline_class

    cls = load_pipeline_class(registered["entry_file"],
                              registered["entry_class"],
                              registered["file_hash"])

    assert cls().get_info()["algorithm"] == "Demo"


def test_its_state_is_ok_not_broken(registered):
    """Kartu katalog membaca keadaan ini. Sebelum penambatan, sebuah pipeline
    yang siap jalan tampil dengan label "bermasalah"."""
    from ui.components.registry_view import STATE_OK, version_state

    state, reason = version_state(registered)

    assert state == STATE_OK, reason


def test_a_genuinely_changed_file_is_still_refused(registered):
    """Penambatan tidak boleh melonggarkan pemeriksaan hash: berkas yang
    BERUBAH tetap ditolak, di lingkungan mana pun jalurnya dicatat."""
    from ui.components.registry_view import STATE_OK, version_state

    registered["path"].write_text(SOURCE + chr(10) + "# diubah", encoding="utf-8")
    state, _reason = version_state(registered)

    assert state != STATE_OK


# ── Pemakainya benar-benar memakainya ────────────────────────────────────

@pytest.mark.parametrize("module, needle", [
    ("orchestrator/submission_service.py", "stored_location(item"),
    ("orchestrator/trial_service.py", "stored_location(item"),
    ("orchestrator/trial_dataset_service.py", "stored_location(info"),
])
def test_the_readers_go_through_the_helper(module, needle):
    """Satu pembaca yang terlewat akan tetap melaporkan paket itu hilang."""
    source = (Path(__file__).resolve().parents[1] / module).read_text(
        encoding="utf-8")

    assert needle in source
    # …dan tidak ada lagi pembacaan mentah yang menyentuh disk.
    assert 'Path(item["stored_path"])' not in source
    assert 'Path(info["stored_path"])' not in source


def test_the_bound_dataset_is_found_too():
    """Dataset milik research pipeline kontribusi disimpan dengan jalur absolut
    yang sama, jadi ia ikut hilang di lingkungan yang lain."""
    source = (Path(__file__).resolve().parents[1]
              / "orchestrator" / "research_registry.py").read_text(
        encoding="utf-8")

    assert "stored_location(path)" in source
