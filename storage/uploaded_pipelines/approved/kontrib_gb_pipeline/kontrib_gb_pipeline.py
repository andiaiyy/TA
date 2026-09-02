"""Contoh pipeline kontribusi: Gradient Boosting untuk HIKARI2021.

Dipakai untuk menguji alur: unggah -> validasi -> setujui -> aktif -> sunting.
"""
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineResult


class KontribGBPipeline(BasePipeline):
    """Gradient Boosting Classifier pada dataset HIKARI2021."""

    ALGORITHM = "Gradient Boosting Classifier"
    N_ESTIMATORS = 60
    LEARNING_RATE = 0.1
    MAX_DEPTH = 3

    def run(self, pipeline_input, progress=None):
        self._emit_progress(progress, "Preprocessing")

        df = pipeline_input.df
        label_col = pipeline_input.label_column
        y = df[label_col].to_numpy()
        X_df = df.drop(columns=[label_col]).select_dtypes(include=[np.number])
        feature_names = list(X_df.columns)
        X = X_df.to_numpy()

        # anti-kebocoran: pisah dulu, baru fit scaler pada data latih saja
        self._emit_progress(progress, "Train-test split")
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y,
            test_size=pipeline_input.test_size,
            random_state=pipeline_input.random_state,
            stratify=y,
        )

        scaler = StandardScaler().fit(X_tr)
        X_tr = scaler.transform(X_tr)
        X_te = scaler.transform(X_te)

        self._emit_progress(progress, "Training")
        model = GradientBoostingClassifier(
            n_estimators=self.N_ESTIMATORS,
            learning_rate=self.LEARNING_RATE,
            max_depth=self.MAX_DEPTH,
            random_state=pipeline_input.random_state,
        )
        model.fit(X_tr, y_tr)

        self._emit_progress(progress, "Evaluation")
        preds = model.predict(X_te)

        return PipelineResult(
            accuracy=float(accuracy_score(y_te, preds)),
            precision=float(precision_score(y_te, preds, average="weighted", zero_division=0)),
            recall=float(recall_score(y_te, preds, average="weighted", zero_division=0)),
            f1_score=float(f1_score(y_te, preds, average="weighted", zero_division=0)),
            confusion_matrix=confusion_matrix(y_te, preds).tolist(),
            model=model,
            feature_names=feature_names,
            label_mapping={0: "Benign", 1: "Malicious"},
            extra_info={
                "feature_importance": [
                    {"feature": n, "importance": float(v)}
                    for n, v in sorted(
                        zip(feature_names, model.feature_importances_),
                        key=lambda p: p[1], reverse=True,
                    )[:20]
                ],
            },
        )

    def get_info(self):
        return {
            "paper": "Kontribusi pengguna — contoh Gradient Boosting",
            "algorithm": self.ALGORITHM,
            "preprocessing_steps": [
                "Pilih kolom numerik",
                "Train-test split (stratified)",
                "StandardScaler di-fit hanya pada data latih",
            ],
            "feature_selection": "None — seluruh fitur numerik dipakai",
            "fixed_params": {
                "n_estimators": 60,
                "learning_rate": 0.1,
                "max_depth": 3,
            },
            "train_test_split": "stratified, test_size dari PipelineInput",
        }
