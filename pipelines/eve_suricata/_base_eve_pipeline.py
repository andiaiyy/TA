"""
Abstract base for all EVE/Suricata pipelines.

Handles the shared preprocessing chain (Phases 1-9) via phase_runner,
then delegates model training to subclasses via _train_and_extract().

Architecture:
  run() calls phase_runner.run_phases_1_through_9()  → prep dict
  run() calls self._train_and_extract(prep, rs)       → PipelineResult
  cleanup() always called in finally (temp dirs removed even on failure)
"""
from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Optional

from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score, roc_curve,
)

from contracts.pipeline_contracts import PipelineInput, PipelineResult
from pipelines.base import BasePipeline, ProgressCallback

logger = logging.getLogger(__name__)

_TARGET = "Target"
_LABEL_NAMES = ["Benign", "Attack"]
_LABEL_MAPPING = {0: "Benign", 1: "Attack"}


class BaseEvePipeline(BasePipeline):
    """
    Shared EVE/Suricata pipeline. Subclasses implement _train_and_extract().
    Requires pipeline_input.dataset_path — the path to the EVE NDJSON file.
    """

    def run(
        self,
        pipeline_input: PipelineInput,
        progress: Optional[ProgressCallback] = None,
    ) -> PipelineResult:
        if not pipeline_input.dataset_path:
            raise ValueError(
                "EVE/Suricata pipelines require dataset_path in PipelineInput. "
                "Pass the path to the EVE NDJSON or CSV file."
            )

        from pipelines.eve_suricata.phase_runner import run_phases_1_through_9

        rs = pipeline_input.random_state
        self._emit_progress(progress, "Running phases 1-9 (preprocessing)")
        prep = run_phases_1_through_9(
            dataset_path=pipeline_input.dataset_path,
            random_state=rs,
        )
        try:
            self._emit_progress(progress, "Training & evaluation")
            result = self._train_and_extract(prep, rs)
        finally:
            prep["cleanup"]()

        return result

    @abstractmethod
    def _train_and_extract(self, prep: dict, rs: int) -> PipelineResult:
        """
        Train a model on Phase 8 train/test splits using Phase 9 feature sets.

        Args:
            prep: dict returned by run_phases_1_through_9():
                  df_train, df_test, feature_sets, pca, scaler, phase_summaries, ...
            rs:   random_state integer

        Returns:
            PipelineResult with all standard fields populated.
        """

    def _select_features(self, prep: dict, prefer: str = "RFE") -> list[str]:
        """
        Pick a feature list from phase9 feature_sets, filtering to columns
        that actually exist in df_train (Phase 8 drops may remove some).
        Falls back across RFE → MI if preferred set is empty.
        """
        feature_sets = prep["feature_sets"]
        df_train = prep["df_train"]
        candidates = (
            feature_sets.get(prefer)
            or feature_sets.get("MI")
            or feature_sets.get("RFE")
            or []
        )
        return [f for f in candidates if f in df_train.columns]

    def _build_result(
        self,
        clf,
        X_test,
        y_test,
        features: list[str],
        extra: dict,
        feature_importances=None,
    ) -> PipelineResult:
        """
        Compute all standard metrics and return a PipelineResult.
        ROC is computed via predict_proba if available, else decision_function.
        """
        y_pred = clf.predict(X_test)

        accuracy = float(accuracy_score(y_test, y_pred))
        precision = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        recall = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        cm = confusion_matrix(y_test, y_pred).tolist()

        extra_info = dict(extra)

        try:
            if hasattr(clf, "predict_proba"):
                y_score = clf.predict_proba(X_test)[:, 1]
            else:
                y_score = clf.decision_function(X_test)
            fpr, tpr, _ = roc_curve(y_test, y_score)
            extra_info["roc_auc"] = float(roc_auc_score(y_test, y_score))
            extra_info["roc_curve"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}
        except Exception as e:
            logger.warning(f"ROC computation failed: {e}")

        extra_info["feature_importance"] = (
            sorted(
                [
                    {"feature": n, "importance": round(float(v), 6)}
                    for n, v in zip(features, feature_importances)
                ],
                key=lambda x: x["importance"],
                reverse=True,
            )
            if feature_importances is not None
            else []
        )

        extra_info["classification_report"] = classification_report(
            y_test, y_pred,
            target_names=_LABEL_NAMES,
            output_dict=True,
            zero_division=0,
        )

        return PipelineResult(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            confusion_matrix=cm,
            model=clf,
            feature_names=features,
            label_mapping=_LABEL_MAPPING,
            extra_info=extra_info,
        )
