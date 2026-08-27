"""Tests for the enriched "Progress & Status" history table.

The rules that matter most here are about honesty, not layout:

  * a metric semantics note travels with every comparison and every CSV row,
    because precision/recall/F1 mean different things per pipeline family
    (HIKARI = weighted average over all classes; EVE = attack class on the
    natural holdout);
  * nothing is ever ranked across families — the "best value" highlight is
    computed *within* a family;
  * no parameter is invented. The database and the artifacts store none, so the
    only source is the pipeline definition, and a pipeline that lacks a key
    shows "—" rather than a borrowed value.
"""
import csv
import io
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ui.components import experiment_table as et

REPO_ROOT = Path(__file__).resolve().parents[1]

HIKARI, EVE = et.FAMILY_HIKARI, et.FAMILY_EVE

PARAMS = {
    "hikari2021.dt_pipeline": {"random_state": 42, "test_size": 0.3,
                               "balancing": "None"},
    "eve_cbr.dt": {"cv_folds": 2, "models": ["DT"]},
}


def _reader():
    return PARAMS


def _exp(i, *, dataset=HIKARI, pipeline="hikari2021.dt_pipeline",
         status="FINISHED", created="2026-03-05T10:00:00+00:00",
         accuracy=0.9, f1=0.88, dhash="aaaa1111bbbb2222", owner=None,
         version=None):
    return {
        "id": f"exp-{i}-0000-0000", "dataset_type": dataset,
        "dataset_path": "/app/storage/datasets/file.csv", "dataset_hash": dhash,
        "pipeline_id": pipeline, "status": status, "created_at": created,
        "started_at": created, "completed_at": "2026-03-05T10:02:00+00:00",
        "accuracy": accuracy, "precision_score": 0.91, "recall": 0.89,
        "f1_score": f1, "owner": owner, "pipeline_version": version,
    }


def _rows(*experiments, roc=None):
    return et.build_rows(list(experiments),
                         roc_reader=(lambda _id: roc) if roc is not None else None,
                         params_reader=_reader)


# ── grouped columns ───────────────────────────────────────────────────────

def test_columns_are_grouped_identity_parameter_metric():
    columns = et.build_columns(["random_state", "test_size"])
    groups = et.columns_by_group(columns)

    assert list(et.GROUP_ORDER) == [et.GROUP_IDENTITY, et.GROUP_PARAM,
                                    et.GROUP_METRIC]
    assert {c["label"] for c in groups[et.GROUP_IDENTITY]} >= {
        "Waktu", "Pipeline", "Dataset", "Status", "Pemilik", "Durasi"}
    assert {c["label"] for c in groups[et.GROUP_PARAM]} == {"random_state",
                                                            "test_size"}
    assert {c["label"] for c in groups[et.GROUP_METRIC]} == {
        "Accuracy", "Precision", "Recall", "F1-score", "ROC-AUC"}


def test_parameter_columns_are_derived_from_the_pipelines_themselves():
    """Union dihitung dari get_info, bukan didaftar manual."""
    keys = et.parameter_keys(_reader)
    assert keys == sorted({"random_state", "test_size", "balancing",
                           "cv_folds", "models"})


def test_a_pipeline_without_a_parameter_shows_a_dash_not_a_borrowed_value():
    """EVE tidak punya test_size — kolomnya kosong, bukan diisi nilai HIKARI."""
    rows = _rows(_exp(1, pipeline="eve_cbr.dt", dataset=EVE))
    columns = {c["label"]: c for c in et.build_columns(et.parameter_keys(_reader))}

    assert et.cell_text(rows[0], columns["cv_folds"]) == "2"
    assert et.cell_text(rows[0], columns["test_size"]) == "—"
    assert et.cell_text(rows[0], columns["random_state"]) == "—"


def test_parameters_come_from_the_pipeline_definition_and_say_so():
    """Sejak ada mode eksekusi, parameter punya DUA asal-usul — dan keterangan
    itu harus menyebut keduanya, bukan menyamakannya."""
    assert "get_info" in et.PARAM_PROVENANCE
    assert "direkam saat eksperimen" in et.PARAM_PROVENANCE
    assert "definisi pipeline" in et.PARAM_PROVENANCE


