"""
Execution service — pipeline dispatch.
No database access. Raises on errors (experiment_service catches).
"""
import pandas as pd
from contracts.pipeline_contracts import PipelineInput, PipelineResult
from contracts.dataset_schemas import get_schema
from config.pipeline_registry import get_pipeline_instance
from workers.local_worker import run_pipeline


def execute_pipeline(
    pipeline_id: str,
    df: pd.DataFrame,
    dataset_type: str,
    dataset_path: str = "",
) -> PipelineResult:
    """
    Resolve pipeline, build input, execute, return result.
    Raises ValueError if pipeline or schema not found.
    """
    instance = get_pipeline_instance(pipeline_id)
    if instance is None:
        raise ValueError(f"Pipeline not found: {pipeline_id}")

    schema = get_schema(dataset_type)
    if schema is None:
        raise ValueError(f"Dataset schema not found: {dataset_type}")

    pipeline_input = PipelineInput(
        df=df,
        label_column=schema["label_column"],
        dataset_type=dataset_type,
        dataset_path=dataset_path,
    )
    return run_pipeline(instance, pipeline_input)


def get_pipeline_info(pipeline_id: str) -> dict | None:
    """Get pipeline metadata for UI display. Returns None if not found."""
    instance = get_pipeline_instance(pipeline_id)
    if instance is None:
        return None
    return instance.get_info()
