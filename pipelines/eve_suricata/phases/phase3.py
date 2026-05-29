# src/cbr/phases/phase3.py
from __future__ import annotations

import gc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, List, Tuple, Dict

import numpy as np
import pandas as pd
from tqdm import tqdm


RAW_SUFFIX = "_raw"


# =============================================================================
# Helpers (existing, unchanged)
# =============================================================================
def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


def _stable_hash_series(s: pd.Series, mod: int = 2**31 - 1) -> pd.Series:
    s = s.astype("string").fillna("unknown")
    h = pd.util.hash_pandas_object(s, index=False).astype("uint64")
    return (h % np.uint64(mod)).astype("int64")


def ensure_numeric_except_raw(df_: pd.DataFrame, *, raw_suffix: str = RAW_SUFFIX) -> pd.DataFrame:
    """
    Convert any non-numeric columns (except Target and *_raw) into numeric.
    Keeps *_raw as strings for Phase 6 plots.
    """
    out = df_
    for col in out.columns:
        if col == "Target" or str(col).endswith(raw_suffix):
            continue

        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = _to_numeric_safe(out[col])
            continue

        num_try = pd.to_numeric(out[col], errors="coerce")
        ratio = float(num_try.notna().mean()) if len(num_try) else 0.0
        if ratio >= 0.98:
            out[col] = _to_numeric_safe(out[col])
        else:
            out[col] = _stable_hash_series(out[col])

    if "Target" in out.columns:
        out["Target"] = _to_numeric_safe(out["Target"]).astype(int)

    return out


