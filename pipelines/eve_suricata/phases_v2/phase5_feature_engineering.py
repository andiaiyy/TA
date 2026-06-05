# src/cbr/phases/phase5_feature_engineering.py
from __future__ import annotations

import gc
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =============================================================================
# PHASE 5: FEATURE ENGINEERING (APP-AWARE, SHARDED, DISK-BACKED)
# =============================================================================
# Purpose:
#   Feature engineering after Phase 4 has finalized Target.
#
# Input:
#   results/phase4_labeled_dataset/app={app}/part-*.parquet
#
# Output:
#   results/phase5_feature_engineered_dataset/app={app}/part-*.parquet
#   results/phase5_feature_engineered_dataset/metrics/phase5_feature_engineering_summary_{app}.json
#   results/phase5_feature_engineered_dataset/metrics/phase5_feature_engineering_summary_all.json
#   results/phase5_feature_engineered_dataset/metrics/phase5_feature_engineering_summary_by_app.csv
#
# Important:
#   - This phase no longer reads attacks/benign folders.
#   - This phase works per application: dns/http/tls/ssh.
#   - Target is assumed to be final from Phase 4.
#   - Leakage/audit columns are preserved for later auditing, but must be dropped
#     before modeling in leakage/split phases.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")
RAW_SUFFIX_DEFAULT = "_raw"
RAW_KEEP_COLS_DEFAULT: Tuple[str, ...] = (
    "proto",
    "event_type",
    "application",
    "app_proto",
)


CANON_NUMERIC_COLS: Tuple[str, ...] = (
    "pkts_toserver",
    "pkts_toclient",
    "bytes_toserver",
    "bytes_toclient",
    "duration",
    "total_pkts",
    "total_bytes",
    "alert_severity",
    "has_alert",
    "src_port",
    "dest_port",
    "probe_score",
    "is_possible_probe",
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",
    "label_confidence",
)


LEAKAGE_AUDIT_COLS: Tuple[str, ...] = (
    "has_alert",
    "alert_category",
    "alert_severity",
    "Target_prelim",
    "label_status",
    "label_status_final",
    "label_source",
    "label_reason",
    "label_confidence",
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",
    "probe_score",
    "is_possible_probe",
    "probe_reason",
)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Phase5FeatureEngineeringConfig:
    input_dir: Path = Path("results/phase4_labeled_dataset")
    output_dir: Path = Path("results/phase5_feature_engineered_dataset")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    write_format: str = "parquet"  # "parquet" or "csv"
    parquet_engine: Optional[str] = "fastparquet"  # "fastparquet" | "pyarrow" | None
    parquet_compression: Optional[str] = "snappy"

    use_advanced_module: bool = True

    raw_keep_cols: Tuple[str, ...] = RAW_KEEP_COLS_DEFAULT
    raw_suffix: str = RAW_SUFFIX_DEFAULT
    hash_mod: int = 2**31 - 1

    return_df_sample: int = 100_000
    overwrite: bool = True
    gc_each_shard: bool = True

    # If true, keep object raw columns with *_raw suffix for visualization.
    # Other object/categorical columns are encoded to stable hash integers.
    keep_raw_columns_for_visualization: bool = True


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


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _find_col_by_tokens(df: pd.DataFrame, token_sets: Iterable[tuple[str, ...]]) -> Optional[str]:
    cols = list(df.columns)
    norm_map = {c: _norm_name(c) for c in cols}
    for toks in token_sets:
        toks = [t.lower() for t in toks]
        for c in cols:
            nc = norm_map[c]
            if all(t in nc for t in toks):
                return c
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
    """
    Stable integer encoding for categorical/text columns across shards.
    """
    s = s.astype("string").fillna("unknown")
    h = pd.util.hash_pandas_object(s, index=False).astype("uint64")
    return (h % np.uint64(mod)).astype("int64")


def _ensure_python_str_series(s: pd.Series) -> pd.Series:
    out = s.astype("object")
    out = out.where(pd.notna(out), "")
    return out.astype(str)


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


