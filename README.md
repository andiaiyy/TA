# IDS Research Pipeline Execution System

A controlled, reproducible platform for running fixed machine learning pipelines on cybersecurity intrusion detection datasets. Built for thesis research — every pipeline is locked to its paper's exact configuration so results are directly comparable.

---

## What It Does

Given a CSV dataset and a pipeline selection, the system:

1. Validates the CSV against a known schema
2. Trains the ML model using the paper's exact hyperparameters
3. Evaluates: accuracy, precision, recall, F1, ROC-AUC, confusion matrix, per-class report
4. Saves the trained model + all metrics as artifacts
5. Records everything in a local SQLite database
6. Renders results in a Streamlit UI with charts and a PDF download

No user-configurable hyperparameters — every parameter is locked per paper.

---

## Architecture

```
ui/                     ← Streamlit pages (only talks to orchestrator/)
orchestrator/           ← Business logic: validation, execution, DB writes
  ├─ experiment_service.py   (main facade — the only file that touches the DB)
  ├─ execution_service.py    (pipeline dispatch, no DB access)
  ├─ validation_service.py   (dataset validation for UI)
  ├─ result_service.py       (read-only metrics retrieval)
  └─ dataset_parser.py       (CSV loading)
pipelines/              ← Pure ML: no DB imports, no UI imports
  ├─ base.py                 (BasePipeline ABC)
  ├─ cicids2017/
  │   └─ rf_paper_a.py       (RF + RFE)
  ├─ hikari2021/
  │   ├─ _common.py          (shared preprocessing helper)
  │   ├─ rfc_pipeline.py     (Random Forest + RandomUnderSampler)
  │   ├─ dt_pipeline.py      (Decision Tree)
  │   ├─ knn_pipeline.py     (KNN + RUS post-split)
  │   ├─ svc_pipeline.py     (SVC, probability=True)
  │   ├─ nbgc_pipeline.py    (Gaussian Naive Bayes)
  │   └─ lr_pipeline.py      (Logistic Regression + PCA)
  └─ eve_suricata/
      ├─ phase_runner.py     (shared phases 1-9 for all EVE models)
      ├─ eve_rfc_pipeline.py (Random Forest on RFE features)
      ├─ eve_dt_pipeline.py  (Decision Tree on RFE features)
      ├─ eve_lsvc_pipeline.py(Linear SVC on MI features, decision_function ROC)
      └─ eve_xgb_pipeline.py (XGBoost on MI features, optional dependency)
database/               ← SQLite CRUD + schema migrations
contracts/              ← Shared data classes (no project-layer imports)
config/                 ← Pipeline registry + Celery config
utils/                  ← Artifact saving, hashing, PDF generation
workers/                ← Pipeline runners (local + Celery async)
  ├─ local_worker.py         (synchronous, wraps pipeline.run())
  └─ celery_worker.py        (async task via Redis broker)
docker/                 ← Dockerfiles for UI and Celery worker
tests/                  ← Pytest suite (~100 tests)
storage/                ← Datasets + saved artifacts (gitignored)
run_pipeline.py         ← CLI runner
docker-compose.yml      ← Full stack: UI + Celery worker + Redis
```

**Import boundary rule:** `pipelines/` never imports from `database/`, `ui/`, or `orchestrator/`. `orchestrator/` is the only layer that touches the database.

---

## Supported Datasets & Pipelines

### CICIDS2017
Network traffic dataset — Canadian Institute for Cybersecurity, 2017. 78-column feature space. Labels are string class names (e.g. `BENIGN`, `DDoS`, `PortScan`).

| Pipeline ID | Algorithm | Paper |
|---|---|---|
| `cicids2017.rf_paper_a` | Random Forest + RFE (10 features) | Sharafaldin et al., ICISSP 2018 |

### HIKARI2021
Network traffic dataset — ALLFLOWMETER variant. 88-column feature space. Labels are integers (0 = Benign, 1 = Malicious). Class distribution: ~517K benign vs ~37K malicious.

| Pipeline ID | Algorithm | Preprocessing |
|---|---|---|
| `hikari2021.rfc_pipeline` | Random Forest | RUS before split, StandardScaler |
| `hikari2021.dt_pipeline` | Decision Tree | None |
| `hikari2021.knn_pipeline` | K-Nearest Neighbors (k=5) | RUS post-split (train only), StandardScaler |
| `hikari2021.svc_pipeline` | SVC (probability=True) | None |
| `hikari2021.nbgc_pipeline` | Gaussian Naive Bayes | None |
| `hikari2021.lr_pipeline` | Logistic Regression | StandardScaler + PCA(95% variance) on all data |

