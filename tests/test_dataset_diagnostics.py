"""Tests for orchestrator/dataset_diagnostics.py.

All fixtures are TINY files written to tmp_path — never a real dataset. They
exercise the specific failure messages the UI shows: missing label column, wrong
file format, single class, non-numeric features, missing JSON keys, and an EVE
file with no alert evidence.

Pure/read-only: no pipeline is run, no model is loaded.
"""
import json

import pandas as pd
import pytest

from contracts.dataset_schemas import HIKARI2021_SCHEMA, EVE_SURICATA_SCHEMA
from orchestrator.dataset_diagnostics import (
    CHECK_CLASSES, CHECK_DTYPE, CHECK_FEATURES, CHECK_FORMAT, CHECK_LABEL,
    SAMPLE_ROWS, diagnose_all, diagnose_dataset, read_dataset_sample,
    required_format,
)


@pytest.fixture(autouse=True)
def _allow_tmp_datasets(tmp_path, monkeypatch):
    """Point DATASETS_DIR/BASE_DIR at tmp_path so resolve_dataset_path's
    containment check accepts the tiny fixture files (same pattern as
    tests/test_path_fallback.py). Keeps the real path-safety rule exercised."""
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", tmp_path)
    monkeypatch.setattr(_s, "DATASETS_DIR", str(tmp_path))


# ── helpers ───────────────────────────────────────────────────────────────

def _check(result: dict, key: str) -> dict:
    return next(c for c in result["checks"] if c["key"] == key)