# =============================================================================
# Phase 3 (IN-MEMORY) - existing behavior
# =============================================================================
def phase3_computed_features(
    df_in: pd.DataFrame,
    *,
    n_selected: int = 15,
    max_interactions: int = 20,
    n_norm: int = 10,
    raw_suffix: str = RAW_SUFFIX,
    leak_cols: Iterable[str] = ("is_malicious",),
    # IMPORTANT: default exclude leakage-prone cols (Target derived from alert/severity in Phase 1).
    # pkt_src / app_proto / flow_id / proto are categorical Phase-1 outputs hash-encoded by Phase 2
    # whose distributions differ systematically between alert-records and flow-records, so any
    # interaction/norm/row-stat built from them leaks Target. Must be excluded here too — Phase 8/9
    # drops them but only AFTER Phase 3 has already baked them into derived features.
    exclude_from_features: Iterable[str] = (
        "has_alert", "alert_severity", "alert_category", "event_type", "event_type_h",
        "pkt_src", "app_proto", "flow_id", "proto",
    ),
    thr_sample_rows: int = 50_000,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict]:
    """
    Phase 3 (in-memory):
    - Ensure all non-raw columns numeric (hash for objects)
    - Keep *_raw columns intact
    - Add interaction features, row stats, normalization, ratios, binary indicators
    """
    print("\n" + "🟠 " + "=" * 76)
    print("PHASE 3: ADVANCED COMPUTED FEATURES (NaN-SAFE, IN-MEMORY)")
    print("🟠 " + "=" * 76 + "\n")

    t0 = datetime.now()
    if df_in is None or len(df_in) == 0:
        raise ValueError("Phase 3 received empty df_in")

    df = df_in.copy()

    # Drop leak cols if present
    leak_cols = list(leak_cols)
    if leak_cols:
        df = df.drop(columns=[c for c in leak_cols if c in df.columns], errors="ignore")

    if "Target" not in df.columns:
        raise RuntimeError("Target column missing in Phase 3 input. Fix Phase 1/2.")

    # Ensure numeric except *_raw
    df = ensure_numeric_except_raw(df, raw_suffix=raw_suffix)

    # Build feature list: numeric columns except Target, leak, exclude
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    blocked = set(["Target"]) | set(leak_cols) | set(exclude_from_features)
    feature_cols = [c for c in numeric_cols if c not in blocked]

    # Stabilize ordering
    feature_cols = sorted(feature_cols)
    if len(feature_cols) == 0:
        raise RuntimeError("No numeric feature columns found after exclusions.")

    selected_features = feature_cols[: min(n_selected, len(feature_cols))]

    # Plan interaction pairs by index positions within selected_features
    interaction_pairs = []
    for i in range(len(selected_features)):
        for j in range(i + 1, len(selected_features)):
            interaction_pairs.append((i, j))
            if len(interaction_pairs) >= max_interactions:
                break
        if len(interaction_pairs) >= max_interactions:
            break

    # Matrix for row-stats
    fmat = df[feature_cols]

    # Interaction features
    for (i, j) in interaction_pairs:
        col1 = selected_features[i]
        col2 = selected_features[j]
        df[f"interact_{i}_{j}"] = (df[col1] * df[col2]).replace([np.inf, -np.inf], 0).fillna(0)

    # Row-wise stats
    df["row_mean"] = fmat.mean(axis=1).replace([np.inf, -np.inf], 0).fillna(0)
    df["row_std"] = fmat.std(axis=1).replace([np.inf, -np.inf], 0).fillna(0)
    df["row_max"] = fmat.max(axis=1).replace([np.inf, -np.inf], 0).fillna(0)
    df["row_min"] = fmat.min(axis=1).replace([np.inf, -np.inf], 0).fillna(0)
    df["row_sum"] = fmat.sum(axis=1).replace([np.inf, -np.inf], 0).fillna(0)
    df["row_nonzero"] = (fmat != 0).sum(axis=1).astype(int)

    # Normalization (global max per feature)
    for k, col in enumerate(feature_cols[: min(n_norm, len(feature_cols))]):
        denom = float(_to_numeric_safe(df[col]).max() + 1.0)
        df[f"norm_{k}"] = (_to_numeric_safe(df[col]) / denom).replace([np.inf, -np.inf], 0).fillna(0) if denom > 0 else 0

    # Ratios
    df["ratio_max_to_min"] = (df["row_max"] / df["row_min"].replace(0, 1)).replace([np.inf, -np.inf], 0).fillna(0)
    df["ratio_sum_to_count"] = (df["row_sum"] / df["row_nonzero"].replace(0, 1)).replace([np.inf, -np.inf], 0).fillna(0)

    # Binary indicators (threshold from sample)
    rng = np.random.default_rng(seed)
    n = len(df)
    if n > 0:
        sample_n = min(thr_sample_rows, n)
        idx = rng.choice(n, size=sample_n, replace=False) if sample_n < n else np.arange(n)
        arr = df.iloc[idx][feature_cols].to_numpy(copy=False)
        thr_high = float(arr.mean() + arr.std()) if arr.size else 0.0
    else:
        thr_high = 0.0

    df["has_high_values"] = (df["row_max"] > thr_high).astype(int)

    thr_low_var = float(df["row_std"].quantile(0.25)) if len(df) else 0.0
    df["has_low_variance"] = (df["row_std"] < thr_low_var).astype(int)

    denom_sparse = float(len(feature_cols)) if len(feature_cols) else 1.0
    df["is_sparse"] = ((df["row_nonzero"] / denom_sparse) < 0.3).astype(int)

    # Final cleanup: numeric only; raw stays string
    for col in df.select_dtypes(include=[np.number]).columns:
        df[col] = df[col].replace([np.inf, -np.inf], 0).fillna(0)

    for col in df.columns:
        if str(col).endswith(raw_suffix):
            df[col] = df[col].astype("string").fillna("unknown")

    # Ensure Target int
    df["Target"] = _to_numeric_safe(df["Target"]).astype(int)

    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 3,
        "mode": "in_memory",
        "input_shape": [int(df_in.shape[0]), int(df_in.shape[1])],
        "output_shape": [int(df.shape[0]), int(df.shape[1])],
        "feature_cols_count": int(len(feature_cols)),
        "selected_features_count": int(len(selected_features)),
        "interaction_pairs_count": int(len(interaction_pairs)),
        "n_norm": int(min(n_norm, len(feature_cols))),
        "thr_high_sample_rows": int(min(thr_sample_rows, len(df))),
        "thr_high": float(thr_high),
        "thr_low_var": float(thr_low_var),
        "seconds": float(elapsed),
        "blocked_feature_cols": sorted(list(set(exclude_from_features))),
        "note": (
            "Phase 3 operates fully in-memory. "
            "Default excludes has_alert/alert_* from feature columns to reduce leakage."
        ),
    }

    print("✅ PHASE 3 COMPLETE")
    print(f"   df_phase3: {df.shape}")
    print(f"   Features: {len(feature_cols)} | Interactions: {len(interaction_pairs)} | Norm: {summary['n_norm']}")
    print(f"   Time: {elapsed/60:.2f} minutes\n")

    gc.collect()
    return df, summary


