"""Tests for the shared result-view pure helpers (ui/components/result_views).

Covers the two source-unifying + interpretation functions that both the Run
Experiment and Experiment History pages rely on:
  - normalize_result_payload(): merges in-memory result vs metrics/metadata.
  - confusion_breakdown(): binary CM breakdown with positive class taken from
    the label NAME (int or str keys), never hardcoded 0/1.

These are pure (no Streamlit runtime needed); the module imports streamlit as a
library which is fine at import time.
"""
from ui.components.result_views import normalize_result_payload, confusion_breakdown


# ── normalize_result_payload ──────────────────────────────────────────────

def test_normalize_explicit_wins_over_metadata():
    p = normalize_result_payload(
        experiment_id="e1",
        metrics={"accuracy": 0.9},
        metadata={"label_mapping": {0: "Benign"}, "feature_names": ["a"],
                  "pipeline_id": "meta.pid", "dataset_type": "META"},
        label_mapping={0: "Normal", 1: "Attack"},
        feature_names=["x", "y"],
        pipeline_id="explicit.pid",
        dataset_type="HIKARI2021",
    )
    assert p["experiment_id"] == "e1"
    assert p["metrics"] == {"accuracy": 0.9}
    assert p["label_mapping"] == {0: "Normal", 1: "Attack"}
    assert p["feature_names"] == ["x", "y"]
    assert p["pipeline_id"] == "explicit.pid"
    assert p["dataset_type"] == "HIKARI2021"


def test_normalize_falls_back_to_metadata():
    p = normalize_result_payload(
        experiment_id="e2",
        metrics={"f1_score": 0.8},
        metadata={"label_mapping": {0: "Benign", 1: "Attack"},
                  "feature_names": ["f1", "f2"],
                  "pipeline_id": "eve_cbr.rfc", "dataset_type": "EVE_SURICATA"},
    )
    assert p["label_mapping"] == {0: "Benign", 1: "Attack"}
    assert p["feature_names"] == ["f1", "f2"]
    assert p["pipeline_id"] == "eve_cbr.rfc"
    assert p["dataset_type"] == "EVE_SURICATA"


def test_normalize_defaults_when_missing():
    p = normalize_result_payload(experiment_id="e3", metrics=None)
    assert p["metrics"] == {}
    assert p["label_mapping"] == {}
    assert p["feature_names"] == []
    assert p["pipeline_id"] == ""
    assert p["dataset_type"] == ""


def test_normalize_stable_keys():
    p = normalize_result_payload(experiment_id="e4", metrics={})
    assert set(p.keys()) == {
        "experiment_id", "metrics", "label_mapping",
        "feature_names", "pipeline_id", "dataset_type",
    }


# ── confusion_breakdown (positive class from label name) ──────────────────

def test_breakdown_int_keys_positive_from_name():
    # [[TN, FP], [FN, TP]] with attack = index 1
    b = confusion_breakdown([[750, 10], [5, 235]], {0: "Benign", 1: "Malicious"})
    assert b is not None
    assert (b["tn"], b["fp"], b["fn"], b["tp"]) == (750, 10, 5, 235)
    assert b["attack_name"] == "Malicious"
    assert b["normal_name"] == "Benign"
    assert b["total"] == 1000
    assert abs(b["attack_recall"] - 235 / 240) < 1e-9
    assert abs(b["fp_rate"] - 10 / 760) < 1e-9


def test_breakdown_str_keys_same_result():
    # JSON-loaded metadata has string keys — must behave identically
    b_int = confusion_breakdown([[90, 10], [3, 40]], {0: "Benign", 1: "Attack"})
    b_str = confusion_breakdown([[90, 10], [3, 40]], {"0": "Benign", "1": "Attack"})
    assert b_str is not None
    assert (b_str["tp"], b_str["fn"], b_str["fp"], b_str["tn"]) == \
           (b_int["tp"], b_int["fn"], b_int["fp"], b_int["tn"])
    assert b_str["attack_name"] == "Attack"


def test_breakdown_positive_class_not_hardcoded_index():
    # If the attack label sits at index 0, the breakdown must follow the NAME,
    # not blindly treat index 1 as positive.
    b = confusion_breakdown([[40, 5], [8, 900]], {0: "Attack", 1: "Benign"})
    assert b["attack_name"] == "Attack"
    # TP must be the attack (index 0) diagonal = 40, not 900
    assert b["tp"] == 40
    assert b["tn"] == 900


def test_breakdown_non_binary_or_empty_returns_none():
    assert confusion_breakdown([[1, 2, 3], [4, 5, 6], [7, 8, 9]], {}) is None
    assert confusion_breakdown([[0, 0], [0, 0]], {0: "Benign", 1: "Attack"}) is None
    assert confusion_breakdown(None, {}) is None
