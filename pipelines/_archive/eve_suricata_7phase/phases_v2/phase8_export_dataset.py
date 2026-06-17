# src/cbr/phases/phase8_export_dataset.py
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
# PHASE 8: EXPORT PROCESSED DATASET (APP-AWARE, SHARDED-SAFE)
# =============================================================================
# Purpose:
#   Export/audit checkpoint after Phase 7 clean dataset.
#
# Input:
#   results/phase7_clean_dataset/app={app}/part-*.parquet
#
# Output:
#   results/phase8_export_dataset/app={app}/
#     schema.json
#     manifest.csv
#     sample/eve_processed_{app}_sample{N}.csv
#     sample/eve_processed_{app}_sample{N}.parquet
#
#   results/phase8_export_dataset/metrics/
#     phase8_export_summary_{app}.json
#     phase8_export_summary_all.json
#     phase8_export_summary_by_app.csv
#
# Important:
#   - Default mode is sample_csv, not full export.
#   - This phase no longer receives one in-memory DataFrame.
#   - This phase no longer assumes attacks/benign folders.
#   - Full copy/export is optional because Phase 7 already stores the main clean
#     dataset checkpoint.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")


@dataclass(frozen=True)
class Phase8ExportConfig:
    input_dir: Path = Path("results/phase7_clean_dataset")
    output_dir: Path = Path("results/phase8_export_dataset")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    # Export modes:
    #   "none"          -> only summary/manifest/schema
    #   "manifest_only" -> same as none, clearer name
    #   "sample_csv"    -> export sampled CSV per app
    #   "sample_parquet"-> export sampled Parquet per app
    #   "sample_both"   -> export sampled CSV + Parquet per app
    #   "copy_shards"   -> copy full clean shards into phase8 output/app={app}/shards/
    #
    # Avoid full CSV export for 400GB-scale data.
    mode: str = "sample_csv"

    sample_rows: int = 200_000
    filename_stem: str = "eve_processed"
    sample_size_tag: str = "NA"

    include_columns: Optional[Tuple[str, ...]] = None
    index: bool = False

    # Deterministic sampling.
    seed: int = 42
    stratify: bool = True
    stratify_col: str = "Target"

    # IO format/read/write
    parquet_engine: Optional[str] = "fastparquet"
    parquet_compression: Optional[str] = "snappy"

    overwrite: bool = True
    gc_each_shard: bool = True


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


def _select_columns(df: pd.DataFrame, include_columns: Optional[Sequence[str]]) -> pd.DataFrame:
    if include_columns is None:
        return df

    cols = [c for c in include_columns if c in df.columns]
    if not cols:
        return df.iloc[:, 0:0].copy()
    return df[cols].copy()


def _schema_from_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for c in df.columns:
        s = df[c]
        rows.append({
            "column": str(c),
            "dtype": str(s.dtype),
            "non_null_sample_count": int(s.notna().sum()),
            "sample_values": [str(x) for x in s.dropna().head(5).tolist()],
        })
    return rows


def _write_sample_csv(df: pd.DataFrame, path: Path, *, index: bool) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=index)
    return _file_size_bytes(path)


def _write_sample_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    parquet_engine: Optional[str],
    parquet_compression: Optional[str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)

    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == "object":
            try:
                df[c] = _ensure_python_str_series(df[c])
            except Exception:
                pass

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

    return _file_size_bytes(path)


def _safe_target_counter(df: pd.DataFrame, target_col: str = "Target") -> Counter:
    if target_col not in df.columns:
        return Counter()
    try:
        return Counter(pd.to_numeric(df[target_col], errors="coerce").fillna(-1).astype(int).tolist())
    except Exception:
        return Counter(df[target_col].astype(str).tolist())


# =============================================================================
# Sampling helpers
# =============================================================================

