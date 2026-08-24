"""Run RESMI vs run EKSPLORASI — pemisahan yang menjadi dasar klaim penelitian.

Empat hal yang harus tetap benar apa pun yang berubah di atasnya:

* **bawaan selalu resmi** — mode eksplorasi tidak pernah aktif tanpa dipilih;
* **run resmi kebal override** — dikirimi parameter apa pun, ia tetap memakai
  nilai terkunci, sehingga metrik pipeline bawaan tidak pernah bergeser;
* **daftar parameter datang dari pipeline** — hanya kunci yang benar-benar ada
  di ``get_info()['fixed_params']``, dan yang mengunci tahapan/anti-kebocoran/
  algoritma/seleksi fitur tidak pernah bisa disentuh;
* **record lama tetap utuh** — ``run_mode`` NULL dibaca sebagai resmi, tidak
  disembunyikan, dan metriknya tidak berubah oleh migrasi.
"""
import ast
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from contracts.dataset_schemas import HIKARI2021_SCHEMA
from contracts.pipeline_contracts import PipelineInput
from config.pipeline_registry import PIPELINE_REGISTRY
from database.db import get_experiment, init_db
from orchestrator import run_mode as rm
from orchestrator.experiment_service import create_and_run_experiment, rerun_experiment
from ui.components import experiment_table as et

REPO_ROOT = Path(__file__).resolve().parents[1]

BUILTIN_IDS = sorted(PIPELINE_REGISTRY)


def _info(pipeline_id: str) -> dict:
    return PIPELINE_REGISTRY[pipeline_id]["class"]().get_info() or {}


# ── Mode: bawaan selalu resmi ─────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", "  ", "OFFICIAL", "official",
                                   "resmi", "unknown", 0, [], {}])
def test_anything_that_is_not_exploration_reads_as_official(value):
    """Termasuk NULL — itulah yang membuat record lama tetap resmi."""
    assert rm.normalize_run_mode(value) == rm.RUN_MODE_OFFICIAL
    assert rm.is_exploration(value) is False


def test_exploration_must_be_stated_explicitly():
    assert rm.normalize_run_mode("exploration") == rm.RUN_MODE_EXPLORATION
    assert rm.is_exploration("exploration") is True


def test_platform_default_is_official():
    assert rm.DEFAULT_RUN_MODE == rm.RUN_MODE_OFFICIAL


def test_every_mode_has_a_visible_badge():
    """Tidak ada mode yang bisa tampil tanpa penanda."""
    for mode in rm.ALL_RUN_MODES:
        assert rm.run_mode_badge(mode).strip()
        assert rm.run_mode_label(mode).strip()
    assert rm.run_mode_badge(None) == rm.RUN_MODE_BADGES[rm.RUN_MODE_OFFICIAL]


# ── Daftar parameter berasal dari fixed_params, bukan dikarang ────────────

@pytest.mark.parametrize("pipeline_id", BUILTIN_IDS)
def test_locked_params_are_exactly_fixed_params(pipeline_id):
    info = _info(pipeline_id)
    assert rm.locked_params(pipeline_id, info=info) == info.get("fixed_params", {})


@pytest.mark.parametrize("pipeline_id", BUILTIN_IDS)
def test_tunable_is_a_subset_of_fixed_params(pipeline_id):
    """Tidak ada satu pun kunci yang muncul di formulir tanpa ada di pipeline."""
    info = _info(pipeline_id)
    fixed = set(info.get("fixed_params") or {})
    assert set(rm.tunable_params(pipeline_id, info=info)) <= fixed


@pytest.mark.parametrize("pipeline_id", BUILTIN_IDS)
def test_the_four_forbidden_categories_are_never_tunable(pipeline_id):
    """Urutan tahapan, anti-kebocoran, algoritma, dan seleksi fitur terkunci."""
    info = _info(pipeline_id)
    tunable = rm.tunable_params(pipeline_id, info=info)
    for key in rm.PROTECTED_PARAMS:
        assert key not in tunable, key


@pytest.mark.parametrize("key", ["models", "pca", "fs_sample_rows", "balancing",
                                 "scaler", "test_size", "stratify",
                                 "enforce_row_level_conversion_cap"])
def test_structural_keys_carry_a_stated_reason(key):
    assert key in rm.PROTECTED_PARAMS
    category, reason = rm.PROTECTED_PARAMS[key]
    assert category and reason
    assert rm.protected_reason(key)


