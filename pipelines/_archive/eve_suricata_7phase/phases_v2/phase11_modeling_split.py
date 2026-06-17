# src/cbr/phases/phase11_modeling_split.py
from __future__ import annotations

import gc
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =============================================================================
# PHASE 11: MODELING SPLIT (APP-AWARE, SHARDED, DISK-BACKED)
# =============================================================================
# Purpose:
#   Build train/test modeling datasets per application after Phase 7 cleaning
#   and Phase 10 leakage analysis.
#
# Input:
#   results/phase7_clean_dataset/app={app}/part-*.parquet
#   results/phase10_correlation_leakage/app={app}/features_to_drop_{app}_{tag}.json
#
# Output:
#   results/modeling/app={app}/
#     train/part-*.parquet
#     test/part-*.parquet
#     meta.json
#
# Important:
#   - This phase no longer reads attacks/benign folders.
#   - It reads mixed-label app shards and splits by Target.
#   - It applies per-app features_to_drop from Phase 10 before modeling.
#   - It writes sharded train/test outputs to avoid one huge CSV/Parquet.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")

DEFAULT_EXTRA_DROP_COLS: Tuple[str, ...] = (
    # Defensive leakage list in case Phase 10 artifact is absent/incomplete.
    # Raw identifiers are allowed to exist until split time, but must not enter
    # model training as direct or hashed identifier features.
    "src_ip",
    "dest_ip",
    "timestamp",
    "flow_id",
    "community_id",
    "pkt_src",
    "tx_id",
    "is_malicious",
    "event_type",
    "event_type_h",
    "event_type_raw",
    "has_alert",
    "alert_category",
    "alert_category_h",
    "alert_severity",
    "alert_signature",
    "alert_signature_h",
    "alert_signature_id",
    "Target_prelim",
    "label_status",
    "label_status_h",
    "label_status_final",
    "label_status_final_h",
    "label_source",
    "label_source_h",
    "label_reason",
    "label_reason_h",
    "label_confidence",
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",
    "probe_score",
    "is_possible_probe",
    "probe_reason",
    "probe_reason_h",
    "window_start",
    "window_start_h",
)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Phase11ModelingSplitConfig:
    input_dir: Path = Path("results/phase7_clean_dataset")
    phase10_dir: Path = Path("results/phase10_correlation_leakage")
    output_dir: Path = Path("results/modeling")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    target_col: str = "Target"

    # Split strategy:
    #   "stratified_random" -> random by Target with class quotas
    #   "source_ip_hash"    -> deterministic split by src_ip hash; avoids source-IP overlap
    #
    # source_ip_hash is stricter methodologically, but may produce class imbalance.
    split_strategy: str = "stratified_random"
    source_ip_col: str = "src_ip"

    train_ratio: float = 0.80
    seed: int = 42

    # Class allocation:
    #   "balanced" -> same number of benign/malicious rows, bounded by minority class
    #   "preserve" -> preserve per-class availability according to train_ratio
    class_balance_mode: str = "balanced"

    # Optional caps for output size.
    # None/0 means no explicit cap beyond available data.
    max_train_rows: Optional[int] = 8_000_000
    max_test_rows: Optional[int] = 2_000_000
    min_attack_required: int = 50

    # Drop/clean model features.
    phase10_filename_tag: str = "run"
    extra_drop_cols: Tuple[str, ...] = DEFAULT_EXTRA_DROP_COLS
    drop_raw_cols_for_model: bool = True
    drop_non_numeric_for_model: bool = True
    coerce_numeric_like_for_model: bool = True
    numeric_coercion_min_fraction: float = 0.80

    # Schema probe
    schema_sample_files: int = 6
    schema_sample_rows_per_file: int = 2_000

    # Output format
    write_format: str = "parquet"  # "parquet" or "csv"
    parquet_engine: Optional[str] = "fastparquet"
    parquet_compression: Optional[str] = "snappy"
    compress_csv: bool = True

    # Return bounded in-memory samples for downstream smoke/debug only.
    return_train_rows: int = 100_000
    return_test_rows: int = 100_000

    overwrite: bool = True
    gc_each_shard: bool = True


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


