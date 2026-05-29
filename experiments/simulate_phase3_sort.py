"""
Simulate Phase 3's feature_cols selection and alphabetical sort
under the new exclude list (event_type + event_type_h added).
Reports what norm_6 (the 7th norm column) is now derived from.

Runs phases 1 and 2 inside the container, then introspects what
ensure_numeric_except_raw + the blocked-set filter produces.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd

from pipelines.eve_suricata.phases.phase1 import phase1_load_and_label, Phase1DiskConfig
from pipelines.eve_suricata.phases.phase2 import phase2_advanced_feature_engineering
from pipelines.eve_suricata.phases.phase3 import (
    ensure_numeric_except_raw,
    RAW_SUFFIX,
)

DATASET = "/app/storage/datasets/eve_100k_fixed.json"

# Run phase 1
import tempfile, shutil
tmp = tempfile.mkdtemp(prefix="sim_p3_")
try:
    p1_cfg = Phase1DiskConfig(output_dir=Path(tmp) / "phase1_shards")
    df1, _ = phase1_load_and_label(Path(DATASET), seed=42, disk=p1_cfg)
    df2, _ = phase2_advanced_feature_engineering(df1, use_advanced_module=False)
    print("Phase 2 columns (input to Phase 3):", list(df2.columns))
    print("Phase 2 shape:", df2.shape)

    # Apply ensure_numeric_except_raw the same way phase3 does
    df = df2.copy()
    leak_cols = ["is_malicious"]
    df = df.drop(columns=[c for c in leak_cols if c in df.columns], errors="ignore")
    df = ensure_numeric_except_raw(df, raw_suffix=RAW_SUFFIX)

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    # --- OLD exclude list (pre-fix) ---
    old_exclude = ("has_alert", "alert_severity", "alert_category")
    old_blocked = set(["Target"]) | set(leak_cols) | set(old_exclude)
    old_feature_cols = sorted([c for c in numeric_cols if c not in old_blocked])

    # --- NEW exclude list (post-fix) ---
    new_exclude = ("has_alert", "alert_severity", "alert_category", "event_type", "event_type_h")
    new_blocked = set(["Target"]) | set(leak_cols) | set(new_exclude)
    new_feature_cols = sorted([c for c in numeric_cols if c not in new_blocked])

    print("\n=== OLD feature_cols (pre-fix) ===")
    for i, c in enumerate(old_feature_cols):
        marker = " <-- norm_6" if i == 6 else ""
        print(f"  [{i:2d}] {c}{marker}")

    print("\n=== NEW feature_cols (post-fix) ===")
    for i, c in enumerate(new_feature_cols):
        marker = " <-- norm_6" if i == 6 else ""
        print(f"  [{i:2d}] {c}{marker}")

    print("\n=== Norm column derivations ===")
    print("OLD: norm_0..norm_9 derived from columns:")
    for k, c in enumerate(old_feature_cols[:10]):
        print(f"   norm_{k} <- {c}")
    print("\nNEW: norm_0..norm_9 derived from columns:")
    for k, c in enumerate(new_feature_cols[:10]):
        print(f"   norm_{k} <- {c}")

    print("\n=== Diff ===")
    old_set = set(old_feature_cols)
    new_set = set(new_feature_cols)
    print("Removed by new fix:", sorted(old_set - new_set))
    print("Added by new fix:  ", sorted(new_set - old_set))

finally:
    shutil.rmtree(tmp, ignore_errors=True)