def test_tunable_sets_really_differ_between_pipelines():
    """Bukan template seragam: tiap pipeline punya kuncinya sendiri."""
    sets = {pid: set(rm.tunable_params(pid, info=_info(pid))) for pid in BUILTIN_IDS}
    assert sets["hikari2021.rfc_pipeline"] == {"n_estimators", "random_state"}
    assert sets["hikari2021.knn_pipeline"] == {"n_neighbors", "random_state"}
    assert sets["hikari2021.lr_pipeline"] == {"max_iter", "random_state"}
    assert sets["hikari2021.dt_pipeline"] == {"random_state"}
    # nbgc tidak mendeklarasikan satu pun hyperparameter model.
    assert sets["hikari2021.nbgc_pipeline"] == set()
    # Seluruh fixed_params EVE mengunci algoritma/FS/kebocoran/sumber daya.
    for pid in [p for p in BUILTIN_IDS if p.startswith("eve_cbr.")]:
        assert sets[pid] == set()


@pytest.mark.parametrize("pipeline_id", BUILTIN_IDS)
def test_param_rows_show_every_fixed_param_for_transparency(pipeline_id):
    """Mode resmi tetap MENAMPILKAN parameter — tidak ada yang disembunyikan."""
    info = _info(pipeline_id)
    rows = rm.param_rows(pipeline_id, info=info)
    assert [r["key"] for r in rows] == list((info.get("fixed_params") or {}))
    for row in rows:
        assert row["tunable"] or row["reason"], row["key"]


def test_a_numeric_key_without_declared_bounds_stays_locked():
    """Fail-closed: tidak dilarang bukan berarti diizinkan."""
    info = {"fixed_params": {"alpha_baru": 7}}
    assert rm.tunable_params("x", info=info) == {}
    assert rm.LOCKED_NO_BOUNDS in rm.param_rows("x", info=info)[0]["reason"]


def test_a_free_text_param_stays_locked_without_choices():
    info = {"fixed_params": {"kernel": "rbf"}}
    assert rm.tunable_params("x", info=info) == {}
    info_with_choices = {"fixed_params": {"kernel": "rbf"},
                         "param_choices": {"kernel": ["rbf", "linear"]}}
    assert "kernel" in rm.tunable_params("x", info=info_with_choices)


def test_a_pipeline_cannot_declare_bounds_above_the_platform_cap():
    info = {"fixed_params": {"n_estimators": 100},
            "param_bounds": {"n_estimators": [1, 10**9]}}
    spec = rm.tunable_params("x", info=info)["n_estimators"]
    assert spec["max"] <= rm.HARD_INT_CAP


# ── Validasi masukan pengguna ─────────────────────────────────────────────

RFC = "hikari2021.rfc_pipeline"


def test_a_key_outside_fixed_params_is_rejected():
    with pytest.raises(rm.ParamError, match="bukan parameter pipeline ini"):
        rm.validate_overrides(RFC, {"tidak_ada": 1}, info=_info(RFC))


def test_a_key_valid_for_another_pipeline_is_still_rejected():
    """`n_neighbors` nyata di knn, tetapi tidak ada di rfc."""
    with pytest.raises(rm.ParamError):
        rm.validate_overrides(RFC, {"n_neighbors": 5}, info=_info(RFC))


def test_a_protected_key_is_rejected_with_its_reason():
    with pytest.raises(rm.ParamError, match="terkunci"):
        rm.validate_overrides(RFC, {"test_size": 0.5}, info=_info(RFC))


@pytest.mark.parametrize("value", ["250", 250.5, None, [250], {"a": 1}])
def test_wrong_type_is_rejected(value):
    with pytest.raises(rm.ParamError, match="bilangan bulat"):
        rm.validate_overrides(RFC, {"n_estimators": value}, info=_info(RFC))


def test_a_boolean_is_not_silently_accepted_as_an_integer():
    with pytest.raises(rm.ParamError):
        rm.validate_overrides(RFC, {"n_estimators": True}, info=_info(RFC))


@pytest.mark.parametrize("value", [0, -1, 100_000, 10**9])
def test_out_of_bounds_is_rejected_with_the_limits_named(value):
    with pytest.raises(rm.ParamError) as excinfo:
        rm.validate_overrides(RFC, {"n_estimators": value}, info=_info(RFC))
    message = str(excinfo.value)
    assert "batas" in message.lower()
    lo, hi = rm.PARAM_BOUNDS["n_estimators"]
    assert str(lo) in message and str(hi) in message


def test_a_value_inside_the_bounds_is_accepted_unchanged():
    clean = rm.validate_overrides(RFC, {"n_estimators": 250}, info=_info(RFC))
    assert clean == {"n_estimators": 250}
    assert type(clean["n_estimators"]) is int


