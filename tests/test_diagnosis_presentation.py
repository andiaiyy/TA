"""Tests for the diagnosis PRESENTATION layer (ui/views/run_experiment).

The diagnosis logic itself lives in orchestrator/dataset_diagnostics.py and is
covered by tests/test_dataset_diagnostics.py. What is tested here is only how a
result is presented: the three-tier verdict, the one-sentence cause, the
"Agar cocok…" action mapping, and the ordering — plus a regression test for the
mojibake ("�") that public IDS datasets ship inside their label values.

Pure: built on hand-made check dicts, never on a real dataset file.
"""
from pathlib import Path

import pytest

from contracts.dataset_schemas import supported_datasets
from orchestrator.dataset_diagnostics import sanitize_display_value
from ui.views.run_experiment import (
    VERDICT_NEAR, VERDICT_NO, VERDICT_OK, _ACTION_HINTS, _action_sentence,
    _any_compatible, _cause_sentence, _compatible_names, _primary_failure,
    _requirement_summary, _sorted_results, _verdict,
)


def _check(key, status, message="pesan", count=0, examples=None):
    return {"key": key, "title": key.title(), "status": status,
            "message": message, "count": count, "examples": examples or []}


def _result(compatible, checks):
    return {"compatible": compatible, "checks": checks}


def _all_pass():
    return [_check(k, "pass") for k in ("format", "label", "features", "dtype", "classes")]


# ── verdict: three tiers, not binary ──────────────────────────────────────

def test_compatible_result_is_cocok():
    assert _verdict(_result(True, _all_pass())) == VERDICT_OK


def test_warn_only_result_is_still_cocok():
    checks = _all_pass()
    checks[3] = _check("dtype", "warn")
    assert _verdict(_result(True, checks)) == VERDICT_OK


def test_features_failure_with_good_format_and_label_is_hampir_cocok():
    checks = _all_pass()
    checks[2] = _check("features", "fail", count=87)
    assert _verdict(_result(False, checks)) == VERDICT_NEAR


def test_class_failure_with_good_format_and_label_is_hampir_cocok():
    checks = _all_pass()
    checks[4] = _check("classes", "fail", count=1)
    assert _verdict(_result(False, checks)) == VERDICT_NEAR


def test_format_failure_is_tidak_cocok():
    checks = [_check("format", "fail")] + [
        _check(k, "skip") for k in ("label", "features", "dtype", "classes")]
    assert _verdict(_result(False, checks)) == VERDICT_NO


def test_label_failure_is_tidak_cocok():
    """A missing label column is fundamental, not a near miss."""
    checks = _all_pass()
    checks[1] = _check("label", "fail")
    checks[4] = _check("classes", "skip")
    assert _verdict(_result(False, checks)) == VERDICT_NO


# ── primary failure + one-sentence cause ──────────────────────────────────

def test_primary_failure_follows_priority_order():
    checks = [_check("format", "fail"), _check("label", "fail"),
              _check("features", "fail"), _check("dtype", "pass"),
              _check("classes", "fail")]
    assert _primary_failure(_result(False, checks))["key"] == "format"


def test_cause_for_format_names_both_formats():
    diag = {"detected_format": "csv"}
    checks = [_check("format", "fail")] + [
        _check(k, "skip") for k in ("label", "features", "dtype", "classes")]
    cause = _cause_sentence(diag, "EVE_SURICATA", _result(False, checks))
    assert "NDJSON" in cause and "CSV" in cause


def test_cause_for_features_summarises_count_without_listing_columns():
    """The summary must carry the number, never the 87 column names."""
    names = [f"col_{i}" for i in range(87)]
    checks = _all_pass()
    checks[2] = _check("features", "fail",
                       message="Dataset Anda kurang 87 kolom: " + ", ".join(names),
                       count=87, examples=names[:5])
    cause = _cause_sentence({"detected_format": "csv"}, "HIKARI2021",
                            _result(False, checks))
    assert "87" in cause
    assert "col_10" not in cause          # no column dump in the summary
    assert len(cause) < 200


def test_cause_for_single_class_is_one_sentence():
    checks = _all_pass()
    checks[4] = _check("classes", "fail", count=1)
    cause = _cause_sentence({"detected_format": "csv"}, "HIKARI2021",
                            _result(False, checks))
    assert "dua kelas" in cause
    assert cause.count(".") == 1


def test_cause_for_compatible_result_has_no_failure():
    cause = _cause_sentence({"detected_format": "csv"}, "HIKARI2021",
                            _result(True, _all_pass()))
    assert "lulus" in cause.lower()


# ── action mapping lives in ONE dict ──────────────────────────────────────

