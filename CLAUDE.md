# CLAUDE.md

> **This file is the source of truth for project conventions.**
> Read it in full before touching any file in this repository.
> If anything in this file contradicts a user instruction, **stop and ask** — do not silently reconcile.

---

## 1. Project Identity

**Name:** IDS Research Pipeline Execution System
**Type:** Thesis-grade, on-premise web platform for reproducible ML experiments on Intrusion Detection System datasets.
**Contribution:** Not a new algorithm. The contribution is **controlled, auditable, reproducible research execution infrastructure**. Every design choice in this codebase serves that goal.

**Critical implication:** Reproducibility is not a nice-to-have. It is the thesis claim. Any change that weakens reproducibility — even slightly — is a thesis-breaking change. Treat that property with the same care you would treat the safety properties of a medical device.

---

## 2. Tech Stack (locked — do not propose alternatives)

| Layer | Technology |
|-------|-----------|
| UI | Streamlit |
| Orchestrator | Plain Python functions |
| Sync execution | `workers/local_worker.py` |
| Async execution | Celery + Redis (toggle via `USE_ASYNC` env var) |
| Metadata storage | SQLite (stdlib `sqlite3`, WAL mode) |
| Artifact storage | Filesystem under `storage/artifacts/{experiment_id}/` |
| ML | scikit-learn + imbalanced-learn + XGBoost (EVE only) |
| Containerization | Docker + docker-compose |
| Reports | reportlab (PDF) |
| Packaging | `pip install -e .` via `pyproject.toml` |

**Do not introduce new dependencies without an explicit user instruction.** If you think something is missing, ask before adding.

---

## 3. Layer Architecture (NON-NEGOTIABLE)

```
ui/                       ← Streamlit pages
  │ imports only from: orchestrator/, config/, utils/ (read-only utilities)
  ▼
orchestrator/             ← Business logic
  ├─ experiment_service.py    ← ONLY file in orchestrator that WRITES to DB
  ├─ result_service.py        ← DB read-only
  ├─ execution_service.py     ← NO DB, dispatches to workers
  ├─ validation_service.py    ← Pure, no DB
  ├─ dataset_parser.py        ← CSV/JSON → DataFrame
  └─ validator.py             ← Schema check
  │
  ▼
workers/                  ← Execute pipelines, return results
  │ imports only from: pipelines/, contracts/, utils/
  │ NO DB access, NO UI imports
  ▼
pipelines/                ← Pure ML computation
  │ NO DB, NO UI, NO orchestrator imports
  │ Returns PipelineResult dataclass
  ▼
contracts/, utils/, config/, database/   ← Importable by all layers above
```

### Hard rules (violations = revert immediately)

1. **`pipelines/` may not import from `database/`, `ui/`, `orchestrator/`, or `workers/`.** Pipelines are pure computation.
2. **`experiment_service.py` is the ONLY orchestrator file allowed to write to the database.** All other DB writes happen elsewhere. If you find yourself wanting to write from another orchestrator file, you are doing something wrong.
3. **`workers/` may not write to the database directly.** Workers return results to the orchestrator, which writes them.
4. **`ui/` may not import from `pipelines/`, `workers/`, or `database/` directly.** All UI access goes through `orchestrator/`.
5. **`contracts/` and `utils/` may be imported from anywhere.** They have no upward dependencies.

### Before writing any import in a new file, check

- Which layer am I in?
- Is the import I am about to add allowed by the rules above?
- If unsure, **stop and ask the user.**

---

## 4. Reproducibility Invariants (NEVER VIOLATE)

These are the properties that make the thesis claim true. Breaking any of them silently is the single worst thing you can do in this codebase.

1. **All `random_state` parameters MUST be set to 42.** Train/test splits, samplers, classifiers, anything stochastic. No exceptions, no `None`, no missing parameters.
2. **All train/test splits MUST use `stratify=y`.** HIKARI2021 in particular has severe class imbalance; non-stratified splits produce unreliable test sets.
3. **Scalers, samplers, and PCA MUST be fit on training data only, never on the full dataset before splitting.** This is the "data leakage" rule. The only exception is the LR pipeline if it is intentionally replicating the original notebook's leakage — but that exception MUST be explicit in code comments. If you are not sure whether leakage is intentional, ask.
4. **Every dataset input MUST be hashed with SHA-256 and recorded in the experiment metadata.** Use `utils/hashing.py`. Do not bypass it.
5. **Pipeline hyperparameters MUST be hard-coded in the pipeline file.** Never expose them via UI controls, config files, or function arguments. The locked-hyperparameter property is the platform's value proposition.
6. **`PipelineResult` is the stable contract between pipelines and the rest of the system.** Do not add required fields to it. If a pipeline produces extra metrics (ROC, feature importance, learning curve), put them in `extra_info: dict`.

If a task seems to require violating any of these, **stop and ask before proceeding.** Do not silently work around them.

---

## 5. Datasets & Pipelines (current state)

### Datasets

| Dataset | Format | Status |
|---------|--------|--------|
| CICIDS2017 | CSV | Complete |
| HIKARI2021 | CSV | Complete |
| EVE_SURICATA | NDJSON (and CSV adapter in progress) | Integration in progress |

### Registered pipelines