def test_a_recorded_run_is_not_presented_as_a_definition_value():
    import json
    rows = et.build_rows(
        [{"id": "a", "pipeline_id": "hikari2021.rfc_pipeline",
          "dataset_type": HIKARI, "params_used": json.dumps({"n_estimators": 250})},
         {"id": "b", "pipeline_id": "hikari2021.rfc_pipeline", "dataset_type": HIKARI}],
        params_reader=lambda: {"hikari2021.rfc_pipeline": {"n_estimators": 100}},
    )
    assert (rows[0]["param_n_estimators"], rows[0]["_params_recorded"]) == (250, True)
    assert (rows[1]["param_n_estimators"], rows[1]["_params_recorded"]) == (100, False)


def test_the_real_registry_supplies_real_parameters():
    """Tanpa mock: nilai yang dipakai halaman benar-benar ada di pipeline."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    params = {}
    for pid, meta in PIPELINE_REGISTRY.items():
        info = meta["class"]().get_info() or {}
        fixed = info.get("fixed_params")
        params[pid] = dict(fixed) if isinstance(fixed, dict) else {}

    assert params["hikari2021.dt_pipeline"]["test_size"] == 0.3
    assert "test_size" not in params["eve_cbr.dt"]
    assert et.parameter_keys(lambda: params)


def test_the_page_no_longer_hardcodes_parameter_values():
    """Regresi: tabel lama menuliskan random_state 42 & test_split 0.20 untuk
    SETIAP baris — padahal 0.20 tidak pernah dipakai pipeline mana pun."""
    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
    assert '"random_state": "42"' not in src
    assert '"test_split"' not in src
    assert "0.20" not in src


# ── number formatting ─────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    (0.8607489314700091, "0.8607"), (1, "1.0000"), (0, "0.0000"),
    (None, "—"), ("x", "—"), (float("nan"), "—"),
])
def test_metrics_are_shown_with_four_decimals(value, expected):
    assert et.format_metric(value) == expected


@pytest.mark.parametrize("start, end, expected", [
    ("2026-03-05T10:00:00+00:00", "2026-03-05T10:00:30+00:00", "30s"),
    ("2026-03-05T10:00:00+00:00", "2026-03-05T10:03:00+00:00", "3.0 menit"),
    ("2026-03-05T10:00:00+00:00", "2026-03-05T12:30:00+00:00", "2.5 jam"),
    (None, "2026-03-05T10:00:00+00:00", "—"),
    ("2026-03-05T10:00:00+00:00", None, "—"),
])
def test_duration_is_readable(start, end, expected):
    assert et.format_duration(start, end) == expected


def test_a_missing_metric_is_never_shown_as_zero():
    rows = _rows(_exp(1, accuracy=None, f1=None))
    columns = {c["key"]: c for c in et.build_columns()}
    assert et.cell_text(rows[0], columns["accuracy"]) == "—"
    assert rows[0]["accuracy"] is None


def test_built_in_pipelines_show_a_dash_for_version_not_zero():
    """pipeline_version NULL untuk pipeline bawaan — jangan jadi 0."""
    rows = _rows(_exp(1, version=None))
    assert rows[0]["pipeline_version"] == "—"


def test_an_experiment_without_an_owner_reads_as_sistem():
    assert _rows(_exp(1, owner=None))[0]["pemilik"] == "sistem"


def test_windows_and_posix_dataset_paths_both_shorten():
    assert et.basename("/app/storage/datasets/a.csv") == "a.csv"
    assert et.basename(r"D:\Program\TA\storage\datasets\b.csv") == "b.csv"
    assert et.basename(None) == "—"


# ── column picker ─────────────────────────────────────────────────────────

def test_the_default_column_set_is_the_core_one():
    """"mode" ikut inti: run eksplorasi harus terbedakan tanpa membuka pemilih
    kolom lebih dulu."""
    assert et.DEFAULT_COLUMNS == ["waktu", "pipeline", "dataset", "mode",
                                  "status", "accuracy", "f1"]


def test_visible_columns_keep_the_spec_order_not_the_click_order():
    columns = et.build_columns()
    picked = et.visible_columns(columns, ["f1", "waktu", "status"])
    assert [c["key"] for c in picked] == ["waktu", "status", "f1"]


def test_unknown_column_keys_are_ignored():
    columns = et.build_columns()
    assert et.visible_columns(columns, ["waktu", "tidak_ada"]) == [
        c for c in columns if c["key"] == "waktu"]


# ── filters ───────────────────────────────────────────────────────────────

def test_filter_options_come_from_the_data():
    rows = _rows(_exp(1), _exp(2, dataset=EVE, pipeline="eve_cbr.dt",
                               status="FAILED"))
    options = et.filter_options(rows)
    assert options["datasets"] == sorted([HIKARI, EVE])
    assert options["statuses"] == ["FAILED", "FINISHED"]
    assert options["pipelines"] == sorted(["hikari2021.dt_pipeline", "eve_cbr.dt"])


def test_no_filter_means_everything_passes():
    rows = _rows(_exp(1), _exp(2))
    assert len(et.apply_filters(rows)) == 2
    assert len(et.apply_filters(rows, pipelines=[], statuses=[])) == 2


@pytest.mark.parametrize("kwargs, expected", [
    ({"statuses": ["FINISHED"]}, 1),
    ({"datasets": [EVE]}, 1),
    ({"pipelines": ["eve_cbr.dt"]}, 1),
    ({"statuses": ["FINISHED"], "datasets": [EVE]}, 0),
])
def test_filters_narrow_the_rows(kwargs, expected):
    rows = _rows(_exp(1), _exp(2, dataset=EVE, pipeline="eve_cbr.dt",
                               status="FAILED"))
    assert len(et.apply_filters(rows, **kwargs)) == expected


def test_the_date_range_is_inclusive_on_both_ends():
    rows = _rows(_exp(1, created="2026-03-01T08:00:00+00:00"),
                 _exp(2, created="2026-03-05T08:00:00+00:00"),
                 _exp(3, created="2026-03-09T08:00:00+00:00"))
    got = et.apply_filters(rows, start=date(2026, 3, 1), end=date(2026, 3, 5))
    assert len(got) == 2
    assert len(et.apply_filters(rows, start=date(2026, 3, 5))) == 2
    assert len(et.apply_filters(rows, end=date(2026, 3, 1))) == 1


def test_the_result_summary_shows_both_numbers():
    assert et.result_summary(12, 20) == "12 dari 20 eksperimen"


# ── metric semantics (the honesty rules) ──────────────────────────────────

def test_each_family_has_its_own_documented_semantics():
    assert "weighted" in et.METRIC_SEMANTICS[HIKARI].lower()
    assert "natural-holdout" in et.METRIC_SEMANTICS[EVE]
    assert "serangan" in et.METRIC_SEMANTICS[EVE]


def test_a_single_family_still_states_what_the_numbers_mean():
    note = et.semantics_note(_rows(_exp(1)))
    assert et.METRIC_SEMANTICS[HIKARI] in note
    assert et.METRIC_SEMANTICS[EVE] not in note


def test_mixing_families_is_detected():
    rows = _rows(_exp(1), _exp(2, dataset=EVE, pipeline="eve_cbr.dt"))
    assert et.is_cross_family(rows) is True
    assert et.is_cross_family(_rows(_exp(1))) is False


def test_comparing_across_families_raises_a_semantic_warning():
    rows = _rows(_exp(1), _exp(2, dataset=EVE, pipeline="eve_cbr.dt"))
    warnings = et.comparison_warnings(rows)
    assert any("TIDAK sebanding" in w for w in warnings)
    assert any(et.METRIC_SEMANTICS[EVE] in w for w in warnings)


def test_comparing_within_one_family_raises_no_semantic_warning():
    rows = _rows(_exp(1), _exp(2))
    assert et.CROSS_FAMILY_WARNING not in et.comparison_warnings(rows)


def test_a_different_dataset_hash_is_flagged():
    rows = _rows(_exp(1, dhash="aaaa"), _exp(2, dhash="bbbb"))
    assert any("hash berbeda" in w for w in et.comparison_warnings(rows))


def test_the_same_dataset_hash_is_not_flagged():
    rows = _rows(_exp(1, dhash="aaaa"), _exp(2, dhash="aaaa"))
    assert not any("hash berbeda" in w for w in et.comparison_warnings(rows))


# ── no automatic cross-family ranking ─────────────────────────────────────

def test_the_best_value_is_marked_within_each_family_only():
    rows = _rows(_exp(1, f1=0.70), _exp(2, f1=0.95),
                 _exp(3, dataset=EVE, pipeline="eve_cbr.dt", f1=0.60))
    et.mark_best_within_family(rows)
    flag = et.best_flag_key("f1")

    assert [r[flag] for r in rows] == [False, True, True]


def test_a_lower_score_still_wins_inside_its_own_family():
    """EVE 0.60 tetap ditandai walau HIKARI punya 0.95 — justru itu intinya:
    keduanya bukan angka yang sebanding."""
    rows = _rows(_exp(1, f1=0.95), _exp(2, dataset=EVE,
                                        pipeline="eve_cbr.dt", f1=0.60))
    et.mark_best_within_family(rows)
    assert rows[1][et.best_flag_key("f1")] is True


def test_rows_without_a_known_family_are_never_marked():
    rows = _rows(_exp(1, dataset="SESUATU_LAIN", f1=0.99))
    et.mark_best_within_family(rows)
    assert rows[0][et.best_flag_key("f1")] is False


def test_missing_metrics_are_never_marked_best():
    rows = _rows(_exp(1, f1=None), _exp(2, f1=None))
    et.mark_best_within_family(rows)
    assert not any(r[et.best_flag_key("f1")] for r in rows)


def test_no_overall_best_model_helper_exists():
    """Tidak boleh ada fungsi yang menobatkan juara lintas keluarga."""
    names = dir(et)
    for banned in ("best_model", "rank_experiments", "leaderboard",
                   "best_overall", "top_experiment"):
        assert banned not in names, banned

    src = (REPO_ROOT / "ui" / "components"
           / "experiment_table.py").read_text(encoding="utf-8")
    assert "TIDAK PERNAH menyusun peringkat" in src


# ── side-by-side comparison ───────────────────────────────────────────────

def test_the_comparison_has_one_column_per_experiment():
    rows = _rows(_exp(1), _exp(2))
    data = et.build_comparison(rows, et.parameter_keys(_reader))
    assert len(data["headers"]) == 2
    for section in data["sections"]:
        for field in section["fields"]:
            assert len(field["values"]) == 2


def test_the_comparison_covers_all_three_groups():
    rows = _rows(_exp(1), _exp(2, pipeline="eve_cbr.dt", dataset=EVE))
    data = et.build_comparison(rows, et.parameter_keys(_reader))
    assert [s["group"] for s in data["sections"]] == list(et.GROUP_ORDER)


def test_differing_values_are_flagged_and_identical_ones_are_not():
    rows = _rows(_exp(1, status="FINISHED"), _exp(2, status="FAILED"))
    data = et.build_comparison(rows)
    fields = {f["label"]: f for s in data["sections"] for f in s["fields"]}

    assert fields["Status"]["differs"] is True
    assert fields["Pipeline"]["differs"] is False
    assert fields["Pemilik"]["differs"] is False


def test_the_comparison_shows_traceability_fields():
    rows = _rows(_exp(1), _exp(2))
    data = et.build_comparison(rows)
    labels = {f["label"] for s in data["sections"] for f in s["fields"]}
    assert "Hash dataset" in labels
    assert "Versi pipeline" in labels


def test_parameter_rows_that_are_empty_everywhere_are_dropped():
    """Kunci yang tidak dipakai satu pun eksperimen terpilih hanya jadi bising."""
    rows = _rows(_exp(1), _exp(2))          # keduanya HIKARI
    keys = et.parameter_keys(_reader) + ["tidak_dipakai_siapa_pun"]
    data = et.build_comparison(rows, keys)
    params = next(s for s in data["sections"] if s["group"] == et.GROUP_PARAM)
    labels = {f["label"] for f in params["fields"]}

    assert "tidak_dipakai_siapa_pun" not in labels
    assert "cv_folds" not in labels          # milik EVE, tak satu pun terpilih
    assert "random_state" in labels


def test_the_comparison_carries_its_warnings_and_note():
    rows = _rows(_exp(1), _exp(2, dataset=EVE, pipeline="eve_cbr.dt"))
    data = et.build_comparison(rows, et.parameter_keys(_reader))
    assert data["warnings"]
    assert et.METRIC_SEMANTICS[EVE] in data["note"]


# ── selection limits ──────────────────────────────────────────────────────

def test_comparing_needs_at_least_two():
    assert "minimal dua" in et.compare_selection_error([])
    assert "minimal dua" in et.compare_selection_error(["a"])


def test_comparing_is_capped():
    assert et.MAX_COMPARE == 5
    ids = [f"e{i}" for i in range(6)]
    message = et.compare_selection_error(ids)
    assert str(et.MAX_COMPARE) in message
    assert "6" in message


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_a_legal_selection_has_no_error(count):
    assert et.compare_selection_error([f"e{i}" for i in range(count)]) == ""


# ── CSV export ────────────────────────────────────────────────────────────

def _parsed(csv_text):
    return list(csv.reader(io.StringIO(csv_text)))


def test_the_csv_follows_the_chosen_columns():
    rows = _rows(_exp(1))
    columns = et.visible_columns(et.build_columns(), ["waktu", "f1"])
    table = _parsed(et.to_csv(rows, columns))

    assert table[0] == ["Waktu", "F1-score", et.CSV_SEMANTICS_COLUMN,
                        et.CSV_MODE_COLUMN, et.CSV_PARAMS_COLUMN]
    assert table[1][1] == "0.8800"


def test_the_csv_follows_the_active_filter():
    rows = _rows(_exp(1), _exp(2, status="FAILED"))
    filtered = et.apply_filters(rows, statuses=["FAILED"])
    columns = et.visible_columns(et.build_columns(), ["status"])
    table = _parsed(et.to_csv(filtered, columns))

    assert len(table) == 2                   # header + satu baris
    assert table[1][0] == "FAILED"


def test_every_csv_row_carries_its_metric_semantics():
    """Berkas yang dibaca terpisah dari aplikasi tidak boleh menyesatkan."""
    rows = _rows(_exp(1), _exp(2, dataset=EVE, pipeline="eve_cbr.dt"))
    columns = et.visible_columns(et.build_columns(), ["dataset", "f1"])
    table = _parsed(et.to_csv(rows, columns))

    semantics = table[0].index(et.CSV_SEMANTICS_COLUMN)
    assert et.METRIC_SEMANTICS[HIKARI] in table[1][semantics]
    assert et.METRIC_SEMANTICS[EVE] in table[2][semantics]


def test_an_unknown_family_says_so_rather_than_guessing():
    rows = _rows(_exp(1, dataset="SESUATU_LAIN"))
    columns = et.visible_columns(et.build_columns(), ["dataset"])
    table = _parsed(et.to_csv(rows, columns))
    assert "tidak dikenal" in table[1][table[0].index(et.CSV_SEMANTICS_COLUMN)]


def test_the_csv_is_not_a_raw_database_dump():
    """Hanya kolom yang dipilih — bukan seluruh isi baris basis data."""
    rows = _rows(_exp(1))
    columns = et.visible_columns(et.build_columns(), ["waktu"])
    text = et.to_csv(rows, columns)
    assert "/app/storage/datasets" not in text      # dataset_path tidak ikut
    assert "exp-1-0000-0000" not in text            # id penuh tidak ikut


def test_the_csv_filename_carries_a_timestamp():
    name = et.csv_filename(datetime(2026, 3, 5, 14, 30, 5))
    assert name == "eksperimen-20260305-143005.csv"
    assert re.match(r"eksperimen-\d{8}-\d{6}\.csv$", et.csv_filename())


# ── expression search (safe parser) ───────────────────────────────────────

def test_the_parser_never_uses_eval_or_exec():
    src = (REPO_ROOT / "ui" / "components"
           / "experiment_table.py").read_text(encoding="utf-8")
    import ast

    tree = ast.parse(src)
    called = {getattr(c.func, "id", None) for c in ast.walk(tree)
              if isinstance(c, ast.Call)}
    for banned in ("eval", "exec", "compile", "__import__"):
        assert banned not in called, banned


@pytest.mark.parametrize("text, expected", [
    ("f1 > 0.8", [("f1", ">", 0.8)]),
    ("accuracy >= 0.9", [("accuracy", ">=", 0.9)]),
    ("auc<0.5", [("auc", "<", 0.5)]),
    ("f1 > 0.8 and accuracy >= 0.9",
     [("f1", ">", 0.8), ("accuracy", ">=", 0.9)]),
    ("F1 > 0.8", [("f1", ">", 0.8)]),
    ("roc_auc != 1", [("auc", "!=", 1.0)]),
])
def test_valid_expressions_parse(text, expected):
    assert et.parse_expression(text) == expected


def test_an_empty_expression_means_no_filtering():
    assert et.parse_expression("") == []
    assert et.parse_expression("   ") == []


@pytest.mark.parametrize("text", [
    "f1", "f1 >", "> 0.8", "hapus semua", "f1 ~ 0.8",
    "__import__('os')", "f1 > 0.8; drop table", "loss > 0.1",
])
def test_invalid_expressions_raise_a_clear_message(text):
    with pytest.raises(et.ExpressionError) as excinfo:
        et.parse_expression(text)
    assert str(excinfo.value)                # ada pesan, bukan crash telanjang


def test_expressions_filter_rows():
    rows = _rows(_exp(1, f1=0.95), _exp(2, f1=0.50))
    terms = et.parse_expression("f1 > 0.8")
    assert len(et.apply_expression(rows, terms)) == 1


def test_a_row_without_the_metric_never_passes_a_threshold():
    """Nilai yang tidak ada bukan nol."""
    rows = _rows(_exp(1, f1=None))
    assert et.apply_expression(rows, et.parse_expression("f1 < 0.5")) == []
    assert et.apply_expression(rows, et.parse_expression("f1 > 0.5")) == []


def test_the_help_text_lists_the_usable_names():
    for name in ("accuracy", "precision", "recall", "f1", "auc"):
        assert name in et.EXPR_HELP


# ── the page itself still renders, and keeps what it already had ──────────

PAGE_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
from ui.views.view_results import render
for key, value in (st.session_state.get("_preset") or {{}}).items():
    st.session_state[key] = value
render()
'''


def _run_page(tmp_path, preset=None):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "history_app.py"
    script.write_text(PAGE_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=600)
    if preset:
        at.session_state["_preset"] = preset
    at.run()
    return at


def test_the_page_renders_without_exception(tmp_path):
    at = _run_page(tmp_path)
    assert at.exception is None or not at.exception


def test_the_new_controls_are_present(tmp_path):
    at = _run_page(tmp_path)
    labels = [b.label for b in at.button]

    assert any("Bandingkan terpilih" in l for l in labels)
    assert "Bersihkan filter" in labels
    assert "Kembalikan ke set inti" in labels
    assert any("Unduh CSV" == d.label for d in at.get("download_button"))


def test_the_compare_button_is_disabled_without_a_selection(tmp_path):
    at = _run_page(tmp_path)
    button = next(b for b in at.button if "Bandingkan terpilih" in b.label)
    assert button.disabled is True
    assert "(0)" in button.label


def test_the_result_count_is_shown(tmp_path):
    """Jumlah baris menempel pada tombol Unduh CSV — tombol itu mengikuti
    filter yang persis sama, jadi angkanya selalu cocok dengan isinya."""
    at = _run_page(tmp_path)
    csv = next(b for b in at.get("download_button") if b.label == "Unduh CSV")
    assert re.search(r"\d+ dari \d+ eksperimen", csv.help or "")


def test_the_running_block_and_history_both_survive(tmp_path):
    at = _run_page(tmp_path)
    headers = [s.value for s in at.subheader]
    assert "Sedang Berjalan" in headers
    assert "Riwayat Eksperimen" in headers


def test_the_old_row_actions_are_still_wired(tmp_path):
    """Detail, re-run, cancel, dan PDF tidak ikut hilang saat tabel diperkaya."""
    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")

    for kept in ("_detail_dialog", "rerun_experiment", "cancel_experiment",
                 "_pdf_download_button", "Download PDF Report",
                 "_render_selected_actions", "_render_running_section",
                 "render_results", "normalize_result_payload"):
        assert kept in src, kept
    # Pagination tetap ada untuk riwayat yang panjang.
    assert '"pagination"' in src
    assert '"paginationPageSize"' in src


def test_reading_the_page_never_requires_a_login(tmp_path):
    """Keterbukaan membaca tidak berubah: tidak ada gerbang izin di halaman."""
    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
    for gate in ("require_upload", "require_approve", "require_manage_users",
                 "PermissionDenied", "st.stop()"):
        assert gate not in src, gate


def test_the_comparison_dialog_renders_with_a_preset_selection(tmp_path):
    """Dua eksperimen nyata dari basis data, dibandingkan lewat flag."""
    from orchestrator.result_service import list_all_experiments

    experiments = list_all_experiments()
    if len(experiments) < 2:
        pytest.skip("basis data tidak memuat cukup eksperimen")

    ids = [e["id"] for e in experiments[:2]]
    at = _run_page(tmp_path, preset={"_hist_compare_ids": ids})
    assert at.exception is None or not at.exception

    # Tabel perbandingan kini SATU tabel HTML (st.html) supaya lebar kolomnya
    # benar-benar seragam; di AppTest ia terbaca lewat proto elemen html.
    blocks = [e.proto.body for e in at.get("html")]
    tables = [b for b in blocks if 'class="ids-cmp"' in b]
    assert tables, "tabel perbandingan tidak terender"
    table = next(b for b in tables if "Accuracy" in b)
    # Satu tabel per blok — kolomnya selaras karena semuanya table-layout:fixed
    # dengan lebar kolom pertama yang sama.
    assert table.count("<table") == 1
    assert "table-layout: fixed" in "".join(blocks)   # lebar kolom seragam
    for group in ("Identitas", "Metrik"):             # pemisah antar-kelompok
        assert f'class="ids-cmp-group"' in table and group in table


def test_a_cross_family_comparison_warns_in_the_page(tmp_path):
    from orchestrator.result_service import list_all_experiments

    experiments = list_all_experiments()
    picked = []
    for family in (et.FAMILY_HIKARI, et.FAMILY_EVE):
        hit = next((e for e in experiments if e.get("dataset_type") == family), None)
        if hit:
            picked.append(hit["id"])
    if len(picked) < 2:
        pytest.skip("basis data tidak memuat kedua keluarga pipeline")

    at = _run_page(tmp_path, preset={"_hist_compare_ids": picked})
    warnings = " ".join(w.value for w in at.warning)
    assert "TIDAK sebanding" in warnings


def test_a_stale_comparison_flag_is_dropped_instead_of_crashing(tmp_path):
    at = _run_page(tmp_path, preset={"_hist_compare_ids": ["tidak-ada-1",
                                                           "tidak-ada-2"]})
    assert at.exception is None or not at.exception
    tables = [m.value for m in at.markdown if m.value.startswith("| Field")]
    assert not tables
