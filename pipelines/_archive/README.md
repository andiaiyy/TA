# Archived pipelines (recoverable)

This folder holds retired pipeline code that is **not registered** and **not part
of the live platform**, but is kept fully recoverable (moved via `git mv`, history
preserved).

## `eve_suricata_7phase/`
The legacy EVE/Suricata **7-phase** pipeline family (`eve_suricata.rfc/.dt/.knn/.xgb`),
plus identified dead code (`eve_*_pipeline.py`, `phases_v2/`). Replaced by the
**cbr 14-phase** pipelines under `pipelines/eve_cbr/` (`eve_cbr.dt/.rfc/.lsvc/.xgb`).

### Restore the 7-phase pipelines
```bash
# 1. Move the package back to its original location
git mv pipelines/_archive/eve_suricata_7phase pipelines/eve_suricata

# 2. Re-add imports + registry entries in config/pipeline_registry.py:
#    from pipelines.eve_suricata.rfc_pipeline import EveRFCPipeline   (+ dt/knn/xgb)
#    and the four "eve_suricata.rfc/.dt/.knn/.xgb" registry entries
#    (see git history: commit that performed STAGE 4b, or `git show <commit>^:config/pipeline_registry.py`)
```
Internal imports inside the archived code use the original `pipelines.eve_suricata.*`
paths, so moving the folder back restores them verbatim — no code edits needed.