@pytest.mark.parametrize("key", ["format", "label", "features", "classes"])
@pytest.mark.parametrize("dtype", ["HIKARI2021", "EVE_SURICATA"])
def test_every_failure_type_has_an_action_for_every_dataset_type(key, dtype):
    assert _ACTION_HINTS[key][dtype].strip()


def test_action_sentence_matches_the_primary_failure():
    checks = _all_pass()
    checks[2] = _check("features", "fail", count=87)
    action = _action_sentence("HIKARI2021", _result(False, checks))
    assert action.startswith("**Agar cocok:**")
    assert "ALLFLOWMETER" in action


def test_action_sentence_is_empty_when_compatible():
    assert _action_sentence("HIKARI2021", _result(True, _all_pass())) == ""


# ── ordering: closest match first ─────────────────────────────────────────

def test_results_are_sorted_closest_match_first():
    near = _all_pass()
    near[2] = _check("features", "fail", count=3)
    no = [_check("format", "fail")] + [
        _check(k, "skip") for k in ("label", "features", "dtype", "classes")]
    diag = {"results": {
        "NO_TYPE": _result(False, no),
        "NEAR_TYPE": _result(False, near),
        "OK_TYPE": _result(True, _all_pass()),
    }}
    assert [t for t, _ in _sorted_results(diag)] == ["OK_TYPE", "NEAR_TYPE", "NO_TYPE"]


# ── on-demand flow: any_compatible decides whether the boxes appear ───────

def test_any_compatible_is_true_when_one_pipeline_fits():
    diag = {"compatible_types": ["HIKARI2021"],
            "results": {"HIKARI2021": _result(True, _all_pass())}}
    assert _any_compatible(diag) is True


def test_any_compatible_is_false_when_nothing_fits():
    checks = _all_pass()
    checks[2] = _check("features", "fail", count=9)
    diag = {"compatible_types": [],
            "results": {"HIKARI2021": _result(False, checks)}}
    assert _any_compatible(diag) is False


def test_any_compatible_is_false_on_a_failed_diagnosis():
    """Unreadable file → no results at all → boxes, never the normal flow."""
    assert _any_compatible({"error": "boom", "results": {}, "compatible_types": []}) is False


def test_compatible_names_are_display_names_not_raw_types():
    diag = {"compatible_types": ["HIKARI2021"]}
    names = _compatible_names(diag)
    assert names and names[0] != "HIKARI2021"     # resolved to the research label


# ── the box summary line is schema-derived, one per research pipeline ─────

@pytest.mark.parametrize("dtype", supported_datasets())
def test_every_research_pipeline_has_a_one_line_requirement_summary(dtype):
    from contracts.dataset_schemas import get_schema
    summary = _requirement_summary(dtype)
    assert "\n" not in summary                     # strictly one line
    assert get_schema(dtype)["label_column"] in summary
    assert "—" not in summary                      # no missing-piece placeholder


def test_requirement_summary_names_the_accepted_extensions():
    assert "`.csv`" in _requirement_summary("HIKARI2021")
    assert ".ndjson" in _requirement_summary("EVE_SURICATA")


# ── presentation of long lists and skipped checks ─────────────────────────

def test_missing_columns_summary_shows_count_and_capped_examples():
    from ui.views.run_experiment import _MISSING_PREVIEW, _missing_items_summary

    names = [f"col_{i}" for i in range(87)]
    text = _missing_items_summary(87, names, "HIKARI2021")
    assert "87 kolom" in text
    assert "HIKARI2021" in text
    assert text.count("`col_") == _MISSING_PREVIEW          # contoh dibatasi
    assert f"+{87 - _MISSING_PREVIEW} lainnya" in text
    assert "col_50" not in text                              # tidak ada dump


def test_missing_columns_summary_omits_the_rest_marker_when_all_are_shown():
    from ui.views.run_experiment import _missing_items_summary

    text = _missing_items_summary(2, ["a", "b"], "HIKARI2021")
    assert "lainnya" not in text
    assert "`a`" in text and "`b`" in text


def test_missing_items_summary_respects_the_unit_for_json_schemas():
    from ui.views.run_experiment import _missing_items_summary

    text = _missing_items_summary(3, ["timestamp"], "EVE_SURICATA", unit="kunci JSON")
    assert "3 kunci JSON" in text


def test_identical_skipped_checks_collapse_into_one_line(monkeypatch):
    """Format gagal → empat cek sisanya tidak boleh jadi empat baris identik."""
    import ui.views.run_experiment as rx

    lines: list[str] = []
    monkeypatch.setattr(rx.st, "markdown", lambda s, **k: lines.append(s))
    reason = "Tidak diperiksa karena format berkas belum sesuai."
    checks = [_check("format", "fail", "Format terdeteksi CSV…")] + [
        _check(k, "skip", reason) for k in ("label", "features", "dtype", "classes")]

    rx._render_check_list(_result(False, checks), "EVE_SURICATA")

    assert len(lines) == 2                       # satu baris gagal + satu baris ringkas
    collapsed = lines[1]
    assert collapsed.count(reason) == 1
    for title in ("Label", "Features", "Dtype", "Classes"):
        assert title in collapsed                # semua cek yang dilewati disebut