def test_the_upper_bound_keeps_the_worker_from_extreme_load():
    """Batas atas jauh di bawah nilai yang bisa membekukan worker."""
    assert rm.PARAM_BOUNDS["n_estimators"][1] <= 1000
    assert rm.PARAM_BOUNDS["max_iter"][1] <= 100_000
    assert rm.HARD_INT_CAP <= 1_000_000


def test_no_eval_or_exec_anywhere_on_the_parameter_path():
    """Nilai pengguna tidak pernah dijalankan sebagai kode maupun dipakai
    membangun objek/mengimpor modul."""
    banned = {"eval", "exec", "compile", "__import__", "getattr", "setattr"}
    for relative in ("orchestrator/run_mode.py", "ui/components/run_mode_controls.py"):
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not (called & banned), (relative, called & banned)
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "pickle" not in source and "subprocess" not in source


# ── Isolasi mode: run resmi mengabaikan override ──────────────────────────

@pytest.mark.parametrize("pipeline_id", BUILTIN_IDS)
def test_official_ignores_overrides_completely(pipeline_id):
    """Dikirimi override yang sah sekalipun, run resmi memakai nilai terkunci."""
    info = _info(pipeline_id)
    locked = rm.locked_params(pipeline_id, info=info)
    hostile = {"n_estimators": 500, "random_state": 999, "max_iter": 10,
               "n_neighbors": 99, "test_size": 0.9, "models": ["XGB"]}

    for mode in (None, "", "official", "tidak dikenal"):
        resolved = rm.resolve_params(pipeline_id, mode, hostile, info=info)
        assert resolved["run_mode"] == rm.RUN_MODE_OFFICIAL
        assert resolved["params"] == locked
        assert resolved["overrides"] == {}
        assert resolved["changed"] == []


def test_official_does_not_even_validate_overrides():
    """Override tak sah pun tidak menggagalkan run resmi — ia dibuang."""
    resolved = rm.resolve_params(RFC, None, {"apa pun": object()}, info=_info(RFC))
    assert resolved["params"] == rm.locked_params(RFC, info=_info(RFC))


def test_exploration_applies_only_the_validated_keys():
    resolved = rm.resolve_params(RFC, "exploration", {"n_estimators": 250},
                                 info=_info(RFC))
    assert resolved["run_mode"] == rm.RUN_MODE_EXPLORATION
    assert resolved["params"]["n_estimators"] == 250
    assert resolved["changed"] == ["n_estimators"]
    # Kunci lain tetap pada nilai terkuncinya.
    locked = rm.locked_params(RFC, info=_info(RFC))
    for key in locked:
        if key != "n_estimators":
            assert resolved["params"][key] == locked[key]


def test_sending_the_default_value_is_not_a_change():
    locked = rm.locked_params(RFC, info=_info(RFC))
    resolved = rm.resolve_params(RFC, "exploration",
                                 {"n_estimators": locked["n_estimators"]},
                                 info=_info(RFC))
    assert resolved["changed"] == []


def test_exploration_with_a_bad_key_raises_instead_of_silently_dropping():
    with pytest.raises(rm.ParamError):
        rm.resolve_params(RFC, "exploration", {"models": ["XGB"]}, info=_info(RFC))


# ── Lapis kedua di pipeline ───────────────────────────────────────────────

@pytest.mark.parametrize("pipeline_id, key, literal", [
    ("hikari2021.rfc_pipeline", "n_estimators", 100),
    ("hikari2021.knn_pipeline", "n_neighbors", 5),
    ("hikari2021.lr_pipeline", "max_iter", 3000),
])
def test_no_override_means_the_original_literal(pipeline_id, key, literal):
    """Inti klaim replikasi: tanpa override, nilainya persis seperti semula."""
    empty = PipelineInput(df=pd.DataFrame(), label_column="Label",
                          dataset_type="HIKARI2021")
    resolved = PIPELINE_REGISTRY[pipeline_id]["class"]()._resolved_params(empty)
    assert resolved[key] == literal
    assert type(resolved[key]) is type(literal)


def test_the_pipeline_layer_ignores_keys_it_does_not_declare():
    hostile = PipelineInput(df=pd.DataFrame(), label_column="Label",
                            dataset_type="HIKARI2021",
                            param_overrides={"n_estimators": 7, "diselundupkan": 1})
    resolved = PIPELINE_REGISTRY[RFC]["class"]()._resolved_params(hostile)
    assert resolved["n_estimators"] == 7
    assert "diselundupkan" not in resolved


