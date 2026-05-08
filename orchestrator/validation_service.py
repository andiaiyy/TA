"""
Validation service — high-level validation for UI consumption.
No database access. No side effects.
"""
from orchestrator.dataset_parser import parse_dataset
from orchestrator.validator import validate_dataset, ValidationResult
from contracts.dataset_schemas import get_schema, supported_datasets
from config.pipeline_registry import get_pipelines_for_dataset
from utils.hashing import sha256_file

_FAILURE = dict(
    row_count=None, column_count=None, label_column=None,
    unique_labels=None, dataset_hash=None,
    compatible_pipelines=None, validation_result=None,
)


def validate_for_experiment(dataset_type: str, dataset_path: str) -> dict:
    """
    Full validation for the UI's "Validate Dataset" button.

    Returns dict with:
        success, error, row_count, column_count, label_column,
        unique_labels, dataset_hash, compatible_pipelines, validation_result

    NEVER raises for expected failures — returns success=False with error message.
    """
    if get_schema(dataset_type) is None:
        return {"success": False, "error": f"Unknown dataset type: {dataset_type}", **_FAILURE}

    try:
        df = parse_dataset(dataset_path)
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e), **_FAILURE}

    result = validate_dataset(df, dataset_type)

    if not result.is_valid:
        return {
            "success": False,
            "error": "; ".join(result.errors),
            "row_count": result.row_count,
            "column_count": result.column_count,
            "label_column": result.label_column,
            "unique_labels": result.unique_labels,
            "dataset_hash": None,
            "compatible_pipelines": None,
            "validation_result": result,
        }

    dataset_hash = sha256_file(dataset_path)
    pipelines = get_pipelines_for_dataset(dataset_type)

    return {
        "success": True,
        "error": None,
        "row_count": result.row_count,
        "column_count": result.column_count,
        "label_column": result.label_column,
        "unique_labels": result.unique_labels,
        "dataset_hash": dataset_hash,
        "compatible_pipelines": pipelines,
        "validation_result": result,
    }


def get_available_datasets() -> list[str]:
    """Return list of supported dataset type names."""
    return supported_datasets()


def get_available_pipelines(dataset_type: str) -> dict:
    """Return pipelines compatible with a given dataset type."""
    return get_pipelines_for_dataset(dataset_type)
