"""
EVE/Suricata shared phase runner (Phases 1-9).

Chains phases 1 → 2 → 3 → 4 → 7 → 8 → 9 in sequence, returning
train/test DataFrames and feature sets ready for model training.

All 4 model wrappers (DT, RFC, LSVC, XGB) call this — ensuring
identical preprocessing across all model comparisons.

Rules:
  - No database access
  - No UI imports
  - Phase files in phases/ are imported but NEVER modified
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

# Phase imports — these files are UNTOUCHED copies
from pipelines.eve_suricata.phases.phase1 import (
    phase1_load_and_label,
    Phase1DiskConfig,
)
from pipelines.eve_suricata.phases.phase2 import phase2_advanced_feature_engineering
from pipelines.eve_suricata.phases.phase3 import phase3_computed_features
from pipelines.eve_suricata.phases.phase4 import phase4_clean_aggressive
from pipelines.eve_suricata.phases.phase7_corr import phase7_correlation_analysis, Phase7Config
from pipelines.eve_suricata.phases.phase8_modeling_split import (
    phase8_build_model_splits,
    Phase8Config,
)
from pipelines.eve_suricata.phases.phase9_fs import phase9_feature_selection, Phase9Config


def run_phases_1_through_9(
    dataset_path: str,
    random_state: int = 42,
    artifacts_dir: str | None = None,
) -> dict[str, Any]:
    """
    Execute the 7 preprocessing phases (file IDs 1, 2, 3, 4, 7, 8, 9) for
    an EVE Suricata NDJSON dataset. The numbering gap reflects the modular
    toolkit layout in phases/, where files 5/6/10/11 exist as alternatives
    but are not part of the active 7-phase chain wired into this runner.

    Args:
        dataset_path: Absolute path to EVE Suricata NDJSON file.
        random_state:  Seed for reproducibility.
        artifacts_dir: Directory for intermediate files. A temp dir is created
                       and auto-cleaned on error if None.

    Returns dict with:
        df_train:       pd.DataFrame — Phase 8 training split
        df_test:        pd.DataFrame — Phase 8 test split (df_test_fair)
        feature_sets:   dict — {"MI": [...], "RFE": [...], "PCA": {"n_components": N}}
        pca:            fitted PCA object from Phase 9
        scaler:         fitted StandardScaler from Phase 9
        pca_meta:       dict — PCA diagnostics
        phase_summaries: list[dict] — per-phase row/col counts
        cleanup:        callable — removes temp dir (no-op if artifacts_dir provided)
        work_dir:       str — path to intermediate artifact directory
    """
    if artifacts_dir:
        work_dir = Path(artifacts_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        cleanup = lambda: None
    else:
        tmp = tempfile.mkdtemp(prefix="eve_pipeline_")
        work_dir = Path(tmp)
        cleanup = lambda: shutil.rmtree(tmp, ignore_errors=True)

    phase_summaries: list[dict] = []

    try:
        # ── Phase 1: Load & Label (2-pass, disk-backed) ───────────────────────
        p1_disk = Phase1DiskConfig(output_dir=work_dir / "phase1_shards")
        df_sample, p1_summary = phase1_load_and_label(
            Path(dataset_path),
            seed=random_state,
            disk=p1_disk,
        )
        if df_sample is None or len(df_sample) == 0:
            raise RuntimeError("Phase 1 returned an empty DataFrame")
        phase_summaries.append({"phase": 1, "rows": len(df_sample), "cols": df_sample.shape[1]})

        # ── Phase 2: Feature Engineering (in-memory) ──────────────────────────
        # use_advanced_module=False: skip cbr import that won't be installed
        df2, _p2 = phase2_advanced_feature_engineering(
            df_sample,
            use_advanced_module=False,
        )
        phase_summaries.append({"phase": 2, "rows": len(df2), "cols": df2.shape[1]})

        # ── Phase 3: Computed Features ─────────────────────────────────────────
        df3, _p3 = phase3_computed_features(df2, seed=random_state)
        phase_summaries.append({"phase": 3, "rows": len(df3), "cols": df3.shape[1]})

        # ── Phase 4: Aggressive Cleaning ──────────────────────────────────────
        df4, _p4 = phase4_clean_aggressive(df3, copy_input=True)
        phase_summaries.append({"phase": 4, "rows": len(df4), "cols": df4.shape[1]})

        # ── Phase 7: Correlation Analysis (artifact-only, output not piped) ───
        p7_cfg = Phase7Config(
            target_col="Target",
            out_dir=work_dir / "phase7",
            filename_tag="run",
            sample_seed=random_state,
            force_rebuild=True,
        )
        p7_result = phase7_correlation_analysis(df4, p7_cfg)
        phase_summaries.append({
            "phase": 7,
            "top_corr_features": len(p7_result.get("top_features", [])),
        })

        # ── Phase 8: Train/Test Split ──────────────────────────────────────────
        p8_cfg = Phase8Config(
            out_dir=work_dir / "phase8",
            filename_tag="eve",
            seed=random_state,
            phase_8_export_medium=False,   # no disk export needed; we train sklearn directly
        )
        p8_out = phase8_build_model_splits(df4, p8_cfg)
        df_train = p8_out["df_train"]
        df_test = p8_out["df_test_fair"]   # NOTE: key is df_test_fair, not df_test
        if df_train is None or len(df_train) == 0:
            raise RuntimeError("Phase 8 returned an empty train split")
        phase_summaries.append({
            "phase": 8,
            "train_rows": len(df_train),
            "test_rows": len(df_test) if df_test is not None else 0,
        })

        # ── Phase 9: Feature Selection (MI + RFE + PCA) ───────────────────────
        p9_out = phase9_feature_selection(
            df_train,
            Phase9Config(
                out_dir=work_dir / "phase9",
                filename_tag="eve",
                seed=random_state,
            ),
        )
        feature_sets = p9_out["feature_sets"]
        phase_summaries.append({
            "phase": 9,
            "mi_features": len(feature_sets.get("MI", [])),
            "rfe_features": len(feature_sets.get("RFE", [])),
            "pca_components": feature_sets.get("PCA", {}).get("n_components", 0),
        })

        return {
            "df_train": df_train,
            "df_test": df_test,
            "feature_sets": feature_sets,
            "pca": p9_out.get("pca"),
            "scaler": p9_out.get("scaler"),
            "pca_meta": p9_out.get("pca_meta"),
            "p1_summary": p1_summary,
            "phase_summaries": phase_summaries,
            "cleanup": cleanup,
            "work_dir": str(work_dir),
        }

    except Exception:
        cleanup()
        raise