def _write_df(
    df: pd.DataFrame,
    path: Path,
    *,
    write_format: str,
    parquet_engine: Optional[str],
    parquet_compression: Optional[str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    # Fastparquet can be sensitive to pandas string extension arrays.
    # Normalize object/string cols to plain Python strings.
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == "object":
            try:
                df[c] = _ensure_python_str_series(df[c])
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
            # Some environments lack a codec. Retry without compression.
            kwargs.pop("compression", None)
            df.to_parquet(path, **kwargs)
    else:
        df.to_csv(path, index=False, compression="gzip")

    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


# =============================================================================
# Feature engineering helpers
# =============================================================================

def _ensure_flow_alert_totals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure canonical columns exist:
      pkts_toserver, pkts_toclient, bytes_toserver, bytes_toclient, duration,
      alert_severity, has_alert, total_pkts, total_bytes.
    """
    out = df

    if "pkts_toserver" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("pkts", "toserver"), ("pkt", "toserver"),
            ("flow", "pkts", "toserver"), ("flow", "pkt", "toserver"),
        ])
        out["pkts_toserver"] = _to_numeric_safe(out[c]) if c else 0

    if "pkts_toclient" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("pkts", "toclient"), ("pkt", "toclient"),
            ("flow", "pkts", "toclient"), ("flow", "pkt", "toclient"),
        ])
        out["pkts_toclient"] = _to_numeric_safe(out[c]) if c else 0

    if "bytes_toserver" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("bytes", "toserver"), ("byte", "toserver"),
            ("flow", "bytes", "toserver"), ("flow", "byte", "toserver"),
        ])
        out["bytes_toserver"] = _to_numeric_safe(out[c]) if c else 0

    if "bytes_toclient" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("bytes", "toclient"), ("byte", "toclient"),
            ("flow", "bytes", "toclient"), ("flow", "byte", "toclient"),
        ])
        out["bytes_toclient"] = _to_numeric_safe(out[c]) if c else 0

    if "duration" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("duration",), ("age",), ("flow", "age"), ("flow", "duration"),
        ])
        out["duration"] = _to_numeric_safe(out[c]) if c else 0

    if "alert_severity" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("alert", "severity"), ("alert_severity",), ("severity",),
        ])
        out["alert_severity"] = _to_numeric_safe(out[c]) if c else 0

    if "has_alert" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("has", "alert"), ("has_alert",),
        ])
        if c:
            out["has_alert"] = _to_numeric_safe(out[c]).astype(np.int8)
        else:
            out["has_alert"] = (_to_numeric_safe(out["alert_severity"]) > 0).astype(np.int8)

    if "total_pkts" not in out.columns:
        out["total_pkts"] = _to_numeric_safe(out["pkts_toserver"]) + _to_numeric_safe(out["pkts_toclient"])
    else:
        out["total_pkts"] = _to_numeric_safe(out["total_pkts"])

    if "total_bytes" not in out.columns:
        out["total_bytes"] = _to_numeric_safe(out["bytes_toserver"]) + _to_numeric_safe(out["bytes_toclient"])
    else:
        out["total_bytes"] = _to_numeric_safe(out["total_bytes"])

    return out


def _add_basic_domain_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Lightweight domain features that are safe to compute per shard.
    AdvancedFeatureEngineer can still add more features if available.
    """
    out = df

    for c in [
        "src_port", "dest_port",
        "pkts_toserver", "pkts_toclient",
        "bytes_toserver", "bytes_toclient",
        "duration", "total_pkts", "total_bytes",
    ]:
        if c in out.columns:
            out[c] = _to_numeric_safe(out[c])
        else:
            out[c] = 0

    eps = 1e-9
    duration_safe = out["duration"].replace(0, np.nan)

    out["bytes_per_pkt"] = out["total_bytes"] / out["total_pkts"].replace(0, np.nan)
    out["bytes_per_pkt"] = out["bytes_per_pkt"].replace([np.inf, -np.inf], np.nan).fillna(0)

    out["pkts_per_sec"] = out["total_pkts"] / duration_safe
    out["bytes_per_sec"] = out["total_bytes"] / duration_safe
    out["pkts_per_sec"] = out["pkts_per_sec"].replace([np.inf, -np.inf], np.nan).fillna(0)
    out["bytes_per_sec"] = out["bytes_per_sec"].replace([np.inf, -np.inf], np.nan).fillna(0)

    out["bytes_toserver_ratio"] = out["bytes_toserver"] / (out["total_bytes"] + eps)
    out["bytes_toclient_ratio"] = out["bytes_toclient"] / (out["total_bytes"] + eps)
    out["pkts_toserver_ratio"] = out["pkts_toserver"] / (out["total_pkts"] + eps)
    out["pkts_toclient_ratio"] = out["pkts_toclient"] / (out["total_pkts"] + eps)

    out["log_total_bytes"] = np.log1p(np.maximum(out["total_bytes"], 0))
    out["log_total_pkts"] = np.log1p(np.maximum(out["total_pkts"], 0))
    out["log_duration"] = np.log1p(np.maximum(out["duration"], 0))

    out["dport_is_dns"] = (out["dest_port"] == 53).astype(np.int8)
    out["dport_is_http"] = (out["dest_port"] == 80).astype(np.int8)
    out["dport_is_https"] = (out["dest_port"] == 443).astype(np.int8)
    out["dport_is_ssh"] = (out["dest_port"] == 22).astype(np.int8)

    if "timestamp" in out.columns:
        ts = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
        out["ts_hour"] = ts.dt.hour.fillna(0).astype(np.int16)
        out["ts_dow"] = ts.dt.dayofweek.fillna(0).astype(np.int16)
        out["ts_day"] = ts.dt.day.fillna(0).astype(np.int16)
    else:
        out["ts_hour"] = 0
        out["ts_dow"] = 0
        out["ts_day"] = 0

    return out


def _prepare_raw_backups(
    df: pd.DataFrame,
    *,
    raw_keep_cols: Sequence[str],
    raw_suffix: str,
    enabled: bool,
) -> Dict[str, pd.Series]:
    if not enabled:
        return {}

    backups: Dict[str, pd.Series] = {}
    for c in raw_keep_cols:
        raw_name = f"{c}{raw_suffix}"
        if c in df.columns:
            backups[raw_name] = df[c].astype("string").fillna("unknown").reset_index(drop=True)
        else:
            backups[raw_name] = pd.Series(["unknown"] * len(df), dtype="string")

    return backups


def _prepare_canon_backups(df: pd.DataFrame) -> Dict[str, pd.Series]:
    backups: Dict[str, pd.Series] = {}
    for c in CANON_NUMERIC_COLS:
        if c in df.columns:
            backups[c] = _to_numeric_safe(df[c]).reset_index(drop=True)
        else:
            backups[c] = pd.Series(np.zeros(len(df), dtype=np.float64))
    return backups


def _encode_leftover_categoricals(
    df: pd.DataFrame,
    *,
    raw_suffix: str,
    hash_mod: int,
) -> pd.DataFrame:
    """
    Ensure no unexpected object/string columns remain except *_raw.
    Target stays int.
    """
    out = df.copy()
    raw_cols = {c for c in out.columns if c.endswith(raw_suffix)}

    for col in list(out.columns):
        if col == "Target" or col in raw_cols:
            continue

        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = _to_numeric_safe(out[col])
            continue

        num_try = pd.to_numeric(out[col], errors="coerce")
        ratio = float(num_try.notna().mean()) if len(num_try) else 0.0
        if ratio >= 0.98:
            out[col] = _to_numeric_safe(out[col])
        else:
            out[col] = _stable_hash_series(out[col], mod=hash_mod)

    if "Target" not in out.columns:
        raise RuntimeError("Target missing after encoding. Phase 4 output is invalid.")

    out["Target"] = _to_numeric_safe(out["Target"]).astype(np.int8)
    return out


def _inline_feature_engineering(
    df: pd.DataFrame,
    *,
    raw_keep_cols: Sequence[str],
    raw_suffix: str,
    hash_mod: int,
    keep_raw_columns_for_visualization: bool,
) -> pd.DataFrame:
    out = df.reset_index(drop=True).copy()

    if "Target" not in out.columns:
        raise RuntimeError("Target missing. Phase 5 requires final Target from Phase 4.")

    out = _ensure_flow_alert_totals(out)
    out = _add_basic_domain_features(out)

    raw_backup = _prepare_raw_backups(
        out,
        raw_keep_cols=raw_keep_cols,
        raw_suffix=raw_suffix,
        enabled=keep_raw_columns_for_visualization,
    )

    for k, v in raw_backup.items():
        out[k] = v.values

    out = _encode_leftover_categoricals(out, raw_suffix=raw_suffix, hash_mod=hash_mod)
    out = _ensure_flow_alert_totals(out)
    out = _add_basic_domain_features(out)

    return out


def _load_advanced_feature_engineer() -> Any:
    """
    Try common import paths.
    """
    errors: List[str] = []

    try:
        from cbr.feature_engineering_advanced import AdvancedFeatureEngineer  # type: ignore
        return AdvancedFeatureEngineer
    except Exception as e:
        errors.append(f"cbr.feature_engineering_advanced: {repr(e)}")

    try:
        from src.cbr.feature_engineering_advanced import AdvancedFeatureEngineer  # type: ignore
        return AdvancedFeatureEngineer
    except Exception as e:
        errors.append(f"src.cbr.feature_engineering_advanced: {repr(e)}")

    raise ImportError("Failed to import AdvancedFeatureEngineer. " + " | ".join(errors))


def _process_dataframe_feature_engineering(
    df_in: pd.DataFrame,
    *,
    cfg: Phase5FeatureEngineeringConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Process one shard dataframe.
    """
    t0 = datetime.now()

    if df_in is None or df_in.empty:
        return pd.DataFrame(), {
            "input_shape": [0, 0],
            "output_shape": [0, 0],
            "engineer_loaded": False,
            "engineer_fail": None,
            "seconds": 0.0,
        }

    df_work = df_in.reset_index(drop=True).copy()

    if "Target" not in df_work.columns:
        raise RuntimeError("Target missing before Phase 5. Phase 4 label refinement must run first.")

    df_work["Target"] = _to_numeric_safe(df_work["Target"]).astype(np.int8)

    if "application" not in df_work.columns:
        df_work["application"] = "unknown"

    df_work = _ensure_flow_alert_totals(df_work)
    df_work = _add_basic_domain_features(df_work)

    raw_backup = _prepare_raw_backups(
        df_work,
        raw_keep_cols=cfg.raw_keep_cols,
        raw_suffix=cfg.raw_suffix,
        enabled=cfg.keep_raw_columns_for_visualization,
    )
    canon_backup = _prepare_canon_backups(df_work)
    target_backup = df_work["Target"].reset_index(drop=True)

    engineer_loaded = False
    engineer_fail: Optional[str] = None
    df_proc: Optional[pd.DataFrame] = None

    if cfg.use_advanced_module:
        try:
            AdvancedFeatureEngineer = _load_advanced_feature_engineer()
            engineer = AdvancedFeatureEngineer(verbose=False)
            tmp = engineer.process_dataframe(df_work).reset_index(drop=True)

            if len(tmp) != len(df_work):
                raise RuntimeError(
                    f"AdvancedFeatureEngineer changed row count: {len(df_work)} -> {len(tmp)}"
                )

            engineer_loaded = True

            tmp["Target"] = target_backup.values

            for k, v in raw_backup.items():
                tmp[k] = v.values

            for k, v in canon_backup.items():
                tmp[k] = v.values

            if "application" not in tmp.columns and "application" in df_work.columns:
                tmp["application"] = df_work["application"].values

            tmp = _ensure_flow_alert_totals(tmp)
            tmp = _add_basic_domain_features(tmp)

            df_proc = _encode_leftover_categoricals(
                tmp,
                raw_suffix=cfg.raw_suffix,
                hash_mod=cfg.hash_mod,
            )

        except Exception as e:
            engineer_fail = repr(e)
            df_proc = None

    if df_proc is None:
        df_proc = _inline_feature_engineering(
            df_work,
            raw_keep_cols=cfg.raw_keep_cols,
            raw_suffix=cfg.raw_suffix,
            hash_mod=cfg.hash_mod,
            keep_raw_columns_for_visualization=cfg.keep_raw_columns_for_visualization,
        )

    for col in df_proc.columns:
        if col == "Target" or col.endswith(cfg.raw_suffix):
            continue
        if pd.api.types.is_numeric_dtype(df_proc[col]):
            df_proc[col] = df_proc[col].replace([np.inf, -np.inf], np.nan).fillna(0)

    df_proc["Target"] = _to_numeric_safe(df_proc["Target"]).astype(np.int8)
    df_proc = _ensure_flow_alert_totals(df_proc)

    elapsed = (datetime.now() - t0).total_seconds()
    raw_cols = [c for c in df_proc.columns if c.endswith(cfg.raw_suffix)]
    numeric_cols_count = int(sum(pd.api.types.is_numeric_dtype(df_proc[c]) for c in df_proc.columns))
    object_cols = [c for c in df_proc.columns if df_proc[c].dtype == "object" and not c.endswith(cfg.raw_suffix)]

    info = {
        "input_shape": [int(df_in.shape[0]), int(df_in.shape[1])],
        "output_shape": [int(df_proc.shape[0]), int(df_proc.shape[1])],
        "engineer_loaded": bool(engineer_loaded),
        "engineer_fail": engineer_fail,
        "raw_cols": raw_cols,
        "numeric_cols_count": numeric_cols_count,
        "unexpected_object_cols": object_cols[:50],
        "seconds": float(elapsed),
    }

    return df_proc, info


# =============================================================================
# Public API
# =============================================================================

def phase5_feature_engineering_for_app(
    app: str,
    *,
    cfg: Phase5FeatureEngineeringConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Run Phase 5 for a single app.
    """
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
            "phase": 5,
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
        _json_dump(summary, metrics_dir / f"phase5_feature_engineering_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\n🟢 PHASE 5: Feature engineering for app={app}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    sample_chunks: List[pd.DataFrame] = []
    sample_left = max(0, int(cfg.return_df_sample))

    rows_in = 0
    rows_out = 0
    shards_out = 0
    output_bytes = 0
    engineer_loaded_count = 0
    engineer_fail_counter: Counter = Counter()
    target_counter: Counter = Counter()
    feature_count_min: Optional[int] = None
    feature_count_max: Optional[int] = None
    unexpected_object_cols: set[str] = set()

    pbar = tqdm(shard_files, desc=f"PHASE 5 app={app}", unit="shard", dynamic_ncols=True)

    for idx, fp in enumerate(pbar, start=1):
        df_in = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df_in is None or df_in.empty:
            if cfg.gc_each_shard:
                del df_in
                gc.collect()
            continue

        rows_in += int(len(df_in))

        df_proc, info = _process_dataframe_feature_engineering(df_in, cfg=cfg)
        rows_out += int(len(df_proc))

        if info.get("engineer_loaded"):
            engineer_loaded_count += 1
        if info.get("engineer_fail"):
            engineer_fail_counter[str(info["engineer_fail"])] += 1

        for c in info.get("unexpected_object_cols", []):
            unexpected_object_cols.add(str(c))

        ncols = int(df_proc.shape[1])
        feature_count_min = ncols if feature_count_min is None else min(feature_count_min, ncols)
        feature_count_max = ncols if feature_count_max is None else max(feature_count_max, ncols)

        if "Target" in df_proc.columns:
            target_counter.update(_to_numeric_safe(df_proc["Target"]).astype(int).tolist())

        if cfg.write_format == "parquet":
            out_name = f"part-{idx:06d}.parquet"
        else:
            out_name = f"part-{idx:06d}.csv.gz"

        out_path = out_app_dir / out_name
        bytes_written = _write_df(
            df_proc,
            out_path,
            write_format=cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
        )
        output_bytes += int(bytes_written)
        shards_out += 1

        if sample_left > 0:
            take_n = min(sample_left, len(df_proc))
            sample_chunks.append(df_proc.iloc[:take_n].copy())
            sample_left -= take_n

        pbar.set_postfix({
            "rows": f"{rows_out:,}",
            "cols": f"{ncols}",
            "size": _human_bytes(output_bytes),
        })

        if cfg.gc_each_shard:
            del df_in, df_proc
            gc.collect()

    pbar.close()

    df_sample = pd.concat(sample_chunks, ignore_index=True) if sample_chunks else pd.DataFrame()
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 5,
        "app": app,
        "status": "completed",
        "input_dir": str(cfg.input_dir),
        "output_dir": str(out_app_dir),
        "selected_apps": list(cfg.selected_apps),
        "write_format": cfg.write_format,
        "parquet_engine": cfg.parquet_engine,
        "parquet_compression": cfg.parquet_compression,
        "use_advanced_module": bool(cfg.use_advanced_module),
        "raw_keep_cols": list(cfg.raw_keep_cols),
        "raw_suffix": cfg.raw_suffix,
        "keep_raw_columns_for_visualization": bool(cfg.keep_raw_columns_for_visualization),
        "shards_in": int(len(shard_files)),
        "shards_out": int(shards_out),
        "rows_in": int(rows_in),
        "rows_out": int(rows_out),
        "feature_count_min": int(feature_count_min or 0),
        "feature_count_max": int(feature_count_max or 0),
        "engineer_loaded_shards": int(engineer_loaded_count),
        "engineer_fail_counter_top5": dict(engineer_fail_counter.most_common(5)),
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "unexpected_object_cols": sorted(unexpected_object_cols),
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "output_bytes": int(output_bytes),
        "output_gib": float(_gib(output_bytes)),
        "seconds": float(elapsed),
        "leakage_audit_cols_present": [
            c for c in LEAKAGE_AUDIT_COLS
            if (not df_sample.empty and c in df_sample.columns)
        ],
        "note_leakage": (
            "Phase 5 preserves label/evidence audit columns if present. "
            "They must be removed before modeling by the leakage/split phases."
        ),
    }

    _json_dump(summary, metrics_dir / f"phase5_feature_engineering_summary_{app}.json")

    print(f"✅ Phase 5 complete app={app}")
    print(f"   Rows out: {rows_out:,}")
    print(f"   Output  : {_human_bytes(output_bytes)}")
    print(f"   Sample  : {df_sample.shape}")
    print(f"   Time    : {elapsed/60:.2f} minutes")

    return df_sample, summary


def phase5_feature_engineering(
    *,
    cfg: Phase5FeatureEngineeringConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """
    Run Phase 5 for all selected apps.
    """
    print("\n" + "🟢 " + "=" * 76)
    print("PHASE 5: FEATURE ENGINEERING (APP-AWARE, SHARDED)")
    print("🟢 " + "=" * 76)

    t0 = datetime.now()

    samples_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        df_sample, summary = phase5_feature_engineering_for_app(app_norm, cfg=cfg)
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
            "feature_count_min": int(s.get("feature_count_min", 0)),
            "feature_count_max": int(s.get("feature_count_max", 0)),
            "shards_out": int(s.get("shards_out", 0)),
            "output_gib": float(s.get("output_gib", 0.0)),
            "engineer_loaded_shards": int(s.get("engineer_loaded_shards", 0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase5_feature_engineering_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows_out = int(sum(int(s.get("rows_out", 0)) for s in summaries.values()))
    total_output_bytes = int(sum(int(s.get("output_bytes", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 5,
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
            "Phase 5 is app-aware and reads Phase 4 labeled app partitions. "
            "It no longer expects attacks/benign folders."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase5_feature_engineering_summary_all.json")

    print("\n✅ PHASE 5 COMPLETE")
    print(f"   Total rows out: {total_rows_out:,}")
    print(f"   Output size   : {_human_bytes(total_output_bytes)}")
    print(f"   Output dir    : {cfg.output_dir}")
    print(f"   Time          : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all


# =============================================================================
# RAM MODE API (SMALL DATASET / SEMINAR MODE)
# =============================================================================

def phase5_feature_engineering_ram(
    df: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase5FeatureEngineeringConfig] = None,
    use_advanced_module: Optional[bool] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode Phase 5 for the small-data seminar pipeline.

    This function keeps the Phase 5 feature-engineering logic, but avoids all
    disk-backed behavior:
      - no shard reading;
      - no Parquet/CSV writing;
      - no output dataset checkpoint;
      - returns the full feature-engineered DataFrame for the active app.

    Expected flow:
      df_phase4 -> phase5_feature_engineering_ram(...) -> df_phase5

    Disk-backed Phase 5 remains available through phase5_feature_engineering(...)
    for the future 800M-line / 400GB mode.
    """
    t0 = datetime.now()
    app = str(app).strip().lower() or "unknown"

    if cfg is None:
        cfg = Phase5FeatureEngineeringConfig(
            selected_apps=(app,),
            use_advanced_module=True,
            return_df_sample=0,
            overwrite=False,
        )
    else:
        # Ensure the active app is reflected in the summary/config context.
        cfg = replace(cfg, selected_apps=(app,))

    if use_advanced_module is not None:
        cfg = replace(cfg, use_advanced_module=bool(use_advanced_module))

    if df is None or df.empty:
        elapsed = (datetime.now() - t0).total_seconds()
        summary = {
            "phase": 5,
            "phase_name": "feature_engineering",
            "mode": "ram",
            "app": app,
            "status": "skipped_empty_input",
            "rows_in": 0,
            "rows_out": 0,
            "cols_in": 0,
            "cols_out": 0,
            "features_added": [],
            "features_added_count": 0,
            "target_counts": {},
            "seconds": float(elapsed),
            "note_storage": "RAM mode does not write Parquet/CSV checkpoints.",
        }
        return pd.DataFrame(), summary

    if "Target" not in df.columns:
        raise RuntimeError("Phase 5 RAM requires final Target from Phase 4.")

    df_in = df.reset_index(drop=True).copy()
    if "application" not in df_in.columns:
        df_in["application"] = app
    else:
        df_in["application"] = df_in["application"].where(pd.notna(df_in["application"]), app).astype(str)

    input_cols = list(df_in.columns)
    df_out, info = _process_dataframe_feature_engineering(df_in, cfg=cfg)

    if "application" not in df_out.columns:
        df_out["application"] = app

    # Target distribution after feature engineering.
    if "Target" in df_out.columns:
        target_counter = Counter(_to_numeric_safe(df_out["Target"]).astype(int).tolist())
    else:
        target_counter = Counter()

    added_cols = [c for c in df_out.columns if c not in input_cols]
    leakage_present = [c for c in LEAKAGE_AUDIT_COLS if c in df_out.columns]
    numeric_cols_count = int(sum(pd.api.types.is_numeric_dtype(df_out[c]) for c in df_out.columns))
    object_cols = [
        c for c in df_out.columns
        if df_out[c].dtype == "object" and not str(c).endswith(cfg.raw_suffix)
    ]

    elapsed = (datetime.now() - t0).total_seconds()
    summary = {
        "phase": 5,
        "phase_name": "feature_engineering",
        "mode": "ram",
        "app": app,
        "status": "completed",
        "rows_in": int(df.shape[0]),
        "rows_out": int(df_out.shape[0]),
        "cols_in": int(df.shape[1]),
        "cols_out": int(df_out.shape[1]),
        "features_added": added_cols,
        "features_added_count": int(len(added_cols)),
        "numeric_cols_count": int(numeric_cols_count),
        "unexpected_object_cols": object_cols[:50],
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "engineer_loaded": bool(info.get("engineer_loaded", False)),
        "engineer_fail": info.get("engineer_fail"),
        "raw_keep_cols": list(cfg.raw_keep_cols),
        "raw_suffix": str(cfg.raw_suffix),
        "use_advanced_module": bool(cfg.use_advanced_module),
        "keep_raw_columns_for_visualization": bool(cfg.keep_raw_columns_for_visualization),
        "leakage_audit_cols_present": leakage_present,
        "seconds": float(elapsed),
        "note_storage": "RAM mode returns df_phase5 and does not write Parquet/CSV checkpoints.",
        "note_leakage": (
            "Phase 5 may preserve label/evidence audit columns if present. "
            "They must be removed before modeling by later leakage/split phases."
        ),
    }

    gc.collect()
    return df_out, summary


# Compatibility aliases for RAM-mode pipeline imports.
def phase5_feature_engineering_in_memory(
    df: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase5FeatureEngineeringConfig] = None,
    use_advanced_module: Optional[bool] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase5_feature_engineering_ram(
        df,
        app=app,
        cfg=cfg,
        use_advanced_module=use_advanced_module,
    )


def run_phase5_feature_engineering_ram(
    df: pd.DataFrame,
    *,
    app: str = "unknown",
    cfg: Optional[Phase5FeatureEngineeringConfig] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase5_feature_engineering_ram(df, app=app, cfg=cfg)



# Compatibility aliases.
def phase5_advanced_feature_engineering_sharded(
    *,
    cfg: Phase5FeatureEngineeringConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase5_feature_engineering(cfg=cfg)


def build_phase5_feature_engineering(
    *,
    cfg: Phase5FeatureEngineeringConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase5_feature_engineering(cfg=cfg)


if __name__ == "__main__":
    samples, summary = phase5_feature_engineering(
        cfg=Phase5FeatureEngineeringConfig(
            input_dir=Path("results/phase4_labeled_dataset"),
            output_dir=Path("results/phase5_feature_engineered_dataset"),
            selected_apps=("dns", "http", "tls", "ssh"),
            write_format="parquet",
            parquet_engine="fastparquet",
            parquet_compression="snappy",
            use_advanced_module=True,
            return_df_sample=100_000,
            overwrite=True,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
