# src/cbr/phases/phase6_computed_features.py
from __future__ import annotations

import gc
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =============================================================================
# PHASE 6: COMPUTED FEATURES (APP-AWARE, SHARDED, DISK-BACKED)
# =============================================================================
# Purpose:
#   Add computed/tabular features after Phase 5 feature engineering:
#     - interaction features
#     - row-wise statistics
#     - normalized features
#     - ratio features
#     - binary indicators
#
# Input:
#   results/phase5_feature_engineered_dataset/app={app}/part-*.parquet
#
# Output:
#   results/phase6_computed_features_dataset/app={app}/part-*.parquet
#   results/phase6_computed_features_dataset/metrics/phase6_computed_features_summary_{app}.json
#   results/phase6_computed_features_dataset/metrics/phase6_computed_features_summary_all.json
#   results/phase6_computed_features_dataset/metrics/phase6_computed_features_summary_by_app.csv
#
# Important:
#   - This phase no longer reads attacks/benign folders.
#   - This phase works per application: dns/http/tls/ssh.
#   - Label/evidence/audit columns are preserved in the output, but excluded from
#     computed feature construction to reduce leakage risk.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")
RAW_SUFFIX = "_raw"


DEFAULT_EXCLUDE_FROM_FEATURES: Tuple[str, ...] = (
    # Target / labels
    "Target",
    "Target_prelim",
    "is_malicious",
    "label_status",
    "label_status_final",
    "label_source",
    "label_reason",
    "label_confidence",

    # Alert-derived / label evidence
    "has_alert",
    "alert_category",
    "alert_severity",
    "alert_signature",
    "alert_signature_id",
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",

    # Probing evidence used during label refinement
    "probe_score",
    "is_possible_probe",
    "probe_reason",

    # Join/helper columns
    "window_start",
)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Phase6ComputedFeaturesConfig:
    input_dir: Path = Path("results/phase5_feature_engineered_dataset")
    output_dir: Path = Path("results/phase6_computed_features_dataset")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    write_format: str = "parquet"  # "parquet" or "csv"
    parquet_engine: Optional[str] = "fastparquet"
    parquet_compression: Optional[str] = "snappy"

    raw_suffix: str = RAW_SUFFIX

    # Feature construction parameters
    n_selected: int = 15
    max_interactions: int = 20
    n_norm: int = 10

    # Exclude from computed feature construction, but preserve in output.
    exclude_from_features: Tuple[str, ...] = DEFAULT_EXCLUDE_FROM_FEATURES

    # PASS 1 sampling for global-ish thresholds.
    thr_sample_rows_per_shard: int = 2_000
    thr_rowstd_sample_max: int = 200_000
    seed: int = 42

    return_df_sample: int = 100_000
    overwrite: bool = True
    gc_each_shard: bool = True

    # Use this to avoid ultra-wide fmat memory explosion.
    max_feature_cols_for_row_stats: Optional[int] = None


# =============================================================================
# General helpers
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


