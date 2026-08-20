"""Tests for the read-only "Persyaratan Dataset" panel data (ui/views/run_experiment).

These guard the ONE central requirements dict against going stale: every
supported dataset_type must have an entry, and every column/field NAME shown in
the sample structure must actually exist in the structured sources (the dataset
schema, the HIKARI preprocessing _DROP_COLS, the EVE cbr adapter). Pure — the
module imports streamlit as a library, which needs no Streamlit runtime.

Display-only: nothing here touches a pipeline, a seed, or a metric.
"""
from contracts.dataset_schemas import get_schema, supported_datasets
from ui.views.run_experiment import (
    _DATASET_REQUIREMENTS, _dataset_extensions, _hikari_column_facts,
    _eve_label_facts,
)


def test_every_supported_dataset_type_has_requirements():
    for dtype in supported_datasets():
        assert dtype in _DATASET_REQUIREMENTS, f"no requirements entry for {dtype}"
        entry = _DATASET_REQUIREMENTS[dtype]
        assert entry.get("row_unit"), f"{dtype} misses a row unit"
        assert entry.get("feature_nature"), f"{dtype} misses a feature description"


def test_hikari_sample_columns_are_real_schema_columns():
    """The sample header must never invent a column name."""
    expected = set(get_schema("HIKARI2021")["expected_columns"])
    for col in _DATASET_REQUIREMENTS["HIKARI2021"]["sample_columns"]:
        assert col in expected, f"{col} is not a real HIKARI2021 schema column"


def test_hikari_feature_columns_exclude_dropped_and_label():
    features, drops, class_names = _hikari_column_facts()
    label_col = get_schema("HIKARI2021")["label_column"]
    assert features, "expected a non-empty HIKARI feature column list"
    assert label_col not in features
    assert not (set(features) & set(drops))
    assert class_names == ["Benign", "Malicious"]


def test_eve_sample_keys_include_every_schema_top_level_key():
    """The NDJSON sample must show the schema's expected top-level keys."""
    keys = set(get_schema("EVE_SURICATA")["expected_top_level_keys"])
    sample = set(_DATASET_REQUIREMENTS["EVE_SURICATA"]["sample_values"])
    assert keys <= sample, f"sample misses schema keys: {sorted(keys - sample)}"


def test_eve_label_facts_come_from_the_cbr_adapter():
    target_final, class_names = _eve_label_facts()
    assert target_final == "Target_refined"
    assert class_names == ["Benign", "Attack"]


def test_extensions_match_the_file_picker_mapping():
    assert _dataset_extensions("HIKARI2021") == (".csv",)
    assert _dataset_extensions("EVE_SURICATA") == (".json", ".jsonl", ".ndjson")
