"""
Pipeline registry — maps pipeline_id to class + metadata.

Adding a new pipeline: create the file, add one entry here. That's it.
"""
from pipelines.hikari2021.rfc_pipeline import HikariRFCPipeline
from pipelines.hikari2021.dt_pipeline import HikariDTPipeline
from pipelines.hikari2021.knn_pipeline import HikariKNNPipeline
from pipelines.hikari2021.svc_pipeline import HikariSVCPipeline
from pipelines.hikari2021.nbgc_pipeline import HikariNBGCPipeline
from pipelines.hikari2021.lr_pipeline import HikariLRPipeline
from pipelines.eve_cbr.dt_pipeline import EveCbrDTPipeline
from pipelines.eve_cbr.rfc_pipeline import EveCbrRFCPipeline
from pipelines.eve_cbr.lsvc_pipeline import EveCbrLSVCPipeline
from pipelines.eve_cbr.xgb_pipeline import EveCbrXGBPipeline

PIPELINE_REGISTRY = {
    "hikari2021.rfc_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Random Forest + RandomUnderSampler — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Random Forest",
        "class": HikariRFCPipeline,
        "stages": [
            "Preprocessing",
            "Balancing & scaling",
            "Training",
            "Computing learning curve",
        ],
    },
    "hikari2021.dt_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Decision Tree — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Decision Tree",
        "class": HikariDTPipeline,
        "stages": [
            "Preprocessing",
            "Training",
            "Evaluating",
            "Computing learning curve",
        ],
    },
    "hikari2021.knn_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "K-Nearest Neighbors + RandomUnderSampler — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "K-Nearest Neighbors",
        "class": HikariKNNPipeline,
        "stages": [
            "Preprocessing",
            "Balancing & scaling",
            "Training",
            "Computing learning curve",
        ],
    },
    "hikari2021.svc_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Support Vector Classifier — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "SVC",
        "class": HikariSVCPipeline,
        "stages": [
            "Preprocessing",
            "Scaling",
            "Training (SVC — slow on large datasets)",
            "Evaluating",
            "Computing learning curve",
        ],
    },
    "hikari2021.nbgc_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Gaussian Naive Bayes — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Gaussian Naive Bayes",
        "class": HikariNBGCPipeline,
        "stages": [
            "Preprocessing",
            "Training",
            "Computing learning curve",
        ],
    },
    "hikari2021.lr_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Logistic Regression + PCA — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Logistic Regression",
        "class": HikariLRPipeline,
        "stages": [
            "Preprocessing",
            "Scaling & PCA",
            "Training",
            "Computing learning curve",
        ],
    },
    # --- EVE/Suricata cbr 14-phase anti-leakage pipeline (TLS), natural-holdout ---
    # NOTE: the legacy 7-phase EVE pipelines (eve_suricata.*) were archived
    # (recoverable) under pipelines/_archive/eve_suricata_7phase/ and replaced
    # by these cbr pipelines as the sole EVE/Suricata pipeline family.
    "eve_cbr.rfc": {
        "dataset_type": "EVE_SURICATA",
        "name": "Random Forest — EVE/Suricata cbr (TLS, anti-leakage)",
        "paper": "EVE/Suricata IDS — cbr 14-phase anti-leakage pipeline",
        "algorithm": "Random Forest",
        "class": EveCbrRFCPipeline,
        "stages": [
            "Splitting TLS from EVE dataset",
            "Running cbr 14-phase pipeline (TLS)",
            "Collecting natural-holdout metrics",
        ],
    },
    "eve_cbr.dt": {
        "dataset_type": "EVE_SURICATA",
        "name": "Decision Tree — EVE/Suricata cbr (TLS, anti-leakage)",
        "paper": "EVE/Suricata IDS — cbr 14-phase anti-leakage pipeline",
        "algorithm": "Decision Tree",
        "class": EveCbrDTPipeline,
        "stages": [
            "Splitting TLS from EVE dataset",
            "Running cbr 14-phase pipeline (TLS)",
            "Collecting natural-holdout metrics",
        ],
    },
    "eve_cbr.lsvc": {
        "dataset_type": "EVE_SURICATA",
        "name": "Linear SVC — EVE/Suricata cbr (TLS, anti-leakage)",
        "paper": "EVE/Suricata IDS — cbr 14-phase anti-leakage pipeline",
        "algorithm": "Linear SVC",
        "class": EveCbrLSVCPipeline,
        "stages": [
            "Splitting TLS from EVE dataset",
            "Running cbr 14-phase pipeline (TLS)",
            "Collecting natural-holdout metrics",
        ],
    },
    "eve_cbr.xgb": {
        "dataset_type": "EVE_SURICATA",
        "name": "XGBoost — EVE/Suricata cbr (TLS, anti-leakage)",
        "paper": "EVE/Suricata IDS — cbr 14-phase anti-leakage pipeline",
        "algorithm": "XGBoost",
        "class": EveCbrXGBPipeline,
        "stages": [
            "Splitting TLS from EVE dataset",
            "Running cbr 14-phase pipeline (TLS)",
            "Collecting natural-holdout metrics",
        ],
    },
}


def get_pipeline(pipeline_id: str) -> dict | None:
    """Return registry entry for pipeline_id, or None."""
    return PIPELINE_REGISTRY.get(pipeline_id)


def get_pipelines_for_dataset(dataset_type: str) -> dict:
    """Return all pipeline entries that match a dataset type."""
    return {pid: info for pid, info in PIPELINE_REGISTRY.items() if info["dataset_type"] == dataset_type}


def get_pipeline_instance(pipeline_id: str):
    """Instantiate and return the pipeline class, or None if unknown."""
    entry = PIPELINE_REGISTRY.get(pipeline_id)
    return entry["class"]() if entry else None


def list_all_pipelines() -> dict:
    """Return the full registry."""
    return PIPELINE_REGISTRY
