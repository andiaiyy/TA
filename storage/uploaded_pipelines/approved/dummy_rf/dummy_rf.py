"""Dummy Random Forest — pipeline contoh untuk menguji alur kontribusi."""
from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineResult


class DummyRandomForestPipeline(BasePipeline):
    """Random Forest atas kolom numerik. Parameter terkunci, split stratified."""

    def run(self, pipeline_input, progress=None):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (accuracy_score, confusion_matrix,
                                     f1_score, precision_score, recall_score)
        from sklearn.model_selection import train_test_split

        self._emit_progress(progress, "Preprocessing")
        df = pipeline_input.df
        y = df[pipeline_input.label_column]
        X = df.drop(columns=[pipeline_input.label_column]).select_dtypes(
            include="number")

        self._emit_progress(progress, "Training")
        params = self._resolved_params(pipeline_input)
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.3, stratify=y, random_state=42)
        model = RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 100)),
            max_depth=params.get("max_depth"), random_state=42, n_jobs=1)
        model.fit(X_tr, y_tr)

        self._emit_progress(progress, "Evaluating")
        pred = model.predict(X_te)
        return PipelineResult(
            accuracy=float(accuracy_score(y_te, pred)),
            precision=float(precision_score(y_te, pred, average="weighted",
                                            zero_division=0)),
            recall=float(recall_score(y_te, pred, average="weighted",
                                      zero_division=0)),
            f1_score=float(f1_score(y_te, pred, average="weighted",
                                    zero_division=0)),
            confusion_matrix=confusion_matrix(y_te, pred).tolist(),
            model=model,
            feature_names=list(X.columns),
            label_mapping={str(v): int(i)
                           for i, v in enumerate(sorted(y.unique()))},
        )

    def get_info(self):
        return {
            "paper": "Contoh kontribusi (2026), Universitas Hasanuddin",
            "algorithm": "Random Forest",
            "preprocessing_steps": [
                "Ambil kolom numerik saja",
                "Split stratified 70/30 (random_state=42)",
            ],
            "feature_selection": "None — seluruh kolom numerik dipakai",
            "fixed_params": {"n_estimators": 100, "max_depth": None,
                             "random_state": 42, "n_jobs": 1},
            "train_test_split": {"test_size": 0.3, "stratify": True,
                                 "random_state": 42},
        }