def test_a_lone_skipped_check_keeps_its_own_line(monkeypatch):
    """Skip yang berdiri sendiri (mis. "tidak berlaku") tetap satu baris utuh."""
    import ui.views.run_experiment as rx

    lines: list[str] = []
    monkeypatch.setattr(rx.st, "markdown", lambda s, **k: lines.append(s))
    checks = _all_pass()
    checks[3] = _check("dtype", "skip", "Tidak berlaku — pipeline merekayasa fiturnya.")

    rx._render_check_list(_result(True, checks), "EVE_SURICATA")

    assert len(lines) == 5
    assert "Tidak berlaku" in lines[3]
    assert "Pemeriksaan lain" not in lines[3]


def test_features_failure_in_the_check_list_uses_the_shared_summary(monkeypatch):
    """Rincian dialog dan ringkasan validasi harus berbunyi sama."""
    import ui.views.run_experiment as rx

    lines: list[str] = []
    monkeypatch.setattr(rx.st, "markdown", lambda s, **k: lines.append(s))
    names = [f"col_{i}" for i in range(87)]
    checks = _all_pass()
    checks[2] = _check("features", "fail",
                       message="Dataset Anda kurang 87 kolom: " + ", ".join(names),
                       count=87, examples=names[:rx._MISSING_PREVIEW])

    rx._render_check_list(_result(False, checks), "HIKARI2021")

    features_line = lines[2]
    assert "87 kolom" in features_line
    assert rx._missing_items_summary(87, names[:rx._MISSING_PREVIEW], "HIKARI2021") in features_line
    assert "col_40" not in features_line          # daftar penuh tidak ikut


def test_validation_failure_never_prints_the_raw_column_dump(monkeypatch):
    """Regresi: "Missing required columns: [80+ kolom]" tidak boleh muncul."""
    import ui.views.run_experiment as rx
    from orchestrator.validator import ValidationResult

    shown: list[str] = []
    for name in ("markdown", "error", "code", "caption"):
        monkeypatch.setattr(rx.st, name, lambda s, **k: shown.append(str(s)))
    expanders: list[tuple] = []

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(rx.st, "expander",
                        lambda label, **k: (expanders.append((label, k.get("expanded"))), _Ctx())[1])

    missing = [f"col_{i}" for i in range(87)]
    vr = ValidationResult(is_valid=False, dataset_type="HIKARI2021", row_count=10,
                          column_count=5, label_column="Label",
                          missing_columns=missing,
                          errors=[f"Missing required columns: {missing}"])
    rx._render_validation_failure({"success": False, "error": "; ".join(vr.errors),
                                   "validation_result": vr}, "HIKARI2021")

    assert not any("Missing required columns" in s for s in shown)
    assert any("87 kolom" in s for s in shown)
    assert any("Uji kecocokan" in s for s in shown)
    # Daftar penuh hanya di dalam expander yang TERTUTUP secara default.
    assert expanders and expanders[0][1] is False


def test_validation_failure_keeps_other_short_errors_verbatim(monkeypatch):
    import ui.views.run_experiment as rx
    from orchestrator.validator import ValidationResult

    shown: list[str] = []
    for name in ("markdown", "error", "code", "caption"):
        monkeypatch.setattr(rx.st, name, lambda s, **k: shown.append(str(s)))

    vr = ValidationResult(is_valid=False, dataset_type="HIKARI2021", row_count=0,
                          column_count=88, label_column="Label",
                          errors=["DataFrame is empty (0 rows)"])
    rx._render_validation_failure({"success": False, "error": "DataFrame is empty (0 rows)",
                                   "validation_result": vr}, "HIKARI2021")

    assert any("DataFrame is empty (0 rows)" in s for s in shown)


# ── dialog wiring: flag-only buttons, dialog opened from the main flow ────

def test_test_button_only_sets_the_flag_and_never_opens_the_dialog():
    """Regression for StreamlitAPIException: the button runs inside a column /
    container, which is not a valid context to open a dialog from. It must do
    nothing but record the choice."""
    import ui.views.run_experiment as rx

    state: dict = {}
    original = rx.st.session_state
    rx.st.session_state = state
    try:
        rx._request_compat_check("EVE_SURICATA")
    finally:
        rx.st.session_state = original
    assert state == {"_compat_check_type": "EVE_SURICATA"}