# =============================================================================
# Phase 3 (SHARDED) - for Parquet shards
# =============================================================================
def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(max(0, n))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} B"


@dataclass(frozen=True)
class Phase3ShardConfig:
    input_dir: Path                      # expects input_dir/attacks + input_dir/benign with part-*.parquet
    out_dir: Path                        # writes out_dir/attacks + out_dir/benign
    write_format: str = "parquet"        # "parquet" or "csv" (csv -> csv.gz)
    parquet_engine: Optional[str] = "fastparquet"
    parquet_compression: Optional[str] = "snappy"
    return_df_sample: int = 200_000
    include_attacks: bool = True
    include_benign: bool = True

    # pass1 sampling for thresholds (approx; keeps memory small)
    thr_sample_rows_per_shard: int = 2000
    thr_rowstd_sample_max: int = 200_000


def _iter_shards(root: Path, *, include_attacks: bool, include_benign: bool) -> List[Path]:
    root = Path(root)
    files: List[Path] = []
    if include_attacks:
        files += sorted((root / "attacks").glob("part-*.parquet"))
        files += sorted((root / "attacks").glob("part-*.csv.gz"))
    if include_benign:
        files += sorted((root / "benign").glob("part-*.parquet"))
        files += sorted((root / "benign").glob("part-*.csv.gz"))
    return files


def _read_shard(path: Path, *, parquet_engine: Optional[str]) -> pd.DataFrame:
    if path.suffix == ".parquet":
        kwargs = {}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        return pd.read_parquet(path, **kwargs)
    return pd.read_csv(path)


def _write_shard(
    df: pd.DataFrame,
    out_path: Path,
    *,
    write_format: str,
    parquet_engine: Optional[str],
    parquet_compression: Optional[str],
) -> int:
    if write_format == "parquet":
        kwargs = {}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        if parquet_compression:
            kwargs["compression"] = parquet_compression
        try:
            df.to_parquet(out_path, index=False, **kwargs)
        except Exception:
            kwargs.pop("compression", None)
            df.to_parquet(out_path, index=False, **kwargs)
    else:
        df.to_csv(out_path, index=False, compression="gzip")
    return int(out_path.stat().st_size)


class _RunningMoments:
    """Streaming mean/variance for scalar values (flattened feature matrix sample)."""
    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.M2 = 0.0

    def update_batch(self, arr: np.ndarray) -> None:
        a = np.asarray(arr, dtype=np.float64).ravel()
        if a.size == 0:
            return
        # Replace NaN/Inf with 0 to match pipeline semantics
        a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)

        nb = int(a.size)
        mb = float(a.mean())
        vb = float(a.var(ddof=0))  # population var
        if nb <= 0:
            return

        if self.n == 0:
            self.n = nb
            self.mean = mb
            self.M2 = vb * nb
            return

        n1 = self.n
        n2 = nb
        delta = mb - self.mean
        n = n1 + n2
        self.mean = self.mean + delta * (n2 / n)
        self.M2 = self.M2 + (vb * n2) + (delta * delta) * (n1 * n2 / n)
        self.n = n

    def std(self) -> float:
        if self.n <= 0:
            return 0.0
        var = self.M2 / self.n
        return float(np.sqrt(max(0.0, var)))