class _ReservoirSampler:
    """
    Deterministic-ish reservoir sampler for streaming shards.
    This avoids loading all rows into RAM.
    """
    def __init__(self, k: int, seed: int):
        self.k = max(0, int(k))
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.n_seen = 0
        self.parts: List[pd.DataFrame] = []

    def add(self, df: pd.DataFrame) -> None:
        if self.k <= 0 or df is None or df.empty:
            return

        # If reservoir is still under capacity, append directly.
        current = sum(len(x) for x in self.parts)
        if current < self.k:
            need = self.k - current
            if len(df) <= need:
                self.parts.append(df.copy())
                self.n_seen += len(df)
                return
            else:
                take_idx = self.rng.choice(len(df), size=need, replace=False)
                self.parts.append(df.iloc[take_idx].copy())
                self.n_seen += len(df)
                return

        # Once full, use standard reservoir replacement.
        # This is row-level but implemented in a compact enough way for samples.
        reservoir = pd.concat(self.parts, ignore_index=True)
        self.parts = [reservoir]

        for i in range(len(df)):
            self.n_seen += 1
            j = int(self.rng.integers(0, max(1, self.n_seen)))
            if j < self.k:
                self.parts[0].iloc[j] = df.iloc[i]

    def dataframe(self) -> pd.DataFrame:
        if not self.parts:
            return pd.DataFrame()
        out = pd.concat(self.parts, ignore_index=True)
        if len(out) > self.k:
            out = out.sample(n=self.k, random_state=self.seed).reset_index(drop=True)
        return out.reset_index(drop=True)


def _target_sample_plan(total_target_counts: Counter, sample_rows: int) -> Dict[Any, int]:
    sample_rows = max(0, int(sample_rows))
    total = int(sum(total_target_counts.values()))
    if sample_rows <= 0 or total <= 0:
        return {}

    n = min(sample_rows, total)
    plan: Dict[Any, int] = {}

    # proportional allocation
    for k, v in total_target_counts.items():
        plan[k] = int((int(v) / max(1, total)) * n)

    # ensure at least 1 sample for existing class when n allows
    for k, v in total_target_counts.items():
        if int(v) > 0 and plan.get(k, 0) == 0 and sum(plan.values()) < n:
            plan[k] = 1

    # distribute remainder
    remaining = n - sum(plan.values())
    for k, _v in sorted(total_target_counts.items(), key=lambda kv: int(kv[1]), reverse=True):
        if remaining <= 0:
            break
        plan[k] = plan.get(k, 0) + 1
        remaining -= 1

    # trim overshoot
    while sum(plan.values()) > n:
        kmax = max(plan, key=lambda kk: plan[kk])
        plan[kmax] -= 1
        if plan[kmax] <= 0:
            del plan[kmax]

    return {k: int(v) for k, v in plan.items() if int(v) > 0}


def _collect_sample_two_pass(
    shard_files: List[Path],
    *,
    cfg: Phase8ExportConfig,
    app: str,
    total_target_counts: Counter,
) -> pd.DataFrame:
    """
    Collect sample from sharded app dataset without materializing all rows.

    If stratify=True and Target exists, use class-wise reservoir sampling.
    Otherwise use a single reservoir sampler.
    """
    sample_rows = max(0, int(cfg.sample_rows))
    if sample_rows <= 0:
        return pd.DataFrame()

    if cfg.stratify and total_target_counts:
        plan = _target_sample_plan(total_target_counts, sample_rows)
        samplers = {
            str(k): _ReservoirSampler(v, seed=int(cfg.seed) + abs(hash((app, str(k)))) % 100_000)
            for k, v in plan.items()
        }

        for fp in tqdm(shard_files, desc=f"PHASE 8 sample app={app}", unit="shard", dynamic_ncols=True):
            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is None or df.empty:
                continue
            df = _select_columns(df, cfg.include_columns)

            if cfg.stratify_col not in df.columns:
                # fallback to non-stratified if selected columns omit Target
                sampler = _ReservoirSampler(sample_rows, seed=int(cfg.seed))
                sampler.add(df)
                return sampler.dataframe()

            target_series = pd.to_numeric(df[cfg.stratify_col], errors="coerce").fillna(-1).astype(int).astype(str)
            for key, sampler in samplers.items():
                sub = df[target_series == str(key)]
                if not sub.empty:
                    sampler.add(sub)

            if cfg.gc_each_shard:
                del df
                gc.collect()

        parts = [s.dataframe() for s in samplers.values() if not s.dataframe().empty]
        if not parts:
            return pd.DataFrame()

        out = pd.concat(parts, ignore_index=True)
        if len(out) > sample_rows:
            out = out.sample(n=sample_rows, random_state=cfg.seed).reset_index(drop=True)
        else:
            out = out.sample(frac=1.0, random_state=cfg.seed).reset_index(drop=True)
        return out

    sampler = _ReservoirSampler(sample_rows, seed=int(cfg.seed))
    for fp in tqdm(shard_files, desc=f"PHASE 8 sample app={app}", unit="shard", dynamic_ncols=True):
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue
        df = _select_columns(df, cfg.include_columns)
        sampler.add(df)
        if cfg.gc_each_shard:
            del df
            gc.collect()

    return sampler.dataframe()