| ID | Status |
|----|--------|
| `cicids2017.rf_paper_a` | Working, tested, reproducible |
| `hikari2021.rfc_pipeline` | Working |
| `hikari2021.dt_pipeline` | Working |
| `hikari2021.knn_pipeline` | Working |
| `hikari2021.svc_pipeline` | Working (slow — UI displays runtime warning) |
| `hikari2021.nbgc_pipeline` | Working |
| `hikari2021.lr_pipeline` | Working |
| `eve_suricata.rfc` | ML logic exists, end-to-end integration pending |
| `eve_suricata.dt` | ML logic exists, end-to-end integration pending |
| `eve_suricata.knn` | ML logic exists, end-to-end integration pending |
| `eve_suricata.xgb` | ML logic exists, end-to-end integration pending |

**Before claiming a pipeline "works," verify it produces FINISHED status end-to-end through the UI on real data. Never assume.**

---

## 6. Test Discipline

### Existing tests are sacred

- Before making any change, run `pytest tests/ -v` to record the baseline (expected: 162 passing, 7 skipped, 0 failed at last check — verify before assuming).
- After your change, run `pytest tests/ -v` again. The pass count MUST not decrease.
- If a previously-passing test fails after your change, the change is wrong by default. Do not "update the test to match the new behavior" unless the user explicitly says the behavior change is intentional.

### When to add tests

- Any new file in `pipelines/`, `orchestrator/`, or `database/` MUST have a corresponding test file.
- Any bug fix MUST include a regression test that fails before the fix and passes after.
- Pipeline tests MUST include a reproducibility check: run twice, assert identical metrics.

### Test naming

Follow the existing convention: `tests/test_{module_name}.py`. Read an existing test file before writing a new one to match style.

---

## 7. File & Path Conventions

| Path | Purpose | Editable? |
|------|---------|-----------|
| `pyproject.toml` | Package definition | Only with explicit user permission |
| `config/settings.py` | Paths and environment detection | Only with explicit user permission |
| `config/pipeline_registry.py` | Pipeline registration | Yes, additive only |
| `contracts/` | Cross-layer dataclasses | Avoid changes; if needed, ask |
| `pipelines/{dataset}/` | Per-pipeline files | Yes, follow existing patterns |
| `tests/` | Test files | Yes, additive preferred |
| `storage/datasets/` | Input data | **Read-only — never write here** |
| `storage/artifacts/` | Experiment outputs | Written by orchestrator only |
| `outputs/` | Phase prompts and documentation | User-managed; do not modify without permission |

### Never do these without explicit permission

- Delete files
- Rename files
- Reorganize directories
- Modify `pyproject.toml`, `requirements.txt`, `docker-compose.yml`, `Dockerfile`
- Modify any file under `storage/datasets/`
- Reset the database (`database/migration.py reset_db`)
- Change the database schema in `database/models.py`

---

## 8. Coding Conventions

- **Python version:** 3.11 (matches the Docker image).
- **Style:** Match the existing code. Read a similar file first before writing a new one.
- **Logging:** Use `utils/logging_config.py`. Do not `print()` in non-CLI code.
- **Exceptions:** Never silently swallow exceptions. Log with `logger.exception()` at minimum. Bare `pass` in an `except` block is a bug.
- **Type hints:** Encouraged but not required. Match the surrounding file's style.
- **Imports:** Group as stdlib / third-party / local, separated by blank lines. Match existing files.
- **Comments:** Explain *why*, not *what*. Do not narrate the code.

---

## 9. Behaviors That Are Always Wrong in This Codebase

These are listed because they are tempting and the user has explicitly forbidden them.

- ❌ Adding a "configurable hyperparameter" feature to the UI or pipelines
- ❌ Skipping `stratify=y` to "make it simpler"
- ❌ Removing `random_state=42` because it "shouldn't matter"
- ❌ Fitting a scaler on the full dataset because "it converges faster"
- ❌ Writing to the database from inside a pipeline file
- ❌ Importing pipeline code from inside UI code
- ❌ Mocking the ML model in pipeline tests instead of running it on synthetic data
- ❌ Adding a dependency without asking
- ❌ Refactoring "while you're in there" — do the asked task and only that task
- ❌ Updating tests to match new buggy behavior instead of fixing the bug
- ❌ Claiming a pipeline works without running it end-to-end

---

## 10. Known In-Progress Work

- **EVE/Suricata Phase 1 CSV adapter:** The phase currently reads NDJSON only. A CSV input adapter is in progress that reconstructs nested events from dotted columns. Do not modify the existing NDJSON path. Add the CSV path as a separate code branch, gated by file extension detection.
- **Bab 4 testing matrix:** Functional, reproducibility, and stability testing data is not yet collected. Any helper scripts for this go in `experiments/`, not in production directories.

---

## 11. When to Stop and Ask

You MUST stop and ask the user before proceeding if any of the following applies:

1. The task as written requires violating a rule in Sections 3, 4, 7, or 9.
2. The task is ambiguous on a point that affects more than one file.
3. The "obvious" implementation requires adding a dependency, deleting a file, or modifying a forbidden path.
4. You discover a bug adjacent to the task that you were not asked to fix.
5. A test fails after your change and the fix is non-obvious.
6. The user's task description contradicts what is in this CLAUDE.md.
7. You are about to make a decision that will affect reproducibility, performance characteristics, or the database schema.

**Asking is not weakness. Silent assumptions are.**

---

## 12. Authoritative References

When this file is ambiguous, the following files are the next source of truth, in order:

1. `pyproject.toml` — package & dependency definition
2. `config/pipeline_registry.py` — what pipelines exist
3. `contracts/pipeline_contracts.py` — `PipelineResult` shape
4. `contracts/dataset_schemas.py` — dataset structure
5. `database/models.py` — DB schema
6. Existing test files matching the area of work — read these before writing similar tests

If those files disagree with this CLAUDE.md, **the code wins** and CLAUDE.md needs updating — flag it.
