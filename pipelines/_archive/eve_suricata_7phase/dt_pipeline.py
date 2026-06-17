"""
Decision Tree pipeline for EVE/Suricata — OOP variant.

Inherits shared preprocessing (Phases 1-9) from BaseEvePipeline.
Trains on Phase-9 RFE-selected features.
"""
from __future__ import annotations

from sklearn.tree import DecisionTreeClassifier

from pipelines.eve_suricata._base_eve_pipeline import BaseEvePipeline
from contracts.pipeline_contracts import PipelineResult

_TARGET = "Target"


class EveDTPipeline(BaseEvePipeline):

    def _train_and_extract(self, prep: dict, rs: int) -> PipelineResult:
        features = self._select_features(prep, prefer="RFE")
        if not features:
            raise RuntimeError("Phase 9 returned no usable features for DT")

        df_train = prep["df_train"]
        df_test = prep["df_test"]
        X_train = df_train[features].values
        y_train = df_train[_TARGET].values
        X_test = df_test[features].values if df_test is not None else X_train
        y_test = df_test[_TARGET].values if df_test is not None else y_train

        clf = DecisionTreeClassifier(random_state=rs)
        clf.fit(X_train, y_train)

        extra = {"phase_summaries": prep["phase_summaries"]}
        return self._build_result(clf, X_test, y_test, features, extra, clf.feature_importances_)

    def get_info(self) -> dict:
        return {
            "paper": "EVE Suricata IDS — 7-Phase Pipeline (selected from 11-file modular toolkit)",
            "algorithm": "Decision Tree",
            "preprocessing_steps": [
                "Step 1 of 7: NDJSON ingestion + binary labeling (alert severity → Attack/Benign)",
                "Step 2 of 7: Advanced feature engineering (hash encoding, flow/alert aggregates)",
                "Step 3 of 7: Computed features (interactions, row statistics, normalization)",
                "Step 4 of 7: Aggressive cleaning (NaN/Inf removal, constant-column drop)",
                "Step 5 of 7: Correlation analysis (leakage detection, artifact removal)",
                "Step 6 of 7: Stratified train/test split (attack-aware balancing)",
                "Step 7 of 7: Feature selection — MI + RFE top-25 + PCA",
            ],
            "feature_selection": "Step 7: RFE top-25",
            "fixed_params": {
                "criterion": "gini",
                "feature_method": "RFE",
            },
            "train_test_split": {"method": "Phase 8 stratified split"},
        }