def test_dialog_is_only_ever_taken_from_the_st_module():
    """`dialog` is a MODULE-level API. On a DeltaGenerator (what st.columns() /
    st.container() return) it is not usable — older Streamlit raises
    AttributeError, current Streamlit raises a StreamlitAPIException from a
    __getattr__ stub. Either way `col.dialog(...)` must never appear in the UI.
    """
    import streamlit as st_mod
    import ui.views.run_experiment as rx

    assert rx._HAS_ST_DIALOG is hasattr(st_mod, "dialog")
    with pytest.raises(Exception):
        st_mod.container().dialog("x")

    source = Path(rx.__file__).with_suffix(".py").read_text(encoding="utf-8")
    offenders = [ln.strip() for ln in source.splitlines()
                 if ".dialog(" in ln and "st.dialog(" not in ln
                 and not ln.strip().startswith("#")]
    assert offenders == [], f"dialog dipanggil pada objek non-st: {offenders}"


def test_stale_flag_for_another_dataset_is_dropped(monkeypatch):
    """Switching dataset must not leave a dialog pointing at a vanished type."""
    import ui.views.run_experiment as rx

    opened: list = []
    monkeypatch.setattr(rx, "_compat_dialog", lambda diag, dt: opened.append(dt))
    state = {"_compat_check_type": "GONE_TYPE"}
    monkeypatch.setattr(rx.st, "session_state", state)

    rx._maybe_render_compat_dialog({"results": {"HIKARI2021": _result(True, _all_pass())}})
    assert opened == []
    assert "_compat_check_type" not in state


def test_dialog_opens_from_the_main_flow_when_the_flag_matches(monkeypatch):
    import ui.views.run_experiment as rx

    opened: list = []
    monkeypatch.setattr(rx, "_compat_dialog", lambda diag, dt: opened.append(dt))
    monkeypatch.setattr(rx.st, "session_state", {"_compat_check_type": "HIKARI2021"})

    rx._maybe_render_compat_dialog({"results": {"HIKARI2021": _result(True, _all_pass())}})
    assert opened == ["HIKARI2021"]


# ── encoding regression: no "�" reaches the UI ────────────────────────────

def test_replacement_character_is_repaired_not_shown():
    """CICIDS ships "Web Attack <U+FFFD> Brute Force" INSIDE the file."""
    assert sanitize_display_value("Web Attack � Brute Force") == "Web Attack - Brute Force"


def test_sanitizer_strips_control_characters():
    assert sanitize_display_value("a\tb\nc") == "a b c"


def test_sanitizer_never_breaks_inline_code_spans():
    assert "`" not in sanitize_display_value("weird`name")


def test_sanitizer_handles_non_string_and_empty_values():
    assert sanitize_display_value(0) == "0"
    assert sanitize_display_value("   ") == "(kosong)"


def test_class_values_with_mojibake_are_clean_in_the_check_message(tmp_path, monkeypatch):
    """End-to-end: a CSV whose label values contain U+FFFD must not surface it."""
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", tmp_path)
    monkeypatch.setattr(_s, "DATASETS_DIR", str(tmp_path))

    import pandas as pd
    from contracts.dataset_schemas import HIKARI2021_SCHEMA
    from orchestrator.dataset_diagnostics import diagnose_dataset

    cols = HIKARI2021_SCHEMA["expected_columns"]
    data = {c: [0.0, 1.0] for c in cols if c != "Label"}
    data["Label"] = ["BENIGN", "Web Attack � Brute Force"]
    path = tmp_path / "mojibake.csv"
    pd.DataFrame(data)[cols].to_csv(path, index=False)

    result = diagnose_dataset(str(path), "HIKARI2021")
    classes = next(c for c in result["checks"] if c["key"] == "classes")
    assert "�" not in classes["message"]
    assert "Web Attack - Brute Force" in classes["message"]
    assert all("�" not in e for e in classes["examples"])


def test_cp1252_csv_is_readable_instead_of_failing(tmp_path, monkeypatch):
    """A non-UTF-8 CSV must fall back to cp1252 rather than abort the diagnosis."""
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", tmp_path)
    monkeypatch.setattr(_s, "DATASETS_DIR", str(tmp_path))

    import pandas as pd
    from contracts.dataset_schemas import HIKARI2021_SCHEMA
    from orchestrator.dataset_diagnostics import read_dataset_sample

    cols = HIKARI2021_SCHEMA["expected_columns"]
    data = {c: [0.0, 1.0] for c in cols if c != "Label"}
    data["Label"] = ["BENIGN", "Web Attack – Brute Force"]   # real en-dash
    path = tmp_path / "cp1252.csv"
    pd.DataFrame(data)[cols].to_csv(path, index=False, encoding="cp1252")

    sample = read_dataset_sample(str(path))
    assert sample.error is None
    assert sample.encoding == "cp1252"
    assert "Web Attack – Brute Force" in sample.frame["Label"].tolist()
