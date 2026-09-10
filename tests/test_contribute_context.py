"""Tests for the contextual panels on "Add Pipeline & Dataset".

The page answers two questions before the user tries anything: what happens
after I upload, and what usually goes wrong. Everything shown is *computed* —
from the submission table and the real check names — so the page can never
drift from the platform it describes.

It used to answer two more, with three counted numbers and a line stating the
user's rights. Both were removed: the numbers describe the platform rather than
guide an action, and the rights line repeats what the live-or-dead controls
already say. Their tests went with them; what survives here is what the page
still shows.
"""
from pathlib import Path

import pytest

from ui.components.contribute_context import (
    AFTER_UPLOAD_FLOW, AFTER_UPLOAD_FLOW_ALT, submission_counts,
)
from ui.components.instructions import (
    ENTRY_POINT_RULE, common_dataset_mistakes, common_pipeline_mistakes,
    pipeline_skeleton,
)
from ui.i18n.core import lookup

REPO_ROOT = Path(__file__).resolve().parents[1]

VISITOR = None
PENDING = {"username": "baru", "role": "contributor", "status": "pending"}
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}


# ── the submission queue summary ──────────────────────────────────────────

def test_visitors_have_no_queue():
    assert submission_counts(VISITOR) == {}
    assert submission_counts({"role": "contributor"}) == {}


def test_queue_counts_group_by_status(monkeypatch):
    import orchestrator.submission_service as svc
    monkeypatch.setattr(svc, "list_submissions", lambda **kw: [
        {"status": "pending"}, {"status": "pending"}, {"status": "approved"},
    ])
    assert submission_counts(CONTRIBUTOR) == {"pending": 2, "approved": 1}


def test_queue_only_asks_for_the_users_own_submissions(monkeypatch):
    """Tidak menyaring tampilan orang lain — hanya meminta miliknya sendiri."""
    import orchestrator.submission_service as svc
    seen: dict = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(svc, "list_submissions", _spy)
    submission_counts(CONTRIBUTOR)
    assert seen == {"submitted_by": "rina"}


def test_queue_survives_a_broken_table(monkeypatch):
    import orchestrator.submission_service as svc

    def _boom(**kw):
        raise RuntimeError("tabel hilang")

    monkeypatch.setattr(svc, "list_submissions", _boom)
    assert submission_counts(CONTRIBUTOR) == {}


def test_after_upload_flow_separates_data_from_code():
    """Dataset tersimpan langsung; hanya pipeline yang ditinjau."""
    labels = [label for _icon, label in AFTER_UPLOAD_FLOW]
    assert len(AFTER_UPLOAD_FLOW) == 4
    assert "Dataset tersimpan" in labels
    assert "Pipeline ditinjau" in labels
    # Label tahap pemeriksaan kini menyebut OBJEK-nya ("Periksa berkas");
    # "Periksa otomatis" dulu tidak menjelaskan apa yang diperiksa.
    assert "Periksa berkas" in labels
    assert labels.index("Periksa berkas") < labels.index("Dataset tersimpan")
    # Teks alternatif kini kunci katalog; yang diuji kalimatnya.
    assert "tersimpan" in lookup(AFTER_UPLOAD_FLOW_ALT, "id")
    assert "kode yang dieksekusi" in lookup(AFTER_UPLOAD_FLOW_ALT, "id")


# ── the worked example is built from the contract constants ───────────────

def test_skeleton_uses_the_validator_constants():
    from orchestrator.pipeline_validator import (
        BASE_CLASS_NAME, EXPECTED_INFO_KEYS, REQUIRED_METHODS, RUN_FIRST_PARAM,
        RUN_PROGRESS_PARAM,
    )

    code = pipeline_skeleton()
    assert f"({BASE_CLASS_NAME})" in code
    for method in REQUIRED_METHODS:
        assert f"def {method}(" in code
    assert f"{RUN_FIRST_PARAM}, {RUN_PROGRESS_PARAM}=None" in code
    for key in EXPECTED_INFO_KEYS:
        assert f'"{key}"' in code


def test_skeleton_is_valid_python():
    """Contoh yang tidak dapat diurai justru menyesatkan."""
    import ast
    ast.parse(pipeline_skeleton())


def test_skeleton_imports_the_real_contract_modules():
    from contracts.pipeline_contracts import PipelineResult
    from pipelines.base import BasePipeline

    code = pipeline_skeleton()
    assert f"from {BasePipeline.__module__} import" in code
    assert f"from {PipelineResult.__module__} import" in code


def test_skeleton_stays_short():
    assert len(pipeline_skeleton().splitlines()) <= 20


# ── common mistakes are derived from real checks ──────────────────────────

def test_pipeline_mistakes_reference_checks_that_actually_exist():
    from ui.components.instructions import _PIPELINE_MISTAKE_ORDER
    from ui.components.pipeline_upload import _CAUSE_PRIORITY

    for name in _PIPELINE_MISTAKE_ORDER:
        assert name == ENTRY_POINT_RULE or name in _CAUSE_PRIORITY, name


def test_pipeline_mistakes_are_a_short_list():
    items = common_pipeline_mistakes()
    assert 3 <= len(items) <= 5
    assert len(set(items)) == len(items)
    for item in items:
        assert "\n" not in item


def test_pipeline_mistakes_quote_the_validator_constants():
    from orchestrator.pipeline_validator import (
        BASE_CLASS_NAME, FORBIDDEN_CALLS, FORBIDDEN_MODULES, REQUIRED_METHODS,
    )

    text = " ".join(common_pipeline_mistakes(limit=10))
    assert BASE_CLASS_NAME in text
    assert f"{REQUIRED_METHODS[0]}()" in text
    assert sorted(FORBIDDEN_MODULES)[0] in text
    assert sorted(FORBIDDEN_CALLS)[0] in text


