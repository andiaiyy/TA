"""Dispatch a single DT run for reproducibility check."""
from orchestrator.experiment_service import create_and_run_experiment

result = create_and_run_experiment(
    dataset_type="EVE_SURICATA",
    dataset_path="/app/storage/datasets/eve_100k_fixed.json",
    pipeline_id="eve_suricata.dt",
)
print(
    f"DT run 2 dispatch: success={result['success']} "
    f"async={result['async_mode']} "
    f"experiment_id={result['experiment_id']} "
    f"error={result.get('error')}"
)
