"""Gaussian Naive Bayes pipeline for HIKARI2021."""
from typing import Optional

from sklearn.naive_bayes import GaussianNB
from sklearn.model_selection import train_test_split, learning_curve
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix, roc_auc_score, roc_curve,
    classification_report,
)

from pipelines.base import BasePipeline, ProgressCallback
from pipelines.hikari2021._common import common_preprocess, _LABEL_NAMES
from contracts.pipeline_contracts import PipelineInput, PipelineResult


class HikariNBGCPipeline(BasePipeline):

    def run(
        self,
        pipeline_input: PipelineInput,
        progress: Optional[ProgressCallback] = None,
    ) -> PipelineResult:
        self._emit_progress(progress, "Preprocessing")
        df = pipeline_input.df.copy()
        label_col = pipeline_input.label_column
        random_state = pipeline_input.random_state

        X, y, feature_names, label_mapping = common_preprocess(df, label_col)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=random_state, stratify=y
        )

        self._emit_progress(progress, "Training")
        clf = GaussianNB()
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_test)
        accuracy = float(accuracy_score(y_test, y_pred))
        precision = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        recall = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        cm = confusion_matrix(y_test, y_pred).tolist()

        extra_info: dict = {}

        y_prob = clf.predict_proba(X_test)[:, 1]
        fpr, tpr, _ = roc_curve(y_test, y_prob)
        extra_info["roc_auc"] = float(roc_auc_score(y_test, y_prob))
        extra_info["roc_curve"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}

        extra_info["feature_importance"] = []

        extra_info["classification_report"] = classification_report(
            y_test, y_pred,
            target_names=_LABEL_NAMES,
            output_dict=True,
            zero_division=0,
        )

        self._emit_progress(progress, "Computing learning curve")
        try:
            train_sizes, train_scores, val_scores = learning_curve(
                estimator=GaussianNB(),
                X=X_train, y=y_train,
                train_sizes=[0.2, 0.4, 0.6, 0.8, 1.0],
                cv=5, scoring="f1_weighted", n_jobs=2, random_state=random_state,
            )
            extra_info["learning_curve"] = {
                "train_sizes": train_sizes.tolist(),
                "train_scores_mean": train_scores.mean(axis=1).tolist(),
                "train_scores_std": train_scores.std(axis=1).tolist(),
                "val_scores_mean": val_scores.mean(axis=1).tolist(),
                "val_scores_std": val_scores.std(axis=1).tolist(),
            }
        except Exception as e:
            extra_info["learning_curve"] = {"error": str(e)}

        return PipelineResult(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            confusion_matrix=cm,
            model=clf,
            feature_names=feature_names,
            label_mapping=label_mapping,
            extra_info=extra_info,
        )

    def get_info(self) -> dict:
        return {
            "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant. Gaussian Naive Bayes classifier.",
            "algorithm": "Gaussian Naive Bayes",
            "preprocessing_steps": [
                "Drop index artifacts and identifier columns",
                "Drop non-numeric columns",
                "Drop NaN rows",
                "70/30 stratified train/test split",
            ],
            "feature_selection": "None — all numeric features used",
            "fixed_params": {
                "balancing": "None",
                "scaler": "None",
                "pca": False,
                "test_size": 0.3,
                "stratify": True,
            },
        }
