from __future__ import annotations

"""
Central run configuration for the CBR/TA Suricata EVE pipeline.

Recommended location:
    src/cbr/config.py

Main idea:
- main.py should only create RunConfig and call run_pipeline(cfg).
- pipeline.py should receive RunConfig and orchestrate the selected apps/phases.
- phase files should read paths/options from RunConfig instead of hardcoding paths.

This config follows the latest large-data decision:
- raw/split/archive data can live on external SSD
- current app processing happens in internal working directory
- pipeline runs one app at a time
- Phase 5/6/7 create rules/schema/policies, not full datasets
- Phase 8 performs the full streaming export and directly creates train/test CSV
- Phase 9+ should use summaries/samples/splits rather than rereading raw data
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


VALID_APPS = ("http", "tls", "dns", "ssh")
VALID_RUN_MODES = ("small_ram", "large_disk_supervised")
VALID_EXPORT_FORMATS = ("csv", "jsonl")
VALID_SPLIT_STRATEGIES = ("group_hash", "time_based", "random_stratified")


@dataclass(slots=True)
class PhaseToggles:
    """Enable/disable pipeline phases without editing pipeline.py."""

    phase1: bool = True
    phase2: bool = True
    phase3: bool = True
    phase4: bool = True
    phase5: bool = True
    phase6: bool = True
    phase7: bool = True
    phase8: bool = True
    phase9: bool = True
    phase10: bool = True
    phase11: bool = True
    phase12: bool = True
    phase13: bool = True
    phase14: bool = True

    def as_dict(self) -> Dict[str, bool]:
        return {
            "phase1": self.phase1,
            "phase2": self.phase2,
            "phase3": self.phase3,
            "phase4": self.phase4,
            "phase5": self.phase5,
            "phase6": self.phase6,
            "phase7": self.phase7,
            "phase8": self.phase8,
            "phase9": self.phase9,
            "phase10": self.phase10,
            "phase11": self.phase11,
            "phase12": self.phase12,
            "phase13": self.phase13,
            "phase14": self.phase14,
        }


@dataclass(slots=True)
class StorageConfig:
    """Storage layout for supervised large-data processing."""

    # Project root is inferred from src/cbr/config.py -> project root.
    # If this file is placed elsewhere, set these paths explicitly in main.py.
    project_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2]
    )

    # External/archive side. For the 800M run, point these to the external SSD.
    external_archive_root: Optional[Path] = None
    split_app_dir: Optional[Path] = None
    archive_output_dir: Optional[Path] = None

    # Internal/active side. Point this to the internal SSD working area.
    internal_work_root: Optional[Path] = None

    # File naming convention from the pre-pipeline split.
    app_file_template: str = "eve_{app}.jsonl"

    # Keep/delete active app files after a run.
    cleanup_internal_after_app: bool = False
    archive_app_outputs_after_app: bool = False

    def __post_init__(self) -> None:
        if self.external_archive_root is None:
            self.external_archive_root = self.project_root / "archive_large"
        if self.split_app_dir is None:
            self.split_app_dir = self.external_archive_root / "split_app"
        if self.archive_output_dir is None:
            self.archive_output_dir = self.external_archive_root / "outputs"
        if self.internal_work_root is None:
            self.internal_work_root = self.project_root / "work_large"

    def app_external_input(self, app: str) -> Path:
        return self.split_app_dir / self.app_file_template.format(app=app)

    def app_work_dir(self, app: str) -> Path:
        return self.internal_work_root / "apps" / app

    def app_work_input(self, app: str) -> Path:
        return self.app_work_dir(app) / self.app_file_template.format(app=app)

    def app_output_dir(self, app: str) -> Path:
        return self.app_work_dir(app) / "outputs"

    def phase_dir(self, app: str, phase_name: str) -> Path:
        return self.app_output_dir(app) / phase_name

    def app_archive_dir(self, app: str) -> Path:
        return self.archive_output_dir / app


@dataclass(slots=True)
class SplitConfig:
    """Train/test split config used during Phase 8 export."""

    # The primary label for modeling/evaluation.
    target_column: str = "Target_refined"

    # Default: avoid splitting the same src_ip+window group across train/test.
    strategy: str = "group_hash"
    train_ratio: float = 0.8
    test_ratio: float = 0.2
    random_seed: int = 42

    # Key used by group_hash split. It should match probing key granularity.
    group_key_columns: List[str] = field(
        default_factory=lambda: ["app", "window_start", "src_ip"]
    )

    # Phase 8 should directly export train/test to avoid a later full reread.
    export_train_test_in_phase8: bool = True

    # Avoid writing a third full feature_ready file unless explicitly needed.
    export_full_feature_ready: bool = False

    def validate(self) -> None:
        if self.strategy not in VALID_SPLIT_STRATEGIES:
            raise ValueError(
                f"Invalid split strategy {self.strategy!r}. "
                f"Valid options: {VALID_SPLIT_STRATEGIES}"
            )
        if not (0.0 < self.train_ratio < 1.0):
            raise ValueError("train_ratio must be between 0 and 1.")
        if not (0.0 < self.test_ratio < 1.0):
            raise ValueError("test_ratio must be between 0 and 1.")
        if abs((self.train_ratio + self.test_ratio) - 1.0) > 1e-9:
            raise ValueError("train_ratio + test_ratio must equal 1.0.")


@dataclass(slots=True)
class ExportConfig:
    """Phase 8 export format and summary/sample controls."""

    # Working output. Keep uncompressed for active training speed.
    format: str = "csv"
    compression: Optional[str] = None  # None, "gzip"

    # Archive compression can be applied after training/evaluation.
    archive_compression: str = "gzip"

    # If one split file becomes too large, pipeline can switch to part files.
    # None means single train.csv/test.csv per app.
    max_rows_per_part: Optional[int] = None
    max_uncompressed_gb_per_part: Optional[float] = None

    # Phase 8 should produce summaries needed by Phase 9 visualization/audit.
    write_export_summary: bool = True
    write_label_distribution: bool = True
    write_feature_availability: bool = True
    write_missing_value_summary: bool = True
    write_feature_group_summary: bool = True

    # Samples produced once during export so Phase 9/10 do not reread full data.
    visualization_sample_rows: int = 300_000
    corr_leak_sample_rows: int = 1_000_000

    # Summary/sample controls used by Phase 8/9/10.
    summary_sample_rows: int = 100_000
    heatmap_max_features: int = 60
    corr_top_k: int = 15

    def validate(self) -> None:
        if self.format not in VALID_EXPORT_FORMATS:
            raise ValueError(
                f"Invalid export format {self.format!r}. "
                f"Valid options: {VALID_EXPORT_FORMATS}"
            )
        if self.compression not in (None, "gzip"):
            raise ValueError("compression must be None or 'gzip'.")
        if self.archive_compression not in ("gzip",):
            raise ValueError("archive_compression currently supports only 'gzip'.")


@dataclass(slots=True)
class ProbingConfig:
    """Phase 3 probing and Phase 4 refinement settings."""

    window_minutes: int = 5

    # Safety: never use IP-only relabeling.
    ip_only_relabeling_enabled: bool = False

    # Conservative refinement thresholds, calculated per app from Phase 3 stats.
    same_window_probe_percentile: float = 90.0
    near_window_probe_percentile: float = 95.0
    extreme_probe_percentile: float = 99.0
    near_window_radius: int = 1

    # Guard against the old failure mode where almost all benign became malicious.
    max_benign_conversion_pct: float = 5.0
    stop_if_conversion_exceeds_limit: bool = True

    # Fix 1: enforce max_benign_conversion_pct at ROW level during Phase 8 export.
    # Phase 4 keys are conservative, but Phase 8 used to propagate each (src_ip,
    # window) key to EVERY no-alert row in that window, so a few high-volume
    # windows could flip the majority of benign rows to attack. When enabled,
    # Phase 8 caps the total no-alert -> attack conversions to
    # max_benign_conversion_pct of all no-alert rows, allocating the budget to
    # the strongest-evidence keys first. Set False to restore legacy behavior.
    enforce_row_level_conversion_cap: bool = True

    # No-alert extreme probing without alert association is suspicious only by default.
    extreme_probe_changes_target: bool = False

    def validate(self) -> None:
        if self.window_minutes <= 0:
            raise ValueError("window_minutes must be positive.")
        if self.ip_only_relabeling_enabled:
            raise ValueError(
                "IP-only relabeling is disabled by design. "
                "Do not set ip_only_relabeling_enabled=True."
            )
        for name in (
            "same_window_probe_percentile",
            "near_window_probe_percentile",
            "extreme_probe_percentile",
        ):
            value = getattr(self, name)
            if not (0.0 <= value <= 100.0):
                raise ValueError(f"{name} must be between 0 and 100.")
        if self.near_window_radius < 0:
            raise ValueError("near_window_radius must be >= 0.")
        if not (0.0 <= self.max_benign_conversion_pct <= 100.0):
            raise ValueError("max_benign_conversion_pct must be between 0 and 100.")


@dataclass(slots=True)
class ModelingConfig:
    """Phase 12-14 modeling settings.

    The full dataset is generated in Phase 8. The chosen models normally require
    an in-memory matrix, so Phase 13 may use a representative modeling subset/cache
    if full train.csv exceeds available RAM.
    """

    methods: List[str] = field(default_factory=lambda: ["MI", "RFE", "PCA"])
    models: List[str] = field(default_factory=lambda: ["DT", "RFC", "LSVC", "XGB"])

    # Feature selection uses train only and outputs selected_features.json, not a large dataset.
    # Serious-run policy: 500k balanced sample = 250k benign + 250k attack.
    fs_sample_rows: int = 500_000
    fs_sampling_strategy: str = "balanced"
    fs_per_class_rows: int = 250_000
    fs_top_k: int = 30
    mi_max_rows: int = 50_000
    rfe_max_rows: int = 150_000
    pca_max_rows: int = 300_000
    read_chunksize: int = 100_000
    seed: int = 42

    # Controlled modeling subset/cache from train split, if full training is infeasible.
    # Serious-run training policy: 10M balanced sample = 5M benign + 5M attack.
    allow_modeling_subset: bool = True
    modeling_train_rows: int = 10_000_000
    modeling_train_sampling_strategy: str = "balanced"
    modeling_train_per_class_rows: int = 5_000_000

    # Phase 13 evaluation policy:
    # - primary: natural holdout sample, 2M-5M rows, original class ratio
    # - secondary: balanced holdout sample, 2M rows = 1M benign + 1M attack
    # Compatibility note: current phase13_train.py still reads modeling_test_rows only.
    # Until Phase 13 is patched for dual holdout, modeling_test_rows maps to balanced_test_rows.
    modeling_test_rows: int = 2_000_000
    modeling_sampling_strategy: str = "balanced"
    modeling_natural_test_min_rows: int = 2_000_000
    modeling_natural_test_max_rows: int = 5_000_000
    modeling_balanced_test_rows: int = 2_000_000
    modeling_balanced_test_per_class_rows: int = 1_000_000

    # Dtypes for RAM-aware training cache.
    numeric_dtype: str = "float32"
    target_dtype: str = "int8"

    # Temporary cache is not for archive/publication.
    create_temporary_training_cache: bool = False
    cleanup_training_cache_after_run: bool = True

    # Evaluation can stream/chunk test if full test is too large.
    evaluation_chunk_rows: int = 250_000

    # Phase 13 training defaults.
    cv_folds: int = 2
    blas_thread_limit: int = 1
    save_fitted_models: bool = False
    pca_default_n_components: int = 10

    rfc_estimators: int = 100
    rfc_n_jobs: int = 8
    rfc_max_depth: Optional[int] = 16
    rfc_min_samples_leaf: int = 2

    lsvc_c: float = 1.0
    lsvc_max_iter: int = 5_000

    xgb_n_estimators: int = 150
    xgb_max_depth: int = 6
    xgb_learning_rate: float = 0.1
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_lambda: float = 1.0
    xgb_n_jobs: int = 8
    xgb_tree_method: str = "hist"
    xgb_device: str = "cpu"
    xgb_eval_metric: str = "logloss"


@dataclass(slots=True)
class RunConfig:
    """Top-level configuration passed from main.py to pipeline.py."""

    run_mode: str = "large_disk_supervised"
    selected_apps: List[str] = field(default_factory=lambda: ["http", "tls", "dns", "ssh"])

    phases: PhaseToggles = field(default_factory=PhaseToggles)
    storage: StorageConfig = field(default_factory=StorageConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    probing: ProbingConfig = field(default_factory=ProbingConfig)
    modeling: ModelingConfig = field(default_factory=ModelingConfig)

    # Phase 1/2 can be skipped if pre-pipeline summary already covers them.
    use_prepipeline_summary_for_phase1: bool = True
    use_prepipeline_summary_for_phase2: bool = True
    prepipeline_summary_path: Optional[Path] = None

    # General execution.
    copy_app_to_internal_before_run: bool = False
    require_app_input_exists: bool = True
    verbose: bool = True

    # Console heartbeat / small previews.
    phase_progress_every: int = 100_000
    feature_preview_rows: int = 200

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.run_mode not in VALID_RUN_MODES:
            raise ValueError(f"Invalid run_mode {self.run_mode!r}. Valid options: {VALID_RUN_MODES}")

        normalized_apps = []
        for app in self.selected_apps:
            app_l = str(app).lower().strip()
            if app_l not in VALID_APPS:
                raise ValueError(f"Invalid app {app!r}. Valid options: {VALID_APPS}")
            normalized_apps.append(app_l)
        self.selected_apps = normalized_apps

        self.split.validate()
        self.export.validate()
        self.probing.validate()

    def enabled_phases(self) -> Dict[str, bool]:
        return self.phases.as_dict()

    def app_external_input(self, app: str) -> Path:
        return self.storage.app_external_input(app)

    def app_work_input(self, app: str) -> Path:
        return self.storage.app_work_input(app)

    def app_work_dir(self, app: str) -> Path:
        return self.storage.app_work_dir(app)

    def app_output_dir(self, app: str) -> Path:
        return self.storage.app_output_dir(app)

    def phase_dir(self, app: str, phase_name: str) -> Path:
        return self.storage.phase_dir(app, phase_name)

    def ensure_base_dirs(self) -> None:
        self.storage.internal_work_root.mkdir(parents=True, exist_ok=True)
        self.storage.external_archive_root.mkdir(parents=True, exist_ok=True)
        self.storage.split_app_dir.mkdir(parents=True, exist_ok=True)
        self.storage.archive_output_dir.mkdir(parents=True, exist_ok=True)

    def ensure_app_dirs(self, app: str) -> None:
        self.app_work_dir(app).mkdir(parents=True, exist_ok=True)
        self.app_output_dir(app).mkdir(parents=True, exist_ok=True)
        self.storage.app_archive_dir(app).mkdir(parents=True, exist_ok=True)

    def describe(self) -> str:
        phases = ", ".join(
            f"{name}={'ON' if enabled else 'OFF'}"
            for name, enabled in self.enabled_phases().items()
        )
        return (
            f"RunConfig(run_mode={self.run_mode}, apps={self.selected_apps}, "
            f"target={self.split.target_column}, split={self.split.strategy}, "
            f"export={self.export.format}, phases=[{phases}])"
        )


def create_default_large_config() -> RunConfig:
    """
    Single source of truth for one-click pipeline runs.

    Edit ONLY this function for normal runs.

    For your current test data, expected files are:
        data/eve_sample_10000000_jsonl/eve_http.jsonl
        data/eve_sample_10000000_jsonl/split_summary.json

    Normal command:
        python src/main.py
    """

    project_root = Path(__file__).resolve().parents[2]

    # ========================================================
    # EDIT HERE FOR EACH RUN
    # ========================================================

    selected_apps = ["http","tls"]

    split_app_dir = project_root / "data" / "eve_json"
    prepipeline_summary = split_app_dir / "split_summary.json"

    internal_work_root = project_root / "work_test"
    archive_output_dir = project_root / "outputs_test"

    # Serious-run sampling policy.
    # Phase 12 FS: 500k balanced = 250k benign + 250k attack.
    # Phase 13 train: 10M balanced = 5M benign + 5M attack.
    # Phase 13 primary test: 2M-5M natural distribution.
    # Phase 13 secondary test: 2M balanced = 1M benign + 1M attack.
    visualization_sample_rows = 300_000
    corr_leak_sample_rows = 1_000_000

    fs_sample_rows = 500_000
    fs_per_class_rows = 250_000

    modeling_train_rows = 10_000_000
    modeling_train_per_class_rows = 5_000_000

    modeling_natural_test_min_rows = 2_000_000
    modeling_natural_test_max_rows = 5_000_000
    modeling_balanced_test_rows = 2_000_000
    modeling_balanced_test_per_class_rows = 1_000_000

    # Current Phase 13 compatibility: until dual natural+balanced holdout is patched,
    # modeling_test_rows is the balanced holdout size used by current phase13_train.py.
    modeling_test_rows = modeling_balanced_test_rows

    # Toggle phases here.
    phases = PhaseToggles(
        phase1=True,
        phase2=True,
        phase3=True,
        phase4=True,
        phase5=True,
        phase6=True,
        phase7=True,
        phase8=True,
        phase9=True,
        phase10=True,
        phase11=True,
        phase12=True,
        phase13=True,
        phase14=True,
    )

    # ========================================================
    # DO NOT EDIT BELOW UNLESS CHANGING PIPELINE POLICY
    # ========================================================

    return RunConfig(
        run_mode="large_disk_supervised",
        selected_apps=selected_apps,
        phases=phases,
        storage=StorageConfig(
            project_root=project_root,
            external_archive_root=project_root,
            split_app_dir=split_app_dir,
            archive_output_dir=archive_output_dir,
            internal_work_root=internal_work_root,
            app_file_template="eve_{app}.jsonl",
            cleanup_internal_after_app=False,
            archive_app_outputs_after_app=False,
        ),
        split=SplitConfig(
            target_column="Target_refined",
            strategy="group_hash",
            train_ratio=0.8,
            test_ratio=0.2,
            random_seed=42,
            group_key_columns=["app", "window_start", "src_ip"],
            export_train_test_in_phase8=True,
            export_full_feature_ready=False,
        ),
        export=ExportConfig(
            format="csv",
            compression=None,
            archive_compression="gzip",
            visualization_sample_rows=visualization_sample_rows,
            corr_leak_sample_rows=corr_leak_sample_rows,
            summary_sample_rows=100_000,
            heatmap_max_features=60,
            corr_top_k=15,
        ),
        probing=ProbingConfig(
            window_minutes=5,
            ip_only_relabeling_enabled=False,
            same_window_probe_percentile=90.0,
            near_window_probe_percentile=95.0,
            extreme_probe_percentile=99.0,
            near_window_radius=1,
            max_benign_conversion_pct=5.0,
            stop_if_conversion_exceeds_limit=True,
            extreme_probe_changes_target=False,
            enforce_row_level_conversion_cap=True,
        ),
        modeling=ModelingConfig(
            methods=["MI", "RFE", "PCA"],
            models=["DT", "RFC", "LSVC", "XGB"],
            fs_sample_rows=fs_sample_rows,
            fs_sampling_strategy="balanced",
            fs_per_class_rows=fs_per_class_rows,
            fs_top_k=30,
            mi_max_rows=50_000,
            rfe_max_rows=150_000,
            pca_max_rows=300_000,
            read_chunksize=100_000,
            seed=42,
            allow_modeling_subset=True,
            modeling_train_rows=modeling_train_rows,
            modeling_train_sampling_strategy="balanced",
            modeling_train_per_class_rows=modeling_train_per_class_rows,
            modeling_test_rows=modeling_test_rows,
            modeling_sampling_strategy="balanced",
            modeling_natural_test_min_rows=modeling_natural_test_min_rows,
            modeling_natural_test_max_rows=modeling_natural_test_max_rows,
            modeling_balanced_test_rows=modeling_balanced_test_rows,
            modeling_balanced_test_per_class_rows=modeling_balanced_test_per_class_rows,
            create_temporary_training_cache=False,
            cleanup_training_cache_after_run=True,
            evaluation_chunk_rows=250_000,
            cv_folds=2,
            blas_thread_limit=1,
            save_fitted_models=False,
            pca_default_n_components=10,
            rfc_estimators=100,
            rfc_n_jobs=8,
            rfc_max_depth=16,
            rfc_min_samples_leaf=2,
            lsvc_c=1.0,
            lsvc_max_iter=5_000,
            xgb_n_estimators=150,
            xgb_max_depth=6,
            xgb_learning_rate=0.1,
            xgb_subsample=0.8,
            xgb_colsample_bytree=0.8,
            xgb_reg_lambda=1.0,
            xgb_n_jobs=8,
            xgb_tree_method="hist",
            xgb_device="cpu",
            xgb_eval_metric="logloss",
        ),
        use_prepipeline_summary_for_phase1=True,
        use_prepipeline_summary_for_phase2=True,
        prepipeline_summary_path=prepipeline_summary,
        copy_app_to_internal_before_run=False,
        require_app_input_exists=True,
        verbose=True,
        phase_progress_every=100_000,
        feature_preview_rows=200,
    )