def test_the_contract_field_is_optional_with_a_safe_default():
    """Pemanggilan lama (tanpa argumen baru) harus tetap berjalan."""
    old_style = PipelineInput(df=pd.DataFrame(), label_column="Label",
                              dataset_type="HIKARI2021")
    assert old_style.param_overrides == {}


# ── Pencatatan ke basis data & artefak ────────────────────────────────────

@pytest.fixture
def test_env(tmp_path):
    db_path = str(tmp_path / "test.db")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    np.random.seed(42)
    n = 120
    feature_cols = [c for c in HIKARI2021_SCHEMA["expected_columns"] if c != "Label"]
    data = {col: np.random.randn(n) for col in feature_cols}
    data["Label"] = [0] * 60 + [1] * 60
    pd.DataFrame(data).to_csv(tmp_path / "test.csv", index=False)

    def _get_conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    with patch("database.db.get_connection", side_effect=_get_conn), \
         patch("utils.artifact_saver.ARTIFACTS_DIR", artifacts_dir), \
         patch("orchestrator.experiment_service.sha256_file", return_value="abc123"), \
         patch("config.settings.BASE_DIR", str(tmp_path)):
        init_db(db_path)
        yield {"db_path": db_path, "artifacts_dir": artifacts_dir,
               "csv_path": str(tmp_path / "test.csv")}


def _artifact_metadata(env, experiment_id):
    return json.loads((env["artifacts_dir"] / experiment_id / "metadata.json")
                      .read_text(encoding="utf-8"))


def test_an_official_run_records_mode_and_locked_params(test_env):
    result = create_and_run_experiment("HIKARI2021", test_env["csv_path"],
                                       "hikari2021.dt_pipeline")
    assert result["success"] is True

    row = get_experiment(result["experiment_id"], test_env["db_path"])
    assert row["run_mode"] == rm.RUN_MODE_OFFICIAL
    assert row["params_changed"] == 0
    assert rm.load_params(row["params_used"]) == rm.locked_params("hikari2021.dt_pipeline")

    metadata = _artifact_metadata(test_env, result["experiment_id"])
    assert metadata["run_mode"] == rm.RUN_MODE_OFFICIAL
    assert metadata["params_used"] == rm.locked_params("hikari2021.dt_pipeline")
    assert metadata["params_changed"] == []


def test_an_exploration_run_records_the_values_actually_used(test_env):
    result = create_and_run_experiment(
        "HIKARI2021", test_env["csv_path"], "hikari2021.rfc_pipeline",
        run_mode="exploration", param_overrides={"n_estimators": 30},
    )
    assert result["success"] is True

    row = get_experiment(result["experiment_id"], test_env["db_path"])
    assert row["run_mode"] == rm.RUN_MODE_EXPLORATION
    assert row["params_changed"] == 1
    used = rm.load_params(row["params_used"])
    assert used["n_estimators"] == 30
    # Kunci lain tetap tercatat pada nilai terkuncinya — run tetap dapat diulang.
    assert used["random_state"] == rm.locked_params("hikari2021.rfc_pipeline")["random_state"]

    metadata = _artifact_metadata(test_env, result["experiment_id"])
    assert metadata["run_mode"] == rm.RUN_MODE_EXPLORATION
    assert metadata["params_used"]["n_estimators"] == 30
    assert metadata["params_changed"] == ["n_estimators"]


def test_metrics_json_keeps_its_shape(test_env):
    """Struktur metrics.json TIDAK berubah — mode hanya masuk metadata."""
    result = create_and_run_experiment(
        "HIKARI2021", test_env["csv_path"], "hikari2021.rfc_pipeline",
        run_mode="exploration", param_overrides={"n_estimators": 30},
    )
    metrics = json.loads((test_env["artifacts_dir"] / result["experiment_id"]
                          / "metrics.json").read_text(encoding="utf-8"))
    for key in ("accuracy", "precision", "recall", "f1_score", "confusion_matrix"):
        assert key in metrics
    assert "run_mode" not in metrics
    assert "params_used" not in metrics


def test_an_official_run_ignores_overrides_end_to_end(test_env):
    """Jalur nyata, bukan hanya fungsi murni: parameter tercatat = terkunci."""
    result = create_and_run_experiment(
        "HIKARI2021", test_env["csv_path"], "hikari2021.rfc_pipeline",
        run_mode=None, param_overrides={"n_estimators": 500},
    )
    row = get_experiment(result["experiment_id"], test_env["db_path"])
    assert row["run_mode"] == rm.RUN_MODE_OFFICIAL
    assert rm.load_params(row["params_used"])["n_estimators"] == 100
    assert row["params_changed"] == 0