All HIKARI2021 pipelines use 70/30 train/test split. The RFC pipeline uses 80/20.

> **Note on LR:** The StandardScaler + PCA is fitted on the full dataset before splitting — intentionally faithful to the original notebook. This constitutes data leakage and is documented as such.

> **Note on SVC:** SVC has O(n²) complexity. A runtime warning is logged when the dataset exceeds 50K rows. Consider using a subset for initial testing.

### EVE_SURICATA
Network traffic dataset from Suricata IDS in EVE JSON (NDJSON) format. Labels are binary: 0 = Benign, 1 = Attack (derived from alert severity). Unlike CICIDS2017 and HIKARI2021, input is a `.json` / `.log` file — not a CSV.

All four EVE pipelines share an identical 11-phase preprocessing chain (Phases 1–9 implemented in `phase_runner.py`). Only the model differs between them.

**Shared phase pipeline:**

| Phase | Name | What it does |
|---|---|---|
| 1 | Load & Label | 2-pass NDJSON ingestion, binary labeling, disk-backed sharding |
| 2 | Feature Engineering | Hash encoding, flow/alert totals, categorical expansion |
| 3 | Computed Features | Interaction terms, row-level stats, normalization |
| 4 | Aggressive Cleaning | NaN/Inf elimination, constant-column removal |
| 7 | Correlation Analysis | Leakage detection — artifacts written but output not piped forward |
| 8 | Train/Test Split | Stratified attack-aware split |
| 9 | Feature Selection | MI + RFE (top 25) + PCA — returns three feature sets |

**Pipelines:**

| Pipeline ID | Algorithm | Features used | ROC method |
|---|---|---|---|
| `eve_suricata.rfc` | Random Forest (100 trees) | RFE top 25 | predict_proba |
| `eve_suricata.dt` | Decision Tree | RFE top 25 | predict_proba |
| `eve_suricata.lsvc` | Linear SVC + StandardScaler | MI top 25 | decision_function |
| `eve_suricata.xgb` | XGBoost | MI top 25 | predict_proba |

> **XGBoost is an optional dependency.** If `xgboost` is not installed, the pipeline raises a clear `ImportError` at run time. All other pipelines are unaffected.

---

## Setup

### Option A — Local (Python venv)

**Requirements:** Python 3.10+

```bash
# 1. Clone / navigate to project
cd d:/Program/TA

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt
```

**`requirements.txt`**
```
streamlit>=1.30.0
pandas>=2.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
joblib>=1.3.0
matplotlib>=3.7.0
pytest>=7.4.0
reportlab>=4.0.0
imbalanced-learn>=0.11.0
celery>=5.3.0
redis>=5.0.0
xgboost>=2.0.0
tqdm>=4.65.0
```

### Option B — Docker (full async stack)

**Requirements:** Docker + Docker Compose

```bash
# Start all services (UI + Celery worker + Redis)
docker-compose up --build

# Start in background
docker-compose up --build -d

# Watch worker logs
docker-compose logs -f worker

# Shell into UI container
docker-compose exec ui bash

# Stop all services
docker-compose down
```

The UI will be available at **http://localhost:8501**.

**Data persistence:** mount points are pre-configured in `docker-compose.yml`:
- `storage/datasets/` — place CSVs here **before** starting
- `storage/artifacts/` — experiment outputs persist across restarts
- `storage/experiments.db` — SQLite DB persists across restarts

Set `USE_ASYNC=true` (default in Docker) to route pipeline execution through the Celery worker. Set `USE_ASYNC=false` to run synchronously in the UI process (local dev only).

---

## Running the System

### Streamlit UI (primary)

```bash
streamlit run ui/app.py
```

The app has three pages:

- **Run Experiment** — validate a dataset, select a pipeline, run training, view results, download PDF report
- **Experiment History** — browse all past runs with metrics and re-run capability
- **Environment Info** — Python version, installed packages, storage paths

> Always start Streamlit from the project root with `streamlit run ui/app.py`. Do not navigate into `ui/` first — the `sys.path` setup in `app.py` depends on the file's location.

### Celery async worker (standalone)

```bash
celery -A workers.celery_worker worker --loglevel=info --pool=solo
```

