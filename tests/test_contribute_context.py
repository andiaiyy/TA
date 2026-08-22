"""Tests for the contextual panels on "Add Pipeline & Dataset".

The page must answer four questions before the user tries anything: what
ecosystem am I adding to, what am I allowed to do, what happens after I upload,
and what usually goes wrong. Everything shown must be *computed* — from the
registry, the dataset folder, the submission table, and the real check names —
so the page can never drift from the platform it describes.
"""
from pathlib import Path

import pytest

from ui.components.contribute_context import (
    AFTER_UPLOAD_FLOW, capability, platform_stats, submission_counts,
)
from ui.components.instructions import (
    ENTRY_POINT_RULE, common_dataset_mistakes, common_pipeline_mistakes,
    pipeline_skeleton,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

VISITOR = None
PENDING = {"username": "baru", "role": "contributor", "status": "pending"}
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}


# ── platform summary is COUNTED, never typed ──────────────────────────────

def _fake_registry(entries: list[tuple[str, str]]) -> dict:
    return {f"p{i}": {"dataset_type": dt, "algorithm": algo}
            for i, (dt, algo) in enumerate(entries)}


def test_platform_numbers_come_from_the_registry(monkeypatch):
    import config.pipeline_registry as registry
    import ui.views.run_experiment as run_exp

    monkeypatch.setattr(registry, "list_all_pipelines", lambda: _fake_registry([
        ("A", "Decision Tree"), ("A", "Random Forest"), ("B", "XGBoost"),
    ]))
    monkeypatch.setattr(run_exp, "_all_dataset_options", lambda: [("x.csv", "A")])

    stats = platform_stats()
    assert stats["research"] == 2            # dua dataset_type berbeda
    assert stats["algorithms"] == 3
    assert stats["datasets"] == 1


def test_platform_numbers_follow_the_registry_when_it_changes(monkeypatch):
    """Angka BUKAN konstanta: menambah entri langsung mengubah hasilnya."""
    import config.pipeline_registry as registry
    import ui.views.run_experiment as run_exp

    monkeypatch.setattr(run_exp, "_all_dataset_options", lambda: [])
    monkeypatch.setattr(registry, "list_all_pipelines",
                        lambda: _fake_registry([("A", "DT")]))
    before = platform_stats()

    monkeypatch.setattr(registry, "list_all_pipelines", lambda: _fake_registry([
        ("A", "DT"), ("A", "RF"), ("B", "DT"), ("C", "SVC"),
    ]))
    after = platform_stats()

    assert (before["research"], before["algorithms"]) == (1, 1)
    assert (after["research"], after["algorithms"]) == (3, 4)


def test_duplicate_algorithm_names_within_one_research_are_counted_once(monkeypatch):
    """Sama seperti daftar pilihan di Run Experiment: dedup per research."""
    import config.pipeline_registry as registry
    import ui.views.run_experiment as run_exp

    monkeypatch.setattr(run_exp, "_all_dataset_options", lambda: [])
    monkeypatch.setattr(registry, "list_all_pipelines", lambda: _fake_registry([
        ("A", "Decision Tree"), ("A", "Decision Tree"), ("B", "Decision Tree"),
    ]))
    stats = platform_stats()
    assert stats["research"] == 2
    assert stats["algorithms"] == 2          # satu per research, bukan tiga


def test_dataset_count_reads_the_server_folder(monkeypatch):
    import ui.views.run_experiment as run_exp
    monkeypatch.setattr(run_exp, "_all_dataset_options",
                        lambda: [("a.csv", "A"), ("b.ndjson", "B"), ("c.csv", "A")])
    assert platform_stats()["datasets"] == 3


def test_platform_stats_survive_a_broken_source(monkeypatch):
    """Ringkasan tidak boleh menjatuhkan halaman bila salah satu sumber gagal."""
    import config.pipeline_registry as registry

    def _boom():
        raise RuntimeError("registry rusak")

    monkeypatch.setattr(registry, "list_all_pipelines", _boom)
    stats = platform_stats()
    assert stats["research"] == 0 and stats["algorithms"] == 0


def test_the_real_platform_reports_plausible_numbers():
    """Tanpa monkeypatch: angka nyata harus positif & konsisten."""
    stats = platform_stats()
    assert stats["research"] >= 1
    assert stats["algorithms"] >= stats["research"]
    assert stats["datasets"] >= 0