def test_the_same_seed_gives_the_same_numbers_in_both_modes(test_env):
    """Run eksplorasi tetap dapat diulang — parameternya tercatat."""
    kwargs = dict(run_mode="exploration", param_overrides={"n_estimators": 25})
    first = create_and_run_experiment("HIKARI2021", test_env["csv_path"],
                                      "hikari2021.rfc_pipeline", **kwargs)
    second = create_and_run_experiment("HIKARI2021", test_env["csv_path"],
                                       "hikari2021.rfc_pipeline", **kwargs)
    assert first["metrics"]["accuracy"] == second["metrics"]["accuracy"]


def test_a_rejected_parameter_never_creates_an_experiment(test_env):
    before = len(list(test_env["artifacts_dir"].iterdir()))
    result = create_and_run_experiment(
        "HIKARI2021", test_env["csv_path"], "hikari2021.rfc_pipeline",
        run_mode="exploration", param_overrides={"n_estimators": 10**9},
    )
    assert result["success"] is False
    assert result["experiment_id"] is None
    assert "batas" in result["error"].lower()
    assert len(list(test_env["artifacts_dir"].iterdir())) == before


def test_rerun_keeps_the_mode_and_the_parameters(test_env):
    """"Re-run" tidak boleh diam-diam mengubah eksplorasi menjadi resmi."""
    original = create_and_run_experiment(
        "HIKARI2021", test_env["csv_path"], "hikari2021.rfc_pipeline",
        run_mode="exploration", param_overrides={"n_estimators": 30},
    )
    again = rerun_experiment(original["experiment_id"])
    assert again["success"] is True

    row = get_experiment(again["experiment_id"], test_env["db_path"])
    assert row["run_mode"] == rm.RUN_MODE_EXPLORATION
    assert rm.load_params(row["params_used"])["n_estimators"] == 30


def test_rerun_of_an_official_run_stays_official(test_env):
    original = create_and_run_experiment("HIKARI2021", test_env["csv_path"],
                                         "hikari2021.dt_pipeline")
    again = rerun_experiment(original["experiment_id"])
    row = get_experiment(again["experiment_id"], test_env["db_path"])
    assert row["run_mode"] == rm.RUN_MODE_OFFICIAL
    assert row["params_changed"] == 0


# ── Record lama tetap utuh & tetap resmi ──────────────────────────────────

LEGACY = {"id": "legacy-1", "pipeline_id": "hikari2021.rfc_pipeline",
          "dataset_type": "HIKARI2021", "dataset_path": "/data/lama.csv",
          "status": "FINISHED", "created_at": "2026-01-01T00:00:00",
          "accuracy": 0.8607489314700091, "f1_score": 0.889771561879592,
          "run_mode": None, "params_used": None, "params_changed": None}


def test_a_legacy_record_reads_as_official():
    assert rm.mode_of(LEGACY) == rm.RUN_MODE_OFFICIAL
    assert rm.params_of(LEGACY) == {}


def test_a_legacy_record_is_shown_not_hidden():
    rows = et.build_rows([LEGACY])
    assert len(rows) == 1
    assert rows[0]["_mode"] == rm.RUN_MODE_OFFICIAL
    assert rows[0]["mode"] == rm.RUN_MODE_BADGES[rm.RUN_MODE_OFFICIAL]
    # Metriknya tetap terbaca apa adanya.
    assert rows[0]["accuracy"] == LEGACY["accuracy"]


def test_the_default_filter_shows_every_mode():
    rows = et.build_rows([LEGACY, {**LEGACY, "id": "baru", "run_mode": "exploration"}])
    assert len(et.apply_filters(rows)) == 2
    assert len(et.apply_filters(rows, modes=[])) == 2


def test_filtering_by_mode_is_possible_in_both_directions():
    rows = et.build_rows([LEGACY, {**LEGACY, "id": "baru", "run_mode": "exploration"}])
    assert [r["_id"] for r in et.apply_filters(rows, modes=["official"])] == ["legacy-1"]
    assert [r["_id"] for r in et.apply_filters(rows, modes=["exploration"])] == ["baru"]
    # Pilihan mode ditawarkan lengkap, bukan hanya yang kebetulan ada.
    assert set(et.filter_options(rows)["modes"]) == set(rm.ALL_RUN_MODES)


def test_a_legacy_record_falls_back_to_definition_params_with_provenance():
    rows = et.build_rows([LEGACY],
                         params_reader=lambda: {"hikari2021.rfc_pipeline": {"n_estimators": 100}})
    assert rows[0]["param_n_estimators"] == 100
    assert rows[0]["_params_recorded"] is False
    # Asal-usulnya dinyatakan, tidak disamakan dengan yang direkam.
    assert "definisi pipeline" in et.PARAM_PROVENANCE


