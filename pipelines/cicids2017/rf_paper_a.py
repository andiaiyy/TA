"""
Pipeline 1: Random Forest + RFE (Sharafaldin et al., ICISSP 2018).

Standardised deviations from the original notebook are documented in SCOPE.md.
No database imports. No UI imports. Fully deterministic at random_state=42.
"""
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler, label_binarize
from sklearn.model_selection import train_test_split, learning_curve
from sklearn.feature_selection import RFE
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, roc_auc_score, roc_curve, classification_report,
)

from contracts.pipeline_contracts import PipelineInput, PipelineResult
from pipelines.base import BasePipeline, ProgressCallback

_PROBLEMATIC_COLS = ["Flow Bytes/s", "Flow Packets/s"]


class RFPaperAPipeline(BasePipeline):

    def run(
        self,
        pipeline_input: PipelineInput,
        progress: Optional[ProgressCallback] = None,
    ) -> PipelineResult:
        """Execute the full RF+RFE pipeline and return structured results."""
        self._emit_progress(progress, "Preprocessing")
        df = pipeline_input.df.copy()
        label_col = pipeline_input.label_column

        # Step 1: Label encoding
        le = LabelEncoder()
        y_encoded = le.fit_transform(df[label_col])
        label_names: list[str] = list(le.classes_)
        label_mapping = {name: int(code) for name, code in zip(le.classes_, range(len(le.classes_)))}

        # Step 2: Separate X and y
        X = df.drop(columns=[label_col])
        y = pd.Series(y_encoded, index=df.index)

        # Step 3: Drop problematic columns
        X = X.drop(columns=_PROBLEMATIC_COLS, errors="ignore")

        # Step 4: Drop NaN rows, keep y aligned via index
        mask = X.notna().all(axis=1)
        X = X[mask]
        y = y[mask]

        feature_col_names = list(X.columns)

        # Step 5: Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self._emit_progress(progress, "Scaling & RFE")
        # Step 6: StandardScaler — fit on train only
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Step 7: RFE with RF estimator — fit on train, transform both
        rfe = RFE(
            estimator=RandomForestClassifier(n_estimators=100, random_state=42),
            n_features_to_select=8,
            step=1,
        )
        X_train_rfe = rfe.fit_transform(X_train_scaled, y_train)
        X_test_rfe = rfe.transform(X_test_scaled)
        selected_features = [feature_col_names[i] for i, sel in enumerate(rfe.support_) if sel]

        self._emit_progress(progress, "Training")
        # Step 8: Train final model
        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X_train_rfe, y_train)

        # Step 9: Evaluate
        y_pred = clf.predict(X_test_rfe)
        acc = float(accuracy_score(y_test, y_pred))
        prec = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        rec = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        cm: list[list[int]] = confusion_matrix(y_test, y_pred).tolist()

        # Step 10: Extended metrics
        extra_info = {}
        y_proba = clf.predict_proba(X_test_rfe)
        n_classes = len(label_names)

        # 10a: ROC-AUC + ROC curve
        try:
            if n_classes == 2:
                roc_auc = float(roc_auc_score(y_test, y_proba[:, 1]))
                fpr, tpr, _ = roc_curve(y_test, y_proba[:, 1])
                roc_curve_data = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}
            else:
                roc_auc = float(
                    roc_auc_score(y_test, y_proba, multi_class="ovr", average="weighted")
                )
                y_bin = label_binarize(y_test, classes=list(range(n_classes)))
                fpr_dict, tpr_dict = {}, {}
                for i, cls_name in enumerate(label_names):
                    fpr_i, tpr_i, _ = roc_curve(y_bin[:, i], y_proba[:, i])
                    fpr_dict[cls_name] = fpr_i.tolist()
                    tpr_dict[cls_name] = tpr_i.tolist()
                roc_curve_data = {"fpr": fpr_dict, "tpr": tpr_dict}
        except Exception as e:
            roc_auc = 0.0
            roc_curve_data = {"fpr": [], "tpr": [], "error": str(e)}

        extra_info["roc_auc"] = roc_auc
        extra_info["roc_curve"] = roc_curve_data

        # 10b: Feature importance — sorted descending
        extra_info["feature_importance"] = sorted(
            [
                {"feature": name, "importance": float(imp)}
                for name, imp in zip(selected_features, clf.feature_importances_)
            ],
            key=lambda x: x["importance"],
            reverse=True,
        )

        # 10c: Classification report
        extra_info["classification_report"] = classification_report(
            y_test, y_pred,
            output_dict=True,
            target_names=label_names,
            zero_division=0,
        )

        # 10d: Learning curve (on already-selected features for speed and consistency)
        self._emit_progress(progress, "Computing learning curve")
        try:
            train_sizes, train_scores, test_scores = learning_curve(
                RandomForestClassifier(n_estimators=100, random_state=42),
                X_train_rfe,
                y_train,
                train_sizes=[0.2, 0.4, 0.6, 0.8, 1.0],
                cv=5,
                scoring="f1_weighted",
                n_jobs=-1,
                random_state=42,
            )
            extra_info["learning_curve"] = {
                "train_sizes": train_sizes.tolist(),
                "train_scores_mean": train_scores.mean(axis=1).tolist(),
                "train_scores_std": train_scores.std(axis=1).tolist(),
                "val_scores_mean": test_scores.mean(axis=1).tolist(),
                "val_scores_std": test_scores.std(axis=1).tolist(),
            }
        except Exception as e:
            extra_info["learning_curve"] = {"error": str(e)}

        return PipelineResult(
            accuracy=acc,
            precision=prec,
            recall=rec,
            f1_score=f1,
            confusion_matrix=cm,
            model=clf,
            feature_names=selected_features,
            label_mapping=label_mapping,
            extra_info=extra_info,
        )

    def get_info(self) -> dict:
        """Return static pipeline metadata."""
        return {
            "paper": "Sharafaldin et al., Toward Generating a New Intrusion Detection Dataset and Intrusion Traffic Characterization, ICISSP 2018",
            "algorithm": "Random Forest + RFE",
            "preprocessing_steps": [
                "LabelEncoder on target column",
                "Drop 'Flow Bytes/s' and 'Flow Packets/s' (inf/NaN columns)",
                "Drop rows with NaN values",
                "StandardScaler (fit on train only)",
            ],
            "feature_selection": "RFE (Recursive Feature Elimination) — 8 features selected using RF estimator",
            "fixed_params": {
                "n_estimators": 100,
                "random_state": 42,
                "rfe_n_features": 8,
                "rfe_step": 1,
                "test_size": 0.2,
                "stratify": True,
            },
            "train_test_split": {"test_size": 0.2, "stratify": True, "random_state": 42},
        }
