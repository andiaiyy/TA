"""
K-Nearest Neighbors pipeline for EVE/Suricata — OOP variant.

Inherits shared preprocessing (Phases 1-9) from BaseEvePipeline.
Trains on Phase-9 MI-selected features with StandardScaler applied
to train data (fitted on train, applied to test).
"""
from __future__ import annotations

from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler

from pipelines.eve_suricata._base_eve_pipeline import BaseEvePipeline
from contracts.pipeline_contracts import PipelineResult

_TARGET = "Target"


class EveKNNPipeline(BaseEvePipeline):

    def _train_and_extract(self, prep: dict, rs: int) -> PipelineResult:
        features = self._select_features(prep, prefer="MI")
        if not features:
            raise RuntimeError("Phase 9 returned no usable features for KNN")

        df_train = prep["df_train"]
        df_test = prep["df_test"]
        X_train = df_train[features].values
        y_train = df_train[_TARGET].values
        X_test = df_test[features].values if df_test is not None else X_train
        y_test = df_test[_TARGET].values if df_test is not None else y_train

        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_test = scaler.transform(X_test)

        clf = KNeighborsClassifier(n_neighbors=5, n_jobs=2)
        clf.fit(X_train, y_train)

        extra = {"phase_summaries": prep["phase_summaries"]}
        return self._build_result(clf, X_test, y_test, features, extra, feature_importances=None)

    def get_info(self) -> dict:
        return {
            "paper": "EVE Suricata IDS — 7-Phase Pipeline (selected from 11-file modular toolkit)",
            "algorithm": "K-Nearest Neighbors",
            "preprocessing_steps": [
                "Step 1 of 7: NDJSON ingestion + binary labeling (alert severity → Attack/Benign)",
                "Step 2 of 7: Advanced feature engineering (hash encoding, flow/alert aggregates)",
                "Step 3 of 7: Computed features (interactions, row statistics, normalization)",
                "Step 4 of 7: Aggressive cleaning (NaN/Inf removal, constant-column drop)",
                "Step 5 of 7: Correlation analysis (leakage detection, artifact removal)",
                "Step 6 of 7: Stratified train/test split (attack-aware balancing)",
                "Step 7 of 7: Feature selection — MI top-25",
                "Training-time: StandardScaler (fit on train, applied to test)",
            ],
            "feature_selection": "Step 7: MI top-25",
            "fixed_params": {
                "n_neighbors": 5,
                "n_jobs": 2,
                "scaler": "StandardScaler",
                "feature_method": "MI",
            },
            "train_test_split": {"method": "Phase 8 stratified split"},
        }