def test_pipeline_mistakes_cover_the_causes_the_page_promises():
    """Butir yang dijanjikan: kelas dasar, metode wajib, modul terlarang,
    lebih dari satu titik masuk."""
    text = " ".join(common_pipeline_mistakes()).lower()
    assert "turunan" in text or "mewarisi" in text
    assert "metode wajib" in text
    assert "terlarang" in text
    assert "titik masuk" in text


def test_a_renamed_check_drops_out_instead_of_lying(monkeypatch):
    """Kalau nama check berubah, butirnya HILANG — tidak tertinggal sebagai
    teks statis yang menjanjikan pemeriksaan yang sudah tidak ada."""
    import ui.components.pipeline_upload as up
    monkeypatch.setattr(up, "_CAUSE_PRIORITY", ("sintaks Python",))

    items = common_pipeline_mistakes(limit=10)
    assert len(items) == 2                   # titik masuk + sintaks Python
    assert not any("metode wajib" in i.lower() for i in items)


def test_dataset_mistakes_come_from_the_diagnosis_checks():
    from orchestrator.dataset_diagnostics import _CHECK_TITLES

    items = common_dataset_mistakes(limit=10)
    assert len(items) == len(_CHECK_TITLES)
    for title in _CHECK_TITLES.values():
        assert any(title in item for item in items), title


def test_dataset_mistakes_mention_the_label_column_failure():
    text = " ".join(common_dataset_mistakes()).lower()
    assert "kolom label" in text
    assert "satu kelas" in text


# ── the page actually renders, for every role and both paths ──────────────

CONTRIB_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import ui.views.contribute as c
c.render()
'''


def _run_page(tmp_path, mode=None, user=None):
    from streamlit.testing.v1 import AppTest

    app = tmp_path / "ctx_app.py"
    app.write_text(CONTRIB_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(app), default_timeout=300)
    if mode:
        at.session_state["_contrib_mode"] = mode
    if user:
        at.session_state["auth_user"] = user
    at.run()
    return at


def _page_text(at) -> str:
    return " ".join([m.value for m in at.markdown]
                    + [c.value for c in at.caption]
                    + [c.value for c in at.code]
                    + [i.value for i in at.info])


@pytest.mark.parametrize("user", [VISITOR, CONTRIBUTOR, ADMIN],
                         ids=["pengunjung", "kontributor", "research_admin"])
@pytest.mark.parametrize("mode", [None, "pipeline", "dataset"],
                         ids=["awal", "pipeline", "dataset"])
def test_the_page_renders_without_exceptions(tmp_path, mode, user):
    at = _run_page(tmp_path, mode, user)
    assert at.exception is None or not at.exception




def test_the_visitor_landing_view_invites_sign_in(tmp_path):
    at = _run_page(tmp_path, None, VISITOR)
    assert any("Masuk" in i.value for i in at.info)


def test_the_landing_view_links_to_run_experiment(tmp_path):
    """Kaitan ke halaman lain kini hidup DI DALAM dropdown pasca-unggah.

    Ia menjawab pertanyaan yang sama dengan dropdown itu — apa yang terjadi
    sesudah berkasnya diterima — jadi tempatnya memang di sana, bukan sebagai
    baris lepas di badan halaman.

    Nama halaman disebut sebagaimana ia tampil di navigasi pada bahasa yang
    sedang aktif: menyebut "Run Experiment" pada mode Indonesia justru menunjuk
    ke label yang tidak ada di sidebar.
    """
    text = _page_text(_run_page(tmp_path, None, CONTRIBUTOR))
    assert lookup("page.run_experiment", "id") in text
    # Aturan yang berbeda tetap dibedakan: dataset langsung, pipeline menunggu.
    assert "langsung" in text.lower()
    assert "disetujui" in text.lower()


# ── honest notes survive the enrichment (regression) ──────────────────────

def _with_guide(at, mode: str = "pipeline"):
    """Buka modal panduan sebuah jalur, seperti pengguna menekan "Info".

    Panduan KEDUA jalur pindah ke modal; yang dijaga tes-tes di bawah tetap
    ISINYA, dan isi itu sekarang dibaca sesudah tombolnya ditekan — bukan dari
    halaman yang menggambarnya tanpa diminta.
    """
    return at.button(key=f"contrib_info_{mode}").click().run()


def test_the_pipeline_path_keeps_its_honest_notes(tmp_path):
    text = _page_text(_with_guide(_run_page(tmp_path, "pipeline"))).lower()
    assert "statis" in text
    assert "tidak dijalankan" in text
    assert "belum aktif" in text or "bukan</b> berarti" in text
    assert "research admin" in text


def test_the_dataset_path_keeps_the_sample_caveat(tmp_path):
    text = _page_text(_with_guide(_run_page(tmp_path, "dataset"),
                                  "dataset")).lower()
    assert "cuplikan" in text
    # Dataset tidak lagi ditinjau — yang harus tersampaikan kini justru
    # bahwa berkasnya tersimpan langsung, dan tinjauan hanya untuk pipeline.
    assert "tersimpan langsung" in text
    assert "pipeline" in text


def test_the_pipeline_path_shows_the_example_and_the_mistakes(tmp_path):
    at = _with_guide(_run_page(tmp_path, "pipeline"))
    code = " ".join(c.value for c in at.code)
    assert "class MyPipeline(" in code            # contoh kerangka
    text = _page_text(at)
    assert "titik masuk" in text.lower()          # kesalahan umum