# ── user status & rights come from the permission helpers ─────────────────

@pytest.mark.parametrize("user, must_say", [
    # Kini berupa FRASA pendek, bukan kalimat — isinya tetap sama.
    (VISITOR, "membaca"),
    (PENDING, "menunggu persetujuan"),
    (CONTRIBUTOR, "mengajukan"),
    (ADMIN, "meninjau"),
])
def test_capability_line_matches_the_role(user, must_say):
    cap = capability(user)
    assert cap["label"]
    assert must_say in cap["what"].lower()


def test_capability_never_promises_more_than_the_guards_allow():
    """Hak yang ditampilkan DIBACA dari can_upload/can_approve — helper yang
    sama dengan yang ditegakkan lapis aksi, bukan penilaian peran sendiri."""
    from orchestrator.auth_service import can_approve, can_upload

    for user in (VISITOR, PENDING, CONTRIBUTOR, ADMIN):
        cap = capability(user)
        assert cap["may_upload"] == bool(can_upload(user)), user
        assert cap["may_review"] == bool(can_approve(user)), user


def test_only_the_permitted_are_told_they_can_submit():
    """Kalimatnya mengikuti boolean, jadi akun pending tidak pernah dijanjikan
    dapat mengajukan."""
    assert capability(PENDING)["may_upload"] is False
    assert "belum dapat mengajukan" in capability(PENDING)["what"].lower()
    assert capability(CONTRIBUTOR)["what"].lower().startswith("mengajukan")
    assert capability(ADMIN)["may_review"] is True


def test_capability_reads_the_shared_helpers_not_its_own_role_check():
    src = (REPO_ROOT / "ui" / "components" / "contribute_context.py").read_text(
        encoding="utf-8")
    assert "can_upload" in src and "can_approve" in src
    # Tidak ada perbandingan peran mentah yang bisa menyimpang dari guard.
    for hardcoded in ('role"] == "', "role') == '", '== "research_admin"'):
        assert hardcoded not in src, hardcoded


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


def test_after_upload_flow_has_review_before_availability():
    labels = [label for _icon, label in AFTER_UPLOAD_FLOW]
    assert len(AFTER_UPLOAD_FLOW) == 4
    assert labels.index("Tinjau Research Admin") < labels.index("Tersedia")


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


@pytest.mark.parametrize("user", [VISITOR, CONTRIBUTOR, ADMIN],
                         ids=["pengunjung", "kontributor", "research_admin"])
def test_the_landing_view_shows_platform_context(tmp_path, user):
    """Konteks platform + status pengguna tampil untuk SEMUA peran."""
    at = _run_page(tmp_path, None, user)
    assert at.metric, "ringkasan keadaan platform harus tampil"
    labels = [m.label for m in at.metric]
    assert "Research pipeline" in labels
    assert "Dataset di server" in labels

    expected = capability(user)["label"]
    assert expected in _page_text(at), expected


def test_the_visitor_landing_view_invites_sign_in(tmp_path):
    at = _run_page(tmp_path, None, VISITOR)
    assert any("Masuk" in i.value for i in at.info)


def test_the_landing_view_links_to_run_experiment(tmp_path):
    """Kaitan ke halaman lain tampil tanpa perlu membuka expander."""
    text = _page_text(_run_page(tmp_path, None, CONTRIBUTOR))
    assert "Run Experiment" in text


# ── honest notes survive the enrichment (regression) ──────────────────────

def test_the_pipeline_path_keeps_its_honest_notes(tmp_path):
    text = _page_text(_run_page(tmp_path, "pipeline")).lower()
    assert "statis" in text
    assert "tidak dijalankan" in text
    assert "belum aktif" in text or "bukan</b> berarti" in text
    assert "research admin" in text


def test_the_dataset_path_keeps_the_sample_caveat(tmp_path):
    text = _page_text(_run_page(tmp_path, "dataset")).lower()
    assert "cuplikan" in text
    assert "research admin" in text


def test_the_pipeline_path_shows_the_example_and_the_mistakes(tmp_path):
    at = _run_page(tmp_path, "pipeline")
    code = " ".join(c.value for c in at.code)
    assert "class MyPipeline(" in code            # contoh kerangka
    text = _page_text(at)
    assert "titik masuk" in text.lower()          # kesalahan umum
