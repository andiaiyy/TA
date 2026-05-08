"""
CLI runner for pipeline execution. Development/testing tool.

Usage:
    python run_pipeline.py --dataset-type CICIDS2017 --dataset-path storage/datasets/file.csv --pipeline cicids2017.rf_paper_a
    python run_pipeline.py --list-pipelines
    python run_pipeline.py --list-pipelines --dataset-type CICIDS2017
"""
import argparse
import uuid
import sys

from orchestrator.dataset_parser import parse_dataset
from orchestrator.validator import validate_dataset
from contracts.pipeline_contracts import PipelineInput
from contracts.dataset_schemas import get_schema
from config.pipeline_registry import get_pipeline_instance, get_pipelines_for_dataset, list_all_pipelines
from utils.hashing import sha256_file
from utils.timestamps import now_iso
from utils.artifact_saver import save_all_artifacts
from workers.local_worker import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run a research pipeline from CLI")
    parser.add_argument("--dataset-type", type=str)
    parser.add_argument("--dataset-path", type=str)
    parser.add_argument("--pipeline", type=str)
    parser.add_argument("--list-pipelines", action="store_true")
    args = parser.parse_args()

    if args.list_pipelines:
        pipelines = get_pipelines_for_dataset(args.dataset_type) if args.dataset_type else list_all_pipelines()
        title = f"Pipelines for {args.dataset_type}" if args.dataset_type else "All pipelines"
        print(f"\n{title}:")
        for pid, info in pipelines.items():
            print(f"  {pid}")
            print(f"    Dataset: {info['dataset_type']}")
            print(f"    Name:    {info['name']}")
            print(f"    Paper:   {info['paper']}\n")
        return

    if not all([args.dataset_type, args.dataset_path, args.pipeline]):
        parser.error("--dataset-type, --dataset-path, and --pipeline are required")

    print(f"[1/7] Parsing dataset: {args.dataset_path}")
    df = parse_dataset(args.dataset_path)
    print(f"      Loaded {len(df)} rows, {len(df.columns)} columns")

    print(f"[2/7] Validating against {args.dataset_type} schema...")
    validation = validate_dataset(df, args.dataset_type)
    if not validation.is_valid:
        print(f"      FAILED: {validation.errors}")
        sys.exit(1)
    print(f"      Valid — {validation.row_count} rows, labels: {validation.unique_labels}")

    print(f"[3/7] Computing dataset hash...")
    dataset_hash = sha256_file(args.dataset_path)
    print(f"      SHA-256: {dataset_hash[:16]}...")

    print(f"[4/7] Resolving pipeline: {args.pipeline}")
    pipeline_instance = get_pipeline_instance(args.pipeline)
    if pipeline_instance is None:
        print(f"      ERROR: Pipeline '{args.pipeline}' not found")
        sys.exit(1)
    info = pipeline_instance.get_info()
    print(f"      Paper:     {info['paper']}")
    print(f"      Algorithm: {info['algorithm']}")

    print(f"[5/7] Running pipeline...")
    schema = get_schema(args.dataset_type)
    pipeline_input = PipelineInput(df=df, label_column=schema["label_column"], dataset_type=args.dataset_type)
    result = run_pipeline(pipeline_instance, pipeline_input)
    print(f"      Accuracy:  {result.accuracy:.4f}")
    print(f"      Precision: {result.precision:.4f}")
    print(f"      Recall:    {result.recall:.4f}")
    print(f"      F1-score:  {result.f1_score:.4f}")

    experiment_id = str(uuid.uuid4())
    print(f"[6/7] Saving artifacts (experiment: {experiment_id[:8]}...)")
    metrics = {
        "accuracy": result.accuracy, "precision": result.precision,
        "recall": result.recall, "f1_score": result.f1_score,
        "confusion_matrix": result.confusion_matrix,
        **result.extra_info,
    }
    metadata = {
        "experiment_id": experiment_id, "dataset_type": args.dataset_type,
        "dataset_path": args.dataset_path, "dataset_hash": dataset_hash,
        "pipeline_id": args.pipeline, "label_mapping": result.label_mapping,
        "feature_names": result.feature_names,
        "created_at": now_iso(), "completed_at": now_iso(),
    }
    paths = save_all_artifacts(experiment_id, result.model, metrics, metadata)
    print(f"      Model:    {paths['model_path']}")
    print(f"      Metrics:  {paths['metrics_path']}")
    print(f"      Metadata: {paths['metadata_path']}")

    print(f"[7/7] Done!")
    print(f"\n{'='*50}")
    print(f"Experiment ID: {experiment_id}")
    print(f"Status:        FINISHED")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
