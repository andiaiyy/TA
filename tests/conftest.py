"""
Shared pytest fixtures.

Project packages are importable via `pip install -e .` (editable install).
"""
import pytest


# ── Paket unggahan menulis ke tmp, bukan ke storage/ sungguhan ────────────
# `config/settings.py` menghitung `STORAGE_DIR` dari letak repo dan tidak dapat
# ditimpa environment (hanya `DB_PATH` yang bisa), sementara area penampungan
# dihitung SEKALI saat modulnya diimpor. Akibatnya setiap tes yang mengajukan
# atau meninjau sebuah paket menaruh berkasnya di `storage/uploaded_pipelines/`
# milik pengguna: satu kali suite meninggalkan 8 folder di `approved/` dan
# puluhan di `rejected/`, yang menumpuk menjadi ratusan lintas run — bercampur
# dengan paket sungguhan yang memang dirujuk basis data.
#
# Pengalihan ada DI SINI, bukan di `config/`: ini sifat lingkungan pengujian,
# bukan sifat aplikasi. Berkas tes yang sudah mengalihkan akarnya sendiri tetap
# menang — ia menimpa nilai yang dipasang di bawah ini.
#
# Satu direktori untuk SATU sesi, bukan satu per tes: dengan begitu perilaku
# penamaannya (paket bernama sama mendapat akhiran `__2`, `__3`, …) tetap
# persis seperti saat berbagi satu folder sungguhan.

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_storage: tes ini memang menguji LETAK sungguhan area unggahan, "
        "jadi pengalihan ke tmp tidak dipasang untuknya")


@pytest.fixture(scope="session")
def _uploads_base(tmp_path_factory):
    return tmp_path_factory.mktemp("uploads")


@pytest.fixture(autouse=True)
def _uploads_stay_out_of_real_storage(request, monkeypatch, _uploads_base):
    # Sebagian kecil tes menjadikan letak sungguhan itu sebagai SUBJEKNYA —
    # "berkas kontribusi tidak boleh mendarat di paket `pipelines/`". Bagi
    # mereka pengalihan ini akan menyembunyikan justru yang diperiksa.
    if request.node.get_closest_marker("real_storage"):
        return

    from orchestrator import submission_service as ss

    pipeline_root = _uploads_base / "uploaded_pipelines"
    dataset_root = _uploads_base / "uploaded_datasets"

    monkeypatch.setattr(ss, "PIPELINE_ROOT", pipeline_root, raising=False)
    monkeypatch.setattr(ss, "DATASET_ROOT", dataset_root, raising=False)
    monkeypatch.setattr(ss, "SUBMISSION_DIRS", {
        kind: {status: (pipeline_root if kind == ss.KIND_PIPELINE
                        else dataset_root) / path.name
               for status, path in per_status.items()}
        for kind, per_status in ss.SUBMISSION_DIRS.items()
    }, raising=False)

    # Akar turunan, dihitung dari PIPELINE_ROOT saat modulnya diimpor — jadi
    # menambal yang di atas saja tidak mengalihkan keduanya.
    from orchestrator import pipeline_versions as pv
    from orchestrator import trial_dataset_service as tds

    monkeypatch.setattr(tds, "TRIAL_DATASET_ROOT",
                        pipeline_root / "trial_datasets", raising=False)
    monkeypatch.setattr(pv, "VERSIONS_ROOT", pipeline_root / "versions",
                        raising=False)

    # Modul UI hanya ditambal bila memang SUDAH dimuat: mengimpornya di sini
    # akan menarik Streamlit ke dalam setiap tes, termasuk yang tidak
    # menyentuh antarmuka sama sekali.
    import sys

    for module, attr, target in (
            ("ui.components.pipeline_upload", "STAGING_DIR", pipeline_root),
            ("ui.views.contribute", "UPLOAD_TMP_DIR",
             _uploads_base / "_upload_tmp"),
    ):
        loaded = sys.modules.get(module)
        if loaded is not None and hasattr(loaded, attr):
            monkeypatch.setattr(loaded, attr, target, raising=False)