The worker handles the full pipeline lifecycle: parse → run → save artifacts → update DB. It reads `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` from the environment (defaults to `redis://localhost:6379`).

### CLI runner

```bash
# List all pipelines
python run_pipeline.py --list-pipelines

# List pipelines for a specific dataset
python run_pipeline.py --list-pipelines --dataset-type HIKARI2021

# Run a pipeline
python run_pipeline.py \
  --dataset storage/datasets/your_file.csv \
  --dataset-type HIKARI2021 \
  --pipeline hikari2021.rfc_pipeline
```

---

## Running Experiments — Step by Step

1. Place your CSV in `storage/datasets/`
2. Open the Streamlit UI
3. Select dataset type and enter the file path
4. Click **Validate Dataset** — the system checks column count and names against the schema
5. Select a pipeline from the dropdown
6. Click **Run Experiment** — a live progress panel shows each stage:
   - Computing SHA-256 hash
   - Registering in database
   - Parsing CSV
   - Training model
   - Saving artifacts
   - Finalizing record
7. Results appear below: metrics cards, confusion matrix, ROC curve, feature importance, per-class report
8. Click **Download PDF Report** to export

---

## Artifacts

Each experiment saves three files under `storage/artifacts/{experiment_id}/`:

| File | Contents |
|---|---|
| `model.pkl` | Trained sklearn model object (joblib format) |
| `metrics.json` | All numeric metrics + extra_info (ROC, feature importance, learning curve) |
| `metadata.json` | Dataset path, hash, pipeline ID, label mapping, feature names, timestamps |

The database (`storage/experiments.db`) stores summary metrics and paths to artifacts. Full metrics (including ROC curve arrays) live only in `metrics.json`.

---

## Database Schema

Single table: `experiments`

| Column | Type | Notes |
|---|---|---|
| `experiment_id` | TEXT | UUID, primary key |
| `dataset_type` | TEXT | `CICIDS2017`, `HIKARI2021`, or `EVE_SURICATA` |
| `dataset_path` | TEXT | Path to source CSV |
| `dataset_hash` | TEXT | SHA-256 of the CSV file |
| `pipeline_id` | TEXT | Registry key |
| `status` | TEXT | `CREATED`, `RUNNING`, `FINISHED`, `FAILED` |
| `created_at` | TEXT | ISO 8601 |
| `started_at` | TEXT | Set when execution begins |
| `completed_at` | TEXT | Set on finish or failure |
| `accuracy` | REAL | |
| `precision_score` | REAL | |
| `recall` | REAL | |
| `f1_score` | REAL | |
| `metrics_path` | TEXT | Relative path to metrics.json |
| `model_path` | TEXT | Relative path to model.pkl |
| `error_message` | TEXT | Populated on FAILED status |

Schema versioning is managed by `database/migration.py`. Migrations run automatically on `init_db()`.

---

## Adding a New Pipeline

1. Create `pipelines/{dataset}/your_pipeline.py` implementing `BasePipeline`:

```python
from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineInput, PipelineResult

class YourPipeline(BasePipeline):
    def run(self, pipeline_input: PipelineInput) -> PipelineResult:
        ...
        return PipelineResult(accuracy=..., precision=..., recall=...,
                              f1_score=..., confusion_matrix=...,
                              model=..., feature_names=...,
                              label_mapping=..., extra_info=...)

    def get_info(self) -> dict:
        return {
            "paper": "...",
            "algorithm": "...",
            "preprocessing_steps": [...],
            "feature_selection": "...",
            "fixed_params": {...},
        }
```

2. Add one entry to `config/pipeline_registry.py`:

```python
"yourdataset.your_pipeline": {
    "dataset_type": "YOURDATASET",
    "name": "Human-readable name",
    "paper": "Citation",
    "algorithm": "Algorithm name",
    "class": YourPipeline,
},
```

That's it. The UI and CLI pick it up automatically.

---

## Adding a New Dataset

1. Add a schema to `contracts/dataset_schemas.py`:

```python
YOURDATA_SCHEMA = {
    "label_column": "Label",
    "expected_columns": ["col1", "col2", ..., "Label"],
}
DATASET_SCHEMAS["YOURDATA"] = YOURDATA_SCHEMA
```

2. Add at least one pipeline for it (see above).

---

## Tests

