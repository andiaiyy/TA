"""
Pipeline registry — maps pipeline_id to class + metadata.

Adding a new pipeline: create the file, add one entry here. That's it.
"""
from pipelines.cicids2017.rf_paper_a import RFPaperAPipeline
from pipelines.hikari2021.rfc_pipeline import HikariRFCPipeline
from pipelines.hikari2021.dt_pipeline import HikariDTPipeline
from pipelines.hikari2021.knn_pipeline import HikariKNNPipeline
from pipelines.hikari2021.svc_pipeline import HikariSVCPipeline
from pipelines.hikari2021.nbgc_pipeline import HikariNBGCPipeline
from pipelines.hikari2021.lr_pipeline import HikariLRPipeline

PIPELINE_REGISTRY = {
    "cicids2017.rf_paper_a": {
        "dataset_type": "CICIDS2017",
        "name": "Random Forest + RFE — Sharafaldin et al. (2018)",
        "paper": "Sharafaldin et al., ICISSP 2018",
        "algorithm": "Random Forest",
        "class": RFPaperAPipeline,
    },
    "hikari2021.rfc_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Random Forest + RandomUnderSampler — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Random Forest",
        "class": HikariRFCPipeline,
    },
    "hikari2021.dt_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Decision Tree — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Decision Tree",
        "class": HikariDTPipeline,
    },
    "hikari2021.knn_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "K-Nearest Neighbors + RandomUnderSampler — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "K-Nearest Neighbors",
        "class": HikariKNNPipeline,
    },
    "hikari2021.svc_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Support Vector Classifier — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "SVC",
        "class": HikariSVCPipeline,
    },
    "hikari2021.nbgc_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Gaussian Naive Bayes — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Gaussian Naive Bayes",
        "class": HikariNBGCPipeline,
    },
    "hikari2021.lr_pipeline": {
        "dataset_type": "HIKARI2021",
        "name": "Logistic Regression + PCA — HIKARI2021",
        "paper": "HIKARI2021 IDS Dataset — ALLFLOWMETER variant",
        "algorithm": "Logistic Regression",
        "class": HikariLRPipeline,
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