def phase3_computed_features_sharded(
    *,
    cfg: Phase3ShardConfig,
    n_selected: int = 15,
    max_interactions: int = 20,
    n_norm: int = 10,
    raw_suffix: str = RAW_SUFFIX,
    leak_cols: Iterable[str] = ("is_malicious",),
    # Same leak surface as the in-memory variant — see comment on phase3_computed_features.
    exclude_from_features: Iterable[str] = (
        "has_alert", "alert_severity", "alert_category", "event_type", "event_type_h",
        "pkt_src", "app_proto", "flow_id", "proto",
    ),
    seed: int = 42,
) -> tuple[pd.DataFrame, dict]:
    """
    Sharded Phase 3:
    - PASS 1: derive global-ish thresholds (thr_high, thr_low_var) + global max for norm columns (approx, shard-safe)
    - PASS 2: process each shard and write outputs
    - Returns only df_sample in RAM
    """
    print("\n" + "🟠 " + "=" * 76)
    print("PHASE 3: ADVANCED COMPUTED FEATURES (SHARDED, DISK-BACKED)")
    print("🟠 " + "=" * 76 + "\n")

    t0 = datetime.now()
    in_dir = Path(cfg.input_dir)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shard_files = _iter_shards(in_dir, include_attacks=cfg.include_attacks, include_benign=cfg.include_benign)
    if not shard_files:
        raise RuntimeError(f"No input shards found under: {in_dir}")

    # output structure
    out_attacks = out_dir / "attacks"
    out_benign = out_dir / "benign"
    out_attacks.mkdir(parents=True, exist_ok=True)
    out_benign.mkdir(parents=True, exist_ok=True)

    leak_cols_list = list(leak_cols)
    exclude_list = list(exclude_from_features)
    blocked = set(["Target"]) | set(leak_cols_list) | set(exclude_list)

    # === PASS 0: determine canonical columns from first shard (lightweight) ===
    df0 = _read_shard(shard_files[0], parquet_engine=cfg.parquet_engine)
    if df0 is None or len(df0) == 0:
        raise RuntimeError(f"First shard is empty: {shard_files[0]}")
    if "Target" not in df0.columns:
        raise RuntimeError("Target missing in Phase 3 sharded input. Fix Phase 1/2 output.")

    # Build canonical columns = union-like baseline from first shard
    canonical_cols = list(df0.columns)
    del df0
    gc.collect()

    # Canonical feature columns: all non-raw, non-blocked columns.
    # We treat them as numeric after ensure_numeric_except_raw (hashes objects).
    feature_cols = sorted([c for c in canonical_cols if (c not in blocked and not str(c).endswith(raw_suffix))])

    if len(feature_cols) == 0:
        raise RuntimeError("No feature columns found (canonical). Check Phase 2 output schema.")

    # Interaction plan (same as in-memory)
    selected_features = feature_cols[: min(n_selected, len(feature_cols))]
    interaction_pairs: List[Tuple[int, int]] = []
    for i in range(len(selected_features)):
        for j in range(i + 1, len(selected_features)):
            interaction_pairs.append((i, j))
            if len(interaction_pairs) >= max_interactions:
                break
        if len(interaction_pairs) >= max_interactions:
            break

    # PASS 1 stats:
    # - global max for first n_norm features (approx across shards)
    norm_cols = feature_cols[: min(n_norm, len(feature_cols))]
    global_max: Dict[str, float] = {c: 0.0 for c in norm_cols}

    # - thr_high via streaming mean+std over sampled feature-matrix values
    moments = _RunningMoments()

    # - thr_low_var via sampled row_std values (approx quantile)
    rowstd_samples: List[float] = []
    rng_global = np.random.default_rng(seed)

    print("🧮 PASS 1 (stats): computing global max (norm) + thresholds (thr_high, thr_low_var)...")
    pbar1 = tqdm(shard_files, desc="PHASE 3 pass1", unit="shard", dynamic_ncols=True)

    for idx_fp, fp in enumerate(pbar1):
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or len(df) == 0:
            continue

        # align to canonical: add missing cols as 0/unknown, drop extras (optional)
        for c in canonical_cols:
            if c not in df.columns:
                df[c] = "unknown" if str(c).endswith(raw_suffix) else 0
        df = df[canonical_cols]

        # drop leak cols
        if leak_cols_list:
            df = df.drop(columns=[c for c in leak_cols_list if c in df.columns], errors="ignore")

        # ensure numeric except raw
        df = ensure_numeric_except_raw(df, raw_suffix=raw_suffix)

        # ensure feature cols exist
        for c in feature_cols:
            if c not in df.columns:
                df[c] = 0

        # update global max for norm cols
        for c in norm_cols:
            try:
                m = float(_to_numeric_safe(df[c]).max())
            except Exception:
                m = 0.0
            if m > global_max[c]:
                global_max[c] = m

        # sample rows for thresholds
        n = len(df)
        s = min(cfg.thr_sample_rows_per_shard, n)
        if s > 0:
            # deterministic per-shard RNG
            rng = np.random.default_rng(seed + idx_fp)
            take_idx = rng.choice(n, size=s, replace=False) if s < n else np.arange(n)

            sub = df.iloc[take_idx][feature_cols].to_numpy(copy=False)
            moments.update_batch(sub)

            # sample row_std for quantile approx
            sub_arr = np.nan_to_num(sub.astype(np.float64, copy=False), nan=0.0, posinf=0.0, neginf=0.0)
            rs = sub_arr.std(axis=1)
            # reservoir-ish keep under cap
            for v in rs:
                if len(rowstd_samples) < cfg.thr_rowstd_sample_max:
                    rowstd_samples.append(float(v))
                else:
                    j = int(rng_global.integers(0, cfg.thr_rowstd_sample_max))
                    rowstd_samples[j] = float(v)

        pbar1.set_postfix({
            "thr_mean": f"{moments.mean:.4f}",
            "thr_std": f"{moments.std():.4f}",
            "rowstd_samp": len(rowstd_samples),
        })

        del df
        gc.collect()

    pbar1.close()

    thr_high = float(moments.mean + moments.std())
    thr_low_var = float(np.quantile(np.array(rowstd_samples, dtype=np.float64), 0.25)) if rowstd_samples else 0.0

    # PASS 2: process and write shards
    print("\n⚙️ PASS 2 (build): processing shards and writing outputs...")
    out_bytes_attack = 0
    out_bytes_benign = 0
    shards_out = 0
    total_in_rows = 0
    total_out_rows = 0

    sample_chunks: List[pd.DataFrame] = []
    sample_left = max(0, int(cfg.return_df_sample))

    pbar2 = tqdm(shard_files, desc="PHASE 3 pass2", unit="shard", dynamic_ncols=True)

    for fp in pbar2:
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or len(df) == 0:
            continue

        total_in_rows += int(len(df))

        # align schema
        for c in canonical_cols:
            if c not in df.columns:
                df[c] = "unknown" if str(c).endswith(raw_suffix) else 0
        df = df[canonical_cols]

        # drop leak cols
        if leak_cols_list:
            df = df.drop(columns=[c for c in leak_cols_list if c in df.columns], errors="ignore")

        if "Target" not in df.columns:
            raise RuntimeError(f"Target missing in shard: {fp}")

        # ensure numeric except raw
        df = ensure_numeric_except_raw(df, raw_suffix=raw_suffix)

        # ensure feature cols exist
        for c in feature_cols:
            if c not in df.columns:
                df[c] = 0

        # fmat as numpy (float32 to keep memory lower)
        fmat = df[feature_cols].to_numpy(dtype=np.float32, copy=True)

        # interactions
        for (i, j) in interaction_pairs:
            col1 = selected_features[i]
            col2 = selected_features[j]
            a = df[col1].to_numpy(dtype=np.float32, copy=False)
            b = df[col2].to_numpy(dtype=np.float32, copy=False)
            df[f"interact_{i}_{j}"] = np.nan_to_num(a * b, nan=0.0, posinf=0.0, neginf=0.0)

        # row-wise stats (numpy)
        row_mean = np.nan_to_num(fmat.mean(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
        row_std = np.nan_to_num(fmat.std(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
        row_max = np.nan_to_num(fmat.max(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
        row_min = np.nan_to_num(fmat.min(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
        row_sum = np.nan_to_num(fmat.sum(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
        row_nonzero = (fmat != 0).sum(axis=1).astype(np.int32)

        df["row_mean"] = row_mean
        df["row_std"] = row_std
        df["row_max"] = row_max
        df["row_min"] = row_min
        df["row_sum"] = row_sum
        df["row_nonzero"] = row_nonzero

        # normalization using global max
        for k, col in enumerate(norm_cols):
            denom = float(global_max.get(col, 0.0) + 1.0)
            x = df[col].to_numpy(dtype=np.float32, copy=False)
            df[f"norm_{k}"] = np.nan_to_num(x / denom, nan=0.0, posinf=0.0, neginf=0.0) if denom > 0 else 0

        # ratios
        safe_row_min = np.where(row_min == 0, 1.0, row_min)
        safe_row_nonzero = np.where(row_nonzero == 0, 1.0, row_nonzero.astype(np.float32))

        df["ratio_max_to_min"] = np.nan_to_num(row_max / safe_row_min, nan=0.0, posinf=0.0, neginf=0.0)
        df["ratio_sum_to_count"] = np.nan_to_num(row_sum / safe_row_nonzero, nan=0.0, posinf=0.0, neginf=0.0)

        # binary indicators (global-ish thresholds)
        df["has_high_values"] = (row_max > thr_high).astype(np.int32)
        df["has_low_variance"] = (row_std < thr_low_var).astype(np.int32)

        denom_sparse = float(len(feature_cols)) if len(feature_cols) else 1.0
        df["is_sparse"] = ((row_nonzero.astype(np.float32) / denom_sparse) < 0.3).astype(np.int32)

        # final cleanup numeric
        for col in df.select_dtypes(include=[np.number]).columns:
            df[col] = df[col].replace([np.inf, -np.inf], 0).fillna(0)

        # keep raw cols as strings
        for col in df.columns:
            if str(col).endswith(raw_suffix):
                df[col] = df[col].astype("string").fillna("unknown")

        df["Target"] = _to_numeric_safe(df["Target"]).astype(int)

        total_out_rows += int(len(df))

        # decide output folder by origin parent name
        origin = fp.parent.name.lower()
        is_attack = (origin == "attacks")
        out_root = out_attacks if is_attack else out_benign

        out_name = fp.name
        if cfg.write_format == "parquet":
            out_name = out_name.replace(".csv.gz", ".parquet")
            if not out_name.endswith(".parquet"):
                out_name = Path(out_name).with_suffix(".parquet").name
        else:
            out_name = out_name.replace(".parquet", ".csv.gz")
            if not out_name.endswith(".csv.gz"):
                out_name = Path(out_name).with_suffix(".csv.gz").name

        out_path = out_root / out_name
        nbytes = _write_shard(
            df,
            out_path,
            write_format=cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
        )
        shards_out += 1
        if is_attack:
            out_bytes_attack += nbytes
        else:
            out_bytes_benign += nbytes

        # sample for downstream/debug
        if sample_left > 0:
            take_n = min(sample_left, len(df))
            sample_chunks.append(df.iloc[:take_n].copy())
            sample_left -= take_n

        pbar2.set_postfix({
            "out_rows": f"{total_out_rows:,}",
            "atk_size": _human_bytes(out_bytes_attack),
            "ben_size": _human_bytes(out_bytes_benign),
        })

        del df
        gc.collect()

    pbar2.close()

    df_sample = pd.concat(sample_chunks, ignore_index=True) if sample_chunks else pd.DataFrame()

    elapsed = (datetime.now() - t0).total_seconds()
    total_bytes = out_bytes_attack + out_bytes_benign
    total_gib = total_bytes / (1024 ** 3)

    print("\n📦 PHASE 3 OUTPUT SIZE (on disk)")
    print(f"   Attacks : {_human_bytes(out_bytes_attack)}")
    print(f"   Benign  : {_human_bytes(out_bytes_benign)}")
    print(f"   TOTAL   : {_human_bytes(total_bytes)}  ({total_gib:.2f} GiB)")
    print(f"   Output dir: {out_dir.resolve()}")

    summary = {
        "phase": 3,
        "mode": "sharded",
        "input_dir": str(in_dir),
        "out_dir": str(out_dir),
        "write_format": cfg.write_format,
        "parquet_engine": cfg.parquet_engine,
        "parquet_compression": cfg.parquet_compression,
        "canonical_cols_count": int(len(canonical_cols)),
        "feature_cols_count": int(len(feature_cols)),
        "selected_features_count": int(len(selected_features)),
        "interaction_pairs_count": int(len(interaction_pairs)),
        "n_norm": int(len(norm_cols)),
        "thr_high": float(thr_high),
        "thr_low_var": float(thr_low_var),
        "shards_in": int(len(shard_files)),
        "shards_out": int(shards_out),
        "total_in_rows": int(total_in_rows),
        "total_out_rows": int(total_out_rows),
        "attack_bytes": int(out_bytes_attack),
        "benign_bytes": int(out_bytes_benign),
        "total_bytes": int(total_bytes),
        "total_gib": float(total_gib),
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "seconds": float(elapsed),
        "blocked_feature_cols": sorted(list(set(exclude_list))),
        "note": (
            "Sharded Phase 3 uses approximate global thresholds from PASS 1 sampling "
            "and global max per norm column across shards."
        ),
    }

    print("\n✅ PHASE 3 COMPLETE (SHARDED)")
    print(f"   shards_out: {shards_out} | out_rows: {total_out_rows:,}")
    print(f"   df_sample: {df_sample.shape} | thr_high={thr_high:.4f} | thr_low_var={thr_low_var:.4f}")
    print(f"   Time: {elapsed/60:.2f} minutes\n")

    return df_sample, summary