def ensure_numeric_except_raw(df_: pd.DataFrame, *, raw_suffix: str = RAW_SUFFIX) -> pd.DataFrame:
    """
    Convert any non-numeric columns except Target and *_raw into numeric/hash.
    Keeps *_raw as strings for visualization.
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
        out["Target"] = _to_numeric_safe(out["Target"]).astype(np.int8)

    return out


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

    # Normalize string/object raw columns for parquet engines.
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


def _is_blocked_computed_feature_source(
    col: str,
    *,
    blocked_exact: set[str],
    raw_suffix: str,
) -> bool:
    c = str(col)
    cl = c.lower()

    if c in blocked_exact or cl in blocked_exact:
        return True

    if c == "Target" or cl == "target":
        return True

    if c.endswith(raw_suffix) or cl.endswith(raw_suffix.lower()):
        return True

    # Label / alert / evidence / probing shortcut families.
    blocked_prefixes = (
        "alert_",
        "label_",
        "evidence_",
        "probe_",
        "target_prelim",
    )
    if any(cl.startswith(p) for p in blocked_prefixes):
        return True

    # Direct shortcut / audit / identifier / categorical hash columns.
    blocked_exact_names = {
        "has_alert",
        "is_malicious",
        "is_possible_probe",
        "is_probe_suspicious",

        "event_type",
        "event_type_h",
        "event_type_raw",
        "proto",
        "proto_h",
        "proto_raw",
        "app_proto",
        "app_proto_h",
        "app_proto_raw",
        "application",
        "application_h",
        "application_raw",
        "app_filter_reason",
        "app_filter_reason_h",

        "src_ip",
        "dest_ip",
        "src_ip_h",
        "dest_ip_h",
        "src_subnet24_h",
        "dest_subnet24_h",
        "flow_id",
        "flow_id_h",
        "community_id",
        "community_id_h",
        "timestamp",
        "timestamp_h",
        "first_seen",
        "last_seen",
        "first_seen_h",
        "last_seen_h",
        "window_start",
        "window_start_h",
    }
    if cl in blocked_exact_names:
        return True

    # Window features are useful for probing analysis, but because they are
    # computed before train/test split, do not use them as source for generic
    # row/norm/interact features.
    blocked_window_sources = {
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "alert_count_window",
        "target_prelim_malicious_count",
        "total_bytes_window",
        "total_pkts_window",
        "bytes_per_event_window",
        "pkts_per_event_window",
    }
    if cl in blocked_window_sources:
        return True

    return False


def _select_feature_cols(
    columns: Sequence[str],
    *,
    raw_suffix: str,
    exclude_from_features: Iterable[str],
    max_feature_cols_for_row_stats: Optional[int] = None,
) -> List[str]:
    blocked_exact = {str(x) for x in exclude_from_features}
    blocked_exact |= {str(x).lower() for x in exclude_from_features}
    blocked_exact |= {"Target", "target"}

    feature_cols = [
        c for c in columns
        if not _is_blocked_computed_feature_source(
            str(c),
            blocked_exact=blocked_exact,
            raw_suffix=raw_suffix,
        )
    ]

    feature_cols = sorted(feature_cols)

    if max_feature_cols_for_row_stats is not None and max_feature_cols_for_row_stats > 0:
        feature_cols = feature_cols[: int(max_feature_cols_for_row_stats)]

    return feature_cols


class _RunningMoments:
    """
    Streaming mean/variance for sampled scalar values from feature matrix.
    """
    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.M2 = 0.0

    def update_batch(self, arr: np.ndarray) -> None:
        a = np.asarray(arr, dtype=np.float64).ravel()
        if a.size == 0:
            return

        a = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
        nb = int(a.size)
        mb = float(a.mean())
        vb = float(a.var(ddof=0))

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


# =============================================================================
# Core feature computation
# =============================================================================

def _plan_interactions(
    selected_features: Sequence[str],
    *,
    max_interactions: int,
) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    for i in range(len(selected_features)):
        for j in range(i + 1, len(selected_features)):
            pairs.append((i, j))
            if len(pairs) >= max_interactions:
                break
        if len(pairs) >= max_interactions:
            break
    return pairs


def _compute_features_on_df(
    df: pd.DataFrame,
    *,
    feature_cols: List[str],
    selected_features: List[str],
    interaction_pairs: List[Tuple[int, int]],
    norm_cols: List[str],
    global_max: Dict[str, float],
    thr_high: float,
    thr_low_var: float,
    raw_suffix: str,
) -> pd.DataFrame:
    if "Target" not in df.columns:
        raise RuntimeError("Target column missing in Phase 6 input. Phase 4/5 output invalid.")

    df = ensure_numeric_except_raw(df, raw_suffix=raw_suffix)

    for c in feature_cols:
        if c not in df.columns:
            df[c] = 0
        else:
            df[c] = _to_numeric_safe(df[c])

    if not feature_cols:
        raise RuntimeError("No numeric feature columns found after exclusions.")

    # Use float32 matrix for memory efficiency.
    fmat = df[feature_cols].to_numpy(dtype=np.float32, copy=True)
    fmat = np.nan_to_num(fmat, nan=0.0, posinf=0.0, neginf=0.0)

    # Interaction features.
    for i, j in interaction_pairs:
        col1 = selected_features[i]
        col2 = selected_features[j]
        a = df[col1].to_numpy(dtype=np.float32, copy=False)
        b = df[col2].to_numpy(dtype=np.float32, copy=False)
        df[f"interact_{i}_{j}"] = np.nan_to_num(a * b, nan=0.0, posinf=0.0, neginf=0.0)

    # Row-wise statistics.
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

    # Normalization with PASS 1 global max.
    for k, col in enumerate(norm_cols):
        denom = float(global_max.get(col, 0.0) + 1.0)
        x = df[col].to_numpy(dtype=np.float32, copy=False)
        df[f"norm_{k}"] = np.nan_to_num(x / denom, nan=0.0, posinf=0.0, neginf=0.0) if denom > 0 else 0

    # Ratios.
    safe_row_min = np.where(row_min == 0, 1.0, row_min)
    safe_row_nonzero = np.where(row_nonzero == 0, 1.0, row_nonzero.astype(np.float32))

    df["ratio_max_to_min"] = np.nan_to_num(row_max / safe_row_min, nan=0.0, posinf=0.0, neginf=0.0)
    df["ratio_sum_to_count"] = np.nan_to_num(row_sum / safe_row_nonzero, nan=0.0, posinf=0.0, neginf=0.0)

    # Binary indicators.
    df["has_high_values"] = (row_max > float(thr_high)).astype(np.int32)
    df["has_low_variance"] = (row_std < float(thr_low_var)).astype(np.int32)

    denom_sparse = float(len(feature_cols)) if feature_cols else 1.0
    df["is_sparse"] = ((row_nonzero.astype(np.float32) / denom_sparse) < 0.3).astype(np.int32)

    # Final cleanup numeric.
    for col in df.select_dtypes(include=[np.number]).columns:
        df[col] = df[col].replace([np.inf, -np.inf], 0).fillna(0)

    # Preserve raw columns as strings.
    for col in df.columns:
        if str(col).endswith(raw_suffix):
            df[col] = df[col].astype("string").fillna("unknown")

    df["Target"] = _to_numeric_safe(df["Target"]).astype(np.int8)

    return df


# =============================================================================
# Public API
# =============================================================================

def phase6_computed_features_for_app(
    app: str,
    *,
    cfg: Phase6ComputedFeaturesConfig,
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
            "phase": 6,
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
        _json_dump(summary, metrics_dir / f"phase6_computed_features_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\n🟠 PHASE 6: Computed features for app={app}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    # -------------------------------------------------------------------------
    # PASS 0: determine canonical schema from the first non-empty shard.
    # -------------------------------------------------------------------------
    canonical_cols: Optional[List[str]] = None
    for fp in shard_files:
        df0 = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df0 is not None and not df0.empty:
            if "Target" not in df0.columns:
                raise RuntimeError(f"Target missing in first non-empty Phase 6 shard: {fp}")
            canonical_cols = list(df0.columns)
            del df0
            gc.collect()
            break

    if not canonical_cols:
        raise RuntimeError(f"No non-empty input shards found for app={app}")

    feature_cols = _select_feature_cols(
        canonical_cols,
        raw_suffix=cfg.raw_suffix,
        exclude_from_features=cfg.exclude_from_features,
        max_feature_cols_for_row_stats=cfg.max_feature_cols_for_row_stats,
    )

    if not feature_cols:
        raise RuntimeError(f"No feature columns found for app={app}. Check Phase 5 output and exclude list.")

    selected_features = feature_cols[: min(cfg.n_selected, len(feature_cols))]
    interaction_pairs = _plan_interactions(
        selected_features,
        max_interactions=int(cfg.max_interactions),
    )
    norm_cols = feature_cols[: min(cfg.n_norm, len(feature_cols))]
    global_max: Dict[str, float] = {c: 0.0 for c in norm_cols}

    # -------------------------------------------------------------------------
    # PASS 1: estimate thresholds and global max for normalization.
    # -------------------------------------------------------------------------
    moments = _RunningMoments()
    rowstd_samples: List[float] = []
    rng_global = np.random.default_rng(cfg.seed)

    print("   PASS 1: threshold/global max estimation...")
    pbar1 = tqdm(shard_files, desc=f"PHASE 6 pass1 app={app}", unit="shard", dynamic_ncols=True)

    for idx_fp, fp in enumerate(pbar1):
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        # Align to canonical columns. Extra columns are ignored for schema stability.
        for c in canonical_cols:
            if c not in df.columns:
                df[c] = "unknown" if str(c).endswith(cfg.raw_suffix) else 0
        df = df[canonical_cols]

        df = ensure_numeric_except_raw(df, raw_suffix=cfg.raw_suffix)

        for c in feature_cols:
            if c not in df.columns:
                df[c] = 0
            else:
                df[c] = _to_numeric_safe(df[c])

        for c in norm_cols:
            try:
                m = float(_to_numeric_safe(df[c]).max())
            except Exception:
                m = 0.0
            if m > global_max[c]:
                global_max[c] = m

        n = len(df)
        sample_n = min(int(cfg.thr_sample_rows_per_shard), n)
        if sample_n > 0:
            rng = np.random.default_rng(int(cfg.seed) + idx_fp)
            take_idx = rng.choice(n, size=sample_n, replace=False) if sample_n < n else np.arange(n)

            sub = df.iloc[take_idx][feature_cols].to_numpy(dtype=np.float32, copy=False)
            sub = np.nan_to_num(sub, nan=0.0, posinf=0.0, neginf=0.0)
            moments.update_batch(sub)

            rs = sub.astype(np.float64, copy=False).std(axis=1)
            for v in rs:
                if len(rowstd_samples) < int(cfg.thr_rowstd_sample_max):
                    rowstd_samples.append(float(v))
                else:
                    j = int(rng_global.integers(0, int(cfg.thr_rowstd_sample_max)))
                    rowstd_samples[j] = float(v)

        pbar1.set_postfix({
            "mean": f"{moments.mean:.4f}",
            "std": f"{moments.std():.4f}",
            "rowstd": len(rowstd_samples),
        })

        if cfg.gc_each_shard:
            del df
            gc.collect()

    pbar1.close()

    thr_high = float(moments.mean + moments.std())
    thr_low_var = float(np.quantile(np.array(rowstd_samples, dtype=np.float64), 0.25)) if rowstd_samples else 0.0

    # -------------------------------------------------------------------------
    # PASS 2: build computed features and write shards.
    # -------------------------------------------------------------------------
    print("   PASS 2: computed feature construction...")

    sample_chunks: List[pd.DataFrame] = []
    sample_left = max(0, int(cfg.return_df_sample))

    rows_in = 0
    rows_out = 0
    shards_out = 0
    output_bytes = 0
    target_counter: Counter = Counter()
    output_cols_min: Optional[int] = None
    output_cols_max: Optional[int] = None

    pbar2 = tqdm(shard_files, desc=f"PHASE 6 pass2 app={app}", unit="shard", dynamic_ncols=True)

    for idx, fp in enumerate(pbar2, start=1):
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            if cfg.gc_each_shard:
                del df
                gc.collect()
            continue

        rows_in += int(len(df))

        for c in canonical_cols:
            if c not in df.columns:
                df[c] = "unknown" if str(c).endswith(cfg.raw_suffix) else 0
        df = df[canonical_cols]

        df = _compute_features_on_df(
            df,
            feature_cols=feature_cols,
            selected_features=selected_features,
            interaction_pairs=interaction_pairs,
            norm_cols=norm_cols,
            global_max=global_max,
            thr_high=thr_high,
            thr_low_var=thr_low_var,
            raw_suffix=cfg.raw_suffix,
        )

        rows_out += int(len(df))
        ncols = int(df.shape[1])
        output_cols_min = ncols if output_cols_min is None else min(output_cols_min, ncols)
        output_cols_max = ncols if output_cols_max is None else max(output_cols_max, ncols)

        if "Target" in df.columns:
            target_counter.update(_to_numeric_safe(df["Target"]).astype(int).tolist())

        if cfg.write_format == "parquet":
            out_name = f"part-{idx:06d}.parquet"
        else:
            out_name = f"part-{idx:06d}.csv.gz"

        out_path = out_app_dir / out_name
        nbytes = _write_shard(
            df,
            out_path,
            write_format=cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
        )

        output_bytes += int(nbytes)
        shards_out += 1

        if sample_left > 0:
            take_n = min(sample_left, len(df))
            sample_chunks.append(df.iloc[:take_n].copy())
            sample_left -= take_n

        pbar2.set_postfix({
            "rows": f"{rows_out:,}",
            "cols": ncols,
            "size": _human_bytes(output_bytes),
        })

        if cfg.gc_each_shard:
            del df
            gc.collect()

    pbar2.close()

    df_sample = pd.concat(sample_chunks, ignore_index=True) if sample_chunks else pd.DataFrame()
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 6,
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
        "shards_in": int(len(shard_files)),
        "shards_out": int(shards_out),
        "rows_in": int(rows_in),
        "rows_out": int(rows_out),
        "canonical_cols_count": int(len(canonical_cols)),
        "feature_cols_count": int(len(feature_cols)),
        "selected_features_count": int(len(selected_features)),
        "selected_features": list(selected_features),
        "interaction_pairs_count": int(len(interaction_pairs)),
        "n_norm": int(len(norm_cols)),
        "norm_cols": list(norm_cols),
        "thr_high": float(thr_high),
        "thr_low_var": float(thr_low_var),
        "thr_sample_rows_per_shard": int(cfg.thr_sample_rows_per_shard),
        "thr_rowstd_sample_max": int(cfg.thr_rowstd_sample_max),
        "blocked_feature_cols": sorted(list(set(cfg.exclude_from_features))),
        "output_cols_min": int(output_cols_min or 0),
        "output_cols_max": int(output_cols_max or 0),
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "output_bytes": int(output_bytes),
        "output_gib": float(_gib(output_bytes)),
        "seconds": float(elapsed),
        "note": (
            "Phase 6 computes interaction, row-stat, normalized, ratio, and binary features per application. "
            "Label/evidence/audit columns are preserved but excluded from feature construction."
        ),
    }

    _json_dump(summary, metrics_dir / f"phase6_computed_features_summary_{app}.json")

    print(f"✅ Phase 6 complete app={app}")
    print(f"   Rows out : {rows_out:,}")
    print(f"   Features : {len(feature_cols):,} source cols | interactions={len(interaction_pairs):,} | norm={len(norm_cols):,}")
    print(f"   Output   : {_human_bytes(output_bytes)}")
    print(f"   Sample   : {df_sample.shape}")
    print(f"   Time     : {elapsed/60:.2f} minutes")

    return df_sample, summary


def phase6_computed_features(
    *,
    cfg: Phase6ComputedFeaturesConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    print("\n" + "🟠 " + "=" * 76)
    print("PHASE 6: COMPUTED FEATURES (APP-AWARE, SHARDED)")
    print("🟠 " + "=" * 76)

    t0 = datetime.now()

    samples_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        df_sample, summary = phase6_computed_features_for_app(app_norm, cfg=cfg)
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
            "feature_cols_count": int(s.get("feature_cols_count", 0)),
            "interaction_pairs_count": int(s.get("interaction_pairs_count", 0)),
            "n_norm": int(s.get("n_norm", 0)),
            "output_cols_min": int(s.get("output_cols_min", 0)),
            "output_cols_max": int(s.get("output_cols_max", 0)),
            "output_gib": float(s.get("output_gib", 0.0)),
            "shards_out": int(s.get("shards_out", 0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase6_computed_features_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows_out = int(sum(int(s.get("rows_out", 0)) for s in summaries.values()))
    total_output_bytes = int(sum(int(s.get("output_bytes", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 6,
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
            "Phase 6 is app-aware and reads Phase 5 app partitions. "
            "It no longer expects attacks/benign folders."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase6_computed_features_summary_all.json")

    print("\n✅ PHASE 6 COMPLETE")
    print(f"   Total rows out: {total_rows_out:,}")
    print(f"   Output size   : {_human_bytes(total_output_bytes)}")
    print(f"   Output dir    : {cfg.output_dir}")
    print(f"   Time          : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all


# Compatibility aliases.
def phase6_computed_features_sharded(
    *,
    cfg: Phase6ComputedFeaturesConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase6_computed_features(cfg=cfg)


def build_phase6_computed_features(
    *,
    cfg: Phase6ComputedFeaturesConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase6_computed_features(cfg=cfg)



# =============================================================================
# RAM MODE API (small-data seminar/PPT workflow)
# =============================================================================

def phase6_computed_features_ram(
    df: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase6ComputedFeaturesConfig] = None,
    seed: Optional[int] = None,
    n_selected: Optional[int] = None,
    max_interactions: Optional[int] = None,
    n_norm: Optional[int] = None,
    max_feature_cols_for_row_stats: Optional[int] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode Phase 6 for one already-active application.

    This is the small-data path used by the seminar/PPT workflow:
    - input is a Phase 5 DataFrame for ONE app;
    - output is a Phase 6 DataFrame in RAM;
    - no Parquet/CSV checkpoint is written;
    - summary is returned to pipeline.py, which stores it incrementally under
      metrics/phase6_summary.json -> by_app[app].

    Disk-backed functions above are preserved for the future 800M-line/400GB mode.
    """
    t0 = datetime.now()
    app = str(app).strip().lower() or "unknown"

    if cfg is None:
        cfg = Phase6ComputedFeaturesConfig(
            selected_apps=(app,),
            n_selected=int(n_selected) if n_selected is not None else 15,
            max_interactions=int(max_interactions) if max_interactions is not None else 20,
            n_norm=int(n_norm) if n_norm is not None else 10,
            seed=int(seed) if seed is not None else 42,
            max_feature_cols_for_row_stats=max_feature_cols_for_row_stats,
        )
    else:
        # Dataclass is frozen; make a copied config with per-call overrides.
        cfg = Phase6ComputedFeaturesConfig(
            input_dir=cfg.input_dir,
            output_dir=cfg.output_dir,
            selected_apps=cfg.selected_apps,
            write_format=cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
            raw_suffix=cfg.raw_suffix,
            n_selected=int(n_selected) if n_selected is not None else int(cfg.n_selected),
            max_interactions=int(max_interactions) if max_interactions is not None else int(cfg.max_interactions),
            n_norm=int(n_norm) if n_norm is not None else int(cfg.n_norm),
            exclude_from_features=cfg.exclude_from_features,
            thr_sample_rows_per_shard=cfg.thr_sample_rows_per_shard,
            thr_rowstd_sample_max=cfg.thr_rowstd_sample_max,
            seed=int(seed) if seed is not None else int(cfg.seed),
            return_df_sample=cfg.return_df_sample,
            overwrite=cfg.overwrite,
            gc_each_shard=cfg.gc_each_shard,
            max_feature_cols_for_row_stats=(
                max_feature_cols_for_row_stats
                if max_feature_cols_for_row_stats is not None
                else cfg.max_feature_cols_for_row_stats
            ),
        )

    if df is None or df.empty:
        return pd.DataFrame(), {
            "phase": 6,
            "app": app,
            "status": "empty_input",
            "mode": "ram",
            "rows_in": 0,
            "rows_out": 0,
            "cols_in": 0,
            "cols_out": 0,
            "seconds": 0.0,
        }

    if "Target" not in df.columns:
        raise RuntimeError("Target column missing in Phase 6 RAM input. Phase 4/5 must run first.")

    print(f"\n🟠 PHASE 6 RAM: Computed features for app={app}")
    print(f"   Input DataFrame : {df.shape[0]:,} rows × {df.shape[1]:,} cols")

    df_work = df.reset_index(drop=True).copy()
    if "application" not in df_work.columns:
        df_work["application"] = app

    df_work = ensure_numeric_except_raw(df_work, raw_suffix=cfg.raw_suffix)

    canonical_cols = list(df_work.columns)
    feature_cols = _select_feature_cols(
        canonical_cols,
        raw_suffix=cfg.raw_suffix,
        exclude_from_features=cfg.exclude_from_features,
        max_feature_cols_for_row_stats=cfg.max_feature_cols_for_row_stats,
    )

    if not feature_cols:
        raise RuntimeError(f"No feature columns found for Phase 6 RAM app={app}.")

    selected_features = feature_cols[: min(int(cfg.n_selected), len(feature_cols))]
    interaction_pairs = _plan_interactions(
        selected_features,
        max_interactions=int(cfg.max_interactions),
    )
    norm_cols = feature_cols[: min(int(cfg.n_norm), len(feature_cols))]

    global_max: Dict[str, float] = {}
    for c in norm_cols:
        try:
            global_max[c] = float(_to_numeric_safe(df_work[c]).max())
        except Exception:
            global_max[c] = 0.0

    # Threshold estimation from RAM DataFrame. For very wide/large data, sample rows
    # to avoid expensive full-matrix statistics. This does not affect the final
    # output rows; it only estimates thresholds for binary indicators.
    rng = np.random.default_rng(int(cfg.seed))
    n_rows = int(len(df_work))
    sample_n = min(n_rows, max(1, int(cfg.thr_rowstd_sample_max)))
    if sample_n < n_rows:
        take_idx = rng.choice(n_rows, size=sample_n, replace=False)
        df_thr = df_work.iloc[take_idx]
    else:
        df_thr = df_work

    X_thr = df_thr[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=np.float32, copy=False)
    X_thr = np.nan_to_num(X_thr, nan=0.0, posinf=0.0, neginf=0.0)
    thr_high = float(X_thr.mean() + X_thr.std()) if X_thr.size else 0.0
    rowstd = X_thr.astype(np.float64, copy=False).std(axis=1) if X_thr.size else np.array([], dtype=np.float64)
    thr_low_var = float(np.quantile(rowstd, 0.25)) if rowstd.size else 0.0

    del df_thr, X_thr, rowstd
    gc.collect()

    df_out = _compute_features_on_df(
        df_work,
        feature_cols=feature_cols,
        selected_features=selected_features,
        interaction_pairs=interaction_pairs,
        norm_cols=norm_cols,
        global_max=global_max,
        thr_high=thr_high,
        thr_low_var=thr_low_var,
        raw_suffix=cfg.raw_suffix,
    )

    target_counter: Counter = Counter()
    if "Target" in df_out.columns:
        target_counter.update(_to_numeric_safe(df_out["Target"]).astype(int).tolist())

    new_cols = [c for c in df_out.columns if c not in df.columns]
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 6,
        "app": app,
        "status": "completed",
        "mode": "ram",
        "rows_in": int(len(df)),
        "rows_out": int(len(df_out)),
        "cols_in": int(df.shape[1]),
        "cols_out": int(df_out.shape[1]),
        "canonical_cols_count": int(len(canonical_cols)),
        "feature_cols_count": int(len(feature_cols)),
        "selected_features_count": int(len(selected_features)),
        "selected_features": list(selected_features),
        "interaction_pairs_count": int(len(interaction_pairs)),
        "n_norm": int(len(norm_cols)),
        "norm_cols": list(norm_cols),
        "thr_high": float(thr_high),
        "thr_low_var": float(thr_low_var),
        "threshold_sample_rows": int(sample_n),
        "blocked_feature_cols": sorted(list(set(cfg.exclude_from_features))),
        "features_added_count": int(len(new_cols)),
        "features_added": new_cols,
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "write_output": False,
        "seconds": float(elapsed),
        "note": (
            "RAM mode computes interaction, row-stat, normalized, ratio, and binary features "
            "for one active application without writing Parquet/CSV checkpoints."
        ),
    }

    print(f"✅ Phase 6 RAM complete app={app}")
    print(f"   Rows out : {len(df_out):,}")
    print(f"   Cols out : {df_out.shape[1]:,}")
    print(f"   Added    : {len(new_cols):,} features")
    print(f"   Time     : {elapsed/60:.2f} minutes")

    return df_out, summary


# Compatibility aliases for pipeline RAM mode.
def phase6_computed_features_in_memory(
    df: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase6ComputedFeaturesConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase6_computed_features_ram(df, app=app, cfg=cfg, **kwargs)


def run_phase6_computed_features_ram(
    df: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase6ComputedFeaturesConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase6_computed_features_ram(df, app=app, cfg=cfg, **kwargs)

if __name__ == "__main__":
    samples, summary = phase6_computed_features(
        cfg=Phase6ComputedFeaturesConfig(
            input_dir=Path("results/phase5_feature_engineered_dataset"),
            output_dir=Path("results/phase6_computed_features_dataset"),
            selected_apps=("dns", "http", "tls", "ssh"),
            write_format="parquet",
            parquet_engine="fastparquet",
            parquet_compression="snappy",
            n_selected=15,
            max_interactions=20,
            n_norm=10,
            return_df_sample=100_000,
            overwrite=True,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
