"""
XGBoost pipeline for EVE/Suricata — OOP variant.

Inherits shared preprocessing (Phases 1-9) from BaseEvePipeline.
Trains on Phase-9 MI-selected features.
XGBoost is a soft dependency — import failure raises ImportError at instantiation.
"""
from __future__ import annotations

try:
    from xgboost import XGBClassifier
    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

from pipelines.eve_suricata._base_eve_pipeline import BaseEvePipeline
from contracts.pipeline_contracts import PipelineResult

_TARGET = "Target"


class EveXGBPipeline(BaseEvePipeline):

    def __init__(self):
        if not _XGB_AVAILABLE:
            raise ImportError(
                "xgboost is not installed. Run: pip install xgboost"
            )

    def _train_and_extract(self, prep: dict, rs: int) -> PipelineResult:
        features = self._select_features(prep, prefer="MI")
        if not features:
            raise RuntimeError("Phase 9 returned no usable features for XGB")

        df_train = prep["df_train"]
        df_test = prep["df_test"]
        X_train = df_train[features].values
        y_train = df_train[_TARGET].values
        X_test = df_test[features].values if df_test is not None else X_train
        y_test = df_test[_TARGET].values if df_test is not None else y_train

        clf = XGBClassifier(
            n_estimators=100,
            random_state=rs,
            eval_metric="logloss",
            n_jobs=2,
        )
        clf.fit(X_train, y_train)

        extra = {"phase_summaries": prep["phase_summaries"]}
        return self._build_result(clf, X_test, y_test, features, extra, clf.feature_importances_)

    def get_info(self) -> dict:
        return {
            "paper": "EVE Suricata IDS — 11-Phase Modular Pipeline",
            "algorithm": "XGBoost",
            "preprocessing_steps": [
                "Phase 1: NDJSON ingestion + binary labeling (alert severity → Attack/Benign)",
                "Phase 2: Advanced feature engineering (hash encoding, flow/alert aggregates)",
                "Phase 3: Computed features (interactions, row statistics, normalization)",
                "Phase 4: Aggressive cleaning (NaN/Inf removal, constant-column drop)",
                "Phase 7: Correlation analysis (leakage detection, artifact removal)",
                "Phase 8: Stratified train/test split (attack-aware balancing)",
                "Phase 9: Feature selection — MI + RFE top-25 + PCA",
            ],
            "feature_selection": "Phase 9: MI top-25",
            "fixed_params": {
                "n_estimators": 100,
                "eval_metric": "logloss",
                "n_jobs": 2,
                "feature_method": "MI",
            },
            "train_test_split": {"method": "Phase 8 stratified split"},
        }
