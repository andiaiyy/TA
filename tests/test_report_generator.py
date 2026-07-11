"""Smoke + defensive tests for the redesigned PDF report generator.

No real artifacts needed — synthetic metrics/metadata exercise both families and
the defensive paths (empty metrics, no feature importance, EVE without learning
curve). Asserts a valid PDF is returned and that the shared confusion-matrix
breakdown (also used by the UI) stays correct.
"""
from utils.report_generator import generate_report, _confusion_breakdown


def _is_pdf(b) -> bool:
    return isinstance(b, (bytes, bytearray)) and b[:4] == b"%PDF" and len(b) > 1000


def _hikari_metrics():
    return {
        "accuracy": 0.99, "precision": 0.98, "recall": 0.99, "f1_score": 0.985,
        "roc_auc": 0.97,
        "confusion_matrix": [[740, 10], [5, 245]],
        "feature_importance": [{"feature": "flow_duration", "importance": 0.31},
                               {"feature": "fwd_pkts_payload.std", "importance": 0.22}],
        "classification_report": {"Benign": {"precision": 0.99, "recall": 0.98, "f1-score": 0.985, "support": 750},
                                  "Malicious": {"precision": 0.96, "recall": 0.98, "f1-score": 0.97, "support": 250}},
        "learning_curve": {"train_sizes": [100, 200, 300], "train_scores_mean": [0.9, 0.95, 0.98],
                           "train_scores_std": [0.01, 0.01, 0.01], "val_scores_mean": [0.85, 0.9, 0.93],
                           "val_scores_std": [0.02, 0.02, 0.02]},
        "roc_curve": {"fpr": [0.0, 0.1, 1.0], "tpr": [0.0, 0.9, 1.0]},
    }


def _eve_metrics():
    return {
        "accuracy": 0.888, "precision": 0.683, "recall": 0.90, "f1_score": 0.777,
        "roc_auc": 0.955,
        "confusion_matrix": [[93638, 12196], [2898, 26314]],
        "feature_importance": [{"feature": "bytes_per_sec", "importance": 0.4}],
        "natural_holdout": {"accuracy": 0.888, "precision_attack": 0.683, "recall_attack": 0.90,
                            "f1_attack": 0.777, "auc": 0.955},
        "balanced_holdout": {"accuracy": 0.892, "precision_attack": 0.885, "recall_attack": 0.90,
                             "f1_attack": 0.892, "auc": 0.962},
        "roc_curve": {"fpr": [0.0, 0.1, 1.0], "tpr": [0.0, 0.9, 1.0]},
    }


def _md(label_mapping):
    return {"created_at": "2026-07-10T10:00:00+00:00", "completed_at": "2026-07-10T10:05:00+00:00",
            "label_mapping": label_mapping, "feature_names": ["a", "b"],
            "environment": {"python_version": "3.11.15", "sklearn_version": "1.9.0",
                            "pandas_version": "3.0.3", "numpy_version": "2.4.6",
                            "platform": "Linux", "is_docker": True}}


def test_generate_hikari_pdf():
    b = generate_report("e1", "HIKARI2021", "/d.csv", "abc123", "hikari2021.rfc_pipeline",
                        {"algorithm": "Random Forest", "fixed_params": {"n_estimators": 100}},
                        _hikari_metrics(), _md({0: "Benign", 1: "Malicious"}))
    assert _is_pdf(b)


def test_generate_eve_pdf_no_learning_curve():
    b = generate_report("e2", "EVE_SURICATA", "/d.jsonl", "8dc4", "eve_cbr.rfc",
                        {"algorithm": "Random Forest", "app": "TLS", "fixed_params": {}},
                        _eve_metrics(), _md({"0": "Benign", "1": "Attack"}))
    assert _is_pdf(b)


def test_generate_no_feature_importance_defensive():
    m = _hikari_metrics()
    m["feature_importance"] = []  # KNN / NBGC case
    b = generate_report("e3", "HIKARI2021", "/d.csv", "abc", "hikari2021.knn_pipeline",
                        {"algorithm": "K-Nearest Neighbors", "fixed_params": {}},
                        m, _md({0: "Benign", 1: "Malicious"}))
    assert _is_pdf(b)


def test_generate_empty_metrics_does_not_raise():
    b = generate_report("e4", "HIKARI2021", "/d.csv", "abc", "hikari2021.dt_pipeline",
                        {}, {}, None)
    assert _is_pdf(b)


def test_breakdown_still_intact_for_report_insight():
    # The security-interpretation section relies on this — attack from label name.
    b = _confusion_breakdown([[740, 10], [5, 245]], {0: "Benign", 1: "Malicious"})
    assert b["tp"] == 245 and b["fn"] == 5 and b["fp"] == 10 and b["tn"] == 740
    assert b["attack_name"] == "Malicious"
    assert abs(b["attack_recall"] - 245 / 250) < 1e-9
