"""
Random Forest pipeline for EVE/Suricata dataset.

Runs phases 1-9 (shared preprocessing via phase_runner) then trains an RFC
on the Phase-9 RFE-selected features. Phase 10/11 visualisation is skipped —
the platform has its own artifact system.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score, roc_curve,
)

from contracts.pipeline_contracts import PipelineInput, PipelineResult
from pipelines.base import BasePipeline
from pipelines.eve_suricata.phase_runner import run_phases_1_through_9

_TARGET = "Target"
_LABEL_NAMES = ["Benign", "Attack"]
_LABEL_MAPPING = {0: "Benign", 1: "Attack"}


class EVERFCPipeline(BasePipeline):

    def run(self, pipeline_input: PipelineInput) -> PipelineResult:
        dataset_path = pipeline_input.dataset_path
        if not dataset_path:
            raise ValueError("EVE Suricata pipeline requires dataset_path in PipelineInput")

        rs = pipeline_input.random_state
        prep = run_phases_1_through_9(dataset_path=dataset_path, random_state=rs)
        try:
            df_train = prep["df_train"]
            df_test = prep["df_test"]
            feature_sets = prep["feature_sets"]

            # RFE features are best for tree models; fall back to MI
            features = feature_sets.get("RFE") or feature_sets.get("MI") or []
            if not features:
                raise RuntimeError("Phase 9 returned no selected features")

            # Only keep features that actually exist in df_train after Phase 8 drops
            features = [f for f in features if f in df_train.columns]
            if not features:
                raise RuntimeError("No selected features remain after Phase 8 column drops")

            X_train = df_train[features].values
            y_train = df_train[_TARGET].values
            X_test = df_test[features].values if df_test is not None else X_train
            y_test = df_test[_TARGET].values if df_test is not None else y_train

            clf = RandomForestClassifier(n_estimators=100, random_state=rs, n_jobs=-1)
            clf.fit(X_train, y_train)
            y_pred = clf.predict(X_test)

            extra_info: dict = {"phase_summaries": prep["phase_summaries"]}

            try:
                y_prob = clf.predict_proba(X_test)[:, 1]
                fpr, tpr, _ = roc_curve(y_test, y_prob)
                extra_info["roc_auc"] = float(roc_auc_score(y_test, y_prob))
                extra_info["roc_curve"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}
            except Exception:
                pass

            extra_info["feature_importance"] = sorted(
                [{"feature": n, "importance": round(float(v), 6)}
                 for n, v in zip(features, clf.feature_importances_)],
                key=lambda x: x["importance"], reverse=True,
            )
            extra_info["classification_report"] = classification_report(
                y_test, y_pred, target_names=_LABEL_NAMES,
                output_dict=True, zero_division=0,
            )

            return PipelineResult(
                accuracy=float(accuracy_score(y_test, y_pred)),
                precision=float(precision_score(y_test, y_pred, average="weighted", zero_division=0)),
                recall=float(recall_score(y_test, y_pred, average="weighted", zero_division=0)),
                f1_score=float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
                confusion_matrix=confusion_matrix(y_test, y_pred).tolist(),
                model=clf,
                feature_names=features,
                label_mapping=_LABEL_MAPPING,
                extra_info=extra_info,
            )
        finally:
            prep["cleanup"]()

    def get_info(self) -> dict:
        return {
            "paper": "EVE/Suricata IDS Pipeline — 11-phase ML system",
            "algorithm": "Random Forest",
            "preprocessing_steps": [
                "Phase 1: NDJSON ingestion + binary labeling (alert severity → attack)",
                "Phase 2: Advanced feature engineering (hash encoding, flow/alert totals)",
                "Phase 3: Computed features (interactions, row stats, normalization)",
                "Phase 4: Aggressive cleaning (NaN/Inf elimination)",
                "Phase 7: Correlation analysis (leakage detection artifacts)",
                "Phase 8: Stratified train/test split (attack-aware balancing)",
                "Phase 9: Feature selection — MI + RFE + PCA (top 25)",
            ],
            "feature_selection": "RFE (Recursive Feature Elimination) — top 25",
            "fixed_params": {
                "n_estimators": 100,
                "random_state": 42,
                "n_jobs": -1,
                "feature_method": "RFE",
            },
            "train_test_split": {"method": "Phase 8 stratified split", "random_state": 42},
        }