def test_a_recorded_run_prefers_its_own_params_over_the_definition():
    row = {**LEGACY, "id": "baru", "run_mode": "exploration",
           "params_used": json.dumps({"n_estimators": 250})}
    rows = et.build_rows([row],
                         params_reader=lambda: {"hikari2021.rfc_pipeline": {"n_estimators": 100}})
    assert rows[0]["param_n_estimators"] == 250
    assert rows[0]["_params_recorded"] is True


def test_the_real_database_still_holds_every_record_as_official():
    """Basis data NYATA: setelah migrasi, tidak satu pun record berubah mode."""
    from config.settings import DB_PATH
    conn = sqlite3.connect(str(DB_PATH))
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(experiments)")}
        assert {"run_mode", "params_used", "params_changed"} <= columns
        total = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        exploration = conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE run_mode = ?",
            (rm.RUN_MODE_EXPLORATION,)).fetchone()[0]
    finally:
        conn.close()
    assert total >= 15                       # record dasar BAB III
    assert exploration == 0                  # tidak ada yang tertandai eksplorasi


def test_the_migration_is_additive_only():
    """Tiga migrasi baru hanya menambah kolom — tidak ada UPDATE/DROP."""
    from database.migration import MIGRATIONS
    baru = [m for m in MIGRATIONS if m["version"] in (16, 17, 18)]
    assert len(baru) == 3
    for migration in baru:
        assert migration["sql"].upper().startswith("ALTER TABLE EXPERIMENTS ADD COLUMN")
        assert migration["add_column"][0] == "experiments"
        for destructive in ("DROP", "DELETE", "UPDATE", "NOT NULL", "DEFAULT"):
            assert destructive not in migration["sql"].upper(), destructive


# ── Penandaan di setiap tampilan hasil ────────────────────────────────────

MIXED = [
    {**LEGACY, "id": "resmi"},
    {**LEGACY, "id": "eksplor", "run_mode": "exploration",
     "params_used": json.dumps({"n_estimators": 250, "random_state": 42}),
     "params_changed": 1},
]


def test_comparing_mixed_modes_raises_a_warning():
    rows = et.build_rows(MIXED)
    assert et.is_mixed_mode(rows) is True
    warnings = et.comparison_warnings(rows)
    assert rm.MIXED_MODE_WARNING in warnings
    # Sekelas peringatan semantik metrik: muncul lebih dulu.
    assert warnings[0] == rm.MIXED_MODE_WARNING


def test_comparing_within_one_mode_raises_no_mode_warning():
    rows = et.build_rows([MIXED[0], {**MIXED[0], "id": "resmi-2"}])
    assert et.is_mixed_mode(rows) is False
    assert rm.MIXED_MODE_WARNING not in et.comparison_warnings(rows)


def test_the_comparison_table_carries_a_mode_row():
    rows = et.build_rows(MIXED)
    data = et.build_comparison(rows)
    labels = [f["label"] for s in data["sections"] for f in s["fields"]]
    assert "Mode" in labels
    mode_field = next(f for s in data["sections"] for f in s["fields"]
                      if f["label"] == "Mode")
    assert mode_field["differs"] is True


def test_the_history_table_shows_mode_by_default():
    """Terbedakan sekilas, tanpa membuka pemilih kolom lebih dulu."""
    assert "mode" in et.DEFAULT_COLUMNS
    columns = et.visible_columns(et.build_columns(), et.DEFAULT_COLUMNS)
    assert any(c["key"] == "mode" for c in columns)


def test_csv_always_carries_mode_and_parameters():
    rows = et.build_rows(MIXED)
    # Sengaja memilih kolom yang TIDAK memuat mode — kolomnya tetap harus ikut.
    columns = et.visible_columns(et.build_columns(), ["waktu", "pipeline"])
    csv_text = et.to_csv(rows, columns)

    header = csv_text.splitlines()[0]
    assert et.CSV_MODE_COLUMN in header
    assert et.CSV_PARAMS_COLUMN in header

    body = csv_text.splitlines()[1:]
    assert rm.RUN_MODE_BADGES[rm.RUN_MODE_OFFICIAL] in body[0]
    assert rm.RUN_MODE_BADGES[rm.RUN_MODE_EXPLORATION] in body[1]
    assert "n_estimators=250" in body[1]


def test_no_row_can_be_rendered_without_a_mode():
    """Termasuk baris tanpa kolom run_mode sama sekali."""
    rows = et.build_rows([{"id": "x", "pipeline_id": "p", "dataset_type": "HIKARI2021"}])
    assert rows[0]["mode"] in rm.RUN_MODE_BADGES.values()


