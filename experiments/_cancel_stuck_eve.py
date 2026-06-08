import os
os.environ["USE_ASYNC"] = "true"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/1"
from orchestrator.experiment_service import cancel_experiment
for label, eid in (("RFC", "d531d485-5ced-4575-a842-b6f88e61d125"),
                   ("DT",  "b5b56cf2-c5f7-4ab2-a367-1a6be7f77c9f")):
    r = cancel_experiment(eid)
    print(f"{label}: success={r['success']}  msg={r['message']}")