# =============================================================================
# Public API
# =============================================================================

def phase8_export_dataset_for_app(
    app: str,
    *,
    cfg: Phase8ExportConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    app = str(app).strip().lower()
    mode = (cfg.mode or "none").strip().lower()
    t0 = datetime.now()

    shard_files = _list_app_shards(cfg.input_dir, app)
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    sample_dir = out_app_dir / "sample"
    shards_copy_dir = out_app_dir / "shards"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    if not shard_files:
        summary = {
            "phase": 8,
            "app": app,
            "status": "skipped_no_input_shards",
            "mode": mode,
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": 0,
            "shards_seen": 0,
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase8_export_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\n🟡 PHASE 8: Export processed dataset for app={app}")
    print(f"   Mode         : {mode}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    rows_seen = 0
    input_bytes = 0
    target_counter: Counter = Counter()
    schema: Optional[List[Dict[str, Any]]] = None
    manifest_rows: List[Dict[str, Any]] = []

    # PASS 1: manifest, schema, counts.
    for idx, fp in enumerate(tqdm(shard_files, desc=f"PHASE 8 scan app={app}", unit="shard", dynamic_ncols=True), start=1):
        input_bytes += _file_size_bytes(fp)
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            manifest_rows.append({
                "app": app,
                "shard_index": idx,
                "path": str(fp),
                "rows": 0,
                "cols": 0,
                "size_bytes": _file_size_bytes(fp),
                "format": fp.suffix,
            })
            continue

        rows_seen += int(len(df))
        target_counter.update(_safe_target_counter(df, cfg.stratify_col))

        if schema is None:
            schema_df = _select_columns(df.head(1000), cfg.include_columns)
            schema = _schema_from_df(schema_df)

        manifest_rows.append({
            "app": app,
            "shard_index": idx,
            "path": str(fp),
            "rows": int(len(df)),
            "cols": int(df.shape[1]),
            "size_bytes": _file_size_bytes(fp),
            "format": "".join(fp.suffixes),
        })

        if cfg.gc_each_shard:
            del df
            gc.collect()

    if schema is None:
        schema = []

    manifest_df = pd.DataFrame(manifest_rows)
    manifest_path = out_app_dir / "manifest.csv"
    manifest_df.to_csv(manifest_path, index=False)

    schema_path = out_app_dir / "schema.json"
    _json_dump(schema, schema_path)

    sample_df = pd.DataFrame()
    sample_paths: List[str] = []
    sample_bytes = 0

    # PASS 2: sample export or shard copy.
    if mode in {"sample_csv", "sample_parquet", "sample_both"}:
        sample_df = _collect_sample_two_pass(
            shard_files,
            cfg=cfg,
            app=app,
            total_target_counts=target_counter,
        )

        n = int(len(sample_df))
        tag = cfg.sample_size_tag or "NA"

        if mode in {"sample_csv", "sample_both"}:
            csv_path = sample_dir / f"{cfg.filename_stem}_{app}_{tag}_sample{n}.csv"
            sample_bytes += _write_sample_csv(sample_df, csv_path, index=cfg.index)
            sample_paths.append(str(csv_path))

        if mode in {"sample_parquet", "sample_both"}:
            parquet_path = sample_dir / f"{cfg.filename_stem}_{app}_{tag}_sample{n}.parquet"
            sample_bytes += _write_sample_parquet(
                sample_df,
                parquet_path,
                parquet_engine=cfg.parquet_engine,
                parquet_compression=cfg.parquet_compression,
            )
            sample_paths.append(str(parquet_path))

    elif mode == "copy_shards":
        shards_copy_dir.mkdir(parents=True, exist_ok=True)
        for fp in tqdm(shard_files, desc=f"PHASE 8 copy app={app}", unit="shard", dynamic_ncols=True):
            dst = shards_copy_dir / fp.name
            shutil.copy2(fp, dst)
        sample_paths = [str(shards_copy_dir)]
        sample_bytes = sum(_file_size_bytes(p) for p in shards_copy_dir.glob("*") if p.is_file())

    elif mode in {"none", "manifest_only"}:
        pass
    else:
        raise ValueError(
            f"Unknown Phase 8 export mode: {cfg.mode}. "
            "Use none | manifest_only | sample_csv | sample_parquet | sample_both | copy_shards."
        )

    elapsed = (datetime.now() - t0).total_seconds()

    sample_target_dist: Dict[str, int] = {}
    if not sample_df.empty and cfg.stratify_col in sample_df.columns:
        sample_target_dist = {
            str(k): int(v)
            for k, v in sample_df[cfg.stratify_col].value_counts(dropna=False).to_dict().items()
        }

    summary = {
        "phase": 8,
        "app": app,
        "status": "completed",
        "mode": mode,
        "input_dir": str(cfg.input_dir),
        "output_dir": str(out_app_dir),
        "selected_apps": list(cfg.selected_apps),
        "rows_seen": int(rows_seen),
        "shards_seen": int(len(shard_files)),
        "input_bytes": int(input_bytes),
        "input_gib": float(_gib(input_bytes)),
        "manifest_path": str(manifest_path),
        "schema_path": str(schema_path),
        "export_paths": sample_paths,
        "export_bytes": int(sample_bytes),
        "export_mb": float(sample_bytes / (1024.0 * 1024.0)),
        "sample_rows_requested": int(cfg.sample_rows),
        "sample_rows_exported": int(len(sample_df)),
        "sample_shape": [int(sample_df.shape[0]), int(sample_df.shape[1])],
        "target_counts_input": {str(k): int(v) for k, v in target_counter.items()},
        "target_counts_sample": sample_target_dist,
        "stratify": bool(cfg.stratify),
        "stratify_col": cfg.stratify_col,
        "seed": int(cfg.seed),
        "include_columns": list(cfg.include_columns) if cfg.include_columns else None,
        "seconds": float(elapsed),
        "note": (
            "Phase 8 exports manifest/schema and optional samples per application. "
            "The main full clean checkpoint remains Phase 7. Avoid copy_shards unless explicitly needed."
        ),
    }

    _json_dump(summary, metrics_dir / f"phase8_export_summary_{app}.json")

    print(f"✅ Phase 8 complete app={app}")
    print(f"   Rows seen : {rows_seen:,}")
    print(f"   Input size: {_human_bytes(input_bytes)}")
    print(f"   Exported  : {_human_bytes(sample_bytes)}")
    print(f"   Sample    : {sample_df.shape}")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    return sample_df, summary


def phase8_export_dataset(
    *,
    cfg: Phase8ExportConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    print("\n" + "🟡 " + "=" * 76)
    print("PHASE 8: EXPORT PROCESSED DATASET (APP-AWARE)")
    print("🟡 " + "=" * 76)

    t0 = datetime.now()

    samples_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        sample_df, summary = phase8_export_dataset_for_app(app_norm, cfg=cfg)
        samples_by_app[app_norm] = sample_df
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        rows.append({
            "app": app,
            "status": s.get("status"),
            "mode": s.get("mode"),
            "rows_seen": int(s.get("rows_seen", 0)),
            "shards_seen": int(s.get("shards_seen", 0)),
            "input_gib": float(s.get("input_gib", 0.0)),
            "sample_rows_exported": int(s.get("sample_rows_exported", 0)),
            "export_mb": float(s.get("export_mb", 0.0)),
            "manifest_path": s.get("manifest_path"),
            "schema_path": s.get("schema_path"),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase8_export_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows_seen = int(sum(int(s.get("rows_seen", 0)) for s in summaries.values()))
    total_input_bytes = int(sum(int(s.get("input_bytes", 0)) for s in summaries.values()))
    total_export_bytes = int(sum(int(s.get("export_bytes", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 8,
        "status": "completed",
        "mode": cfg.mode,
        "selected_apps": list(cfg.selected_apps),
        "input_dir": str(cfg.input_dir),
        "output_dir": str(cfg.output_dir),
        "total_rows_seen": total_rows_seen,
        "total_input_bytes": total_input_bytes,
        "total_input_gib": float(_gib(total_input_bytes)),
        "total_export_bytes": total_export_bytes,
        "total_export_mb": float(total_export_bytes / (1024.0 * 1024.0)),
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Phase 8 is app-aware and reads Phase 7 clean app partitions. "
            "It replaces the old in-memory DataFrame export function."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase8_export_summary_all.json")

    print("\n✅ PHASE 8 COMPLETE")
    print(f"   Total rows seen: {total_rows_seen:,}")
    print(f"   Input size     : {_human_bytes(total_input_bytes)}")
    print(f"   Exported size  : {_human_bytes(total_export_bytes)}")
    print(f"   Output dir     : {cfg.output_dir}")
    print(f"   Time           : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all



# =============================================================================
# RAM MODE API (SMALL DATASET / SEMINAR MODE)
# =============================================================================
def _schema_from_dataframe_ram(df: pd.DataFrame, include_columns: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Build schema directly from an in-memory DataFrame without reading shards."""
    if df is None:
        return []
    view = _select_columns(df, include_columns)
    return _schema_from_df(view.head(1000))


def _target_distribution_ram(df: pd.DataFrame, target_col: str = "Target") -> Dict[str, int]:
    if df is None or df.empty or target_col not in df.columns:
        return {}
    try:
        s = pd.to_numeric(df[target_col], errors="coerce").fillna(-1).astype(int)
        return {str(k): int(v) for k, v in s.value_counts(dropna=False).to_dict().items()}
    except Exception:
        return {str(k): int(v) for k, v in df[target_col].astype(str).value_counts(dropna=False).to_dict().items()}


def _sample_dataframe_ram(
    df: pd.DataFrame,
    *,
    sample_rows: int,
    seed: int,
    stratify: bool = True,
    stratify_col: str = "Target",
) -> pd.DataFrame:
    """Sample from an already-loaded DataFrame. No reservoir, no shard scan."""
    if df is None or df.empty:
        return pd.DataFrame()

    n = int(sample_rows)
    if n <= 0 or len(df) <= n:
        return df.copy().reset_index(drop=True)

    if stratify and stratify_col in df.columns:
        try:
            parts: List[pd.DataFrame] = []
            vc = df[stratify_col].value_counts(dropna=False)
            total = int(vc.sum())
            remaining = n
            for i, (klass, count) in enumerate(vc.items()):
                if i == len(vc) - 1:
                    take = remaining
                else:
                    take = int(round((int(count) / max(1, total)) * n))
                    take = max(1, min(take, int(count), remaining))
                if take <= 0:
                    continue
                sub = df[df[stratify_col] == klass]
                if len(sub) > take:
                    sub = sub.sample(n=take, random_state=int(seed) + i)
                parts.append(sub)
                remaining -= len(sub)
                if remaining <= 0:
                    break
            if parts:
                out = pd.concat(parts, ignore_index=True)
                if len(out) > n:
                    out = out.sample(n=n, random_state=int(seed))
                return out.sample(frac=1.0, random_state=int(seed)).reset_index(drop=True)
        except Exception:
            pass

    return df.sample(n=n, random_state=int(seed)).reset_index(drop=True)


def phase8_export_dataset_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    output_dir: Path,
    mode: str = "manifest_only",
    sample_rows: int = 200_000,
    filename_stem: str = "eve_processed",
    sample_size_tag: str = "NA",
    filename_tag: str = "run",
    include_columns: Optional[Sequence[str]] = None,
    index: bool = False,
    seed: int = 42,
    stratify: bool = True,
    stratify_col: str = "Target",
    overwrite: bool = True,
    parquet_engine: Optional[str] = None,
    parquet_compression: Optional[str] = "snappy",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode Phase 8 for the current small/seminar dataset.

    Purpose:
      - Keep Phase 8 as a lightweight export/audit phase.
      - Do NOT read Phase 7 Parquet shards.
      - Do NOT write Parquet unless mode explicitly asks for sample_parquet/sample_both.
      - Default output is only manifest + schema + summary.

    Input:
      df_clean from Phase 7 for one active app.

    Output:
      output_dir/app={app}/schema.json
      output_dir/app={app}/manifest.json
      optional output_dir/app={app}/sample/*.csv or *.parquet
    """
    print(f"\n🟡 PHASE 8 RAM: Export/audit for app={app}")
    t0 = datetime.now()

    app = str(app).strip().lower()
    mode = (mode or "manifest_only").strip().lower()
    if mode == "none":
        mode = "manifest_only"

    out_app_dir = Path(output_dir) / f"app={app}"
    sample_dir = out_app_dir / "sample"
    metrics_dir = Path(output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    if df_clean is None:
        df_clean = pd.DataFrame()

    selected_df = _select_columns(df_clean, include_columns)
    schema = _schema_from_dataframe_ram(df_clean, include_columns)
    schema_path = out_app_dir / "schema.json"
    _json_dump(schema, schema_path)

    manifest = {
        "app": app,
        "input_source": "dataframe_ram_phase7",
        "rows": int(len(selected_df)),
        "columns": int(selected_df.shape[1]),
        "original_rows": int(len(df_clean)),
        "original_columns": int(df_clean.shape[1]),
        "include_columns": list(include_columns) if include_columns else None,
        "memory_mib": float(selected_df.memory_usage(deep=True).sum() / (1024.0 * 1024.0)) if not selected_df.empty else 0.0,
        "target_counts": _target_distribution_ram(selected_df, stratify_col),
    }
    manifest_path = out_app_dir / "manifest.json"
    _json_dump(manifest, manifest_path)

    sample_df = pd.DataFrame()
    export_paths: List[str] = []
    export_bytes = 0

    if mode in {"sample_csv", "sample_parquet", "sample_both"}:
        sample_df = _sample_dataframe_ram(
            selected_df,
            sample_rows=int(sample_rows),
            seed=int(seed),
            stratify=bool(stratify),
            stratify_col=stratify_col,
        )
        n = int(len(sample_df))
        tag = sample_size_tag or filename_tag or "NA"

        if mode in {"sample_csv", "sample_both"}:
            csv_path = sample_dir / f"{filename_stem}_{app}_{tag}_sample{n}.csv"
            export_bytes += _write_sample_csv(sample_df, csv_path, index=index)
            export_paths.append(str(csv_path))

        if mode in {"sample_parquet", "sample_both"}:
            parquet_path = sample_dir / f"{filename_stem}_{app}_{tag}_sample{n}.parquet"
            export_bytes += _write_sample_parquet(
                sample_df,
                parquet_path,
                parquet_engine=parquet_engine,
                parquet_compression=parquet_compression,
            )
            export_paths.append(str(parquet_path))

    elif mode in {"manifest_only", "schema_only"}:
        pass
    else:
        raise ValueError(
            f"Unknown Phase 8 RAM export mode: {mode}. "
            "Use manifest_only | sample_csv | sample_parquet | sample_both."
        )

    elapsed = (datetime.now() - t0).total_seconds()
    summary = {
        "phase": 8,
        "phase_name": "export_dataset",
        "app": app,
        "status": "completed",
        "mode": mode,
        "input_source": "dataframe_ram_phase7",
        "output_dir": str(out_app_dir),
        "rows_seen": int(len(selected_df)),
        "cols_seen": int(selected_df.shape[1]),
        "manifest_path": str(manifest_path),
        "schema_path": str(schema_path),
        "export_paths": export_paths,
        "export_bytes": int(export_bytes),
        "export_mb": float(export_bytes / (1024.0 * 1024.0)),
        "sample_rows_requested": int(sample_rows),
        "sample_rows_exported": int(len(sample_df)),
        "sample_shape": [int(sample_df.shape[0]), int(sample_df.shape[1])],
        "target_counts_input": _target_distribution_ram(selected_df, stratify_col),
        "target_counts_sample": _target_distribution_ram(sample_df, stratify_col) if not sample_df.empty else {},
        "stratify": bool(stratify),
        "stratify_col": str(stratify_col),
        "seed": int(seed),
        "include_columns": list(include_columns) if include_columns else None,
        "seconds": float(elapsed),
        "note": (
            "RAM-mode Phase 8 is an optional lightweight export/audit phase. "
            "Training split must use df_clean from Phase 7, not Phase 8 export files."
        ),
    }

    _json_dump(summary, metrics_dir / f"phase8_export_summary_{app}.json")

    print(f"✅ Phase 8 RAM complete app={app}")
    print(f"   Rows seen : {len(selected_df):,}")
    print(f"   Mode      : {mode}")
    print(f"   Exported  : {_human_bytes(export_bytes)}")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    return sample_df, summary


def phase8_export_dataset_in_memory(
    df_clean: pd.DataFrame,
    *,
    app: str,
    output_dir: Path,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase8_export_dataset_ram(
        df_clean,
        app=app,
        output_dir=output_dir,
        **kwargs,
    )


def run_phase8_export_dataset_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    output_dir: Path,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase8_export_dataset_ram(
        df_clean,
        app=app,
        output_dir=output_dir,
        **kwargs,
    )


# Compatibility alias.
def build_phase8_export_dataset(
    *,
    cfg: Phase8ExportConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase8_export_dataset(cfg=cfg)


if __name__ == "__main__":
    samples, summary = phase8_export_dataset(
        cfg=Phase8ExportConfig(
            input_dir=Path("results/phase7_clean_dataset"),
            output_dir=Path("results/phase8_export_dataset"),
            selected_apps=("dns", "http", "tls", "ssh"),
            mode="sample_csv",
            sample_rows=200_000,
            filename_stem="eve_processed",
            sample_size_tag="NA",
            stratify=True,
            stratify_col="Target",
            parquet_engine="fastparquet",
            parquet_compression="snappy",
            overwrite=True,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