```bash
# All tests
pytest tests/ -v

# By layer
pytest tests/test_db.py tests/test_migration.py -v          # database
pytest tests/test_validator.py tests/test_parser.py -v      # dataset layer
pytest tests/test_pipeline_rf.py -v                         # CICIDS2017 pipeline
pytest tests/test_pipeline_hikari.py -v                     # HIKARI2021 RFC pipeline
pytest tests/test_hikari_all_pipelines.py -v                # all 5 new HIKARI pipelines (50 tests)
pytest tests/test_eve_pipeline.py -v                        # EVE/Suricata pipelines
pytest tests/test_experiment_service.py -v                  # orchestrator integration
pytest tests/test_execution_service.py -v                   # execution service
pytest tests/test_artifact_saver.py -v                      # utils
```

**Test strategy:**
- Database tests use `tmp_path` (isolated per-test SQLite files)
- Pipeline tests use synthetic DataFrames generated from schema column lists — no real CSV required
- `test_hikari_all_pipelines.py` is fully parametrized: 10 test functions × 5 pipeline classes = 50 tests
- All random seeds fixed at 42; `test_reproducibility` verifies identical outputs on identical inputs
- No mocked ML models — pipelines run end-to-end on synthetic data

---

## Reproducibility

Every pipeline fixes `random_state=42` for all stochastic components (train/test split, RandomUnderSampler, classifier). Given the same input CSV, the system always produces bit-identical metrics. This is verified by `test_reproducibility` tests in every pipeline test file.

SHA-256 hashing of the input file provides an integrity check — the database records the hash alongside each experiment.

---

## Key Design Decisions

**Fixed hyperparameters.** No user tuning. Every parameter value is locked to what the paper specifies. This enforces fair comparison between runs.

**Stratified splits everywhere.** All train/test splits use `stratify=y` to preserve class distribution, critical for the imbalanced HIKARI2021 dataset.

**RUS placement for KNN.** RandomUnderSampler is applied *after* the train/test split (on train only), which is methodologically correct. The RFC pipeline applies RUS before splitting — this faithfully replicates the original notebook's approach, and the difference is documented.

**`ui/views/` not `ui/pages/`.** Using `ui/pages/` would trigger Streamlit's multipage auto-discovery, adding unwanted sidebar entries. Views live in `ui/views/` and are routed manually via `st.sidebar.radio`.

**`orchestrator/` as the sole DB gateway.** Only `orchestrator/experiment_service.py` imports from `database/`. Pipelines and utils have no database dependency, making them testable in isolation without any DB setup.

**Celery idempotency guard.** The worker checks the experiment status before execution (`acks_late=True` can cause redelivery). If the experiment is already `FINISHED` or `FAILED`, the task is skipped safely.

**EVE/Suricata phase isolation.** All four EVE models call the same `run_phases_1_through_9()` function. Intermediate files are written to a `tempfile.mkdtemp()` directory and cleaned up via a `cleanup()` callable in the `finally` block — even on failure. This keeps the pipeline stateless and prevents disk leaks across runs.

**LinearSVC ROC without predict_proba.** `LinearSVC` has no `predict_proba`. The EVE LSVC pipeline uses `decision_function` scores instead, which are valid inputs for `roc_auc_score` and `roc_curve`.

**XGBoost as a soft dependency.** `eve_xgb_pipeline.py` wraps the `xgboost` import in a `try/except` at module level. If XGBoost is not installed, the class still loads but `run()` raises a descriptive `ImportError`. This avoids breaking the registry import for users who don't need XGBoost.

---

## Project Status

| Layer | Status |
|---|---|
| Dataset schemas (CICIDS2017, HIKARI2021, EVE_SURICATA) | ✅ Complete |
| Database (SQLite + migrations) | ✅ Complete |
| CICIDS2017 pipelines (RF + RFE) | ✅ Complete |
| HIKARI2021 pipelines (RFC, DT, KNN, SVC, NBGC, LR) | ✅ Complete |
| EVE/Suricata pipelines (RFC, DT, LinearSVC, XGBoost) | ✅ Complete |
| EVE/Suricata 11-phase shared preprocessing | ✅ Complete |
| Orchestrator services | ✅ Complete |
| CLI runner | ✅ Complete |
| Streamlit UI (3 views) | ✅ Complete |
| PDF report generation | ✅ Complete |
| Live progress indicators | ✅ Complete |
| Test suite | ✅ Complete |
| Async execution (Celery + Redis) | ✅ Complete |
| Docker containerization | ✅ Complete |
