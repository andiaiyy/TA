# src/cbr/phases/phase7_cleaning.py
from __future__ import annotations

import gc
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =============================================================================
# PHASE 7: CLEANING (APP-AWARE, SHARDED, DISK-BACKED)
# =============================================================================
# Purpose:
#   Aggressive NaN/Inf/type cleaning after Phase 6 computed features.
#
# Input:
#   results/phase6_computed_features_dataset/app={app}/part-*.parquet
#
# Output:
#   results/phase7_clean_dataset/app={app}/part-*.parquet
#   results/phase7_clean_dataset/metrics/phase7_cleaning_summary_{app}.json
#   results/phase7_clean_dataset/metrics/phase7_cleaning_summary_all.json
#   results/phase7_clean_dataset/metrics/phase7_cleaning_summary_by_app.csv
#
# Important:
#   - This phase no longer reads attacks/benign folders.
#   - This phase works per application: dns/http/tls/ssh.
#   - *_raw columns are kept as strings for visualization.
#   - Non-raw numeric columns are cleaned to remove NaN/Inf.
#   - Non-raw object/string columns can either be converted to string or hashed.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")
RAW_SUFFIX = "_raw"


@dataclass(frozen=True)
class Phase7CleaningConfig:
    input_dir: Path = Path("results/phase6_computed_features_dataset")
    output_dir: Path = Path("results/phase7_clean_dataset")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    write_format: str = "parquet"  # "parquet" or "csv"
    parquet_engine: Optional[str] = "fastparquet"
    parquet_compression: Optional[str] = "snappy"

    raw_suffix: str = RAW_SUFFIX
    keep_strings_for_raw: bool = True

    # If True: non-raw object/string cols are kept as string "unknown".
    # If False: non-raw object/string cols are hashed to numeric.
    # For modeling safety, later leakage/split phases should still drop audit columns.
    coerce_non_raw_objects_to_string: bool = True

    return_df_sample: int = 100_000
    overwrite: bool = True
    gc_each_shard: bool = True

    # Expensive because it scans NaN/Inf counts across all columns.
    compute_diagnostics: bool = False


# =============================================================================
# Helpers
# =============================================================================

def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(max(0, int(n)))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} B"


def _gib(x_bytes: int) -> float:
    return float(x_bytes) / (1024.0 ** 3)


def _clean_dir(path: Path) -> None:
    if not path.exists():
        return
    for fp in path.glob("*"):
        try:
            if fp.is_file():
                fp.unlink()
            elif fp.is_dir():
                shutil.rmtree(fp)
        except Exception:
            pass


def _get_rss_mb() -> float | None:
    try:
        import os
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
        return float(proc.memory_info().rss) / (1024.0 * 1024.0)
    except Exception:
        return None