def _file_size_bytes(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


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


def _ensure_python_str_series(s: pd.Series) -> pd.Series:
    out = s.astype("object")
    out = out.where(pd.notna(out), "")
    return out.astype(str)


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


def _read_shard_sample(path: Path, nrows: int, *, parquet_engine: Optional[str]) -> pd.DataFrame:
    nrows = max(1, int(nrows))

    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq  # type: ignore
            pf = pq.ParquetFile(path)
            batches = pf.iter_batches(batch_size=nrows)
            try:
                batch = next(batches)
            except StopIteration:
                return pd.DataFrame()
            return batch.to_pandas()
        except Exception:
            try:
                return pd.read_parquet(path, engine=parquet_engine).head(nrows) if parquet_engine else pd.read_parquet(path).head(nrows)
            except Exception:
                return pd.DataFrame()

    try:
        suffixes = "".join(path.suffixes).lower()
        if suffixes.endswith(".csv.gz"):
            return pd.read_csv(path, nrows=nrows, compression="gzip")
        return pd.read_csv(path, nrows=nrows)
    except Exception:
        return pd.DataFrame()


def _list_app_shards(input_dir: Path, app: str) -> List[Path]:
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


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        raise RuntimeError(f"Target column missing: {target_col}")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


def _counter_to_str_dict(c: Counter) -> Dict[str, int]:
    return {str(k): int(v) for k, v in c.items()}


# =============================================================================
# Feature drop / modeling transform helpers
# =============================================================================

_BOOL_STR_MAP = {
    "true": 1,
    "false": 0,
    "yes": 1,
    "no": 0,
    "y": 1,
    "n": 0,
    "t": 1,
    "f": 0,
    "on": 1,
    "off": 0,
}


def _series_to_numeric_like(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.astype("Int8")

    if pd.api.types.is_numeric_dtype(s):
        return s

    s_str = s.astype("string").str.strip()
    s_low = s_str.str.lower()
    mapped = s_low.map(_BOOL_STR_MAP)

    coerced_bool = mapped.astype("float64")
    coerced_num = pd.to_numeric(s_str, errors="coerce")

    out = coerced_num.copy()
    mask_fill = out.isna() & coerced_bool.notna()
    if mask_fill.any():
        out.loc[mask_fill] = coerced_bool.loc[mask_fill]
    return out


def _load_features_to_drop(path: Path) -> List[str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(obj, list):
        return [str(x) for x in obj if str(x).strip()]

    if isinstance(obj, dict):
        for key in ("features_to_drop_for_modeling", "features_to_drop", "drop_cols"):
            value = obj.get(key)
            if isinstance(value, list):
                return [str(x) for x in value if str(x).strip()]

    return []


def _find_phase10_drop_json(cfg: Phase11ModelingSplitConfig, app: str) -> Optional[Path]:
    app = str(app).strip().lower()
    tag = cfg.phase10_filename_tag.strip() or "run"

    app_dirs = [
        Path(cfg.phase10_dir) / f"app={app}",
        Path(cfg.phase10_dir) / app,
    ]

    exact_names = [
        f"features_to_drop_{app}_{tag}.json",
        f"features_to_drop_{tag}.json",
        f"features_to_drop_{app}.json",
        "features_to_drop.json",
    ]

    for d in app_dirs:
        for name in exact_names:
            p = d / name
            if p.exists():
                return p

        matches = sorted(d.glob("features_to_drop*.json"))
        if matches:
            return matches[0]

    return None


def _build_drop_plan(cfg: Phase11ModelingSplitConfig, app: str) -> Dict[str, Any]:
    phase10_drop_path = _find_phase10_drop_json(cfg, app)
    phase10_drop_cols = _load_features_to_drop(phase10_drop_path) if phase10_drop_path else []

    drop_cols = set(str(c) for c in cfg.extra_drop_cols if str(c).strip())
    for c in phase10_drop_cols:
        if c != cfg.target_col:
            drop_cols.add(c)

    drop_cols.discard(cfg.target_col)

    return {
        "phase10_drop_json": str(phase10_drop_path) if phase10_drop_path else None,
        "phase10_drop_cols": phase10_drop_cols,
        "extra_drop_cols": list(cfg.extra_drop_cols),
        "drop_cols": sorted(drop_cols),
        "drop_raw_cols_for_model": bool(cfg.drop_raw_cols_for_model),
        "drop_non_numeric_for_model": bool(cfg.drop_non_numeric_for_model),
        "coerce_numeric_like_for_model": bool(cfg.coerce_numeric_like_for_model),
        "numeric_coercion_min_fraction": float(cfg.numeric_coercion_min_fraction),
    }


def _maybe_drop_raw_cols(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    raw_cols = [c for c in df.columns if str(c).endswith("_raw")]
    if not raw_cols:
        return df, []
    return df.drop(columns=raw_cols, errors="ignore"), raw_cols


def _coerce_or_drop_feature_columns(
    df: pd.DataFrame,
    cfg: Phase11ModelingSplitConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    out = df.copy()

    coerced_numeric: List[str] = []
    dropped_non_numeric: List[str] = []
    kept_numeric: List[str] = []
    all_nan_after_coercion: List[str] = []
    conversion_details: Dict[str, Dict[str, Any]] = {}

    min_fraction = float(cfg.numeric_coercion_min_fraction)
    min_fraction = min(max(min_fraction, 0.0), 1.0)

    for c in list(out.columns):
        if c == cfg.target_col:
            continue

        s = out[c]

        if pd.api.types.is_bool_dtype(s):
            out[c] = s.astype("Int8")
            coerced_numeric.append(c)
            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": "bool_to_int",
                "src_non_null": int(s.notna().sum()),
                "numeric_non_null": int(out[c].notna().sum()),
                "numeric_fraction": 1.0,
            }
            continue

        if pd.api.types.is_numeric_dtype(s):
            out[c] = _to_numeric_safe(s)
            kept_numeric.append(c)
            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": "kept_numeric",
                "src_non_null": int(s.notna().sum()),
                "numeric_non_null": int(s.notna().sum()),
                "numeric_fraction": 1.0,
            }
            continue

        if not cfg.coerce_numeric_like_for_model:
            if cfg.drop_non_numeric_for_model:
                dropped_non_numeric.append(c)
                out = out.drop(columns=[c], errors="ignore")
            else:
                out[c] = _stable_hash_series(out[c])
                coerced_numeric.append(c)
            continue

        src_non_null = int(s.notna().sum())
        coerced = _series_to_numeric_like(s)
        numeric_non_null = int(coerced.notna().sum())
        frac = float(numeric_non_null / src_non_null) if src_non_null > 0 else 0.0

        if src_non_null > 0 and numeric_non_null == 0:
            all_nan_after_coercion.append(c)

        if numeric_non_null > 0 and frac >= min_fraction:
            out[c] = _to_numeric_safe(coerced)
            coerced_numeric.append(c)
            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": "coerced_numeric",
                "src_non_null": src_non_null,
                "numeric_non_null": numeric_non_null,
                "numeric_fraction": round(frac, 6),
            }
        else:
            if cfg.drop_non_numeric_for_model:
                dropped_non_numeric.append(c)
                out = out.drop(columns=[c], errors="ignore")
                action = "dropped_non_numeric"
            else:
                out[c] = _stable_hash_series(out[c])
                coerced_numeric.append(c)
                action = "hashed_non_numeric"

            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": action,
                "src_non_null": src_non_null,
                "numeric_non_null": numeric_non_null,
                "numeric_fraction": round(frac, 6),
            }

    return out, {
        "kept_numeric": kept_numeric,
        "coerced_numeric": coerced_numeric,
        "dropped_non_numeric": dropped_non_numeric,
        "all_nan_after_coercion": all_nan_after_coercion,
        "conversion_details": conversion_details,
        "final_columns_count_after_numeric_handling": int(len(out.columns)),
    }


def _apply_modeling_plan(
    df: pd.DataFrame,
    cfg: Phase11ModelingSplitConfig,
    plan: Dict[str, Any],
    *,
    final_feature_cols: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    out = df.copy()

    out[cfg.target_col] = _target_series(out, cfg.target_col)

    before_cols = list(out.columns)

    drop_cols = list(plan.get("drop_cols", []))
    if drop_cols:
        out = out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")

    raw_dropped: List[str] = []
    if plan.get("drop_raw_cols_for_model", True):
        out, raw_dropped = _maybe_drop_raw_cols(out)

    out, num_info = _coerce_or_drop_feature_columns(out, cfg)

    if final_feature_cols is not None:
        desired = [cfg.target_col] + [c for c in final_feature_cols if c != cfg.target_col]

        for c in desired:
            if c not in out.columns and c != cfg.target_col:
                out[c] = 0

        extra_cols = [c for c in out.columns if c not in desired]
        if extra_cols:
            out = out.drop(columns=extra_cols, errors="ignore")

        out = out[desired]

    # Final numeric hard pass.
    for c in out.columns:
        if c == cfg.target_col:
            continue
        if pd.api.types.is_numeric_dtype(out[c]):
            out[c] = _to_numeric_safe(out[c])
        else:
            # Last guard: either hash or drop should have handled it.
            if cfg.drop_non_numeric_for_model:
                out = out.drop(columns=[c], errors="ignore")
            else:
                out[c] = _stable_hash_series(out[c])

    out[cfg.target_col] = _target_series(out, cfg.target_col)

    after_cols = list(out.columns)

    info = {
        "before_columns_count": int(len(before_cols)),
        "after_columns_count": int(len(after_cols)),
        "drop_cols_applied_count": int(len(set(before_cols) - set(after_cols))),
        "phase10_drop_json": plan.get("phase10_drop_json"),
        "phase10_drop_cols_count": int(len(plan.get("phase10_drop_cols", []))),
        "raw_dropped": raw_dropped,
        "non_numeric_dropped": list(num_info.get("dropped_non_numeric", [])),
        "coerced_numeric": list(num_info.get("coerced_numeric", [])),
        "kept_numeric": list(num_info.get("kept_numeric", [])),
        "all_nan_after_coercion": list(num_info.get("all_nan_after_coercion", [])),
        "final_feature_columns": [c for c in after_cols if c != cfg.target_col],
    }

    return out, info


def _infer_final_feature_cols(
    shard_files: List[Path],
    *,
    cfg: Phase11ModelingSplitConfig,
    plan: Dict[str, Any],
) -> Tuple[List[str], Dict[str, Any]]:
    probe_files = list(shard_files[: max(1, int(cfg.schema_sample_files))])
    ordered_cols: List[str] = []
    seen_cols: set[str] = set()

    kept_accum: set[str] = set()
    coerced_accum: set[str] = set()
    dropped_accum: set[str] = set()

    for fp in probe_files:
        sample = _read_shard_sample(
            fp,
            int(cfg.schema_sample_rows_per_file),
            parquet_engine=cfg.parquet_engine,
        )
        if sample is None or sample.empty:
            continue

        transformed, info = _apply_modeling_plan(sample, cfg, plan, final_feature_cols=None)

        for c in transformed.columns:
            if c == cfg.target_col:
                continue
            if c not in seen_cols:
                ordered_cols.append(c)
                seen_cols.add(c)

        kept_accum.update(info.get("kept_numeric", []))
        coerced_accum.update(info.get("coerced_numeric", []))
        dropped_accum.update(info.get("non_numeric_dropped", []))

    if not ordered_cols:
        raise RuntimeError(
            "Failed to infer modeling feature schema. "
            "All probed shards became empty after drop/coercion."
        )

    info = {
        "probe_files": [str(p) for p in probe_files],
        "probe_files_count": int(len(probe_files)),
        "schema_sample_rows_per_file": int(cfg.schema_sample_rows_per_file),
        "final_feature_cols_count": int(len(ordered_cols)),
        "kept_from_probe": sorted(kept_accum),
        "coerced_from_probe": sorted(coerced_accum),
        "dropped_non_numeric_from_probe": sorted(dropped_accum),
    }

    return ordered_cols, info


# =============================================================================
# Output writers
# =============================================================================

class _PartWriter:
    def __init__(
        self,
        out_dir: Path,
        *,
        write_format: str,
        parquet_engine: Optional[str],
        parquet_compression: Optional[str],
        compress_csv: bool,
    ):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.write_format = (write_format or "parquet").lower().strip()
        self.parquet_engine = parquet_engine
        self.parquet_compression = parquet_compression
        self.compress_csv = bool(compress_csv)
        self.part = 0
        self.total_rows = 0
        self.total_bytes = 0

    def write(self, df: pd.DataFrame) -> Optional[Path]:
        if df is None or df.empty:
            return None

        self.part += 1

        if self.write_format == "parquet":
            path = self.out_dir / f"part-{self.part:06d}.parquet"

            for c in df.columns:
                if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == "object":
                    try:
                        df[c] = _ensure_python_str_series(df[c])
                    except Exception:
                        pass

            kwargs: Dict[str, Any] = {"index": False}
            if self.parquet_engine:
                kwargs["engine"] = self.parquet_engine
            if self.parquet_compression:
                kwargs["compression"] = self.parquet_compression

            try:
                df.to_parquet(path, **kwargs)
            except Exception:
                kwargs.pop("compression", None)
                df.to_parquet(path, **kwargs)
        else:
            suffix = ".csv.gz" if self.compress_csv else ".csv"
            path = self.out_dir / f"part-{self.part:06d}{suffix}"
            compression = "gzip" if self.compress_csv else None
            df.to_csv(path, index=False, compression=compression)

        nbytes = _file_size_bytes(path)
        self.total_rows += int(len(df))
        self.total_bytes += int(nbytes)
        return path


# =============================================================================
# Split planning
# =============================================================================

def _scan_counts_for_app(
    shard_files: List[Path],
    *,
    cfg: Phase11ModelingSplitConfig,
    app: str,
) -> Dict[str, Any]:
    rows_seen = 0
    bytes_seen = 0
    target_counter: Counter = Counter()

    for fp in tqdm(shard_files, desc=f"PHASE 11 scan app={app}", unit="shard", dynamic_ncols=True):
        bytes_seen += _file_size_bytes(fp)
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        y = _target_series(df, cfg.target_col)
        rows_seen += int(len(df))
        target_counter.update(y.astype(int).tolist())

        if cfg.gc_each_shard:
            del df
            gc.collect()

    return {
        "rows_seen": int(rows_seen),
        "bytes_seen": int(bytes_seen),
        "target_counts": target_counter,
    }


def _cap_class_counts(counts: Dict[int, int], max_total: Optional[int]) -> Dict[int, int]:
    if max_total is None or int(max_total) <= 0:
        return {int(k): int(v) for k, v in counts.items()}

    max_total = int(max_total)
    total = int(sum(counts.values()))
    if total <= max_total:
        return {int(k): int(v) for k, v in counts.items()}

    out = {int(k): int((int(v) / max(1, total)) * max_total) for k, v in counts.items()}

    # Ensure at least one row for non-empty classes if possible.
    for k, v in counts.items():
        if int(v) > 0 and out.get(int(k), 0) == 0 and sum(out.values()) < max_total:
            out[int(k)] = 1

    remaining = max_total - sum(out.values())
    for k, _v in sorted(counts.items(), key=lambda kv: int(kv[1]), reverse=True):
        if remaining <= 0:
            break
        kk = int(k)
        if out.get(kk, 0) < int(counts[kk]):
            out[kk] = out.get(kk, 0) + 1
            remaining -= 1

    while sum(out.values()) > max_total:
        kmax = max(out, key=lambda kk: out[kk])
        out[kmax] -= 1
        if out[kmax] <= 0:
            del out[kmax]

    return {int(k): int(v) for k, v in out.items() if int(v) > 0}


def _build_split_plan(
    target_counts: Counter,
    *,
    cfg: Phase11ModelingSplitConfig,
) -> Dict[str, Any]:
    n0 = int(target_counts.get(0, 0))
    n1 = int(target_counts.get(1, 0))

    if n1 < int(cfg.min_attack_required):
        raise RuntimeError(
            f"Attack rows too small for modeling: Target=1 available {n1:,}, "
            f"minimum required {int(cfg.min_attack_required):,}."
        )

    train_ratio = min(max(float(cfg.train_ratio), 0.0), 1.0)
    mode = str(cfg.class_balance_mode or "balanced").lower().strip()

    if mode == "preserve":
        train_counts = {
            0: int(round(n0 * train_ratio)),
            1: int(round(n1 * train_ratio)),
        }
        test_counts = {
            0: max(0, n0 - train_counts[0]),
            1: max(0, n1 - train_counts[1]),
        }
    else:
        # balanced default: use minority class for train/test by class.
        train_0 = int(round(n0 * train_ratio))
        train_1 = int(round(n1 * train_ratio))
        per_class_train = min(train_0, train_1)
        per_class_train = max(0, per_class_train)

        remain_0 = max(0, n0 - per_class_train)
        remain_1 = max(0, n1 - per_class_train)
        per_class_test = min(remain_0, remain_1)

        train_counts = {0: per_class_train, 1: per_class_train}
        test_counts = {0: per_class_test, 1: per_class_test}

    train_counts = _cap_class_counts(train_counts, cfg.max_train_rows)
    test_counts = _cap_class_counts(test_counts, cfg.max_test_rows)

    if int(train_counts.get(1, 0)) < int(cfg.min_attack_required):
        raise RuntimeError(
            f"Attack rows too small in training plan: Target=1 train {train_counts.get(1, 0):,}, "
            f"minimum required {int(cfg.min_attack_required):,}."
        )

    return {
        "class_balance_mode": mode,
        "train_ratio": float(train_ratio),
        "available_counts": {0: n0, 1: n1},
        "train_target_counts": {int(k): int(v) for k, v in train_counts.items()},
        "test_target_counts": {int(k): int(v) for k, v in test_counts.items()},
        "max_train_rows": int(cfg.max_train_rows) if cfg.max_train_rows else None,
        "max_test_rows": int(cfg.max_test_rows) if cfg.max_test_rows else None,
    }


def _take_for_split(
    df_cls: pd.DataFrame,
    *,
    cls: int,
    train_remaining: Dict[int, int],
    test_remaining: Dict[int, int],
    rng: np.random.Generator,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if df_cls is None or df_cls.empty:
        return df_cls.iloc[:0].copy(), df_cls.iloc[:0].copy()

    if len(df_cls) > 1:
        df_cls = df_cls.sample(frac=1.0, random_state=int(rng.integers(0, 2**31 - 1))).reset_index(drop=True)

    train_need = max(0, int(train_remaining.get(cls, 0)))
    test_need = max(0, int(test_remaining.get(cls, 0)))

    take_train = min(train_need, len(df_cls))
    df_train = df_cls.iloc[:take_train].copy()
    train_remaining[cls] = train_need - int(len(df_train))

    rest = df_cls.iloc[take_train:]
    take_test = min(test_need, len(rest))
    df_test = rest.iloc[:take_test].copy()
    test_remaining[cls] = test_need - int(len(df_test))

    return df_train, df_test


def _hash_split_by_source_ip(
    df: pd.DataFrame,
    *,
    cfg: Phase11ModelingSplitConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if cfg.source_ip_col not in df.columns:
        # fallback random
        mask = np.random.default_rng(cfg.seed).random(len(df)) < float(cfg.train_ratio)
        return df.loc[mask].copy(), df.loc[~mask].copy()

    src = df[cfg.source_ip_col].astype("string").fillna("unknown")
    h = pd.util.hash_pandas_object(src, index=False).astype("uint64")
    frac = (h % np.uint64(10_000_000)).astype("float64") / 10_000_000.0
    mask = frac < float(cfg.train_ratio)
    return df.loc[mask].copy(), df.loc[~mask].copy()


# =============================================================================
# Public API
# =============================================================================

def phase11_modeling_split_for_app(
    app: str,
    *,
    cfg: Phase11ModelingSplitConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    app = str(app).strip().lower()
    t0 = datetime.now()

    shard_files = _list_app_shards(cfg.input_dir, app)
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    train_dir = out_app_dir / "train"
    test_dir = out_app_dir / "test"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    if not shard_files:
        summary = {
            "phase": 11,
            "app": app,
            "status": "skipped_no_input_shards",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase11_modeling_split_summary_{app}.json")
        return {"df_train": pd.DataFrame(), "df_test": pd.DataFrame()}, summary

    print(f"\n🧩 PHASE 11: Modeling split for app={app}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    rng = np.random.default_rng(int(cfg.seed) + abs(hash(app)) % 100_000)

    drop_plan = _build_drop_plan(cfg, app)

    scan = _scan_counts_for_app(shard_files, cfg=cfg, app=app)
    split_plan = _build_split_plan(scan["target_counts"], cfg=cfg)

    final_feature_cols, schema_probe = _infer_final_feature_cols(
        shard_files,
        cfg=cfg,
        plan=drop_plan,
    )

    train_writer = _PartWriter(
        train_dir,
        write_format=cfg.write_format,
        parquet_engine=cfg.parquet_engine,
        parquet_compression=cfg.parquet_compression,
        compress_csv=cfg.compress_csv,
    )
    test_writer = _PartWriter(
        test_dir,
        write_format=cfg.write_format,
        parquet_engine=cfg.parquet_engine,
        parquet_compression=cfg.parquet_compression,
        compress_csv=cfg.compress_csv,
    )

    shuffled_files = list(shard_files)
    rng.shuffle(shuffled_files)

    train_remaining = {
        int(k): int(v)
        for k, v in split_plan["train_target_counts"].items()
    }
    test_remaining = {
        int(k): int(v)
        for k, v in split_plan["test_target_counts"].items()
    }

    train_written_counter: Counter = Counter()
    test_written_counter: Counter = Counter()
    rows_read = 0

    train_sample_parts: List[pd.DataFrame] = []
    test_sample_parts: List[pd.DataFrame] = []
    train_sample_left = max(0, int(cfg.return_train_rows))
    test_sample_left = max(0, int(cfg.return_test_rows))

    pbar = tqdm(shuffled_files, desc=f"PHASE 11 app={app}", unit="shard", dynamic_ncols=True)

    for fp in pbar:
        # Stop early when all quotas are satisfied in stratified mode.
        if cfg.split_strategy == "stratified_random":
            if sum(train_remaining.values()) <= 0 and sum(test_remaining.values()) <= 0:
                break

        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        rows_read += int(len(df))

        if cfg.split_strategy == "source_ip_hash":
            # Split BEFORE applying the modeling drop plan so source_ip can be used
            # as a grouping key, then drop source_ip from the actual model features.
            df_train_raw, df_test_raw = _hash_split_by_source_ip(df, cfg=cfg)

            df_train, _info_tr = _apply_modeling_plan(
                df_train_raw,
                cfg,
                drop_plan,
                final_feature_cols=final_feature_cols,
            )
            df_test, _info_te = _apply_modeling_plan(
                df_test_raw,
                cfg,
                drop_plan,
                final_feature_cols=final_feature_cols,
            )
        else:
            df_model, _info = _apply_modeling_plan(
                df,
                cfg,
                drop_plan,
                final_feature_cols=final_feature_cols,
            )

            if df_model.empty:
                if cfg.gc_each_shard:
                    del df, df_model
                    gc.collect()
                continue

            # Stratified random with explicit class quotas.
            parts_train: List[pd.DataFrame] = []
            parts_test: List[pd.DataFrame] = []
            for cls in (0, 1):
                sub = df_model[df_model[cfg.target_col] == int(cls)]
                if sub.empty:
                    continue
                tr, te = _take_for_split(
                    sub,
                    cls=int(cls),
                    train_remaining=train_remaining,
                    test_remaining=test_remaining,
                    rng=rng,
                )
                if not tr.empty:
                    parts_train.append(tr)
                if not te.empty:
                    parts_test.append(te)

            df_train = pd.concat(parts_train, ignore_index=True) if parts_train else df_model.iloc[:0].copy()
            df_test = pd.concat(parts_test, ignore_index=True) if parts_test else df_model.iloc[:0].copy()

        if not df_train.empty:
            train_writer.write(df_train)
            train_written_counter.update(_target_series(df_train, cfg.target_col).astype(int).tolist())
            if train_sample_left > 0:
                take = min(train_sample_left, len(df_train))
                train_sample_parts.append(df_train.iloc[:take].copy())
                train_sample_left -= take

        if not df_test.empty:
            test_writer.write(df_test)
            test_written_counter.update(_target_series(df_test, cfg.target_col).astype(int).tolist())
            if test_sample_left > 0:
                take = min(test_sample_left, len(df_test))
                test_sample_parts.append(df_test.iloc[:take].copy())
                test_sample_left -= take

        pbar.set_postfix({
            "train": f"{sum(train_written_counter.values()):,}",
            "test": f"{sum(test_written_counter.values()):,}",
        })

        if cfg.gc_each_shard:
            del df, df_model, df_train, df_test
            gc.collect()

    pbar.close()

    df_train_sample = pd.concat(train_sample_parts, ignore_index=True) if train_sample_parts else pd.DataFrame()
    df_test_sample = pd.concat(test_sample_parts, ignore_index=True) if test_sample_parts else pd.DataFrame()

    # Shuffle samples for downstream smoke/debug.
    if not df_train_sample.empty:
        df_train_sample = df_train_sample.sample(frac=1.0, random_state=cfg.seed).reset_index(drop=True)
    if not df_test_sample.empty:
        df_test_sample = df_test_sample.sample(frac=1.0, random_state=cfg.seed).reset_index(drop=True)

    elapsed = (datetime.now() - t0).total_seconds()

    meta = {
        "phase": 11,
        "app": app,
        "status": "completed",
        "input_dir": str(cfg.input_dir),
        "phase10_dir": str(cfg.phase10_dir),
        "output_dir": str(out_app_dir),
        "train_dir": str(train_dir),
        "test_dir": str(test_dir),
        "split_strategy": str(cfg.split_strategy),
        "source_ip_col": str(cfg.source_ip_col),
        "class_balance_mode": str(cfg.class_balance_mode),
        "seed": int(cfg.seed),
        "rows_seen_scan": int(scan["rows_seen"]),
        "rows_read_until_done": int(rows_read),
        "input_bytes": int(scan["bytes_seen"]),
        "input_size": _human_bytes(scan["bytes_seen"]),
        "target_counts_input": _counter_to_str_dict(scan["target_counts"]),
        "split_plan": split_plan,
        "drop_plan": drop_plan,
        "schema_probe": schema_probe,
        "stable_model_feature_count": int(len(final_feature_cols)),
        "stable_model_feature_columns": final_feature_cols,
        "train_rows_written": int(train_writer.total_rows),
        "test_rows_written": int(test_writer.total_rows),
        "train_target_counts": _counter_to_str_dict(train_written_counter),
        "test_target_counts": _counter_to_str_dict(test_written_counter),
        "train_parts_written": int(train_writer.part),
        "test_parts_written": int(test_writer.part),
        "train_bytes": int(train_writer.total_bytes),
        "test_bytes": int(test_writer.total_bytes),
        "train_size": _human_bytes(train_writer.total_bytes),
        "test_size": _human_bytes(test_writer.total_bytes),
        "df_train_sample_shape": [int(df_train_sample.shape[0]), int(df_train_sample.shape[1])],
        "df_test_sample_shape": [int(df_test_sample.shape[0]), int(df_test_sample.shape[1])],
        "write_format": cfg.write_format,
        "parquet_engine": cfg.parquet_engine,
        "parquet_compression": cfg.parquet_compression,
        "seconds": float(elapsed),
        "note": (
            "Phase 11 builds per-app modeling train/test shards after applying Phase 10 features_to_drop. "
            "Returned DataFrames are bounded samples only; full train/test outputs are on disk."
        ),
    }

    _json_dump(meta, out_app_dir / "meta.json")
    _json_dump(meta, metrics_dir / f"phase11_modeling_split_summary_{app}.json")

    print(f"✅ Phase 11 complete app={app}")
    print(f"   Train rows: {train_writer.total_rows:,} | dist={meta['train_target_counts']}")
    print(f"   Test rows : {test_writer.total_rows:,} | dist={meta['test_target_counts']}")
    print(f"   Features  : {len(final_feature_cols):,}")
    print(f"   Output    : {out_app_dir}")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    return {"df_train": df_train_sample, "df_test": df_test_sample}, meta


def phase11_modeling_split(
    *,
    cfg: Phase11ModelingSplitConfig,
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, Any]]:
    print("\n" + "🧩 " + "=" * 76)
    print("PHASE 11: MODELING SPLIT (APP-AWARE)")
    print("🧩 " + "=" * 76)

    t0 = datetime.now()

    samples_by_app: Dict[str, Dict[str, pd.DataFrame]] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        samples, summary = phase11_modeling_split_for_app(app_norm, cfg=cfg)
        samples_by_app[app_norm] = samples
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        rows.append({
            "app": app,
            "status": s.get("status"),
            "split_strategy": s.get("split_strategy"),
            "class_balance_mode": s.get("class_balance_mode"),
            "rows_seen_scan": int(s.get("rows_seen_scan", 0)),
            "train_rows_written": int(s.get("train_rows_written", 0)),
            "test_rows_written": int(s.get("test_rows_written", 0)),
            "stable_model_feature_count": int(s.get("stable_model_feature_count", 0)),
            "train_target_counts": json.dumps(s.get("train_target_counts", {})),
            "test_target_counts": json.dumps(s.get("test_target_counts", {})),
            "train_dir": s.get("train_dir"),
            "test_dir": s.get("test_dir"),
            "seconds": float(s.get("seconds", 0.0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase11_modeling_split_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_train = int(sum(int(s.get("train_rows_written", 0)) for s in summaries.values()))
    total_test = int(sum(int(s.get("test_rows_written", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 11,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "input_dir": str(cfg.input_dir),
        "phase10_dir": str(cfg.phase10_dir),
        "output_dir": str(cfg.output_dir),
        "total_train_rows_written": total_train,
        "total_test_rows_written": total_test,
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Phase 11 is app-aware and reads Phase 7 clean app partitions. "
            "It writes per-app train/test shards for Phase 12–14."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase11_modeling_split_summary_all.json")

    print("\n✅ PHASE 11 COMPLETE")
    print(f"   Total train rows: {total_train:,}")
    print(f"   Total test rows : {total_test:,}")
    print(f"   Output dir      : {cfg.output_dir}")
    print(f"   Time            : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all



# =============================================================================
# RAM MODE API (SMALL DATASET / PER-APP PIPELINE)
# =============================================================================

def _build_drop_plan_from_ram_inputs(
    cfg: Phase11ModelingSplitConfig,
    app: str,
    *,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build modeling drop plan without reading Phase 10 artifact from disk."""
    phase10_cols: List[str] = []

    if features_to_drop is not None:
        phase10_cols.extend([str(x) for x in features_to_drop if str(x).strip()])

    if isinstance(phase10_summary, dict):
        for key in ("features_to_drop_for_modeling", "features_to_drop", "drop_cols"):
            val = phase10_summary.get(key)
            if isinstance(val, list):
                phase10_cols.extend([str(x) for x in val if str(x).strip()])
                break

    # Fallback to disk artifact only if the caller did not pass Phase 10 summary.
    phase10_drop_path: Optional[Path] = None
    if not phase10_cols:
        phase10_drop_path = _find_phase10_drop_json(cfg, app)
        if phase10_drop_path:
            phase10_cols = _load_features_to_drop(phase10_drop_path)

    drop_cols = set(str(c) for c in cfg.extra_drop_cols if str(c).strip())
    for c in phase10_cols:
        if c != cfg.target_col:
            drop_cols.add(c)
    drop_cols.discard(cfg.target_col)

    return {
        "phase10_drop_json": str(phase10_drop_path) if phase10_drop_path else None,
        "phase10_drop_cols": list(dict.fromkeys(phase10_cols)),
        "extra_drop_cols": list(cfg.extra_drop_cols),
        "drop_cols": sorted(drop_cols),
        "drop_raw_cols_for_model": bool(cfg.drop_raw_cols_for_model),
        "drop_non_numeric_for_model": bool(cfg.drop_non_numeric_for_model),
        "coerce_numeric_like_for_model": bool(cfg.coerce_numeric_like_for_model),
        "numeric_coercion_min_fraction": float(cfg.numeric_coercion_min_fraction),
        "source": "ram_phase10_summary" if phase10_cols and phase10_drop_path is None else "disk_fallback_or_extra_only",
    }


def _shuffle_df_ram(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    if df is None or df.empty or len(df) <= 1:
        return df.copy() if df is not None else pd.DataFrame()
    return df.sample(frac=1.0, random_state=int(seed)).reset_index(drop=True)


def _align_model_frames(train_df: pd.DataFrame, test_df: pd.DataFrame, target_col: str) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """Ensure train/test have identical feature columns and ordering."""
    feature_cols: List[str] = []
    seen: set[str] = set()
    for frame in (train_df, test_df):
        for c in frame.columns:
            if c == target_col:
                continue
            if c not in seen:
                feature_cols.append(c)
                seen.add(c)

    desired = [target_col] + feature_cols
    for frame in (train_df, test_df):
        if target_col not in frame.columns:
            frame[target_col] = 0
        for c in feature_cols:
            if c not in frame.columns:
                frame[c] = 0

    return train_df[desired].copy(), test_df[desired].copy(), feature_cols


def _cap_frame_by_total(df: pd.DataFrame, max_rows: Optional[int], seed: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if max_rows is None or int(max_rows) <= 0 or len(df) <= int(max_rows):
        return df.copy()
    return df.sample(n=int(max_rows), random_state=int(seed)).reset_index(drop=True)


def phase11_modeling_split_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase11ModelingSplitConfig] = None,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
    write_metadata: bool = True,
    progress_desc: str = "PHASE 11",
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """
    RAM-mode Phase 11 for one active application.

    Input:
      df_clean from Phase 7 RAM mode.
      phase10_summary from Phase 10 RAM mode, used to drop leakage/invalid cols.

    Output:
      full df_train and df_test in RAM for Phase 12-14.

    This function does NOT write train/test Parquet shards. It may write only
    small metadata JSON files for reporting/resume visibility.
    """
    t0 = datetime.now()
    app = str(app).strip().lower()

    if cfg is None:
        cfg = Phase11ModelingSplitConfig(selected_apps=(app,))

    print(f"\n🧩 {progress_desc}: MODELING SPLIT RAM MODE app={app}")

    if df_clean is None or df_clean.empty:
        meta = {
            "phase": 11,
            "app": app,
            "status": "skipped_empty_input",
            "mode": "ram_per_app",
            "rows_seen": 0,
            "train_rows": 0,
            "test_rows": 0,
            "seconds": 0.0,
        }
        return {"df_train": pd.DataFrame(), "df_test": pd.DataFrame()}, meta

    if cfg.target_col not in df_clean.columns:
        raise RuntimeError(f"Target column missing in Phase 11 RAM input for app={app}: {cfg.target_col}")

    rows_seen = int(len(df_clean))
    y_full = _target_series(df_clean, cfg.target_col)
    target_counts = Counter(y_full.astype(int).tolist())

    if int(target_counts.get(1, 0)) < int(cfg.min_attack_required):
        meta = {
            "phase": 11,
            "app": app,
            "status": "skipped_insufficient_attack_rows",
            "mode": "ram_per_app",
            "rows_seen": rows_seen,
            "target_counts_input": _counter_to_str_dict(target_counts),
            "min_attack_required": int(cfg.min_attack_required),
            "train_rows": 0,
            "test_rows": 0,
            "seconds": float((datetime.now() - t0).total_seconds()),
            "note": "Not enough Target=1 rows to create a reliable modeling split for this app.",
        }
        return {"df_train": pd.DataFrame(), "df_test": pd.DataFrame()}, meta

    drop_plan = _build_drop_plan_from_ram_inputs(
        cfg,
        app,
        phase10_summary=phase10_summary,
        features_to_drop=features_to_drop,
    )

    split_strategy = str(cfg.split_strategy or "stratified_random").strip().lower()
    rng_seed = int(cfg.seed) + abs(hash(app)) % 100_000

    split_plan: Dict[str, Any]

    if split_strategy == "source_ip_hash":
        df_train_raw, df_test_raw = _hash_split_by_source_ip(df_clean, cfg=cfg)
        df_train, train_info = _apply_modeling_plan(df_train_raw, cfg, drop_plan, final_feature_cols=None)
        df_test, test_info = _apply_modeling_plan(df_test_raw, cfg, drop_plan, final_feature_cols=None)

        df_train = _cap_frame_by_total(df_train, cfg.max_train_rows, rng_seed)
        df_test = _cap_frame_by_total(df_test, cfg.max_test_rows, rng_seed + 1)
        df_train, df_test, final_feature_cols = _align_model_frames(df_train, df_test, cfg.target_col)

        split_plan = {
            "split_strategy": "source_ip_hash",
            "class_balance_mode": "hash_split_no_class_quota",
            "train_ratio": float(cfg.train_ratio),
            "available_counts": {int(k): int(v) for k, v in target_counts.items()},
            "max_train_rows": int(cfg.max_train_rows) if cfg.max_train_rows else None,
            "max_test_rows": int(cfg.max_test_rows) if cfg.max_test_rows else None,
        }
    else:
        split_plan = _build_split_plan(target_counts, cfg=cfg)
        df_model, model_info = _apply_modeling_plan(df_clean, cfg, drop_plan, final_feature_cols=None)
        final_feature_cols = [c for c in df_model.columns if c != cfg.target_col]

        train_remaining = {int(k): int(v) for k, v in split_plan["train_target_counts"].items()}
        test_remaining = {int(k): int(v) for k, v in split_plan["test_target_counts"].items()}
        rng = np.random.default_rng(rng_seed)

        train_parts: List[pd.DataFrame] = []
        test_parts: List[pd.DataFrame] = []

        for cls in sorted(set(list(train_remaining.keys()) + list(test_remaining.keys()))):
            sub = df_model[df_model[cfg.target_col] == int(cls)]
            if sub.empty:
                continue
            tr, te = _take_for_split(
                sub,
                cls=int(cls),
                train_remaining=train_remaining,
                test_remaining=test_remaining,
                rng=rng,
            )
            if not tr.empty:
                train_parts.append(tr)
            if not te.empty:
                test_parts.append(te)

        df_train = pd.concat(train_parts, ignore_index=True) if train_parts else df_model.iloc[:0].copy()
        df_test = pd.concat(test_parts, ignore_index=True) if test_parts else df_model.iloc[:0].copy()
        train_info = model_info
        test_info = model_info

    df_train = _shuffle_df_ram(df_train, rng_seed)
    df_test = _shuffle_df_ram(df_test, rng_seed + 1)
    df_train, df_test, final_feature_cols = _align_model_frames(df_train, df_test, cfg.target_col)

    train_counter = Counter(_target_series(df_train, cfg.target_col).astype(int).tolist()) if not df_train.empty else Counter()
    test_counter = Counter(_target_series(df_test, cfg.target_col).astype(int).tolist()) if not df_test.empty else Counter()

    elapsed = (datetime.now() - t0).total_seconds()
    train_mem = int(df_train.memory_usage(deep=True).sum()) if not df_train.empty else 0
    test_mem = int(df_test.memory_usage(deep=True).sum()) if not df_test.empty else 0

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"

    meta = {
        "phase": 11,
        "app": app,
        "status": "completed",
        "mode": "ram_per_app",
        "output_dir": str(out_app_dir),
        "split_strategy": split_strategy,
        "source_ip_col": str(cfg.source_ip_col),
        "class_balance_mode": str(cfg.class_balance_mode),
        "seed": int(cfg.seed),
        "rows_seen": rows_seen,
        "target_counts_input": _counter_to_str_dict(target_counts),
        "split_plan": split_plan,
        "drop_plan": drop_plan,
        "stable_model_feature_count": int(len(final_feature_cols)),
        "stable_model_feature_columns": final_feature_cols,
        "train_rows": int(len(df_train)),
        "test_rows": int(len(df_test)),
        "train_target_counts": _counter_to_str_dict(train_counter),
        "test_target_counts": _counter_to_str_dict(test_counter),
        "train_shape": [int(df_train.shape[0]), int(df_train.shape[1])],
        "test_shape": [int(df_test.shape[0]), int(df_test.shape[1])],
        "train_memory_mib": float(train_mem / (1024.0 ** 2)),
        "test_memory_mib": float(test_mem / (1024.0 ** 2)),
        "write_output": False,
        "train_transform_info": train_info,
        "test_transform_info": test_info,
        "seconds": float(elapsed),
        "note": (
            "RAM-mode Phase 11 creates full per-app train/test DataFrames in memory after applying "
            "Phase 10 leakage/invalid feature drops. No train/test Parquet shards are written."
        ),
    }

    if write_metadata:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        out_app_dir.mkdir(parents=True, exist_ok=True)
        _json_dump(meta, out_app_dir / "meta_ram.json")
        _json_dump(meta, metrics_dir / f"phase11_modeling_split_summary_{app}.json")

    print(f"✅ Phase 11 RAM complete app={app}")
    print(f"   Train rows : {len(df_train):,} | dist={meta['train_target_counts']}")
    print(f"   Test rows  : {len(df_test):,} | dist={meta['test_target_counts']}")
    print(f"   Features   : {len(final_feature_cols):,}")
    print(f"   Time       : {elapsed/60:.2f} minutes")

    gc.collect()
    return {"df_train": df_train, "df_test": df_test}, meta


# RAM-mode aliases for pipeline compatibility.
def phase11_modeling_split_in_memory(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase11ModelingSplitConfig] = None,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
    **kwargs: Any,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase11_modeling_split_ram(
        df_clean,
        app=app,
        cfg=cfg,
        phase10_summary=phase10_summary,
        features_to_drop=features_to_drop,
        **kwargs,
    )


def phase11_split_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase11ModelingSplitConfig] = None,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
    **kwargs: Any,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase11_modeling_split_ram(
        df_clean,
        app=app,
        cfg=cfg,
        phase10_summary=phase10_summary,
        features_to_drop=features_to_drop,
        **kwargs,
    )


def run_phase11_modeling_split_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase11ModelingSplitConfig] = None,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
    **kwargs: Any,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase11_modeling_split_ram(
        df_clean,
        app=app,
        cfg=cfg,
        phase10_summary=phase10_summary,
        features_to_drop=features_to_drop,
        **kwargs,
    )

# Compatibility alias.
def build_phase11_modeling_split(
    *,
    cfg: Phase11ModelingSplitConfig,
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, Any]]:
    return phase11_modeling_split(cfg=cfg)




# =============================================================================
# AIRC LEAKAGE-AWARE RAM OVERRIDE
# =============================================================================
# The definitions below intentionally override the earlier RAM function for the
# current AIRC/PPT run. Disk-backed functions above are kept unchanged.

AIRC_MODELING_DROP_COLS: Tuple[str, ...] = (
    # direct identifiers / absolute time
    "src_ip", "dest_ip", "src_ip_h", "dest_ip_h",
    "src_subnet24_h", "dest_subnet24_h",
    "timestamp", "timestamp_h", "first_seen", "last_seen", "first_seen_h", "last_seen_h",
    "flow_id", "flow_id_h", "community_id", "community_id_h", "pkt_src", "tx_id",

    # app-filter / raw categorical artifacts
    "app_filter_reason", "app_filter_reason_h",
    "event_type", "event_type_h", "event_type_raw",
    "proto", "proto_h", "proto_raw",
    "app_proto", "app_proto_h", "app_proto_raw",
    "application", "application_h", "application_raw",

    # alert-derived / target-prelim shortcuts
    "has_alert", "alert_category", "alert_category_h", "alert_severity",
    "alert_signature", "alert_signature_h", "alert_signature_id",
    "alert_count_window", "target_prelim_malicious_count",
    "Target_prelim", "is_malicious",

    # final label explanation / evidence shortcuts
    "label_status", "label_status_h", "label_status_final", "label_status_final_h",
    "label_source", "label_source_h", "label_reason", "label_reason_h", "label_confidence",
    "evidence_alert", "evidence_compromised_ip", "evidence_probe",

    # direct probing flags/scores.
    "probe_score", "is_possible_probe", "is_probe_suspicious",
    "probe_reason", "probe_reason_h", "window_start", "window_start_h",

    # Conservative final-validation guard:
    # these window aggregates are computed before train/test split, so keep them
    # for probing analysis/reporting but do not use them in modeling until they
    # are recomputed inside the train-only pipeline or validated with strict
    # source/time holdout.
    "event_count_window",
    "unique_dest_ip_window",
    "unique_dest_port_window",
    "alert_count_window",
    "target_prelim_malicious_count",
    "total_bytes_window",
    "total_pkts_window",
    "bytes_per_event_window",
    "pkts_per_event_window",
)


def _airc_unique(items: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        x = str(item).strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _airc_phase10_drop_cols(phase10_summary: Optional[Dict[str, Any]], features_to_drop: Optional[Sequence[str]]) -> List[str]:
    cols: List[str] = []
    if features_to_drop is not None:
        cols.extend([str(x) for x in features_to_drop if str(x).strip()])
    if isinstance(phase10_summary, dict):
        for key in ("features_to_drop_for_modeling", "features_to_drop", "drop_cols"):
            val = phase10_summary.get(key)
            if isinstance(val, list):
                cols.extend([str(x) for x in val if str(x).strip()])
                break
    return _airc_unique(cols)


def _airc_build_drop_plan_from_ram_inputs(
    cfg: Phase11ModelingSplitConfig,
    app: str,
    *,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    phase10_cols = _airc_phase10_drop_cols(phase10_summary, features_to_drop)

    # Disk fallback only if RAM Phase 10 did not pass a drop list.
    phase10_drop_path: Optional[Path] = None
    if not phase10_cols:
        phase10_drop_path = _find_phase10_drop_json(cfg, app)
        if phase10_drop_path:
            phase10_cols = _load_features_to_drop(phase10_drop_path)

    drop_cols = _airc_unique([
        *AIRC_MODELING_DROP_COLS,
        *list(cfg.extra_drop_cols or ()),
        *phase10_cols,
    ])
    drop_cols = [c for c in drop_cols if c != cfg.target_col]

    return {
        "phase10_drop_json": str(phase10_drop_path) if phase10_drop_path else None,
        "phase10_drop_cols": _airc_unique(phase10_cols),
        "extra_drop_cols": list(cfg.extra_drop_cols),
        "airc_modeling_drop_cols": list(AIRC_MODELING_DROP_COLS),
        "drop_cols": sorted(set(drop_cols)),
        "drop_raw_cols_for_model": bool(cfg.drop_raw_cols_for_model),
        "drop_non_numeric_for_model": bool(cfg.drop_non_numeric_for_model),
        "coerce_numeric_like_for_model": bool(cfg.coerce_numeric_like_for_model),
        "numeric_coercion_min_fraction": float(cfg.numeric_coercion_min_fraction),
        "source": "ram_phase10_summary" if phase10_cols and phase10_drop_path is None else "disk_fallback_or_extra_only",
        "leakage_policy": {
            "airc_guard": True,
            "drop_direct_identifiers": True,
            "drop_alert_derived_features": True,
            "drop_label_explanation_features": True,
            "drop_direct_probe_flags_scores": True,
            "note": (
                "Window aggregate behavioural features are not forcibly dropped here unless they are present in Phase 10 drops. "
                "Direct probe flags/scores and all label/alert shortcuts are removed before modeling."
            ),
        },
    }


def _airc_has_two_classes(df: pd.DataFrame, target_col: str) -> bool:
    if df is None or df.empty or target_col not in df.columns:
        return False
    try:
        return int(_target_series(df, target_col).nunique(dropna=True)) >= 2
    except Exception:
        return False


def _airc_drop_remaining_forbidden(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    final_feature_cols: List[str],
    drop_plan: Dict[str, Any],
    target_col: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str], List[str]]:
    forbidden = set(str(c) for c in drop_plan.get("drop_cols", []) if str(c).strip())
    remaining = [c for c in final_feature_cols if c in forbidden]

    if remaining:
        df_train = df_train.drop(columns=remaining, errors="ignore")
        df_test = df_test.drop(columns=remaining, errors="ignore")
        final_feature_cols = [c for c in final_feature_cols if c not in set(remaining)]
        desired = [target_col] + final_feature_cols
        for frame in (df_train, df_test):
            if target_col not in frame.columns:
                frame[target_col] = 0
            for c in final_feature_cols:
                if c not in frame.columns:
                    frame[c] = 0
        df_train = df_train[desired].copy()
        df_test = df_test[desired].copy()

    return df_train, df_test, final_feature_cols, remaining


def _airc_stratified_split_ram(
    df_clean: pd.DataFrame,
    *,
    cfg: Phase11ModelingSplitConfig,
    drop_plan: Dict[str, Any],
    seed: int,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any], Dict[str, Any], Dict[str, Any], List[str]]:
    y_full = _target_series(df_clean, cfg.target_col)
    target_counts = Counter(y_full.astype(int).tolist())
    split_plan = _build_split_plan(target_counts, cfg=cfg)

    df_model, model_info = _apply_modeling_plan(df_clean, cfg, drop_plan, final_feature_cols=None)
    final_feature_cols = [c for c in df_model.columns if c != cfg.target_col]

    train_remaining = {int(k): int(v) for k, v in split_plan["train_target_counts"].items()}
    test_remaining = {int(k): int(v) for k, v in split_plan["test_target_counts"].items()}
    rng = np.random.default_rng(seed)

    train_parts: List[pd.DataFrame] = []
    test_parts: List[pd.DataFrame] = []

    for cls in sorted(set(list(train_remaining.keys()) + list(test_remaining.keys()))):
        sub = df_model[df_model[cfg.target_col] == int(cls)]
        if sub.empty:
            continue
        tr, te = _take_for_split(
            sub,
            cls=int(cls),
            train_remaining=train_remaining,
            test_remaining=test_remaining,
            rng=rng,
        )
        if not tr.empty:
            train_parts.append(tr)
        if not te.empty:
            test_parts.append(te)

    df_train = pd.concat(train_parts, ignore_index=True) if train_parts else df_model.iloc[:0].copy()
    df_test = pd.concat(test_parts, ignore_index=True) if test_parts else df_model.iloc[:0].copy()
    return df_train, df_test, split_plan, model_info, model_info, final_feature_cols


def phase11_modeling_split_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase11ModelingSplitConfig] = None,
    phase10_summary: Optional[Dict[str, Any]] = None,
    features_to_drop: Optional[Sequence[str]] = None,
    write_metadata: bool = True,
    progress_desc: str = "PHASE 11",
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """
    AIRC-ready RAM-mode Phase 11.

    Main differences from the original RAM function:
      - always applies an additional conservative AIRC drop guard;
      - consumes Phase 10 RAM features_to_drop directly;
      - supports source_ip_hash split, with a safe fallback to stratified split
        if the hash split creates a one-class train/test set;
      - writes only small metadata JSON files, not train/test Parquet shards.
    """
    t0 = datetime.now()
    app = str(app).strip().lower()

    if cfg is None:
        cfg = Phase11ModelingSplitConfig(selected_apps=(app,))

    print(f"\n🧩 {progress_desc}: MODELING SPLIT RAM MODE app={app}")

    if df_clean is None or df_clean.empty:
        meta = {
            "phase": 11,
            "app": app,
            "status": "skipped_empty_input",
            "mode": "ram_per_app",
            "rows_seen": 0,
            "train_rows": 0,
            "test_rows": 0,
            "seconds": 0.0,
        }
        return {"df_train": pd.DataFrame(), "df_test": pd.DataFrame()}, meta

    if cfg.target_col not in df_clean.columns:
        raise RuntimeError(f"Target column missing in Phase 11 RAM input for app={app}: {cfg.target_col}")

    rows_seen = int(len(df_clean))
    y_full = _target_series(df_clean, cfg.target_col)
    target_counts = Counter(y_full.astype(int).tolist())

    if int(target_counts.get(1, 0)) < int(cfg.min_attack_required) or int(target_counts.get(0, 0)) <= 0:
        meta = {
            "phase": 11,
            "app": app,
            "status": "skipped_insufficient_or_single_class_rows",
            "mode": "ram_per_app",
            "rows_seen": rows_seen,
            "target_counts_input": _counter_to_str_dict(target_counts),
            "min_attack_required": int(cfg.min_attack_required),
            "train_rows": 0,
            "test_rows": 0,
            "seconds": float((datetime.now() - t0).total_seconds()),
            "note": "Not enough two-class data to create a reliable modeling split for this app.",
        }
        return {"df_train": pd.DataFrame(), "df_test": pd.DataFrame()}, meta

    drop_plan = _airc_build_drop_plan_from_ram_inputs(
        cfg,
        app,
        phase10_summary=phase10_summary,
        features_to_drop=features_to_drop,
    )

    requested_split_strategy = str(cfg.split_strategy or "stratified_random").strip().lower()
    effective_split_strategy = requested_split_strategy
    rng_seed = int(cfg.seed) + abs(hash(app)) % 100_000
    split_warnings: List[str] = []

    train_info: Dict[str, Any] = {}
    test_info: Dict[str, Any] = {}
    final_feature_cols: List[str] = []

    if requested_split_strategy == "source_ip_hash":
        df_train_raw, df_test_raw = _hash_split_by_source_ip(df_clean, cfg=cfg)
        raw_hash_train_counts = Counter(_target_series(df_train_raw, cfg.target_col).astype(int).tolist()) if not df_train_raw.empty else Counter()
        raw_hash_test_counts = Counter(_target_series(df_test_raw, cfg.target_col).astype(int).tolist()) if not df_test_raw.empty else Counter()

        if _airc_has_two_classes(df_train_raw, cfg.target_col) and _airc_has_two_classes(df_test_raw, cfg.target_col):
            df_train, train_info = _apply_modeling_plan(df_train_raw, cfg, drop_plan, final_feature_cols=None)
            df_test, test_info = _apply_modeling_plan(df_test_raw, cfg, drop_plan, final_feature_cols=None)
            df_train = _cap_frame_by_total(df_train, cfg.max_train_rows, rng_seed)
            df_test = _cap_frame_by_total(df_test, cfg.max_test_rows, rng_seed + 1)
            df_train, df_test, final_feature_cols = _align_model_frames(df_train, df_test, cfg.target_col)
            split_plan = {
                "split_strategy": "source_ip_hash",
                "class_balance_mode": "hash_split_preserve_distribution",
                "train_ratio": float(cfg.train_ratio),
                "available_counts": {int(k): int(v) for k, v in target_counts.items()},
                "raw_hash_train_counts": {int(k): int(v) for k, v in raw_hash_train_counts.items()},
                "raw_hash_test_counts": {int(k): int(v) for k, v in raw_hash_test_counts.items()},
                "max_train_rows": int(cfg.max_train_rows) if cfg.max_train_rows else None,
                "max_test_rows": int(cfg.max_test_rows) if cfg.max_test_rows else None,
            }
        else:
            split_warnings.append(
                "source_ip_hash split produced a one-class or empty train/test set; falling back to stratified_random."
            )
            effective_split_strategy = "stratified_random_fallback_from_source_ip_hash"
            df_train, df_test, split_plan, train_info, test_info, final_feature_cols = _airc_stratified_split_ram(
                df_clean,
                cfg=cfg,
                drop_plan=drop_plan,
                seed=rng_seed,
            )
    else:
        df_train, df_test, split_plan, train_info, test_info, final_feature_cols = _airc_stratified_split_ram(
            df_clean,
            cfg=cfg,
            drop_plan=drop_plan,
            seed=rng_seed,
        )

    df_train = _shuffle_df_ram(df_train, rng_seed)
    df_test = _shuffle_df_ram(df_test, rng_seed + 1)
    df_train, df_test, final_feature_cols = _align_model_frames(df_train, df_test, cfg.target_col)
    df_train, df_test, final_feature_cols, remaining_forbidden = _airc_drop_remaining_forbidden(
        df_train,
        df_test,
        final_feature_cols,
        drop_plan,
        cfg.target_col,
    )

    if remaining_forbidden:
        split_warnings.append(
            "Additional forbidden features were detected after alignment and removed: " + ", ".join(remaining_forbidden[:20])
        )

    train_counter = Counter(_target_series(df_train, cfg.target_col).astype(int).tolist()) if not df_train.empty else Counter()
    test_counter = Counter(_target_series(df_test, cfg.target_col).astype(int).tolist()) if not df_test.empty else Counter()

    elapsed = (datetime.now() - t0).total_seconds()
    train_mem = int(df_train.memory_usage(deep=True).sum()) if not df_train.empty else 0
    test_mem = int(df_test.memory_usage(deep=True).sum()) if not df_test.empty else 0

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"

    meta = {
        "phase": 11,
        "app": app,
        "status": "completed" if not df_train.empty and not df_test.empty else "completed_empty_split",
        "mode": "ram_per_app",
        "airc_leakage_aware": True,
        "output_dir": str(out_app_dir),
        "split_strategy": effective_split_strategy,
        "requested_split_strategy": requested_split_strategy,
        "source_ip_col": str(cfg.source_ip_col),
        "class_balance_mode": str(cfg.class_balance_mode),
        "seed": int(cfg.seed),
        "rows_seen": rows_seen,
        "target_counts_input": _counter_to_str_dict(target_counts),
        "split_plan": split_plan,
        "split_warnings": split_warnings,
        "drop_plan": drop_plan,
        "remaining_forbidden_features_removed_after_alignment": remaining_forbidden,
        "stable_model_feature_count": int(len(final_feature_cols)),
        "stable_model_feature_columns": final_feature_cols,
        "train_rows": int(len(df_train)),
        "test_rows": int(len(df_test)),
        "train_target_counts": _counter_to_str_dict(train_counter),
        "test_target_counts": _counter_to_str_dict(test_counter),
        "train_shape": [int(df_train.shape[0]), int(df_train.shape[1])],
        "test_shape": [int(df_test.shape[0]), int(df_test.shape[1])],
        "train_memory_mib": float(train_mem / (1024.0 ** 2)),
        "test_memory_mib": float(test_mem / (1024.0 ** 2)),
        "write_output": False,
        "train_transform_info": train_info,
        "test_transform_info": test_info,
        "seconds": float(elapsed),
        "note": (
            "AIRC-ready RAM-mode Phase 11 creates per-app train/test DataFrames in memory after applying "
            "strict alert/label/probe shortcut drops. No train/test Parquet shards are written."
        ),
    }

    if write_metadata:
        metrics_dir.mkdir(parents=True, exist_ok=True)
        out_app_dir.mkdir(parents=True, exist_ok=True)
        _json_dump(meta, out_app_dir / "meta_ram.json")
        _json_dump(meta, metrics_dir / f"phase11_modeling_split_summary_{app}.json")

    print(f"✅ Phase 11 RAM complete app={app}")
    print(f"   Split      : {effective_split_strategy}")
    print(f"   Train rows : {len(df_train):,} | dist={meta['train_target_counts']}")
    print(f"   Test rows  : {len(df_test):,} | dist={meta['test_target_counts']}")
    print(f"   Features   : {len(final_feature_cols):,}")
    print(f"   Drops      : {len(drop_plan.get('drop_cols', [])):,}")
    print(f"   Time       : {elapsed/60:.2f} minutes")

    gc.collect()
    return {"df_train": df_train, "df_test": df_test}, meta


if __name__ == "__main__":
    samples, summary = phase11_modeling_split(
        cfg=Phase11ModelingSplitConfig(
            input_dir=Path("results/phase7_clean_dataset"),
            phase10_dir=Path("results/phase10_correlation_leakage"),
            output_dir=Path("results/modeling"),
            selected_apps=("dns", "http", "tls", "ssh"),
            target_col="Target",
            split_strategy="stratified_random",
            class_balance_mode="balanced",
            train_ratio=0.80,
            max_train_rows=8_000_000,
            max_test_rows=2_000_000,
            min_attack_required=50,
            phase10_filename_tag="run",
            write_format="parquet",
            parquet_engine="fastparquet",
            parquet_compression="snappy",
            seed=42,
            overwrite=True,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