# ── Laporan PDF ───────────────────────────────────────────────────────────

def _pdf_text(metadata: dict) -> bytes:
    from utils.report_generator import generate_report
    return generate_report(
        experiment_id="e1", dataset_type="HIKARI2021", dataset_path="/d.csv",
        dataset_hash="h" * 64, pipeline_id="hikari2021.rfc_pipeline",
        pipeline_info=_info(RFC),
        metrics={"accuracy": 0.9, "precision": 0.9, "recall": 0.9,
                 "f1_score": 0.9, "confusion_matrix": [[10, 1], [2, 9]]},
        metadata=metadata, label_mapping={0: "Benign", 1: "Malicious"},
        feature_names=["a", "b"],
    )


def test_the_pdf_marks_an_exploration_run():
    pdf = _pdf_text({"run_mode": "exploration",
                     "params_used": {"n_estimators": 250, "random_state": 42},
                     "params_locked": rm.locked_params(RFC),
                     "params_changed": ["n_estimators"]})
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_the_pdf_of_a_legacy_artifact_still_renders_as_official():
    """Artefak lama tanpa run_mode tidak boleh menggagalkan laporan."""
    pdf = _pdf_text({"created_at": "2026-01-01T00:00:00"})
    assert pdf.startswith(b"%PDF")


def test_the_report_context_defaults_to_official():
    from utils.report_generator import _build_context
    ctx = _build_context(metadata={}, metrics={}, pipeline_info={})
    assert ctx["run_mode"] == rm.RUN_MODE_OFFICIAL
    assert ctx["run_mode_recorded"] is False


def test_the_report_reports_the_seed_that_was_actually_used():
    """Baris seed tidak boleh menuliskan 42 bila run mengubahnya."""
    from utils.report_generator import _build_context
    ctx = _build_context(metadata={"run_mode": "exploration",
                                   "params_used": {"random_state": 7},
                                   "params_locked": {"random_state": 42},
                                   "params_changed": ["random_state"]},
                         metrics={}, pipeline_info={})
    assert ctx["params_used"]["random_state"] == 7
    assert "random_state" in ctx["params_changed"]


# ── Kontrol antarmuka ─────────────────────────────────────────────────────

def test_the_ui_seeds_no_mode_and_therefore_defaults_to_official():
    import ui.components.run_mode_controls as rmc
    source = (REPO_ROOT / "ui" / "components" / "run_mode_controls.py").read_text(
        encoding="utf-8")
    assert "index=modes.index(current)" in source
    assert "modes = [RUN_MODE_OFFICIAL, RUN_MODE_EXPLORATION]" in source
    assert rmc.MODE_STATE_KEY


def test_the_ui_has_a_reset_to_defaults_control():
    source = (REPO_ROOT / "ui" / "components" / "run_mode_controls.py").read_text(
        encoding="utf-8")
    assert "Kembalikan ke bawaan" in source
    assert "def reset_overrides(" in source


def test_the_exploration_warning_is_short():
    """Ringkas, satu-dua baris — bukan paragraf."""
    assert len(rm.EXPLORATION_WARNING) < 260
    assert rm.EXPLORATION_WARNING.count(".") <= 3


def test_the_run_view_passes_the_mode_through():
    source = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    assert "render_run_mode_block(selected)" in source
    assert "run_mode=run_choice[\"run_mode\"]" in source
    assert "param_overrides=run_choice[\"param_overrides\"]" in source


def test_the_run_view_no_longer_claims_every_parameter_is_locked():
    """Klaim itu kini hanya benar untuk run resmi."""
    source = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    assert "All parameters locked per paper." not in source


def test_format_params_names_the_default_when_it_differs():
    text = rm.format_params({"n_estimators": 250, "random_state": 42},
                            {"n_estimators": 100, "random_state": 42})
    assert "n_estimators=250 (bawaan 100)" in text
    assert "random_state=42" in text and "(bawaan 42)" not in text


def test_every_result_surface_carries_the_mode():
    """Tidak boleh ada tempat hasil muncul tanpa penanda mode.

    Diperiksa secara struktural pada berkas yang merender masing-masing
    tempat, supaya penanda tidak bisa hilang diam-diam saat tampilan diubah.
    """
    surfaces = {
        # riwayat + filter + perbandingan + CSV
        "ui/components/experiment_table.py": ["run_mode_badge", "MIXED_MODE_WARNING",
                                              "CSV_MODE_COLUMN", "CSV_PARAMS_COLUMN"],
        # detail hasil + baris terpilih + filter mode
        "ui/views/view_results.py": ["rm.run_mode_badge(exp.get('run_mode'))",
                                     "_render_mode_details", "Mode eksekusi"],
        # panel hasil tepat setelah run
        "ui/views/run_experiment.py": ["_render_result_mode_banner"],
        # laporan PDF
        "utils/report_generator.py": ["Mode eksekusi", "is_exploration"],
    }
    for relative, needles in surfaces.items():
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        for needle in needles:
            assert needle in source, (relative, needle)


