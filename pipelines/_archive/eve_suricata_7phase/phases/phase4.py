# src/cbr/phases/phase4.py
from __future__ import annotations

import gc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

RAW_SUFFIX = "_raw"


def _get_rss_mb() -> float | None:
    """
    Return process RSS in MB if possible.
    - Uses psutil if installed (recommended).
    - Returns None if not available.
    """
    try:
        import os
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
        return float(proc.memory_info().rss) / (1024.0 * 1024.0)
    except Exception:
        return None


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(max(0, n))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} B"


# =============================================================================
# PHASE 4 (IN-MEMORY) - ORIGINAL (keep for small df_sample runs)
# =============================================================================
def phase4_clean_aggressive(
    df_in: pd.DataFrame,
    *,
    raw_suffix: str = RAW_SUFFIX,
    keep_strings_for_raw: bool = True,
    coerce_non_raw_objects_to_string: bool = True,
    copy_input: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """
    Phase 4 (in-memory):
    - Aggressive NaN/Inf elimination
    - Numeric columns (non-raw): coerce numeric, inf->nan->0
    - Object/string columns:
        - *_raw stays string 'unknown'
        - others -> string 'unknown' (optional)
    """

    print("\n" + "🔴 " + "=" * 76 + "\n")
    print("PHASE 4: DATA CLEANING (AGGRESSIVE NaN/Inf ELIMINATION) [IN-MEMORY]")
    print("\n" + "🔴 " + "=" * 76)

    t0 = datetime.now()
    if df_in is None or len(df_in) == 0:
        raise ValueError("Phase 4 received empty df_in")

    rss_before = _get_rss_mb()

    # IMPORTANT: avoid doubling RAM on huge DF
    df = df_in.copy() if copy_input else df_in

    # diagnostics BEFORE
    total_nan_before = int(df.isna().sum().sum())
    num_cols_pre = df.select_dtypes(include=[np.number]).columns.tolist()
    total_inf_before = int(sum(np.isinf(df[c]).sum() for c in num_cols_pre)) if num_cols_pre else 0

    # Split raw vs non-raw
    raw_cols = [c for c in df.columns if str(c).endswith(raw_suffix)]
    non_raw_cols = [c for c in df.columns if c not in raw_cols]

    # Numeric cleaning (NON-RAW numeric)
    non_raw_num_cols = df[non_raw_cols].select_dtypes(include=[np.number]).columns.tolist()
    for c in non_raw_num_cols:
        df[c] = (
            pd.to_numeric(df[c], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
        )

    # NON-RAW object/string -> string unknown
    if coerce_non_raw_objects_to_string:
        obj_cols = df[non_raw_cols].select_dtypes(include=["object", "string"]).columns.tolist()
        for c in obj_cols:
            df[c] = df[c].astype("string").fillna("unknown")

    # RAW cols always string
    if keep_strings_for_raw and raw_cols:
        for c in raw_cols:
            df[c] = df[c].astype("string").fillna("unknown")

    # Final hard safety pass (numeric only, exclude raw)
    num_cols_post = df.select_dtypes(include=[np.number]).columns.tolist()
    for c in num_cols_post:
        if str(c).endswith(raw_suffix):
            continue
        df[c] = df[c].replace([np.inf, -np.inf], 0).fillna(0)

    # --- ensure Target is binary int (defensive) ---
    if "Target" in df.columns:
        df["Target"] = pd.to_numeric(df["Target"], errors="coerce").fillna(0).astype(int)
        df["Target"] = (df["Target"] == 1).astype(int)

    # diagnostics AFTER
    total_nan_after = int(df.isna().sum().sum())
    num_cols_post2 = df.select_dtypes(include=[np.number]).columns.tolist()
    total_inf_after = int(sum(np.isinf(df[c]).sum() for c in num_cols_post2)) if num_cols_post2 else 0

    rss_after = _get_rss_mb()
    rss_delta = None
    if (rss_before is not None) and (rss_after is not None):
        rss_delta = float(rss_after - rss_before)

    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 4,
        "mode": "in_memory",
        "input_shape": [int(df_in.shape[0]), int(df_in.shape[1])],
        "output_shape": [int(df.shape[0]), int(df.shape[1])],

        "nan_before": total_nan_before,
        "inf_before": total_inf_before,
        "nan_after": total_nan_after,
        "inf_after": total_inf_after,

        "raw_cols_count": int(len(raw_cols)),
        "numeric_cols_count": int(len(df.select_dtypes(include=[np.number]).columns)),

        # memory stats (process RSS)
        "rss_mb_before": None if rss_before is None else float(rss_before),
        "rss_mb_after": None if rss_after is None else float(rss_after),
        "rss_mb_delta": None if rss_delta is None else float(rss_delta),

        "seconds": float(elapsed),
        "note": "In-memory aggressive NaN/Inf cleaning. *_raw columns kept as string.",
    }

    print("\n✅ PHASE 4 COMPLETE")
    print(f"   df_clean: {df.shape}")
    print(f"   NaN: {total_nan_before:,} -> {total_nan_after:,}")
    print(f"   Inf: {total_inf_before:,} -> {total_inf_after:,}")

    # debug: target distribution
    if "Target" in df.columns:
        dist = df["Target"].value_counts(dropna=False).to_dict()
        dist = {int(k) if str(k).isdigit() else str(k): int(v) for k, v in dist.items()}
        print(f"   Target dist: {dist}")
    else:
        print("   Target dist: [Target column missing]")

    if rss_before is None or rss_after is None:
        print("   RSS: N/A (install psutil to enable memory stats)")
    else:
        print(f"   RSS: {rss_before:,.1f} MB -> {rss_after:,.1f} MB (Δ {rss_delta:+,.1f} MB)")

    print(f"   Time: {elapsed/60:.2f} minutes\n")

    gc.collect()
    return df, summary


# =============================================================================
# PHASE 4 (SHARDED, DISK-BACKED) - NEW
# =============================================================================
@dataclass(frozen=True)
class Phase4ShardConfig:
    input_dir: Path                      # expects input_dir/attacks + input_dir/benign with part-*.parquet
    out_dir: Path                        # writes out_dir/attacks + out_dir/benign
    write_format: str = "parquet"        # "parquet" or "csv" (csv -> csv.gz)
    parquet_engine: Optional[str] = "fastparquet"
    parquet_compression: Optional[str] = "snappy"
    return_df_sample: int = 200_000
    include_attacks: bool = True
    include_benign: bool = True

    # set True if you want expensive nan/inf counts aggregated (extra scans)
    compute_diagnostics: bool = False


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


def phase4_clean_aggressive_sharded(
    *,
    cfg: Phase4ShardConfig,
    raw_suffix: str = RAW_SUFFIX,
    keep_strings_for_raw: bool = True,
    coerce_non_raw_objects_to_string: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Phase 4 (sharded):
    - Read shards from cfg.input_dir
    - Apply the same cleaning semantics per shard
    - Write cleaned shards to cfg.out_dir
    - Return only df_sample (small) + summary
    - Print final output size (attacks/benign/total)
    """
    print("\n" + "🔴 " + "=" * 76 + "\n")
    print("PHASE 4: DATA CLEANING (AGGRESSIVE NaN/Inf ELIMINATION) [SHARDED, DISK-BACKED]")
    print("\n" + "🔴 " + "=" * 76)

    t0 = datetime.now()

    in_dir = Path(cfg.input_dir)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shard_files = _iter_shards(in_dir, include_attacks=cfg.include_attacks, include_benign=cfg.include_benign)
    if not shard_files:
        raise RuntimeError(f"No input shards found under: {in_dir}")

    out_attacks = out_dir / "attacks"
    out_benign = out_dir / "benign"
    out_attacks.mkdir(parents=True, exist_ok=True)
    out_benign.mkdir(parents=True, exist_ok=True)

    # output size tracking
    out_bytes_attack = 0
    out_bytes_benign = 0
    shards_out = 0
    shards_in = 0

    total_in_rows = 0
    total_out_rows = 0

    # optional aggregated diagnostics (expensive)
    nan_before_total = 0
    inf_before_total = 0
    nan_after_total = 0
    inf_after_total = 0

    # in-RAM sample
    sample_chunks: List[pd.DataFrame] = []
    sample_left = max(0, int(cfg.return_df_sample))

    pbar = tqdm(shard_files, desc="PHASE 4 (shards)", unit="shard", dynamic_ncols=True)

    for fp in pbar:
        shards_in += 1

        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or len(df) == 0:
            continue

        total_in_rows += int(len(df))

        # diagnostics BEFORE (optional)
        if cfg.compute_diagnostics:
            nan_before_total += int(df.isna().sum().sum())
            num_cols_pre = df.select_dtypes(include=[np.number]).columns.tolist()
            if num_cols_pre:
                inf_before_total += int(sum(np.isinf(df[c]).sum() for c in num_cols_pre))

        # Split raw vs non-raw
        raw_cols = [c for c in df.columns if str(c).endswith(raw_suffix)]
        non_raw_cols = [c for c in df.columns if c not in raw_cols]

        # Numeric cleaning (NON-RAW numeric)
        non_raw_num_cols = df[non_raw_cols].select_dtypes(include=[np.number]).columns.tolist()
        for c in non_raw_num_cols:
            df[c] = (
                pd.to_numeric(df[c], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0)
            )

        # NON-RAW object/string -> string unknown
        if coerce_non_raw_objects_to_string:
            obj_cols = df[non_raw_cols].select_dtypes(include=["object", "string"]).columns.tolist()
            for c in obj_cols:
                df[c] = df[c].astype("string").fillna("unknown")

        # RAW cols always string
        if keep_strings_for_raw and raw_cols:
            for c in raw_cols:
                df[c] = df[c].astype("string").fillna("unknown")

        # Final hard safety pass (numeric only, exclude raw)
        num_cols_post = df.select_dtypes(include=[np.number]).columns.tolist()
        for c in num_cols_post:
            if str(c).endswith(raw_suffix):
                continue
            df[c] = df[c].replace([np.inf, -np.inf], 0).fillna(0)

        # --- ensure Target is binary int (defensive) ---
        if "Target" in df.columns:
            df["Target"] = pd.to_numeric(df["Target"], errors="coerce").fillna(0).astype(int)
            df["Target"] = (df["Target"] == 1).astype(int)

        # diagnostics AFTER (optional)
        if cfg.compute_diagnostics:
            nan_after_total += int(df.isna().sum().sum())
            num_cols_post2 = df.select_dtypes(include=[np.number]).columns.tolist()
            if num_cols_post2:
                inf_after_total += int(sum(np.isinf(df[c]).sum() for c in num_cols_post2))

        total_out_rows += int(len(df))

        # choose output folder by origin parent
        origin = fp.parent.name.lower()
        is_attack = (origin == "attacks")
        out_root = out_attacks if is_attack else out_benign

        # output file name preserve part index
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

        # accumulate sample
        if sample_left > 0:
            take_n = min(sample_left, len(df))
            sample_chunks.append(df.iloc[:take_n].copy())
            sample_left -= take_n

        pbar.set_postfix({
            "out_rows": f"{total_out_rows:,}",
            "atk_size": _human_bytes(out_bytes_attack),
            "ben_size": _human_bytes(out_bytes_benign),
        })

        del df
        gc.collect()

    pbar.close()

    df_sample = pd.concat(sample_chunks, ignore_index=True) if sample_chunks else pd.DataFrame()

    elapsed = (datetime.now() - t0).total_seconds()
    total_bytes = out_bytes_attack + out_bytes_benign
    total_gib = total_bytes / (1024 ** 3)

    print("\n📦 PHASE 4 OUTPUT SIZE (on disk)")
    print(f"   Attacks : {_human_bytes(out_bytes_attack)}")
    print(f"   Benign  : {_human_bytes(out_bytes_benign)}")
    print(f"   TOTAL   : {_human_bytes(total_bytes)}  ({total_gib:.2f} GiB)")
    print(f"   Output dir: {out_dir.resolve()}")

    summary = {
        "phase": 4,
        "mode": "sharded",
        "input_dir": str(in_dir),
        "out_dir": str(out_dir),
        "write_format": cfg.write_format,
        "parquet_engine": cfg.parquet_engine,
        "parquet_compression": cfg.parquet_compression,
        "shards_in": int(shards_in),
        "shards_out": int(shards_out),
        "total_in_rows": int(total_in_rows),
        "total_out_rows": int(total_out_rows),
        "attack_bytes": int(out_bytes_attack),
        "benign_bytes": int(out_bytes_benign),
        "total_bytes": int(total_bytes),
        "total_gib": float(total_gib),
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "seconds": float(elapsed),
        "compute_diagnostics": bool(cfg.compute_diagnostics),
    }

    if cfg.compute_diagnostics:
        summary.update({
            "nan_before": int(nan_before_total),
            "inf_before": int(inf_before_total),
            "nan_after": int(nan_after_total),
            "inf_after": int(inf_after_total),
        })

    print("\n✅ PHASE 4 COMPLETE (SHARDED)")
    print(f"   shards_out: {shards_out} | out_rows: {total_out_rows:,}")
    if cfg.compute_diagnostics:
        print(f"   NaN: {nan_before_total:,} -> {nan_after_total:,}")
        print(f"   Inf: {inf_before_total:,} -> {inf_after_total:,}")
    print(f"   df_sample: {df_sample.shape}")
    print(f"   Time: {elapsed/60:.2f} minutes\n")

    gc.collect()
    return df_sample, summary