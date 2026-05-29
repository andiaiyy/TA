"""
One-off dispatcher: queue all four EVE pipelines on eve_100k_fixed.json.

Runs inside ids_ui container (USE_ASYNC=true), which dispatches Celery
tasks to ids_worker. Prints experiment_ids; downstream poll script
reads DB for FINISHED/FAILED status.
"""
from orchestrator.experiment_service import create_and_run_experiment

DATASET_TYPE = "EVE_SURICATA"
DATASET_PATH = "/app/storage/datasets/eve_100k_fixed.json"
PIPELINE_IDS = [
    "eve_suricata.rfc",
    "eve_suricata.dt",
    "eve_suricata.knn",
    "eve_suricata.xgb",
]

if __name__ == "__main__":
    print(f"Dispatching {len(PIPELINE_IDS)} EVE pipelines on {DATASET_PATH}")
    for pid in PIPELINE_IDS:
        result = create_and_run_experiment(
            dataset_type=DATASET_TYPE,
            dataset_path=DATASET_PATH,
            pipeline_id=pid,
        )
        print(
            f"  {pid}: success={result['success']} "
            f"async={result['async_mode']} "
            f"experiment_id={result['experiment_id']} "
            f"error={result.get('error')}"
        )