def _hikari_frame(n_rows: int = 6, labels=None) -> pd.DataFrame:
    """A minimal but schema-complete HIKARI frame (numeric, plus the real
    non-numeric columns the pipeline drops)."""
    cols = HIKARI2021_SCHEMA["expected_columns"]
    data = {}
    for c in cols:
        if c == "Label":
            continue
        if c in ("uid", "originh", "responh", "traffic_category"):
            data[c] = [f"{c}_{i}" for i in range(n_rows)]
        else:
            data[c] = [float(i) for i in range(n_rows)]
    data["Label"] = labels if labels is not None else [0, 1] * (n_rows // 2)
    return pd.DataFrame(data)[cols]


def _write_csv(tmp_path, df, name="hikari.csv"):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return str(p)


def _write_ndjson(tmp_path, records, name="eve.ndjson"):
    p = tmp_path / name
    with open(p, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return str(p)


def _eve_records(n_tls: int = 4, n_alert: int = 2) -> list[dict]:
    """Records carrying every expected_top_level_key, mirroring real EVE fields."""
    base = {
        "timestamp": "2021-01-05T10:12:44.123456+0700",
        "flow_id": 1234567890,
        "src_ip": "10.0.0.5", "src_port": 51514,
        "dest_ip": "93.184.216.34", "dest_port": 443,
        "proto": "TCP",
    }
    out = [{**base, "event_type": "tls", "app_proto": "tls"} for _ in range(n_tls)]
    out += [{**base, "event_type": "alert", "app_proto": "tls",
             "alert": {"signature": "ET TEST", "category": "trojan", "severity": 1}}
            for _ in range(n_alert)]
    return out


# ── the sample reader is memory-safe by construction ──────────────────────

def test_sample_reader_caps_rows_and_flags_truncation(tmp_path):
    path = _write_csv(tmp_path, _hikari_frame(20))
    sample = read_dataset_sample(path, max_rows=5)
    assert sample.detected_format == "csv"
    assert sample.rows_read == 5          # never the whole file
    assert sample.truncated is True
    assert len(sample.frame) == 5


def test_ndjson_sample_builds_no_dataframe(tmp_path):
    path = _write_ndjson(tmp_path, _eve_records())
    sample = read_dataset_sample(path)
    assert sample.detected_format == "ndjson"
    assert sample.frame is None           # counters only → O(1) memory
    assert sample.tls_rows == 6 and sample.alert_rows == 2
    assert sample.truncated is False


def test_default_sample_size_is_bounded():
    assert 50_000 <= SAMPLE_ROWS <= 100_000


def test_required_format_is_schema_derived():
    assert required_format("HIKARI2021") == "csv"
    assert required_format("EVE_SURICATA") == "ndjson"


# ── HIKARI (CSV) rules ────────────────────────────────────────────────────

def test_valid_hikari_csv_is_compatible(tmp_path):
    path = _write_csv(tmp_path, _hikari_frame())
    result = diagnose_dataset(path, "HIKARI2021")
    assert result["compatible"] is True
    assert _check(result, CHECK_FORMAT)["status"] == "pass"
    assert _check(result, CHECK_LABEL)["status"] == "pass"
    assert _check(result, CHECK_CLASSES)["status"] == "pass"
    # uid/originh/responh/traffic_category are dropped by the pipeline, so they
    # must NOT be reported as non-numeric feature problems.
    assert _check(result, CHECK_DTYPE)["status"] == "pass"


def test_missing_label_column_reports_it_specifically(tmp_path):
    df = _hikari_frame().drop(columns=["Label"])
    path = _write_csv(tmp_path, df)
    result = diagnose_dataset(path, "HIKARI2021")
    assert result["compatible"] is False
    label = _check(result, CHECK_LABEL)
    assert label["status"] == "fail"
    assert "Label" in label["message"]
    assert _check(result, CHECK_CLASSES)["status"] == "skip"


def test_missing_feature_columns_are_named(tmp_path):
    df = _hikari_frame().drop(columns=["flow_duration", "fwd_pkts_tot"])
    path = _write_csv(tmp_path, df)
    result = diagnose_dataset(path, "HIKARI2021")
    assert result["compatible"] is False
    features = _check(result, CHECK_FEATURES)
    assert features["status"] == "fail"
    assert "flow_duration" in features["message"]


def test_single_class_is_reported(tmp_path):
    df = _hikari_frame(labels=[0] * 6)
    path = _write_csv(tmp_path, df)
    result = diagnose_dataset(path, "HIKARI2021")
    assert result["compatible"] is False
    classes = _check(result, CHECK_CLASSES)
    assert classes["status"] == "fail"
    assert "satu kelas" in classes["message"].lower()


def test_non_numeric_feature_is_flagged_without_blocking(tmp_path):
    df = _hikari_frame()
    df["flow_duration"] = ["fast"] * len(df)     # a real feature turned textual
    path = _write_csv(tmp_path, df)
    result = diagnose_dataset(path, "HIKARI2021")
    dtype = _check(result, CHECK_DTYPE)
    assert dtype["status"] == "warn"             # pipeline drops it; run still works
    assert "flow_duration" in dtype["message"]
    assert result["compatible"] is True


def test_label_sorted_csv_is_not_falsely_single_class(tmp_path):
    """A CSV ordered by label: the capped sample sees one class, the confirming
    label-only pass finds the second. Must NOT be reported as incompatible."""
    df = _hikari_frame(n_rows=20, labels=[0] * 10 + [1] * 10)
    path = _write_csv(tmp_path, df)
    result = diagnose_dataset(path, "HIKARI2021",
                              sample=read_dataset_sample(path, max_rows=5))
    assert _check(result, CHECK_CLASSES)["status"] == "pass"
    assert result["compatible"] is True


# ── EVE (NDJSON) rules ────────────────────────────────────────────────────

def test_valid_eve_ndjson_is_compatible(tmp_path):
    path = _write_ndjson(tmp_path, _eve_records())
    result = diagnose_dataset(path, "EVE_SURICATA")
    assert result["compatible"] is True
    # Label is derived from Suricata alerts — not required in the raw file.
    assert _check(result, CHECK_LABEL)["status"] == "pass"
    assert "alert" in _check(result, CHECK_LABEL)["message"].lower()
    assert _check(result, CHECK_DTYPE)["status"] == "skip"


def test_eve_without_alerts_cannot_form_two_classes(tmp_path):
    path = _write_ndjson(tmp_path, _eve_records(n_tls=4, n_alert=0))
    result = diagnose_dataset(path, "EVE_SURICATA")
    assert result["compatible"] is False
    assert _check(result, CHECK_LABEL)["status"] == "fail"
    assert _check(result, CHECK_CLASSES)["status"] == "fail"


def test_eve_missing_schema_keys_are_named(tmp_path):
    records = [{k: v for k, v in r.items() if k != "flow_id"} for r in _eve_records()]
    path = _write_ndjson(tmp_path, records)
    result = diagnose_dataset(path, "EVE_SURICATA")
    assert result["compatible"] is False
    features = _check(result, CHECK_FEATURES)
    assert features["status"] == "fail"
    assert "flow_id" in features["message"]


def test_eve_without_tls_events_is_reported(tmp_path):
    records = [{**r, "event_type": "dns", "app_proto": "dns",
                "src_port": 53, "dest_port": 53} for r in _eve_records(4, 0)]
    records += [{**_eve_records(0, 1)[0], "src_port": 53, "dest_port": 53,
                 "app_proto": "dns"}]
    path = _write_ndjson(tmp_path, records)
    result = diagnose_dataset(path, "EVE_SURICATA")
    assert result["compatible"] is False
    assert _check(result, CHECK_FEATURES)["status"] == "fail"
    assert "TLS" in _check(result, CHECK_FEATURES)["message"]


# ── cross-type: wrong format, broken files, and the one-read entry point ───

def test_csv_against_eve_pipeline_reports_format_mismatch(tmp_path):
    path = _write_csv(tmp_path, _hikari_frame())
    result = diagnose_dataset(path, "EVE_SURICATA")
    assert result["compatible"] is False
    fmt = _check(result, CHECK_FORMAT)
    assert fmt["status"] == "fail"
    assert "CSV" in fmt["message"] and "NDJSON" in fmt["message"]
    # Nothing beyond format is guessed at once the format is wrong.
    assert all(_check(result, k)["status"] == "skip"
               for k in (CHECK_LABEL, CHECK_FEATURES, CHECK_DTYPE, CHECK_CLASSES))


def test_ndjson_against_hikari_pipeline_reports_format_mismatch(tmp_path):
    path = _write_ndjson(tmp_path, _eve_records())
    result = diagnose_dataset(path, "HIKARI2021")
    assert result["compatible"] is False
    fmt = _check(result, CHECK_FORMAT)
    assert fmt["status"] == "fail"
    assert "NDJSON" in fmt["message"] and "CSV" in fmt["message"]


def test_diagnose_all_covers_every_dataset_type(tmp_path):
    path = _write_csv(tmp_path, _hikari_frame())
    diag = diagnose_all(path)
    assert set(diag["results"]) == {"HIKARI2021", "EVE_SURICATA"}
    assert diag["compatible_types"] == ["HIKARI2021"]
    assert diag["error"] is None


def test_file_matching_no_pipeline_still_explains_every_pipeline(tmp_path):
    """The "fits nothing" case: every pipeline must carry its own reason."""
    path = _write_csv(tmp_path, pd.DataFrame({"a": [1, 2], "b": [3, 4]}), "junk.csv")
    diag = diagnose_all(path)
    assert diag["compatible_types"] == []
    for dtype, result in diag["results"].items():
        assert result["compatible"] is False
        assert any(c["status"] == "fail" and c["message"] for c in result["checks"])


def test_unreadable_file_does_not_raise(tmp_path):
    diag = diagnose_all(str(tmp_path / "does_not_exist.csv"))
    assert diag["error"]
    assert diag["compatible_types"] == []
    for result in diag["results"].values():
        assert result["compatible"] is False


def test_corrupt_ndjson_does_not_raise(tmp_path):
    p = tmp_path / "broken.ndjson"
    p.write_text("not json at all\n{oops\n", encoding="utf-8")
    result = diagnose_dataset(str(p), "EVE_SURICATA")
    assert result["compatible"] is False
    assert result["error"]


# ── descriptive profile (display-only, built from the SAME sample) ────────

def test_profile_describes_a_csv_from_the_sample(tmp_path):
    from orchestrator.dataset_diagnostics import build_profile

    df = _hikari_frame(n_rows=8, labels=[0, 0, 0, 0, 0, 0, 1, 1])
    path = _write_csv(tmp_path, df)
    profile = build_profile(read_dataset_sample(path))

    assert profile["detected_format"] == "csv"
    assert profile["rows_read"] == 8
    assert profile["sampled"] is False
    assert profile["column_count"] == len(HIKARI2021_SCHEMA["expected_columns"])
    assert profile["columns"][:2] == HIKARI2021_SCHEMA["expected_columns"][:2]
    assert profile["label_column"] == "Label"
    assert profile["class_counts"] == {"0": 6, "1": 2}
    # 4 kolom non-numerik pada fixture: uid, originh, responh, traffic_category
    assert profile["non_numeric_columns"] == 4
    assert profile["numeric_columns"] == profile["column_count"] - 4


def test_profile_marks_a_truncated_read_as_sampled(tmp_path):
    from orchestrator.dataset_diagnostics import build_profile

    path = _write_csv(tmp_path, _hikari_frame(20))
    profile = build_profile(read_dataset_sample(path, max_rows=5))
    assert profile["sampled"] is True
    assert profile["rows_read"] == 5
    assert sum(profile["class_counts"].values()) == 5      # angka SAMPEL saja


def test_profile_without_a_label_column_stays_empty(tmp_path):
    from orchestrator.dataset_diagnostics import build_profile

    df = _hikari_frame().drop(columns=["Label"])
    profile = build_profile(read_dataset_sample(_write_csv(tmp_path, df)))
    assert profile["label_column"] is None
    assert profile["class_counts"] == {}


def test_profile_of_ndjson_lists_keys_and_class_signals(tmp_path):
    from orchestrator.dataset_diagnostics import build_profile

    path = _write_ndjson(tmp_path, _eve_records(n_tls=4, n_alert=2))
    profile = build_profile(read_dataset_sample(path))

    assert profile["detected_format"] == "ndjson"
    assert "event_type" in profile["columns"]
    assert profile["column_count"] == len(profile["columns"])
    assert profile["label_column"] is None          # Target dibentuk pipeline
    assert profile["numeric_columns"] is None       # tidak berlaku untuk NDJSON
    assert profile["tls_rows"] == 6 and profile["alert_rows"] == 2


def test_profile_class_values_are_sanitised(tmp_path):
    """Nilai kelas bermojibake tidak boleh bocor ke profil."""
    from orchestrator.dataset_diagnostics import build_profile

    df = _hikari_frame(n_rows=2)
    df["Label"] = ["BENIGN", "Web Attack � Brute Force"]
    profile = build_profile(read_dataset_sample(_write_csv(tmp_path, df)))
    assert "Web Attack - Brute Force" in profile["class_counts"]
    assert all("�" not in k for k in profile["class_counts"])


def test_diagnose_all_exposes_the_profile_without_extra_reads(tmp_path, monkeypatch):
    """Profil ikut di hasil diagnose_all dan TIDAK menambah pembacaan berkas."""
    import orchestrator.dataset_diagnostics as dd

    path = _write_csv(tmp_path, _hikari_frame())
    calls = {"n": 0}
    original = dd.read_dataset_sample

    def counting(*a, **k):
        calls["n"] += 1
        return original(*a, **k)

    monkeypatch.setattr(dd, "read_dataset_sample", counting)
    diag = dd.diagnose_all(path)

    assert calls["n"] == 1                       # satu kali baca untuk semuanya
    assert diag["profile"]["label_column"] == "Label"
    assert diag["profile"]["column_count"] > 0


def test_profile_does_not_change_any_verdict(tmp_path):
    """Penambahan profil murni deskriptif: seluruh status & compatible tetap."""
    path = _write_csv(tmp_path, _hikari_frame())
    diag = diagnose_all(path)
    for dtype, result in diag["results"].items():
        recomputed = diagnose_dataset(path, dtype)
        assert result["compatible"] == recomputed["compatible"]
        assert ([c["status"] for c in result["checks"]]
                == [c["status"] for c in recomputed["checks"]])


def test_unknown_dataset_type_is_handled(tmp_path):
    path = _write_csv(tmp_path, _hikari_frame())
    result = diagnose_dataset(path, "NOT_A_TYPE")
    assert result["compatible"] is False