def _to_numeric_safe(s: Any) -> pd.Series:
    if isinstance(s, pd.Series):
        x = pd.to_numeric(s, errors="coerce")
    else:
        x = pd.Series(s)
        x = pd.to_numeric(x, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


def _stable_hash_series(s: pd.Series, mod: int = 2**31 - 1) -> pd.Series:
    s = s.astype("string").fillna("unknown")
    h = pd.util.hash_pandas_object(s, index=False).astype("uint64")
    return (h % np.uint64(mod)).astype("int64")


def _ensure_python_str_series(s: pd.Series) -> pd.Series:
    out = s.astype("object")
    out = out.where(pd.notna(out), "")
    return out.astype(str)


def _read_shard(path: Path, *, parquet_engine: Optional[str] = None) -> pd.DataFrame:
    suffixes = "".join(path.suffixes).lower()
    if path.suffix.lower() == ".parquet":
        kwargs: Dict[str, Any] = {}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        return pd.read_parquet(path, **kwargs)
    if suffixes.endswith(".csv.gz"):
        return pd.read_csv(path, compression="gzip")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported shard format: {path}")


def _write_shard(
    df: pd.DataFrame,
    path: Path,
    *,
    write_format: str,
    parquet_engine: Optional[str],
    parquet_compression: Optional[str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    # Avoid fastparquet pandas StringDtype issues.
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == "object":
            try:
                df[col] = _ensure_python_str_series(df[col])
            except Exception:
                pass

    if write_format == "parquet":
        kwargs: Dict[str, Any] = {"index": False}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        if parquet_compression:
            kwargs["compression"] = parquet_compression
        try:
            df.to_parquet(path, **kwargs)
        except Exception:
            kwargs.pop("compression", None)
            df.to_parquet(path, **kwargs)
    else:
        df.to_csv(path, index=False, compression="gzip")

    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _list_app_shards(input_dir: Path, app: str) -> List[Path]:
    """
    Accept both:
      input_dir/app={app}/part-*.parquet
      input_dir/{app}/part-*.parquet
    """
    app = str(app).strip().lower()
    dirs = [
        Path(input_dir) / f"app={app}",
        Path(input_dir) / app,
    ]

    files: List[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for pat in ("part-*.parquet", "part-*.csv.gz", "part-*.csv", "*.parquet", "*.csv.gz", "*.csv"):
            files.extend(sorted(d.glob(pat)))

    return sorted(set(files))


def _count_inf_numeric(df: pd.DataFrame) -> int:
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if not num_cols:
        return 0

    total = 0
    for c in num_cols:
        try:
            total += int(np.isinf(df[c]).sum())
        except Exception:
            pass
    return int(total)


def _clean_dataframe(
    df_in: pd.DataFrame,
    *,
    raw_suffix: str = RAW_SUFFIX,
    keep_strings_for_raw: bool = True,
    coerce_non_raw_objects_to_string: bool = True,
    hash_mod: int = 2**31 - 1,
    copy_input: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Clean one DataFrame/shard.
    """
    if df_in is None or len(df_in) == 0:
        return pd.DataFrame(), {
            "input_shape": [0, 0],
            "output_shape": [0, 0],
            "nan_before": 0,
            "inf_before": 0,
            "nan_after": 0,
            "inf_after": 0,
            "raw_cols_count": 0,
            "numeric_cols_count": 0,
        }

    df = df_in.copy() if copy_input else df_in

    nan_before = int(df.isna().sum().sum())
    inf_before = _count_inf_numeric(df)

    raw_cols = [c for c in df.columns if str(c).endswith(raw_suffix)]
    non_raw_cols = [c for c in df.columns if c not in raw_cols]

    # Numeric cleaning for all non-raw numeric columns.
    non_raw_num_cols = df[non_raw_cols].select_dtypes(include=[np.number]).columns.tolist()
    for c in non_raw_num_cols:
        df[c] = (
            pd.to_numeric(df[c], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
        )

    # Object/string handling for non-raw columns.
    obj_cols = df[non_raw_cols].select_dtypes(include=["object", "string"]).columns.tolist()
    for c in obj_cols:
        if coerce_non_raw_objects_to_string:
            df[c] = df[c].astype("string").fillna("unknown")
        else:
            # Safer for modeling, but less readable for audit/report.
            df[c] = _stable_hash_series(df[c], mod=hash_mod)

    # Raw columns always string for visualization/report.
    if keep_strings_for_raw and raw_cols:
        for c in raw_cols:
            df[c] = df[c].astype("string").fillna("unknown")

    # Final hard safety pass for numeric columns.
    num_cols_post = df.select_dtypes(include=[np.number]).columns.tolist()
    for c in num_cols_post:
        if str(c).endswith(raw_suffix):
            continue
        df[c] = df[c].replace([np.inf, -np.inf], 0).fillna(0)

    # Target must remain binary int.
    if "Target" in df.columns:
        df["Target"] = pd.to_numeric(df["Target"], errors="coerce").fillna(0).astype(int)
        df["Target"] = (df["Target"] == 1).astype(np.int8)
    else:
        raise RuntimeError("Target column missing in Phase 7 input. Phase 4/5/6 output invalid.")

    nan_after = int(df.isna().sum().sum())
    inf_after = _count_inf_numeric(df)

    info = {
        "input_shape": [int(df_in.shape[0]), int(df_in.shape[1])],
        "output_shape": [int(df.shape[0]), int(df.shape[1])],
        "nan_before": int(nan_before),
        "inf_before": int(inf_before),
        "nan_after": int(nan_after),
        "inf_after": int(inf_after),
        "raw_cols_count": int(len(raw_cols)),
        "numeric_cols_count": int(len(df.select_dtypes(include=[np.number]).columns)),
        "object_cols_count": int(len(df.select_dtypes(include=["object", "string"]).columns)),
    }

    return df, info



# =============================================================================
# Visualization-stat helpers
# =============================================================================

def _counter_to_json_dict(counter: Counter) -> Dict[str, int]:
    return {str(k): int(v) for k, v in counter.items()}


def _target_counts_from_df(df: pd.DataFrame, target_col: str = "Target") -> Dict[str, int]:
    if df is None or df.empty or target_col not in df.columns:
        return {}
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return {str(k): int(v) for k, v in y.value_counts(dropna=False).sort_index().to_dict().items()}


def _safe_quantile_summary(series: pd.Series) -> Dict[str, float | int]:
    x = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if x.empty:
        return {
            "count": 0,
            "min": 0.0,
            "q1": 0.0,
            "median": 0.0,
            "q3": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "std": 0.0,
        }
    q = x.quantile([0.25, 0.50, 0.75])
    return {
        "count": int(x.shape[0]),
        "min": float(x.min()),
        "q1": float(q.loc[0.25]),
        "median": float(q.loc[0.50]),
        "q3": float(q.loc[0.75]),
        "max": float(x.max()),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=0)),
    }


def _numeric_quantiles_by_target(
    df: pd.DataFrame,
    *,
    columns: Tuple[str, ...] = ("total_pkts", "total_bytes", "duration", "pkts_per_sec", "bytes_per_sec"),
    target_col: str = "Target",
) -> Dict[str, Dict[str, Dict[str, float | int]]]:
    out: Dict[str, Dict[str, Dict[str, float | int]]] = {}
    if df is None or df.empty:
        return out

    if target_col in df.columns:
        y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    else:
        y = pd.Series(np.zeros(len(df), dtype=int), index=df.index)

    for col in columns:
        if col not in df.columns:
            continue
        out[col] = {}
        for target_value in sorted(y.unique().tolist()):
            mask = y == int(target_value)
            out[col][str(int(target_value))] = _safe_quantile_summary(df.loc[mask, col])
    return out


def _phase7_visualization_stats(
    df: pd.DataFrame,
    *,
    app: str,
    rows_out: Optional[int] = None,
    target_counts_override: Optional[Dict[str, int]] = None,
    quantile_source: str = "full_df_clean",
) -> Dict[str, Any]:
    """
    Compact statistics for Phase 9 visualization.

    RAM mode uses full df_clean, so packet/byte/duration quantiles are exact for
    the active app. Disk mode may call this with df_sample, in which case the
    quantiles are explicitly marked as sample-based.
    """
    target_counts = target_counts_override or _target_counts_from_df(df)
    rows = int(rows_out if rows_out is not None else (0 if df is None else len(df)))

    return {
        "app": str(app).strip().lower(),
        "rows_after_phase7": rows,
        "target_counts": {str(k): int(v) for k, v in (target_counts or {}).items()},
        "numeric_quantiles_by_target": _numeric_quantiles_by_target(df),
        "quantile_source": quantile_source,
        "notes": (
            "These statistics are intended for Phase 9 plots so visualization does not need to reread raw data. "
            "Heatmaps still require a bounded df_clean sample."
        ),
    }

# =============================================================================
# In-memory API, useful for small smoke tests
# =============================================================================

def phase7_clean_aggressive(
    df_in: pd.DataFrame,
    *,
    raw_suffix: str = RAW_SUFFIX,
    keep_strings_for_raw: bool = True,
    coerce_non_raw_objects_to_string: bool = True,
    copy_input: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """
    Phase 7 in-memory cleaning.
    Useful for small df_sample runs.
    """
    print("\n" + "🔴 " + "=" * 76)
    print("PHASE 7: DATA CLEANING (IN-MEMORY)")
    print("🔴 " + "=" * 76)

    t0 = datetime.now()
    rss_before = _get_rss_mb()

    df, info = _clean_dataframe(
        df_in,
        raw_suffix=raw_suffix,
        keep_strings_for_raw=keep_strings_for_raw,
        coerce_non_raw_objects_to_string=coerce_non_raw_objects_to_string,
        copy_input=copy_input,
    )

    rss_after = _get_rss_mb()
    rss_delta = None
    if rss_before is not None and rss_after is not None:
        rss_delta = float(rss_after - rss_before)

    elapsed = (datetime.now() - t0).total_seconds()

    target_dist = {}
    if "Target" in df.columns:
        target_dist = {str(k): int(v) for k, v in df["Target"].value_counts(dropna=False).to_dict().items()}

    summary = {
        "phase": 7,
        "mode": "in_memory",
        **info,
        "target_distribution": target_dist,
        "target_counts": target_dist,
        "visualization_stats": _phase7_visualization_stats(
            df,
            app="in_memory",
            rows_out=int(len(df)),
            target_counts_override=target_dist,
            quantile_source="full_df_clean",
        ),
        "rss_mb_before": None if rss_before is None else float(rss_before),
        "rss_mb_after": None if rss_after is None else float(rss_after),
        "rss_mb_delta": None if rss_delta is None else float(rss_delta),
        "seconds": float(elapsed),
        "note": "In-memory aggressive NaN/Inf cleaning. *_raw columns kept as string.",
    }

    print("\n✅ PHASE 7 COMPLETE")
    print(f"   df_clean: {df.shape}")
    print(f"   NaN: {info['nan_before']:,} -> {info['nan_after']:,}")
    print(f"   Inf: {info['inf_before']:,} -> {info['inf_after']:,}")
    print(f"   Target dist: {target_dist}")
    print(f"   Time: {elapsed/60:.2f} minutes\n")

    gc.collect()
    return df, summary


# =============================================================================
# App-aware sharded API
# =============================================================================

def phase7_cleaning_for_app(
    app: str,
    *,
    cfg: Phase7CleaningConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    app = str(app).strip().lower()
    t0 = datetime.now()

    shard_files = _list_app_shards(cfg.input_dir, app)
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    if not shard_files:
        summary = {
            "phase": 7,
            "app": app,
            "status": "skipped_no_input_shards",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_in": 0,
            "rows_out": 0,
            "shards_in": 0,
            "shards_out": 0,
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase7_cleaning_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\n🔴 PHASE 7: Cleaning for app={app}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    sample_chunks: List[pd.DataFrame] = []
    sample_left = max(0, int(cfg.return_df_sample))

    rows_in = 0
    rows_out = 0
    shards_out = 0
    output_bytes = 0

    nan_before_total = 0
    inf_before_total = 0
    nan_after_total = 0
    inf_after_total = 0

    target_counter: Counter = Counter()
    raw_cols_count_max = 0
    numeric_cols_count_min: Optional[int] = None
    numeric_cols_count_max: Optional[int] = None
    output_cols_min: Optional[int] = None
    output_cols_max: Optional[int] = None

    pbar = tqdm(shard_files, desc=f"PHASE 7 app={app}", unit="shard", dynamic_ncols=True)

    for idx, fp in enumerate(pbar, start=1):
        df_in = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df_in is None or df_in.empty:
            if cfg.gc_each_shard:
                del df_in
                gc.collect()
            continue

        rows_in += int(len(df_in))

        df_clean, info = _clean_dataframe(
            df_in,
            raw_suffix=cfg.raw_suffix,
            keep_strings_for_raw=cfg.keep_strings_for_raw,
            coerce_non_raw_objects_to_string=cfg.coerce_non_raw_objects_to_string,
            copy_input=False,
        )

        rows_out += int(len(df_clean))

        if cfg.compute_diagnostics:
            nan_before_total += int(info["nan_before"])
            inf_before_total += int(info["inf_before"])
            nan_after_total += int(info["nan_after"])
            inf_after_total += int(info["inf_after"])

        raw_cols_count_max = max(raw_cols_count_max, int(info.get("raw_cols_count", 0)))

        nnum = int(info.get("numeric_cols_count", 0))
        numeric_cols_count_min = nnum if numeric_cols_count_min is None else min(numeric_cols_count_min, nnum)
        numeric_cols_count_max = nnum if numeric_cols_count_max is None else max(numeric_cols_count_max, nnum)

        ncols = int(df_clean.shape[1])
        output_cols_min = ncols if output_cols_min is None else min(output_cols_min, ncols)
        output_cols_max = ncols if output_cols_max is None else max(output_cols_max, ncols)

        if "Target" in df_clean.columns:
            target_counter.update(pd.to_numeric(df_clean["Target"], errors="coerce").fillna(0).astype(int).tolist())

        if cfg.write_format == "parquet":
            out_name = f"part-{idx:06d}.parquet"
        else:
            out_name = f"part-{idx:06d}.csv.gz"

        out_path = out_app_dir / out_name
        nbytes = _write_shard(
            df_clean,
            out_path,
            write_format=cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
        )

        output_bytes += int(nbytes)
        shards_out += 1

        if sample_left > 0:
            take_n = min(sample_left, len(df_clean))
            sample_chunks.append(df_clean.iloc[:take_n].copy())
            sample_left -= take_n

        pbar.set_postfix({
            "rows": f"{rows_out:,}",
            "cols": ncols,
            "size": _human_bytes(output_bytes),
        })

        if cfg.gc_each_shard:
            del df_in, df_clean
            gc.collect()

    pbar.close()

    df_sample = pd.concat(sample_chunks, ignore_index=True) if sample_chunks else pd.DataFrame()
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 7,
        "app": app,
        "status": "completed",
        "mode": "app_aware_sharded",
        "input_dir": str(cfg.input_dir),
        "output_dir": str(out_app_dir),
        "selected_apps": list(cfg.selected_apps),
        "write_format": cfg.write_format,
        "parquet_engine": cfg.parquet_engine,
        "parquet_compression": cfg.parquet_compression,
        "raw_suffix": cfg.raw_suffix,
        "keep_strings_for_raw": bool(cfg.keep_strings_for_raw),
        "coerce_non_raw_objects_to_string": bool(cfg.coerce_non_raw_objects_to_string),
        "compute_diagnostics": bool(cfg.compute_diagnostics),
        "shards_in": int(len(shard_files)),
        "shards_out": int(shards_out),
        "rows_in": int(rows_in),
        "rows_out": int(rows_out),
        "raw_cols_count_max": int(raw_cols_count_max),
        "numeric_cols_count_min": int(numeric_cols_count_min or 0),
        "numeric_cols_count_max": int(numeric_cols_count_max or 0),
        "output_cols_min": int(output_cols_min or 0),
        "output_cols_max": int(output_cols_max or 0),
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "visualization_stats": _phase7_visualization_stats(
            df_sample,
            app=app,
            rows_out=int(rows_out),
            target_counts_override={str(k): int(v) for k, v in target_counter.items()},
            quantile_source="df_sample",
        ),
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "output_bytes": int(output_bytes),
        "output_gib": float(_gib(output_bytes)),
        "seconds": float(elapsed),
        "note": (
            "Phase 7 cleans per-application shards and preserves *_raw columns as strings. "
            "This is the main clean dataset checkpoint for visualization, leakage analysis, split, FS, training, and evaluation."
        ),
    }

    if cfg.compute_diagnostics:
        summary.update({
            "nan_before": int(nan_before_total),
            "inf_before": int(inf_before_total),
            "nan_after": int(nan_after_total),
            "inf_after": int(inf_after_total),
        })

    _json_dump(summary, metrics_dir / f"phase7_cleaning_summary_{app}.json")

    print(f"✅ Phase 7 complete app={app}")
    print(f"   Rows out: {rows_out:,}")
    if cfg.compute_diagnostics:
        print(f"   NaN: {nan_before_total:,} -> {nan_after_total:,}")
        print(f"   Inf: {inf_before_total:,} -> {inf_after_total:,}")
    print(f"   Target : {summary['target_counts']}")
    print(f"   Output : {_human_bytes(output_bytes)}")
    print(f"   Sample : {df_sample.shape}")
    print(f"   Time   : {elapsed/60:.2f} minutes")

    return df_sample, summary


def phase7_cleaning(
    *,
    cfg: Phase7CleaningConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    print("\n" + "🔴 " + "=" * 76)
    print("PHASE 7: CLEANING (APP-AWARE, SHARDED)")
    print("🔴 " + "=" * 76)

    t0 = datetime.now()

    samples_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        df_sample, summary = phase7_cleaning_for_app(app_norm, cfg=cfg)
        samples_by_app[app_norm] = df_sample
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        target_counts = s.get("target_counts", {})
        rows.append({
            "app": app,
            "status": s.get("status"),
            "rows_in": int(s.get("rows_in", 0)),
            "rows_out": int(s.get("rows_out", 0)),
            "target_0_benign": int(target_counts.get("0", 0)),
            "target_1_malicious": int(target_counts.get("1", 0)),
            "output_cols_min": int(s.get("output_cols_min", 0)),
            "output_cols_max": int(s.get("output_cols_max", 0)),
            "numeric_cols_count_min": int(s.get("numeric_cols_count_min", 0)),
            "numeric_cols_count_max": int(s.get("numeric_cols_count_max", 0)),
            "raw_cols_count_max": int(s.get("raw_cols_count_max", 0)),
            "output_gib": float(s.get("output_gib", 0.0)),
            "shards_out": int(s.get("shards_out", 0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase7_cleaning_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows_out = int(sum(int(s.get("rows_out", 0)) for s in summaries.values()))
    total_output_bytes = int(sum(int(s.get("output_bytes", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 7,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "input_dir": str(cfg.input_dir),
        "output_dir": str(cfg.output_dir),
        "total_rows_out": total_rows_out,
        "total_output_bytes": total_output_bytes,
        "total_output_gib": float(_gib(total_output_bytes)),
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Phase 7 is app-aware and reads Phase 6 app partitions. "
            "It no longer expects attacks/benign folders."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase7_cleaning_summary_all.json")

    print("\n✅ PHASE 7 COMPLETE")
    print(f"   Total rows out: {total_rows_out:,}")
    print(f"   Output size   : {_human_bytes(total_output_bytes)}")
    print(f"   Output dir    : {cfg.output_dir}")
    print(f"   Time          : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all




# =============================================================================
# RAM MODE API (SMALL DATASET / PER-APP PIPELINE)
# =============================================================================

def phase7_cleaning_ram(
    df_in: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase7CleaningConfig] = None,
    raw_suffix: str = RAW_SUFFIX,
    keep_strings_for_raw: bool = True,
    coerce_non_raw_objects_to_string: bool = True,
    copy_input: bool = True,
    compute_diagnostics: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode Phase 7 for the small/seminar dataset.

    This function processes ONE active application DataFrame and returns the
    cleaned DataFrame directly. It does not read shards and does not write
    parquet/csv checkpoints.

    Expected RAM pipeline flow:
      df_phase6 -> phase7_cleaning_ram(...) -> df_clean
    """
    print("\n" + "🔴 " + "=" * 76)
    print(f"PHASE 7: CLEANING RAM MODE app={app}")
    print("🔴 " + "=" * 76)

    t0 = datetime.now()
    app = str(app).strip().lower() or "unknown"

    if cfg is not None:
        raw_suffix = getattr(cfg, "raw_suffix", raw_suffix)
        keep_strings_for_raw = bool(getattr(cfg, "keep_strings_for_raw", keep_strings_for_raw))
        coerce_non_raw_objects_to_string = bool(
            getattr(cfg, "coerce_non_raw_objects_to_string", coerce_non_raw_objects_to_string)
        )
        compute_diagnostics = bool(getattr(cfg, "compute_diagnostics", compute_diagnostics))

    if df_in is None:
        df_in = pd.DataFrame()

    rows_in = int(df_in.shape[0])
    cols_in = int(df_in.shape[1])
    rss_before = _get_rss_mb()

    if df_in.empty:
        elapsed = (datetime.now() - t0).total_seconds()
        summary = {
            "phase": 7,
            "phase_name": "cleaning",
            "status": "completed_empty",
            "mode": "ram_per_app",
            "app": app,
            "rows_in": rows_in,
            "rows_out": 0,
            "cols_in": cols_in,
            "cols_out": 0,
            "target_counts": {},
            "seconds": float(elapsed),
            "note": "RAM-mode Phase 7 received an empty DataFrame.",
        }
        print(f"⚠️ Phase 7 RAM app={app}: empty input")
        return pd.DataFrame(), summary

    df_clean, info = _clean_dataframe(
        df_in,
        raw_suffix=raw_suffix,
        keep_strings_for_raw=keep_strings_for_raw,
        coerce_non_raw_objects_to_string=coerce_non_raw_objects_to_string,
        copy_input=copy_input,
    )

    rss_after = _get_rss_mb()
    elapsed = (datetime.now() - t0).total_seconds()

    target_counts: Dict[str, int] = {}
    if "Target" in df_clean.columns:
        target_counts = {
            str(k): int(v)
            for k, v in df_clean["Target"].value_counts(dropna=False).to_dict().items()
        }

    raw_cols = [c for c in df_clean.columns if str(c).endswith(raw_suffix)]
    numeric_cols = df_clean.select_dtypes(include=[np.number]).columns.tolist()
    object_cols = df_clean.select_dtypes(include=["object", "string"]).columns.tolist()

    summary = {
        "phase": 7,
        "phase_name": "cleaning",
        "status": "completed",
        "mode": "ram_per_app",
        "app": app,
        "rows_in": rows_in,
        "rows_out": int(df_clean.shape[0]),
        "cols_in": cols_in,
        "cols_out": int(df_clean.shape[1]),
        "raw_suffix": raw_suffix,
        "keep_strings_for_raw": bool(keep_strings_for_raw),
        "coerce_non_raw_objects_to_string": bool(coerce_non_raw_objects_to_string),
        "raw_cols_count": int(len(raw_cols)),
        "numeric_cols_count": int(len(numeric_cols)),
        "object_cols_count": int(len(object_cols)),
        "target_counts": target_counts,
        "visualization_stats": _phase7_visualization_stats(
            df_clean,
            app=app,
            rows_out=int(df_clean.shape[0]),
            target_counts_override=target_counts,
            quantile_source="full_df_clean",
        ),
        "df_memory_mib": float(df_clean.memory_usage(deep=True).sum() / (1024.0 ** 2)),
        "rss_mb_before": None if rss_before is None else float(rss_before),
        "rss_mb_after": None if rss_after is None else float(rss_after),
        "seconds": float(elapsed),
        "note": (
            "RAM-mode Phase 7 cleans NaN/Inf/type issues for one active application. "
            "No parquet/csv checkpoint is written in this mode."
        ),
    }

    if compute_diagnostics:
        summary.update({
            "nan_before": int(info.get("nan_before", 0)),
            "inf_before": int(info.get("inf_before", 0)),
            "nan_after": int(info.get("nan_after", 0)),
            "inf_after": int(info.get("inf_after", 0)),
        })

    print(f"✅ Phase 7 RAM complete app={app}")
    print(f"   Rows : {rows_in:,} -> {int(df_clean.shape[0]):,}")
    print(f"   Cols : {cols_in:,} -> {int(df_clean.shape[1]):,}")
    print(f"   Target: {target_counts}")
    print(f"   Memory: {summary['df_memory_mib']:.2f} MiB")
    print(f"   Time : {elapsed/60:.2f} minutes")

    gc.collect()
    return df_clean, summary


# RAM-mode aliases for pipeline compatibility.
def phase7_cleaning_in_memory(
    df_in: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase7CleaningConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase7_cleaning_ram(df_in, app=app, cfg=cfg, **kwargs)


def run_phase7_cleaning_ram(
    df_in: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase7CleaningConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase7_cleaning_ram(df_in, app=app, cfg=cfg, **kwargs)


def build_phase7_cleaning_ram(
    df_in: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase7CleaningConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase7_cleaning_ram(df_in, app=app, cfg=cfg, **kwargs)


# Compatibility aliases.
def phase7_clean_aggressive_sharded(
    *,
    cfg: Phase7CleaningConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase7_cleaning(cfg=cfg)


def build_phase7_cleaning(
    *,
    cfg: Phase7CleaningConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase7_cleaning(cfg=cfg)


if __name__ == "__main__":
    samples, summary = phase7_cleaning(
        cfg=Phase7CleaningConfig(
            input_dir=Path("results/phase6_computed_features_dataset"),
            output_dir=Path("results/phase7_clean_dataset"),
            selected_apps=("dns", "http", "tls", "ssh"),
            write_format="parquet",
            parquet_engine="fastparquet",
            parquet_compression="snappy",
            return_df_sample=100_000,
            overwrite=True,
            compute_diagnostics=False,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
