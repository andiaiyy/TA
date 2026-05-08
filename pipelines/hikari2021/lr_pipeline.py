"""Logistic Regression pipeline for HIKARI2021 (split-first, then StandardScaler + PCA on train only)."""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, learning_curve
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix, roc_auc_score, roc_curve,
    classification_report,
)

from pipelines.base import BasePipeline
from pipelines.hikari2021._common import common_preprocess, _LABEL_NAMES
from contracts.pipeline_contracts import PipelineInput, PipelineResult


class HikariLRPipeline(BasePipeline):

    def run(self, pipeline_input: PipelineInput) -> PipelineResult:
        df = pipeline_input.df.copy()
        label_col = pipeline_input.label_column
        random_state = pipeline_input.random_state

        X, y, _, label_mapping = common_preprocess(df, label_col)

        # 5. Train/Test Split FIRST
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=random_state, stratify=y,
        )

        # 6. StandardScaler — fit on TRAIN only (fixes leakage from original notebook)
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # 7. PCA — fit on TRAIN only (fixes leakage from original notebook)
        pca = PCA(n_components=0.95, random_state=random_state)
        X_train_pca = pca.fit_transform(X_train_scaled)
        X_test_pca = pca.transform(X_test_scaled)
        pca_feature_names = [f"PC{i+1}" for i in range(X_train_pca.shape[1])]

        # 8. Train on PCA-transformed train data
        clf = LogisticRegression(max_iter=3000, random_state=random_state)
        clf.fit(X_train_pca, y_train)

        # 9. Evaluate on PCA-transformed test data
        y_pred = clf.predict(X_test_pca)
        accuracy = float(accuracy_score(y_test, y_pred))
        precision = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        recall = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        cm = confusion_matrix(y_test, y_pred).tolist()

        extra_info: dict = {}

        y_prob = clf.predict_proba(X_test_pca)[:, 1]
        fpr, tpr, _ = roc_curve(y_test, y_prob)
        extra_info["roc_auc"] = float(roc_auc_score(y_test, y_prob))
        extra_info["roc_curve"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}

        extra_info["feature_importance"] = sorted(
            [
                {"feature": name, "importance": round(float(imp), 6)}
                for name, imp in zip(pca_feature_names, np.abs(clf.coef_[0]))
            ],
            key=lambda x: x["importance"],
            reverse=True,
        )

        extra_info["classification_report"] = classification_report(
            y_test, y_pred,
            target_names=_LABEL_NAMES,
            output_dict=True,
            zero_division=0,
        )

        try:
            train_sizes, train_scores, val_scores = learning_curve(
                LogisticRegression(max_iter=3000, random_state=random_state),
                X_train_pca, y_train,
                train_sizes=[0.2, 0.4, 0.6, 0.8, 1.0],
                cv=5, scoring="f1_weighted", n_jobs=-1, random_state=random_state,
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
            feature_names=pca_feature_names,
            label_mapping=label_mapping,
            extra_info=extra_info,
        )

    def get_info(self) -> dict:
        return {
            "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant. Logistic Regression with PCA.",
            "algorithm": "Logistic Regression",
            "preprocessing_steps": [
                "Drop index artifacts and identifier columns",
                "Drop non-numeric columns",
                "Drop NaN rows",
                "StandardScaler (fit on train only — corrected from original notebook)",
                "PCA (95% variance retention, fit on train only — corrected from original notebook)",
            ],
            "feature_selection": "PCA retaining 95% explained variance",
            "fixed_params": {
                "max_iter": 3000,
                "random_state": 42,
                "balancing": "None",
                "scaler": "StandardScaler (train only)",
                "pca": "PCA(n_components=0.95, train only)",
                "test_size": 0.3,
                "stratify": True,
            },
        }
