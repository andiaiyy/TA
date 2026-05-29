"""Dump metrics for the four EVE experiments from run 1."""
import json
from pathlib import Path
from database.db import get_experiment

ids = {
    'rfc': '44d6e2b9-e5a3-424f-878b-10062ab9e4f4',
    'dt' : 'a2a73cde-1f35-4ea7-981f-1fc6fdd3374c',
    'knn': '4e220b18-f817-4505-9aa3-3a30051833c5',
    'xgb': '0f9ce3d3-49fd-4b42-bcf2-3da7b3887264',
}

for name, eid in ids.items():
    e = get_experiment(eid)
    print(f'--- {name} ({eid[:8]}) ---')
    print(f'  status   : {e["status"]}')
    print(f'  accuracy : {e["accuracy"]}')
    print(f'  precision: {e["precision_score"]}')
    print(f'  recall   : {e["recall"]}')
    print(f'  f1_score : {e["f1_score"]}')

    # Load metrics JSON for top features (only DT here)
    if name == 'dt':
        mp = e['metrics_path']
        if mp and Path(mp).exists():
            with open(mp) as fh:
                metrics = json.load(fh)
            fi = metrics.get('feature_importance', [])
            print(f'  top 10 features by importance:')
            for f in fi[:10]:
                print(f'    {f["feature"]:30s} {f["importance"]}')
            print(f'  confusion_matrix:')
            for row in metrics.get('confusion_matrix', []):
                print(f'    {row}')
            print(f'  roc_auc  : {metrics.get("roc_auc")}')
