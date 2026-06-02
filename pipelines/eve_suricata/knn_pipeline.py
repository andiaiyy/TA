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
            "paper": "EVE Suricata IDS — 11-Phase Modular Pipeline",
            "algorithm": "K-Nearest Neighbors",
            "preprocessing_steps": [
                "Phase 1: NDJSON ingestion + binary labeling (alert severity → Attack/Benign)",
                "Phase 2: Advanced feature engineering (hash encoding, flow/alert aggregates)",
                "Phase 3: Computed features (interactions, row statistics, normalization)",
                "Phase 4: Aggressive cleaning (NaN/Inf removal, constant-column drop)",
                "Phase 7: Correlation analysis (leakage detection, artifact removal)",
                "Phase 8: Stratified train/test split (attack-aware balancing)",
                "Phase 9: Feature selection — MI + RFE top-25 + PCA",
                "StandardScaler: fit on train, applied to test",
            ],
            "feature_selection": "Phase 9: MI top-25",
            "fixed_params": {
                "n_neighbors": 5,
                "n_jobs": 2,
                "scaler": "StandardScaler",
                "feature_method": "MI",
            },
            "train_test_split": {"method": "Phase 8 stratified split"},
        }