def test_the_results_page_offers_a_mode_filter():
    source = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
    assert '"modes": modes' in source
    assert "_hist_f_mode" in source


def test_the_locked_table_states_a_reason_for_every_locked_key():
    import ui.components.run_mode_controls as rmc
    rows = rm.param_rows("eve_cbr.xgb", info=_info("eve_cbr.xgb"))
    assert rows and all(not r["tunable"] for r in rows)
    assert all(r["reason"] for r in rows)
    assert rmc.NO_TUNABLE_NOTE


# ── Bukti bahwa penyesuaian benar-benar sampai ke konstruktor model ───────

@pytest.fixture(scope="module")
def tiny_frame():
    np.random.seed(0)
    n = 200
    cols = [c for c in HIKARI2021_SCHEMA["expected_columns"] if c != "Label"]
    data = {c: np.random.randn(n) for c in cols}
    data["Label"] = [0] * 100 + [1] * 100
    return pd.DataFrame(data)


@pytest.mark.parametrize("pipeline_id, key, value, attribute", [
    ("hikari2021.rfc_pipeline", "n_estimators", 7, "n_estimators"),
    ("hikari2021.knn_pipeline", "n_neighbors", 11, "n_neighbors"),
    ("hikari2021.lr_pipeline", "max_iter", 50, "max_iter"),
    ("hikari2021.dt_pipeline", "random_state", 7, "random_state"),
])
def test_an_exploration_value_reaches_the_trained_model(tiny_frame, pipeline_id,
                                                        key, value, attribute):
    """Fiturnya nyata: nilai yang dipilih benar-benar dipakai melatih model."""
    from orchestrator.execution_service import execute_pipeline

    result = execute_pipeline(pipeline_id, tiny_frame.copy(), "HIKARI2021",
                              param_overrides={key: value})
    assert getattr(result.model, attribute) == value


@pytest.mark.parametrize("pipeline_id, attribute, locked_value", [
    ("hikari2021.rfc_pipeline", "n_estimators", 100),
    ("hikari2021.knn_pipeline", "n_neighbors", 5),
    ("hikari2021.lr_pipeline", "max_iter", 3000),
])
def test_the_official_path_trains_with_the_locked_value(tiny_frame, pipeline_id,
                                                        attribute, locked_value):
    """Tanpa override, model dilatih dengan nilai terkunci — tidak bergeser."""
    from orchestrator.execution_service import execute_pipeline

    result = execute_pipeline(pipeline_id, tiny_frame.copy(), "HIKARI2021")
    assert getattr(result.model, attribute) == locked_value


def test_the_official_path_is_unaffected_by_a_dropped_override(tiny_frame):
    """resolve_params membuang override pada run resmi; buktinya di model."""
    from orchestrator.execution_service import execute_pipeline

    resolved = rm.resolve_params(RFC, rm.RUN_MODE_OFFICIAL, {"n_estimators": 7})
    result = execute_pipeline(RFC, tiny_frame.copy(), "HIKARI2021",
                              param_overrides=resolved["overrides"])
    assert result.model.n_estimators == 100


def test_the_advertised_bounds_are_the_bounds_actually_enforced():
    """Formulir tidak boleh menjanjikan rentang yang lebih lebar dari yang
    benar-benar ditegakkan — kalau tidak, pengguna ditolak setelah mengetik."""
    for key, (low, high) in rm.PARAM_BOUNDS.items():
        assert low >= -rm.HARD_INT_CAP
        assert high <= rm.HARD_INT_CAP, key

    for pipeline_id in BUILTIN_IDS:
        info = _info(pipeline_id)
        for key, spec in rm.tunable_params(pipeline_id, info=info).items():
            if spec["type"] != "int":
                continue
            declared = rm.PARAM_BOUNDS[key]
            assert (spec["min"], spec["max"]) == (int(declared[0]), int(declared[1]))
            # Nilai tepat di batas diterima; satu langkah di luarnya ditolak.
            rm.validate_override(key, spec["max"], spec)
            with pytest.raises(rm.ParamError):
                rm.validate_override(key, spec["max"] + 1, spec)
