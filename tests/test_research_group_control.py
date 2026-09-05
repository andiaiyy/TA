"""Menonaktifkan satu ALGORITMA atau satu RESEARCH PIPELINE utuh.

Sebuah research pipeline terunggah memuat beberapa algoritma; tiap algoritma
satu baris registry dengan `dataset_type` yang sama. Sampai perubahan ini,
satu-satunya kendali bekerja per baris — padahal yang paling sering dimaksud
adalah "matikan research pipeline ini", dan melakukannya satu per satu berarti
keadaan setengah jalan setiap kali ada yang terlewat.

Yang dijaga di sini:

* dua tingkatnya benar-benar BERBEDA akibatnya, dan keduanya menyeluruh;
* research pipeline BAWAAN tidak dapat disentuh dari jalur ini — ia pembanding
  tetap penelitian, dan kodenya termasuk area yang tidak boleh diubah;
* izin diperiksa DI FUNGSI, bukan hanya dengan menyembunyikan tombol;
* mematikan algoritma terakhir yang masih hidup DITOLAK, karena akibatnya sama
  dengan mematikan research pipeline-nya tanpa pernah menyatakannya.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migration import apply_migrations
from database.models import build_research_dataset_type
from orchestrator import dynamic_registry as dr
from orchestrator.auth_service import AuthError

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
GUEST = {"username": "andi", "role": "kontributor", "status": "active"}

SOURCE = '''
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {"algorithm": "Demo"}
'''

RESEARCH = build_research_dataset_type("Deteksi Anomali")
OTHER = build_research_dataset_type("Riset Lain")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "grp.db"
    apply_migrations(str(db))
    monkeypatch.setattr("database.db.DB_PATH", str(db), raising=False)
    monkeypatch.setattr("orchestrator.auth_service.require_approve",
                        lambda *a, **k: None)
    return {"db": str(db), "tmp": tmp_path}


def _register(env, name: str, dataset_type: str, *, algorithm: str):
    folder = env["tmp"] / dataset_type.replace(":", "_")
    folder.mkdir(parents=True, exist_ok=True)
    entry = folder / f"{algorithm}.py"
    entry.write_text(SOURCE, encoding="utf-8")
    row = dr.register_pipeline(name=name, dataset_type=dataset_type,
                               entry_class="DemoPipeline",
                               entry_file=str(entry), registered_by="boss",
                               db_path=env["db"])
    conn = sqlite3.connect(env["db"])
    try:
        conn.execute("UPDATE registered_pipelines SET algorithm = ? "
                     "WHERE pipeline_id = ?", (algorithm, row["pipeline_id"]))
        conn.commit()
    finally:
        conn.close()
    return dr.get_registered(row["pipeline_id"], env["db"])


def _family(env, count: int = 3, dataset_type: str = RESEARCH):
    return [_register(env, f"pkg{i}", dataset_type, algorithm=f"algo{i}")
            for i in range(count)]


# ── Membaca satu keluarga ────────────────────────────────────────────────

def test_a_research_pipeline_lists_all_of_its_algorithms(env):
    _family(env, 3)
    rows = dr.research_algorithms(RESEARCH, env["db"])
    assert len(rows) == 3
    assert {r["dataset_type"] for r in rows} == {RESEARCH}


def test_another_research_pipeline_is_never_included(env):
    _family(env, 2)
    _register(env, "lain", OTHER, algorithm="x")
    assert len(dr.research_algorithms(RESEARCH, env["db"])) == 2
    assert len(dr.research_algorithms(OTHER, env["db"])) == 1


def test_an_unknown_research_pipeline_lists_nothing(env):
    assert dr.research_algorithms("uploaded:tidak_ada", env["db"]) == []
    assert dr.research_algorithms("", env["db"]) == []


def test_the_count_separates_active_from_total(env):
    rows = _family(env, 3)
    dr.set_pipeline_active(rows[0]["pipeline_id"], False, actor=ADMIN,
                           db_path=env["db"])
    assert dr.research_active_count(RESEARCH, env["db"]) == (2, 3)


# ── Mematikan satu keluarga sekaligus ────────────────────────────────────

def test_deactivating_a_research_pipeline_takes_every_algorithm(env):
    _family(env, 3)
    dr.set_research_active(RESEARCH, False, actor=ADMIN, db_path=env["db"])
    assert dr.research_active_count(RESEARCH, env["db"]) == (0, 3)


def test_it_reaches_algorithms_that_were_already_off(env):
    """Menyeluruh berarti hasilnya sama apa pun keadaan awalnya — kalau tidak,
    "nonaktifkan seluruhnya" menyisakan yang tak terduga."""
    rows = _family(env, 3)
    dr.set_pipeline_active(rows[1]["pipeline_id"], False, actor=ADMIN,
                           db_path=env["db"])
    dr.set_research_active(RESEARCH, True, actor=ADMIN, db_path=env["db"])
    assert dr.research_active_count(RESEARCH, env["db"]) == (3, 3)


def test_it_never_touches_another_research_pipeline(env):
    _family(env, 2)
    other = _register(env, "lain", OTHER, algorithm="x")
    dr.set_research_active(RESEARCH, False, actor=ADMIN, db_path=env["db"])
    assert dr.get_registered(other["pipeline_id"], env["db"])["active"] == 1


def test_deactivating_removes_it_from_the_merged_registry(env):
    """Pengaman yang sesungguhnya: halaman Jalankan Eksperimen membaca registry
    GABUNGAN, jadi di situlah akibatnya harus terlihat."""
    _family(env, 2)
    before = dr.get_all_pipelines(env["db"])
    assert sum(1 for i in before.values()
               if i.get("dataset_type") == RESEARCH) == 2

    dr.set_research_active(RESEARCH, False, actor=ADMIN, db_path=env["db"])
    after = dr.get_all_pipelines(env["db"])
    assert not [i for i in after.values() if i.get("dataset_type") == RESEARCH]


def test_nothing_is_deleted_by_deactivating(env):
    """Eksperimen yang sudah tercatat menunjuk versi dan hash ini."""
    rows = _family(env, 2)
    dr.set_research_active(RESEARCH, False, actor=ADMIN, db_path=env["db"])
    for row in rows:
        assert dr.get_registered(row["pipeline_id"], env["db"]) is not None


# ── Yang tidak boleh ─────────────────────────────────────────────────────

def test_a_builtin_research_pipeline_is_refused(env):
    """`pipelines/` adalah pembanding tetap skripsi ini — tidak dimatikan dari
    sini, dan kodenya tidak disunting."""
    with pytest.raises(dr.DynamicRegistryError) as excinfo:
        dr.set_research_active("HIKARI2021", False, actor=ADMIN,
                               db_path=env["db"])
    assert excinfo.value.key == "err.research_builtin_readonly"


def test_an_unknown_research_pipeline_is_refused(env):
    with pytest.raises(dr.DynamicRegistryError) as excinfo:
        dr.set_research_active("uploaded:tidak_ada", False, actor=ADMIN,
                               db_path=env["db"])
    assert excinfo.value.key == "err.research_not_found"


def test_the_permission_is_checked_inside_the_function(env, monkeypatch):
    """Menyembunyikan tombol tidak pernah menjadi satu-satunya penghalang."""
    def _deny(actor, db_path=None):
        raise AuthError("bukan research admin", key="err.denied_review")

    monkeypatch.setattr("orchestrator.auth_service.require_approve", _deny)
    _family(env, 2)
    with pytest.raises(AuthError):
        dr.set_research_active(RESEARCH, False, actor=GUEST, db_path=env["db"])
    assert dr.research_active_count(RESEARCH, env["db"]) == (2, 2)


def test_the_refusal_happens_before_anything_is_written(env, monkeypatch):
    def _deny(actor, db_path=None):
        raise AuthError("tidak", key="err.denied_review")

    monkeypatch.setattr("orchestrator.auth_service.require_approve", _deny)
    with pytest.raises(AuthError):
        dr.set_research_active("HIKARI2021", False, actor=GUEST,
                               db_path=env["db"])


# ── Algoritma terakhir yang masih hidup ──────────────────────────────────

def test_turning_off_the_last_live_algorithm_is_blocked(env):
    rows = _family(env, 2)
    dr.set_pipeline_active(rows[0]["pipeline_id"], False, actor=ADMIN,
                           db_path=env["db"])
    assert dr.last_active_algorithm_blocker(
        rows[1]["pipeline_id"], env["db"]) == "mp.blocked_last_algorithm"


def test_turning_off_one_of_several_is_allowed(env):
    rows = _family(env, 3)
    assert dr.last_active_algorithm_blocker(rows[0]["pipeline_id"],
                                            env["db"]) == ""


def test_an_already_inactive_algorithm_is_not_blocked(env):
    """Penghalangnya tentang MEMATIKAN yang terakhir — menyalakan kembali
    selalu boleh."""
    rows = _family(env, 2)
    for row in rows:
        dr.set_pipeline_active(row["pipeline_id"], False, actor=ADMIN,
                               db_path=env["db"])
    assert dr.last_active_algorithm_blocker(rows[0]["pipeline_id"],
                                            env["db"]) == ""


def test_an_unknown_pipeline_id_is_blocked_not_crashed(env):
    assert dr.last_active_algorithm_blocker(
        "uploaded:tidak_ada.v1", env["db"]) == "err.pipeline_not_registered"


def test_the_whole_family_switch_is_the_way_out_of_that_block(env):
    """Penghalang di atas menunjuk tombol keluarga — jadi tombol itu memang
    harus bekerja pada keadaan yang sama."""
    rows = _family(env, 2)
    dr.set_pipeline_active(rows[0]["pipeline_id"], False, actor=ADMIN,
                           db_path=env["db"])
    dr.set_research_active(RESEARCH, False, actor=ADMIN, db_path=env["db"])
    assert dr.research_active_count(RESEARCH, env["db"]) == (0, 2)


@pytest.mark.parametrize("key", ["err.research_builtin_readonly",
                                 "err.research_not_found",
                                 "mp.blocked_last_algorithm"])
def test_every_reason_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)
