"""
Random Forest pipeline for HIKARI2021 dataset.

Based on: IDS ML Pipeline for ALLFLOWMETER_HIKARI2021.
Original pipeline uses: loader -> balancer (RandomUnderSampler) -> preprocessor (StandardScaler) -> trainer (RFC).

Fixed configuration:
  - RandomUnderSampler for class imbalance (517K benign vs 37K malicious)
  - StandardScaler (fit on train only)
  - RandomForestClassifier(n_estimators=100, random_state=42)
  - 80/20 stratified split
  - No PCA (USE_PCA=False in original config)
  - No feature selection (all numeric features used)
"""
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split, learning_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix, roc_auc_score, roc_curve,
    classification_report,
)
from imblearn.under_sampling import RandomUnderSampler

from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineInput, PipelineResult


# Columns to drop — index artifacts, identifiers, non-numeric metadata
_DROP_COLS = [
    "Unnamed: 0.1", "Unnamed: 0",
    "uid", "originh", "responh",
    "traffic_category",
]

_LABEL_NAMES = ["Benign", "Malicious"]


class HikariRFCPipeline(BasePipeline):

    def run(self, pipeline_input: PipelineInput) -> PipelineResult:
        """Execute the full RFC pipeline for HIKARI2021 and return structured results."""
        df = pipeline_input.df.copy()
        label_col = pipeline_input.label_column
        random_state = pipeline_input.random_state
        test_size = pipeline_input.test_size

        # Step 1: Drop non-feature columns
        df.drop(columns=[c for c in _DROP_COLS if c in df.columns], inplace=True, errors="ignore")

        # Step 2: Separate X and y — label is already integer (0/1)
        y = df[label_col].copy()
        X = df.drop(columns=[label_col])
        label_mapping = {0: "Benign", 1: "Malicious"}

        # Safety net: drop any remaining non-numeric columns
        non_numeric = X.select_dtypes(exclude=[np.number]).columns.tolist()
        if non_numeric:
            X.drop(columns=non_numeric, inplace=True)

        # Step 3: Drop NaN rows, keep y aligned via index
        mask = X.notna().all(axis=1)
        X = X[mask]
        y = y[mask]

        feature_names = X.columns.tolist()

        # Step 4: Train/Test Split FIRST (before balancing)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=test_size,
            random_state=random_state,
            stratify=y,
        )

        # Step 5: RandomUnderSampler on TRAIN only (corrected — balancing after split)
        rus = RandomUnderSampler(random_state=random_state)
        X_train_bal, y_train_bal = rus.fit_resample(X_train, y_train)
        X_train_bal = pd.DataFrame(X_train_bal, columns=feature_names)
        y_train_bal = pd.Series(y_train_bal, name=label_col)

        # Step 6: StandardScaler — fit on balanced train only
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train_bal)
        X_test_scaled = scaler.transform(X_test)

        # Step 7: Train model on balanced + scaled train data
        clf = RandomForestClassifier(
            n_estimators=100,
            random_state=random_state,
            n_jobs=-1,
        )
        clf.fit(X_train_scaled, y_train_bal)

        # Step 8: Evaluate
        y_pred = clf.predict(X_test_scaled)
        accuracy = float(accuracy_score(y_test, y_pred))
        precision = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        recall = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        cm: list[list[int]] = confusion_matrix(y_test, y_pred).tolist()

        # Step 9: Extended metrics
        extra_info: dict = {}

        # 9a: ROC-AUC (binary)
        y_prob = clf.predict_proba(X_test_scaled)[:, 1]
        fpr, tpr, _ = roc_curve(y_test, y_prob)
        extra_info["roc_auc"] = float(roc_auc_score(y_test, y_prob))
        extra_info["roc_curve"] = {"fpr": fpr.tolist(), "tpr": tpr.tolist()}

        # 9b: Feature importance — sorted descending
        extra_info["feature_importance"] = sorted(
            [
                {"feature": name, "importance": round(float(imp), 6)}
                for name, imp in zip(feature_names, clf.feature_importances_)
            ],
            key=lambda x: x["importance"],
            reverse=True,
        )

        # 9c: Classification report
        extra_info["classification_report"] = classification_report(
            y_test, y_pred,
            target_names=_LABEL_NAMES,
            output_dict=True,
            zero_division=0,
        )

        # 9d: Learning curve
        try:
            train_sizes, train_scores, val_scores = learning_curve(
                estimator=RandomForestClassifier(
                    n_estimators=100, random_state=random_state, n_jobs=-1
                ),
                X=X_train_scaled,
                y=y_train_bal,
                train_sizes=[0.2, 0.4, 0.6, 0.8, 1.0],
                cv=5,
                scoring="f1_weighted",
                n_jobs=-1,
                random_state=random_state,
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
        """Return static pipeline metadata."""
        return {
            "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant. Modular IDS ML Pipeline.",
            "algorithm": "Random Forest",
            "preprocessing_steps": [
                "Drop index artifacts and identifier columns (Unnamed, uid, originh, responh, traffic_category)",
                "Drop non-numeric columns (safety net)",
                "Drop rows with NaN values",
                "RandomUnderSampler on training set only (corrected — balancing after split)",
                "StandardScaler (fit on balanced train only)",
            ],
            "feature_selection": "None — all numeric features used",
            "fixed_params": {
                "n_estimators": 100,
                "random_state": 42,
                "n_jobs": -1,
                "balancing": "RandomUnderSampler",
                "scaler": "StandardScaler",
                "pca": False,
                "test_size": 0.2,
                "stratify": True,
            },
            "train_test_split": {
                "test_size": 0.2,
                "stratify": True,
                "random_state": 42,
            },
        }
