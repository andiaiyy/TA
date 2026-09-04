"""Pipeline kontribusi uji coba — Histogram Gradient Boosting pada dataset HIKARI2021."""

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from contracts.pipeline_contracts import PipelineResult
from pipelines.base import BasePipeline

MAX_ROWS = 60000


class ContribHistGradientBoostingPipeline(BasePipeline):
    """Histogram Gradient Boosting dengan praproses yang di-fit hanya pada data latih."""

    ALGORITHM = "Histogram Gradient Boosting"

    def run(self, pipeline_input, progress=None):
        def say(message):
            if progress is not None:
                progress(message)

        say("Preprocessing")
        frame = pipeline_input.df
        label_col = pipeline_input.label_column

        y_all = frame[label_col]
        x_all = frame.drop(columns=[label_col]).select_dtypes(include=[np.number])
        x_all = x_all.replace([np.inf, -np.inf], np.nan).fillna(0.0)

        seed = int(pipeline_input.random_state)

        # Subsampel berstratifikasi agar uji coba cepat; deterministik terhadap seed.
        if len(x_all) > MAX_ROWS:
            x_all, _, y_all, _ = train_test_split(
                x_all, y_all, train_size=MAX_ROWS,
                random_state=seed, stratify=y_all,
            )

        say("Train-test split")
        x_tr, x_te, y_tr, y_te = train_test_split(
            x_all, y_all, test_size=float(pipeline_input.test_size),
            random_state=seed, stratify=y_all,
        )
        feature_names = list(x_all.columns)

        say("Training")
        model = HistGradientBoostingClassifier(max_iter=100, random_state=seed)
        model.fit(x_tr, y_tr)

        say("Evaluation")
        preds = model.predict(x_te)

        auc = None
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(x_te)
            if proba.shape[1] == 2:
                auc = float(roc_auc_score(y_te, proba[:, 1]))
        elif hasattr(model, "decision_function"):
            auc = float(roc_auc_score(y_te, model.decision_function(x_te)))

        matrix = confusion_matrix(y_te, preds).tolist()

        importances = {}
        if hasattr(model, "feature_importances_"):
            importances = {
                name: float(value)
                for name, value in zip(feature_names, model.feature_importances_)
            }

        return PipelineResult(
            accuracy=float(accuracy_score(y_te, preds)),
            precision=float(precision_score(y_te, preds, average="weighted", zero_division=0)),
            recall=float(recall_score(y_te, preds, average="weighted", zero_division=0)),
            f1_score=float(f1_score(y_te, preds, average="weighted", zero_division=0)),
            confusion_matrix=[[int(v) for v in row] for row in matrix],
            model=model,
            feature_names=feature_names,
            label_mapping={0: "Benign", 1: "Malicious"},
            extra_info={
                "roc_auc": auc,
                "feature_importance": importances,
                "rows_used": int(len(x_all)),
                "note": "Subsampel maksimum 60.000 baris untuk uji coba cepat.",
            },
        )

    def get_info(self):
        return {
            "paper": "Pipeline kontribusi uji coba (bukan replikasi paper).",
            "algorithm": self.ALGORITHM,
            "preprocessing_steps": [
                "Pilih kolom numerik",
                "Ganti nilai tak hingga dan kosong dengan 0",
                "Subsampel berstratifikasi maksimum 60.000 baris",
            ],
            "feature_selection": "None - seluruh kolom numerik dipakai",
            "fixed_params": {"max_iter": 100, "random_state": 42, "max_rows": 60000},
            "train_test_split": "Stratified 80:20; split dilakukan sebelum praproses di-fit",
            "dataset_requirements": "CSV HIKARI2021 dengan kolom label 'Label' bernilai 0/1",
            "target": "Label (0 = Benign, 1 = Malicious)",
            "evaluation_metrics": ["accuracy", "precision", "recall", "f1_score", "roc_auc"],
            "random_seed": 42,
        }
