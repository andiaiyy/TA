"""
Diagnose EVE/Suricata leakage on storage/datasets/eve_100k_fixed.json.

Read-only investigation:
  - Reconstruct the exact X_train that Phase 9/DT consumed (using same Phase 1/2/3/8 chain).
  - Compute Pearson + Spearman correlations between every feature column and Target.
  - Show value distributions per class for selected columns.
  - Single-column classifier ceiling for selected columns.
  - Per-class presence/absence of raw EVE fields for the labeling rule audit.
  - Confirm norm_8 <- which feature_col mapping under the post-fix exclude list.

DOES NOT MODIFY ANY PRODUCTION CODE. DOES NOT WRITE TO DB.
Outputs everything to stdout. Run inside the worker container:
   docker exec -it ids_worker python /app/experiments/diagnose_eve_leakage.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from pipelines.eve_suricata.phases.phase1 import (
    phase1_load_and_label,
    Phase1DiskConfig,
)
from pipelines.eve_suricata.phases.phase2 import phase2_advanced_feature_engineering
from pipelines.eve_suricata.phases.phase3 import (
    phase3_computed_features,
    ensure_numeric_except_raw,
    RAW_SUFFIX,
)
from pipelines.eve_suricata.phases.phase4 import phase4_clean_aggressive
from pipelines.eve_suricata.phases.phase8_modeling_split import (
    phase8_build_model_splits,
    Phase8Config,
    _prepare_drop_plan,
    _apply_modeling_plan,
)

DATASET_NDJSON = Path("/app/storage/datasets/eve_100k_fixed.json")
SEED = 42
np.set_printoptions(suppress=True, precision=6)
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)


def banner(title: str) -> None:
    print()
    print("=" * 88)
    print(title)
    print("=" * 88)


# ---------------------------------------------------------------------------
# STEP 0 — RAW NDJSON SCAN (for Section D and per-field presence/absence)
# ---------------------------------------------------------------------------
def scan_raw_ndjson(path: Path) -> dict:
    """
    Scan every line. For each record:
      - apply Phase 1 labeling rule
      - record presence/absence of top-level fields
      - record presence/absence of nested alert.* and flow.* fields
      - record raw value distributions for pkt_src and event_type per class
    """
    banner("STEP 0: raw NDJSON scan (for Section D — labeling rule audit)")

    fields_top = [
        "timestamp", "src_ip", "dest_ip", "src_port", "dest_port",
        "proto", "event_type", "app_proto", "flow_id", "pkt_src",
        "flow", "alert", "tcp", "http", "dns", "tls", "fileinfo", "smtp",
        "ssh", "stats", "anomaly",
    ]

    presence_by_class = {0: Counter(), 1: Counter()}
    total_by_class = {0: 0, 1: 0}

    pkt_src_per_class = {0: Counter(), 1: Counter()}
    event_type_per_class = {0: Counter(), 1: Counter()}
    alert_category_per_class = {0: Counter(), 1: Counter()}
    alert_severity_per_class = {0: Counter(), 1: Counter()}

    # Track whether alert+severity rule is identical to event_type=="alert"
    has_severity_count = {0: 0, 1: 0}
    is_alert_event_count = {0: 0, 1: 0}
    severity_and_alert_event_count = {0: 0, 1: 0}
    severity_no_alert_event_count = {0: 0, 1: 0}
    alert_event_no_severity_count = {0: 0, 1: 0}

    fp_category = "generic protocol decode"

    with path.open("rb") as fh:
        for raw in fh:
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            alert = obj.get("alert") if isinstance(obj.get("alert"), dict) else None
            cat = ""
            sev = None
            if alert is not None:
                cat = str(alert.get("category", "")).strip().lower()
                sev = alert.get("severity")

            if alert is None:
                tgt = 0
            elif cat == fp_category:
                tgt = 0
            elif sev is not None and "severity" in alert:
                tgt = 1
            else:
                tgt = 0

            total_by_class[tgt] += 1
            for f in fields_top:
                if f in obj and obj[f] is not None:
                    presence_by_class[tgt][f] += 1

            pkt_src_per_class[tgt][str(obj.get("pkt_src", "MISSING"))] += 1
            event_type_per_class[tgt][str(obj.get("event_type", "MISSING"))] += 1
            if alert is not None:
                alert_category_per_class[tgt][str(alert.get("category", "MISSING"))] += 1
                alert_severity_per_class[tgt][str(alert.get("severity", "MISSING"))] += 1

            # rule comparison
            has_sev = (alert is not None) and ("severity" in alert) and (alert.get("severity") is not None)
            is_alert_evt = (str(obj.get("event_type", "")).lower() == "alert")
            if has_sev:
                has_severity_count[tgt] += 1
            if is_alert_evt:
                is_alert_event_count[tgt] += 1
            if has_sev and is_alert_evt:
                severity_and_alert_event_count[tgt] += 1
            if has_sev and not is_alert_evt:
                severity_no_alert_event_count[tgt] += 1
            if is_alert_evt and not has_sev:
                alert_event_no_severity_count[tgt] += 1

    out = {
        "total_by_class": total_by_class,
        "presence_by_class": presence_by_class,
        "pkt_src_per_class": pkt_src_per_class,
        "event_type_per_class": event_type_per_class,
        "alert_category_per_class": alert_category_per_class,
        "alert_severity_per_class": alert_severity_per_class,
        "has_severity_count": has_severity_count,
        "is_alert_event_count": is_alert_event_count,
        "severity_and_alert_event_count": severity_and_alert_event_count,
        "severity_no_alert_event_count": severity_no_alert_event_count,
        "alert_event_no_severity_count": alert_event_no_severity_count,
    }

    print(f"\nTotal benign (Target=0): {total_by_class[0]:,}")
    print(f"Total attack (Target=1): {total_by_class[1]:,}")

    print("\n--- Presence of top-level EVE fields per class ---")
    n0 = max(1, total_by_class[0]); n1 = max(1, total_by_class[1])
    print(f"{'field':<14} {'ben_cnt':>10} {'ben_pct':>8} {'atk_cnt':>10} {'atk_pct':>8}")
    for f in fields_top:
        b = presence_by_class[0].get(f, 0)
        a = presence_by_class[1].get(f, 0)
        print(f"{f:<14} {b:>10,} {b/n0*100:>7.2f}% {a:>10,} {a/n1*100:>7.2f}%")

    print("\n--- pkt_src per class (top 15) ---")
    for cls in (0, 1):
        print(f"  Target={cls}:")
        for v, c in pkt_src_per_class[cls].most_common(15):
            print(f"    {v!s:<60} {c:>10,}")

    print("\n--- event_type per class (top 15) ---")
    for cls in (0, 1):
        print(f"  Target={cls}:")
        for v, c in event_type_per_class[cls].most_common(15):
            print(f"    {v!s:<60} {c:>10,}")

    print("\n--- alert.category per class (top 15) ---")
    for cls in (0, 1):
        print(f"  Target={cls}:")
        for v, c in alert_category_per_class[cls].most_common(15):
            print(f"    {v!s:<60} {c:>10,}")

    print("\n--- alert.severity per class ---")
    for cls in (0, 1):
        print(f"  Target={cls}: {dict(alert_severity_per_class[cls])}")

    print("\n--- Labeling rule comparison (alert+severity vs event_type=='alert') ---")
    print(f"  Records with alert.severity present (=> Target=1 unless FP-cat):")
    print(f"    -> classified Target=0: {has_severity_count[0]:,}")
    print(f"    -> classified Target=1: {has_severity_count[1]:,}")
    print(f"  Records with event_type=='alert':")
    print(f"    -> classified Target=0: {is_alert_event_count[0]:,}")
    print(f"    -> classified Target=1: {is_alert_event_count[1]:,}")
    print(f"  alert.severity present AND event_type=='alert':")
    print(f"    -> Target=0 / Target=1: {severity_and_alert_event_count[0]:,} / {severity_and_alert_event_count[1]:,}")
    print(f"  alert.severity present but event_type != 'alert':")
    print(f"    -> Target=0 / Target=1: {severity_no_alert_event_count[0]:,} / {severity_no_alert_event_count[1]:,}")
    print(f"  event_type=='alert' but no alert.severity:")
    print(f"    -> Target=0 / Target=1: {alert_event_no_severity_count[0]:,} / {alert_event_no_severity_count[1]:,}")

    return out


# ---------------------------------------------------------------------------
# STEP 1 — Re-run Phases 1, 2, 3 deterministically
# ---------------------------------------------------------------------------
def run_phases(dataset_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    banner("STEP 1: re-run Phases 1, 2, 3 with seed=42 (same as DT a2a73cde would have used)")

    tmp = tempfile.mkdtemp(prefix="diag_eve_")
    p1_cfg = Phase1DiskConfig(output_dir=Path(tmp) / "phase1_shards")
    df1, p1_summary = phase1_load_and_label(dataset_path, seed=SEED, disk=p1_cfg)
    print(f"  Phase 1 sample: {df1.shape}  (attack_total={p1_summary['attack_total']:,}, benign_total={p1_summary['benign_total']:,})")
    print(f"  Phase 1 written: attack={p1_summary['attack_written']:,}, benign={p1_summary['benign_written']:,}")

    df2, _ = phase2_advanced_feature_engineering(df1, use_advanced_module=False)
    print(f"  Phase 2 shape: {df2.shape}")
    print(f"  Phase 2 columns: {list(df2.columns)}")

    df3, p3_summary = phase3_computed_features(df2, seed=SEED)
    print(f"  Phase 3 shape: {df3.shape}")
    print(f"  Phase 3 feature_cols_count = {p3_summary['feature_cols_count']}")
    print(f"  Phase 3 blocked = {p3_summary['blocked_feature_cols']}")

    # cleanup
    shutil.rmtree(tmp, ignore_errors=True)
    return df1, df2, df3


# ---------------------------------------------------------------------------
# STEP 2 — Recreate Phase 3's feature_cols sort and norm_k mapping
# ---------------------------------------------------------------------------
def recreate_phase3_feature_cols(df2: pd.DataFrame) -> list[str]:
    banner("STEP 2: recreate Phase 3 feature_cols sort + norm_k mapping (post-fix exclude list)")

    df = df2.copy().drop(columns=[c for c in ["is_malicious"] if c in df2.columns], errors="ignore")
    df = ensure_numeric_except_raw(df, raw_suffix=RAW_SUFFIX)

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    exclude = ("has_alert", "alert_severity", "alert_category", "event_type", "event_type_h")
    blocked = set(["Target"]) | set(["is_malicious"]) | set(exclude)
    feature_cols = sorted([c for c in numeric_cols if c not in blocked])

    print(f"  feature_cols ({len(feature_cols)}, sorted alphabetically):")
    for i, c in enumerate(feature_cols):
        marker = "  <-- norm_{}".format(i) if i < 10 else ""
        print(f"    [{i:2d}] {c}{marker}")

    return feature_cols


# ---------------------------------------------------------------------------
# STEP 3 — Recreate the exact X_train DT consumed
#   Phase 4 -> Phase 8 modeling-plan (drop leak_cols, coerce numeric)
#   Filter to Phase 9-style numeric cols.
#   We DO NOT need to recreate Phase 9 RFE; we want correlations on the FULL
#   post-Phase-8 feature matrix, not the RFE subset. We also compute the
#   subset that matches the metadata.json 25-feature list.
# ---------------------------------------------------------------------------
def build_train_test(df3: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    banner("STEP 3: run Phase 4 + Phase 8 to reconstruct the actual df_train DT saw")

    df4, _ = phase4_clean_aggressive(df3, copy_input=True)
    print(f"  Phase 4 shape: {df4.shape}")

    tmp = tempfile.mkdtemp(prefix="diag_p8_")
    p8_cfg = Phase8Config(
        out_dir=Path(tmp) / "phase8",
        filename_tag="diag",
        seed=SEED,
        phase_8_export_medium=False,
    )
    p8_out = phase8_build_model_splits(df4, p8_cfg)
    df_train = p8_out["df_train"]
    df_test = p8_out["df_test_fair"]
    meta = p8_out["summary"]["meta"]
    print(f"  Phase 8 df_train shape: {df_train.shape}")
    print(f"  Phase 8 df_test shape: {df_test.shape}")
    print(f"  Phase 8 final_columns_count: {meta['drop_strategy']['final_columns_count']}")
    print(f"  Phase 8 drop_cols applied: {meta['drop_strategy']['drop_cols_applied_count']}")
    print(f"  Phase 8 drop_leak_cols: {meta['drop_strategy']['drop_leak_cols']}")
    shutil.rmtree(tmp, ignore_errors=True)
    return df_train, df_test, meta


# ---------------------------------------------------------------------------
# STEP 4 — Section A: correlations on X_train
# ---------------------------------------------------------------------------
def section_a_correlations(df_train: pd.DataFrame, target_col: str = "Target") -> pd.DataFrame:
    banner("SECTION A: Pearson + Spearman correlation between every X_train column and Target")

    y = df_train[target_col].to_numpy()
    feature_cols = [c for c in df_train.columns if c != target_col]
    rows = []
    for c in feature_cols:
        x = df_train[c].to_numpy()
        try:
            pear = float(stats.pearsonr(x, y).statistic) if np.std(x) > 0 else 0.0
        except Exception:
            pear = float("nan")
        try:
            spear = float(stats.spearmanr(x, y).statistic) if np.std(x) > 0 else 0.0
        except Exception:
            spear = float("nan")
        nu = int(pd.Series(x).nunique())
        dt = str(df_train[c].dtype)
        rows.append((c, pear, spear, dt, nu))

    df_corr = pd.DataFrame(rows, columns=["column", "pearson", "spearman", "dtype", "n_unique"])
    df_corr["abs_pearson"] = df_corr["pearson"].abs()
    df_corr = df_corr.sort_values("abs_pearson", ascending=False).reset_index(drop=True)

    print(f"\nTotal feature columns scanned: {len(feature_cols)}")
    print(f"y distribution in df_train: {dict(pd.Series(y).value_counts())}")

    print("\n--- ALL columns sorted by |pearson| desc ---")
    print(df_corr[["column", "pearson", "spearman", "dtype", "n_unique"]].to_string(index=False))

    high = df_corr[df_corr["abs_pearson"] > 0.9].copy()
    print(f"\n--- Columns with |pearson| > 0.9 (n={len(high)}) ---")
    if len(high) > 0:
        print(high[["column", "pearson", "spearman", "dtype", "n_unique"]].to_string(index=False))
    return df_corr


# ---------------------------------------------------------------------------
# STEP 5 — Section C: per-field deep dive
# ---------------------------------------------------------------------------
def section_c_perfield(df_train: pd.DataFrame, columns: list[str]) -> None:
    banner("SECTION C: per-class distribution + single-column classifier ceiling")

    y = df_train["Target"].to_numpy()
    for col in columns:
        if col not in df_train.columns:
            print(f"\n--- {col!r} not in df_train — skipping")
            continue
        x = df_train[col].to_numpy()
        nu = int(pd.Series(x).nunique())
        print(f"\n>>> Column: {col}    dtype={df_train[col].dtype}    n_unique={nu}")

        s0 = pd.Series(x[y == 0])
        s1 = pd.Series(x[y == 1])

        if nu <= 30:
            vc0 = s0.value_counts().sort_index().head(30)
            vc1 = s1.value_counts().sort_index().head(30)
            keys = sorted(set(vc0.index) | set(vc1.index))
            print(f"    {'value':<24} {'cnt_T=0':>10} {'cnt_T=1':>10}")
            for k in keys:
                c0 = int(vc0.get(k, 0))
                c1 = int(vc1.get(k, 0))
                print(f"    {str(k):<24} {c0:>10,} {c1:>10,}")
        else:
            # numeric — print quantiles per class
            def _q(s):
                if len(s) == 0:
                    return [float("nan")] * 5
                return [float(np.quantile(s, q)) for q in (0.0, 0.25, 0.5, 0.75, 1.0)]
            q0 = _q(s0); q1 = _q(s1)
            print(f"    Target=0 quantiles [min, q25, med, q75, max]: {q0}")
            print(f"    Target=1 quantiles [min, q25, med, q75, max]: {q1}")
            print(f"    Target=0 mean={s0.mean():.6g} std={s0.std():.6g}")
            print(f"    Target=1 mean={s1.mean():.6g} std={s1.std():.6g}")

        # Single-column classifier ceiling
        # Best of:
        #   (a) per-value majority-vote rule (for low-cardinality cols)
        #   (b) best monotone threshold (for numeric)
        n = len(y)
        # (a)
        df_xy = pd.DataFrame({"x": x, "y": y})
        per_value_pred = df_xy.groupby("x")["y"].agg(lambda s: int(s.sum() * 2 >= len(s)))
        pred_a = df_xy["x"].map(per_value_pred).to_numpy()
        acc_a = float((pred_a == y).mean())
        # (b) try thresholds at sorted unique values (sampled for speed)
        acc_b = 0.0
        thr_b = float("nan")
        xs = np.sort(np.unique(x))
        if len(xs) > 200:
            xs = xs[np.linspace(0, len(xs) - 1, 200).astype(int)]
        for t in xs:
            pred = (x > t).astype(int)
            acc = max((pred == y).mean(), ((1 - pred) == y).mean())
            if acc > acc_b:
                acc_b = float(acc); thr_b = float(t)

        # Constant baseline
        acc_const = float(max((y == 0).mean(), (y == 1).mean()))

        print(f"    Single-column ceiling: per-value-rule acc={acc_a:.6f}, best-threshold acc={acc_b:.6f} (thr={thr_b:.6g}), const baseline={acc_const:.6f}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    print("DIAGNOSTIC: EVE/Suricata leakage on", DATASET_NDJSON)
    print("Seed:", SEED)

    raw_scan = scan_raw_ndjson(DATASET_NDJSON)

    df1, df2, df3 = run_phases(DATASET_NDJSON)

    feature_cols_after_p3 = recreate_phase3_feature_cols(df2)
    print()
    print("  (Section B note) norm_8 source column (per Phase 3 sort) =", feature_cols_after_p3[8] if len(feature_cols_after_p3) > 8 else "N/A")

    df_train, df_test, p8_meta = build_train_test(df3)

    df_corr = section_a_correlations(df_train, target_col="Target")

    # Section C — per-field deep dive on the requested set
    interact_cols = [c for c in df_train.columns if c.startswith("interact_")]
    target_cols = ["pkt_src", "has_flow", "event_type", "event_type_h"] + interact_cols
    # event_type / event_type_h likely already dropped by Phase 8; that itself is a finding.
    section_c_perfield(df_train, target_cols)

    # Section C — also drill into the highest-correlation columns
    high = df_corr[df_corr["abs_pearson"] > 0.9]["column"].tolist()
    if high:
        banner("SECTION C (extra): per-class distribution for |pearson|>0.9 columns")
        section_c_perfield(df_train, high)

    # also drill into the DT's actual top features
    banner("SECTION C (extra): per-class distribution for DT a2a73cde top features")
    section_c_perfield(df_train, ["norm_8", "bytes_toserver", "interact_0_8", "interact_0_11"])

    # Report on event_type / event_type_h status in df_train (Section B aux)
    banner("EXTRA: Phase 8 drop status for event_type / event_type_h / has_alert / alert_*")
    for c in ("event_type", "event_type_h", "has_alert", "alert_severity", "alert_category"):
        print(f"  {c} in df_train? -> {c in df_train.columns}")

    # confirm norm_8 source
    banner("EXTRA: norm_8 source verification")
    if "norm_8" in df_train.columns and len(feature_cols_after_p3) > 8:
        src = feature_cols_after_p3[8]
        if src in df3.columns:
            x_src = pd.to_numeric(df3[src], errors="coerce").fillna(0).to_numpy()
            denom = float(x_src.max() + 1.0)
            recomputed = x_src / denom
            actual = df3["norm_8"].to_numpy()
            diff = np.abs(actual - recomputed).max() if len(actual) == len(recomputed) else float("nan")
            print(f"  feature_cols_after_p3[8] = {src!r}")
            print(f"  Reconstruction check: max|actual norm_8 - source/(max+1)| = {diff:.8g}")
        else:
            print(f"  feature_cols_after_p3[8] = {src!r} (not in df3 — odd)")

    # Done
    banner("DONE.")


if __name__ == "__main__":
    main()
