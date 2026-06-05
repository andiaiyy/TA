from __future__ import annotations

import gc
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =========================================================
# PHASE 3: PROBING ANALYSIS (APP-AWARE / AGGREGATE OUTPUT)
# ---------------------------------------------------------
# Goal:
# - Read Phase 2 per-application shards from storage.
# - Build source-IP + time-window probing features.
# - Save aggregate evidence/features only, not another full copy
#   of the application dataset.
# - Keep final Target creation for phase4_label_refinement.py.
#
# Important:
# - This phase does NOT create final Target.
# - This phase creates probing evidence that can be joined later
#   by (application, src_ip, window_start).
# - Output size should be much smaller than full row-level data.
# =========================================================

DEFAULT_SELECTED_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")


@dataclass(frozen=True)
class Phase3ProbingConfig:
    """Configuration for Phase 3 probing analysis.

    input_dir:
        Usually Phase 2 output directory, for example:
        results/phase2_app_dataset

    output_dir:
        Phase 3 output directory, for example:
        results/phase3_probing

    selected_apps:
        Applications to process. Each app is expected to have one of:
        - input_dir/app={app}/part-*.parquet
        - input_dir/{app}/part-*.parquet

    window_minutes:
        Time-window size used to aggregate source-IP behavior.

    Unique-count note:
        This implementation aggregates shard-by-shard for huge-data safety.
        event_count, alert_count, bytes, and packets are exact sums.
        unique_dest_ip and unique_dest_port are summed from per-shard windows.
        If a same (src_ip, window) spans multiple shards, unique counts may be
        slightly overestimated. For probing detection this is usually acceptable
        and safer than keeping very large exact Python sets in RAM.
    """

    input_dir: Path
    output_dir: Path

    selected_apps: Sequence[str] = field(default_factory=lambda: DEFAULT_SELECTED_APPS)
    window_minutes: int = 5

    # Thresholds for initial probing evidence.
    min_event_count: int = 50
    min_unique_dest_ip: int = 10
    min_unique_dest_port: int = 5
    min_alert_count: int = 1
    min_probe_score: float = 3.0

    # Score weights.
    event_weight: float = 1.0
    dest_ip_weight: float = 1.25
    dest_port_weight: float = 1.25
    alert_weight: float = 1.0
    prelim_malicious_weight: float = 0.75

    # Output behavior.
    write_format: str = "parquet"          # "parquet" or "csv"
    parquet_engine: Optional[str] = None    # "fastparquet" | "pyarrow" | None
    parquet_compression: Optional[str] = "snappy"
    max_candidates_csv_rows: int = 200_000
    max_return_sample_per_app: int = 20_000
    skip_if_exists: bool = False


# -----------------------------
# IO helpers
# -----------------------------
def _normalize_apps(apps: Sequence[str]) -> List[str]:
    out: List[str] = []
    for app in apps:
        a = str(app).strip().lower()
        if a and a not in out:
            out.append(a)
    return out


def _resolve_app_dir(input_dir: Path, app: str) -> Path:
    input_dir = Path(input_dir)
    candidates = [
        input_dir / f"app={app}",
        input_dir / app,
    ]
    for p in candidates:
        if p.exists():
            return p
    # Return canonical path for clearer error messages.
    return input_dir / f"app={app}"


def _iter_shards(app_dir: Path) -> List[Path]:
    patterns = ["*.parquet", "*.csv.gz", "*.csv"]
    files: List[Path] = []
    for pat in patterns:
        files.extend(sorted(Path(app_dir).glob(pat)))
    return sorted(files)


def _read_shard(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if name.endswith(".csv.gz"):
        return pd.read_csv(path, compression="gzip")
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported shard format: {path}")


def _resolve_parquet_engine(engine: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return (actual_format, parquet_engine)."""
    if engine:
        eng = engine.strip().lower()
        if eng == "pyarrow":
            try:
                import pyarrow  # noqa: F401
                return "parquet", "pyarrow"
            except Exception:
                return "csv", None
        if eng == "fastparquet":
            try:
                import fastparquet  # noqa: F401
                return "parquet", "fastparquet"
            except Exception:
                return "csv", None

    try:
        import pyarrow  # noqa: F401
        return "parquet", None
    except Exception:
        pass

    try:
        import fastparquet  # noqa: F401
        return "parquet", None
    except Exception:
        return "csv", None


def _write_dataframe(
    df: pd.DataFrame,
    path_no_suffix: Path,
    *,
    fmt: str = "parquet",
    parquet_engine: Optional[str] = None,
    parquet_compression: Optional[str] = "snappy",
) -> Path:
    path_no_suffix = Path(path_no_suffix)
    path_no_suffix.parent.mkdir(parents=True, exist_ok=True)

    fmt = (fmt or "parquet").strip().lower()
    if fmt not in {"parquet", "csv"}:
        fmt = "parquet"

    actual_fmt = fmt
    engine = parquet_engine
    if actual_fmt == "parquet":
        actual_fmt, engine = _resolve_parquet_engine(parquet_engine)

    if actual_fmt == "parquet":
        path = path_no_suffix.with_suffix(".parquet")
        kwargs: Dict[str, Any] = {"index": False}
        if engine:
            kwargs["engine"] = engine
        if parquet_compression:
            kwargs["compression"] = parquet_compression
        df.to_parquet(path, **kwargs)
        return path

    path = path_no_suffix.with_suffix(".csv.gz")
    df.to_csv(path, index=False, compression="gzip")
    return path


def _write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        if not np.isfinite(obj):
            return None
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return obj
    return obj


def _dir_size_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    total = 0
    for fp in p.rglob("*"):
        try:
            if fp.is_file():
                total += fp.stat().st_size
        except Exception:
            pass
    return total


def _gib(x_bytes: int) -> float:
    return float(x_bytes) / (1024.0 ** 3)


# -----------------------------
# Data helpers
# -----------------------------
def _safe_str_series(s: pd.Series) -> pd.Series:
    out = s.astype("object")
    out = out.where(pd.notna(out), "")
    return out.astype(str).str.strip()


def _safe_lower_series(s: pd.Series) -> pd.Series:
    return _safe_str_series(s).str.lower()


def _safe_num_series(s: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(default)


def _first_existing_col(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _get_timestamp_series(df: pd.DataFrame) -> pd.Series:
    col = _first_existing_col(df, ["timestamp", "ts", "time"])
    if col is None:
        return pd.Series(pd.NaT, index=df.index)
    return pd.to_datetime(df[col], errors="coerce", utc=True)


def _get_port_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0, index=df.index, dtype="int64")
    return _safe_num_series(df[col], 0).astype(np.int64)


def _get_total_bytes(df: pd.DataFrame) -> pd.Series:
    if "total_bytes" in df.columns:
        return _safe_num_series(df["total_bytes"], 0)
    a = _safe_num_series(df["bytes_toserver"], 0) if "bytes_toserver" in df.columns else pd.Series(0, index=df.index)
    b = _safe_num_series(df["bytes_toclient"], 0) if "bytes_toclient" in df.columns else pd.Series(0, index=df.index)
    return a + b


def _get_total_pkts(df: pd.DataFrame) -> pd.Series:
    if "total_pkts" in df.columns:
        return _safe_num_series(df["total_pkts"], 0)
    a = _safe_num_series(df["pkts_toserver"], 0) if "pkts_toserver" in df.columns else pd.Series(0, index=df.index)
    b = _safe_num_series(df["pkts_toclient"], 0) if "pkts_toclient" in df.columns else pd.Series(0, index=df.index)
    return a + b


def _get_alert_series(df: pd.DataFrame) -> pd.Series:
    if "has_alert" in df.columns:
        return (_safe_num_series(df["has_alert"], 0) > 0).astype(np.int64)
    if "label_evidence_alert" in df.columns:
        return (_safe_num_series(df["label_evidence_alert"], 0) > 0).astype(np.int64)
    if "alert_category" in df.columns:
        s = _safe_lower_series(df["alert_category"])
        return ((s != "") & (s != "none") & (s != "nan")).astype(np.int64)
    return pd.Series(0, index=df.index, dtype="int64")


def _get_target_prelim_malicious(df: pd.DataFrame) -> pd.Series:
    if "Target_prelim" in df.columns:
        return (_safe_num_series(df["Target_prelim"], -1) == 1).astype(np.int64)
    if "label_status" in df.columns:
        return (_safe_lower_series(df["label_status"]) == "malicious_evidence").astype(np.int64)
    return pd.Series(0, index=df.index, dtype="int64")


def _prepare_window_frame(df: pd.DataFrame, *, app: str, window_minutes: int) -> Tuple[pd.DataFrame, dict]:
    """Return a compact DataFrame used for window aggregation."""
    n_input = int(len(df))
    if df.empty:
        return pd.DataFrame(), {"input_rows": n_input, "usable_rows": 0, "dropped_no_timestamp": 0, "dropped_no_src_ip": 0}

    ts = _get_timestamp_series(df)
    src_ip = _safe_str_series(df["src_ip"]) if "src_ip" in df.columns else pd.Series("", index=df.index)
    dest_ip = _safe_str_series(df["dest_ip"]) if "dest_ip" in df.columns else pd.Series("", index=df.index)
    dest_port = _get_port_series(df, "dest_port")

    # Floor timestamp to time window.
    window_rule = f"{int(window_minutes)}min"
    window_start = ts.dt.floor(window_rule)

    total_bytes = _get_total_bytes(df)
    total_pkts = _get_total_pkts(df)
    has_alert = _get_alert_series(df)
    target_prelim_malicious = _get_target_prelim_malicious(df)

    work = pd.DataFrame({
        "application": app,
        "timestamp": ts,
        "window_start": window_start,
        "src_ip": src_ip,
        "dest_ip": dest_ip,
        "dest_port": dest_port,
        "has_alert": has_alert,
        "target_prelim_malicious": target_prelim_malicious,
        "total_bytes": total_bytes,
        "total_pkts": total_pkts,
    })

    no_ts = work["window_start"].isna()
    no_src = work["src_ip"].eq("") | work["src_ip"].str.lower().eq("nan")
    usable = work.loc[~no_ts & ~no_src].copy()

    stats = {
        "input_rows": n_input,
        "usable_rows": int(len(usable)),
        "dropped_no_timestamp": int(no_ts.sum()),
        "dropped_no_src_ip": int(no_src.sum()),
    }
    return usable, stats


def _aggregate_shard_window_features(df: pd.DataFrame, *, app: str, window_minutes: int) -> Tuple[pd.DataFrame, dict]:
    work, stats = _prepare_window_frame(df, app=app, window_minutes=window_minutes)
    if work.empty:
        return pd.DataFrame(), stats

    keys = ["application", "window_start", "src_ip"]
    gb = work.groupby(keys, sort=False, dropna=False)

    agg = gb.agg(
        event_count_window=("src_ip", "size"),
        unique_dest_ip_window=("dest_ip", "nunique"),
        unique_dest_port_window=("dest_port", "nunique"),
        alert_count_window=("has_alert", "sum"),
        target_prelim_malicious_count=("target_prelim_malicious", "sum"),
        total_bytes_window=("total_bytes", "sum"),
        total_pkts_window=("total_pkts", "sum"),
        first_seen=("timestamp", "min"),
        last_seen=("timestamp", "max"),
    ).reset_index()

    return agg, stats


def _merge_aggregate_frames(frames: List[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df

    keys = ["application", "window_start", "src_ip"]
    gb = df.groupby(keys, sort=False, dropna=False)
    merged = gb.agg(
        event_count_window=("event_count_window", "sum"),
        # See config docstring: these are sum-of-shard unique estimates.
        unique_dest_ip_window=("unique_dest_ip_window", "sum"),
        unique_dest_port_window=("unique_dest_port_window", "sum"),
        alert_count_window=("alert_count_window", "sum"),
        target_prelim_malicious_count=("target_prelim_malicious_count", "sum"),
        total_bytes_window=("total_bytes_window", "sum"),
        total_pkts_window=("total_pkts_window", "sum"),
        first_seen=("first_seen", "min"),
        last_seen=("last_seen", "max"),
    ).reset_index()

    return merged


def _safe_ratio(num: pd.Series, den: float) -> pd.Series:
    den = float(den) if den else 1.0
    return num.astype(float) / den


def _add_probe_score(df: pd.DataFrame, cfg: Phase3ProbingConfig) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    for c in [
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "alert_count_window",
        "target_prelim_malicious_count",
        "total_bytes_window",
        "total_pkts_window",
    ]:
        if c not in out.columns:
            out[c] = 0
        out[c] = _safe_num_series(out[c], 0)

    event_component = np.minimum(_safe_ratio(out["event_count_window"], cfg.min_event_count), 5.0)
    dest_ip_component = np.minimum(_safe_ratio(out["unique_dest_ip_window"], cfg.min_unique_dest_ip), 5.0)
    dest_port_component = np.minimum(_safe_ratio(out["unique_dest_port_window"], cfg.min_unique_dest_port), 5.0)
    alert_component = np.minimum(_safe_ratio(out["alert_count_window"], max(1, cfg.min_alert_count)), 5.0)
    prelim_component = np.minimum(_safe_ratio(out["target_prelim_malicious_count"], max(1, cfg.min_alert_count)), 5.0)

    out["probe_score"] = (
        event_component * float(cfg.event_weight)
        + dest_ip_component * float(cfg.dest_ip_weight)
        + dest_port_component * float(cfg.dest_port_weight)
        + alert_component * float(cfg.alert_weight)
        + prelim_component * float(cfg.prelim_malicious_weight)
    )

    out["bytes_per_event_window"] = np.where(
        out["event_count_window"] > 0,
        out["total_bytes_window"] / out["event_count_window"],
        0.0,
    )
    out["pkts_per_event_window"] = np.where(
        out["event_count_window"] > 0,
        out["total_pkts_window"] / out["event_count_window"],
        0.0,
    )

    high_event = out["event_count_window"] >= int(cfg.min_event_count)
    high_dest_ip = out["unique_dest_ip_window"] >= int(cfg.min_unique_dest_ip)
    high_dest_port = out["unique_dest_port_window"] >= int(cfg.min_unique_dest_port)
    has_alert = out["alert_count_window"] >= int(cfg.min_alert_count)
    high_score = out["probe_score"] >= float(cfg.min_probe_score)

    out["is_possible_probe"] = (
        high_score & high_event & (high_dest_ip | high_dest_port | has_alert)
    ).astype(np.int64)

    # Build compact text reason. Number of rows here is already aggregate-level,
    # so row-wise apply is acceptable.
    def reason(row: pd.Series) -> str:
        reasons: List[str] = []
        if row.get("event_count_window", 0) >= cfg.min_event_count:
            reasons.append("high_event_count")
        if row.get("unique_dest_ip_window", 0) >= cfg.min_unique_dest_ip:
            reasons.append("many_dest_ip")
        if row.get("unique_dest_port_window", 0) >= cfg.min_unique_dest_port:
            reasons.append("many_dest_port")
        if row.get("alert_count_window", 0) >= cfg.min_alert_count:
            reasons.append("alert_present")
        if row.get("probe_score", 0) >= cfg.min_probe_score:
            reasons.append("high_probe_score")
        return ";".join(reasons) if reasons else "below_threshold"

    out["probe_reason"] = out.apply(reason, axis=1)

    # Make timestamps storage/report friendly.
    for c in ["window_start", "first_seen", "last_seen"]:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Stable column order.
    preferred = [
        "application",
        "window_start",
        "src_ip",
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "alert_count_window",
        "target_prelim_malicious_count",
        "total_bytes_window",
        "total_pkts_window",
        "bytes_per_event_window",
        "pkts_per_event_window",
        "probe_score",
        "is_possible_probe",
        "probe_reason",
        "first_seen",
        "last_seen",
    ]
    existing = [c for c in preferred if c in out.columns]
    rest = [c for c in out.columns if c not in existing]
    return out[existing + rest]


def _make_src_ip_summary(features: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame()

    df = features.copy()
    for c in [
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "alert_count_window",
        "target_prelim_malicious_count",
        "probe_score",
        "is_possible_probe",
    ]:
        if c not in df.columns:
            df[c] = 0
        df[c] = _safe_num_series(df[c], 0)

    gb = df.groupby(["application", "src_ip"], sort=False)
    out = gb.agg(
        windows_seen=("window_start", "nunique"),
        total_events=("event_count_window", "sum"),
        max_event_count_window=("event_count_window", "max"),
        max_unique_dest_ip_window=("unique_dest_ip_window", "max"),
        max_unique_dest_port_window=("unique_dest_port_window", "max"),
        total_alerts=("alert_count_window", "sum"),
        max_probe_score=("probe_score", "max"),
        mean_probe_score=("probe_score", "mean"),
        possible_probe_windows=("is_possible_probe", "sum"),
    ).reset_index()

    out = out.sort_values(
        ["possible_probe_windows", "max_probe_score", "total_events"],
        ascending=[False, False, False],
    )
    return out


def _counter_from_series(s: pd.Series, top_n: int = 30) -> Dict[str, int]:
    if s is None or s.empty:
        return {}
    vc = s.astype(str).value_counts(dropna=False).head(top_n)
    return {str(k): int(v) for k, v in vc.to_dict().items()}


# -----------------------------
# Main phase function
# -----------------------------
def phase3_probing_analysis(
    *,
    cfg: Phase3ProbingConfig,
    progress_desc: str = "PHASE 3",
) -> Tuple[Dict[str, pd.DataFrame], dict]:
    """Run Phase 3 probing analysis for selected applications.

    Expected input:
      cfg.input_dir/app=dns/part-*.parquet
      cfg.input_dir/app=http/part-*.parquet
      cfg.input_dir/app=tls/part-*.parquet
      cfg.input_dir/app=ssh/part-*.parquet

    Output:
      cfg.output_dir/app=dns/src_ip_window_features.parquet
      cfg.output_dir/app=dns/probing_candidates.csv
      cfg.output_dir/app=dns/src_ip_probing_summary.csv
      cfg.output_dir/metrics/phase3_probing_summary_dns.json
      cfg.output_dir/metrics/phase3_probing_summary_all.json

    Returns:
      samples_by_app: small DataFrame of top probing candidates per app
      summary_all: JSON-serializable summary dict
    """
    print("\n" + "🟠 " + "=" * 76 + "\n")
    print("PHASE 3: PROBING ANALYSIS (APP-AWARE / SOURCE-IP TIME-WINDOW)")
    print("\n" + "🟠 " + "=" * 76)

    t0 = datetime.now()
    input_dir = Path(cfg.input_dir)
    output_dir = Path(cfg.output_dir)
    metrics_dir = output_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    selected_apps = _normalize_apps(cfg.selected_apps)
    if not selected_apps:
        raise ValueError("selected_apps is empty. Provide at least one app.")

    summary_all_path = metrics_dir / "phase3_probing_summary_all.json"
    if cfg.skip_if_exists and summary_all_path.exists():
        with summary_all_path.open("r", encoding="utf-8") as f:
            summary_all = json.load(f)
        print(f"⚠️  Phase 3 skipped because summary exists: {summary_all_path}")
        return {app: pd.DataFrame() for app in selected_apps}, summary_all

    samples_by_app: Dict[str, pd.DataFrame] = {}
    app_summaries: Dict[str, dict] = {}

    total_input_rows = 0
    total_usable_rows = 0
    total_feature_rows = 0
    total_probe_candidates = 0

    for app in selected_apps:
        app_t0 = datetime.now()
        app_dir = _resolve_app_dir(input_dir, app)
        app_out_dir = output_dir / f"app={app}"
        app_out_dir.mkdir(parents=True, exist_ok=True)

        shards = _iter_shards(app_dir)
        if not shards:
            app_summary = {
                "phase": 3,
                "phase_name": "probing_analysis",
                "application": app,
                "input_app_dir": str(app_dir),
                "output_app_dir": str(app_out_dir),
                "input_shards": 0,
                "input_rows": 0,
                "usable_rows": 0,
                "feature_rows": 0,
                "possible_probe_rows": 0,
                "note": "No Phase 2 shards found for this application.",
            }
            app_summaries[app] = app_summary
            with (metrics_dir / f"phase3_probing_summary_{app}.json").open("w", encoding="utf-8") as f:
                json.dump(_json_safe(app_summary), f, indent=2, ensure_ascii=False)
            samples_by_app[app] = pd.DataFrame()
            print(f"⚠️  {app.upper()}: no shards found in {app_dir}")
            continue

        partial_frames: List[pd.DataFrame] = []
        input_rows = 0
        usable_rows = 0
        dropped_no_timestamp = 0
        dropped_no_src_ip = 0
        shard_group_rows = 0
        event_type_counter: Counter = Counter()
        label_status_counter: Counter = Counter()

        pbar = tqdm(shards, desc=f"{progress_desc} ({app})", unit="shard", dynamic_ncols=True)
        for shard_path in pbar:
            df = _read_shard(shard_path)
            if df.empty:
                continue

            if "event_type" in df.columns:
                event_type_counter.update(_safe_lower_series(df["event_type"]).value_counts().head(30).to_dict())
            if "label_status" in df.columns:
                label_status_counter.update(_safe_lower_series(df["label_status"]).value_counts().head(30).to_dict())

            agg, stats = _aggregate_shard_window_features(
                df,
                app=app,
                window_minutes=int(cfg.window_minutes),
            )

            input_rows += int(stats.get("input_rows", 0))
            usable_rows += int(stats.get("usable_rows", 0))
            dropped_no_timestamp += int(stats.get("dropped_no_timestamp", 0))
            dropped_no_src_ip += int(stats.get("dropped_no_src_ip", 0))

            if not agg.empty:
                shard_group_rows += int(len(agg))
                partial_frames.append(agg)

            pbar.set_postfix({
                "rows": f"{input_rows:,}",
                "usable": f"{usable_rows:,}",
                "groups": f"{shard_group_rows:,}",
            })

            del df, agg
            gc.collect()

        features = _merge_aggregate_frames(partial_frames)
        del partial_frames
        gc.collect()

        features = _add_probe_score(features, cfg)
        feature_rows = int(len(features))
        possible_probe_rows = int(features["is_possible_probe"].sum()) if not features.empty and "is_possible_probe" in features.columns else 0

        # Save main aggregate feature table.
        feature_path: Optional[Path] = None
        if not features.empty:
            feature_path = _write_dataframe(
                features,
                app_out_dir / "src_ip_window_features",
                fmt=cfg.write_format,
                parquet_engine=cfg.parquet_engine,
                parquet_compression=cfg.parquet_compression,
            )

        # Save candidates CSV for quick inspection/reporting.
        candidates = pd.DataFrame()
        candidates_path: Optional[Path] = None
        if not features.empty:
            candidates = features.loc[features["is_possible_probe"] == 1].copy()
            candidates = candidates.sort_values(
                ["probe_score", "event_count_window", "unique_dest_ip_window", "unique_dest_port_window"],
                ascending=[False, False, False, False],
            )
            if cfg.max_candidates_csv_rows and len(candidates) > int(cfg.max_candidates_csv_rows):
                candidates_to_save = candidates.head(int(cfg.max_candidates_csv_rows))
            else:
                candidates_to_save = candidates
            candidates_path = app_out_dir / "probing_candidates.csv"
            candidates_to_save.to_csv(candidates_path, index=False)

        # Save source-IP summary.
        src_ip_summary = _make_src_ip_summary(features)
        src_ip_summary_path: Optional[Path] = None
        if not src_ip_summary.empty:
            src_ip_summary_path = app_out_dir / "src_ip_probing_summary.csv"
            src_ip_summary.to_csv(src_ip_summary_path, index=False)

        # Keep small return sample only.
        if not candidates.empty:
            samples_by_app[app] = candidates.head(int(cfg.max_return_sample_per_app)).copy()
        else:
            samples_by_app[app] = pd.DataFrame()

        # Summary rows for report/debug.
        top_src_rows: List[dict] = []
        if not src_ip_summary.empty:
            for _, row in src_ip_summary.head(30).iterrows():
                top_src_rows.append({
                    "src_ip": str(row.get("src_ip", "")),
                    "windows_seen": int(row.get("windows_seen", 0)),
                    "total_events": int(row.get("total_events", 0)),
                    "possible_probe_windows": int(row.get("possible_probe_windows", 0)),
                    "max_probe_score": float(row.get("max_probe_score", 0.0)),
                    "max_unique_dest_ip_window": int(row.get("max_unique_dest_ip_window", 0)),
                    "max_unique_dest_port_window": int(row.get("max_unique_dest_port_window", 0)),
                    "total_alerts": int(row.get("total_alerts", 0)),
                })

        app_elapsed = (datetime.now() - app_t0).total_seconds()
        app_output_bytes = _dir_size_bytes(app_out_dir)

        app_summary = {
            "phase": 3,
            "phase_name": "probing_analysis",
            "application": app,
            "input_dir": str(input_dir),
            "input_app_dir": str(app_dir),
            "output_app_dir": str(app_out_dir),
            "metrics_dir": str(metrics_dir),
            "window_minutes": int(cfg.window_minutes),
            "thresholds": {
                "min_event_count": int(cfg.min_event_count),
                "min_unique_dest_ip": int(cfg.min_unique_dest_ip),
                "min_unique_dest_port": int(cfg.min_unique_dest_port),
                "min_alert_count": int(cfg.min_alert_count),
                "min_probe_score": float(cfg.min_probe_score),
            },
            "score_weights": {
                "event_weight": float(cfg.event_weight),
                "dest_ip_weight": float(cfg.dest_ip_weight),
                "dest_port_weight": float(cfg.dest_port_weight),
                "alert_weight": float(cfg.alert_weight),
                "prelim_malicious_weight": float(cfg.prelim_malicious_weight),
            },
            "input_shards": int(len(shards)),
            "input_rows": int(input_rows),
            "usable_rows": int(usable_rows),
            "dropped_no_timestamp": int(dropped_no_timestamp),
            "dropped_no_src_ip": int(dropped_no_src_ip),
            "shard_group_rows_before_merge": int(shard_group_rows),
            "feature_rows": int(feature_rows),
            "possible_probe_rows": int(possible_probe_rows),
            "possible_probe_percentage_of_windows": (possible_probe_rows / feature_rows * 100.0) if feature_rows else 0.0,
            "feature_path": str(feature_path) if feature_path else None,
            "candidates_path": str(candidates_path) if candidates_path else None,
            "src_ip_summary_path": str(src_ip_summary_path) if src_ip_summary_path else None,
            "top_event_type": {str(k): int(v) for k, v in event_type_counter.most_common(20)},
            "top_label_status": {str(k): int(v) for k, v in label_status_counter.most_common(20)},
            "top_src_ip_by_probe": top_src_rows,
            "unique_count_method": "sum_of_per_shard_nunique_estimate",
            "note_target": "Phase 3 creates probing evidence only. Final Target must be created in Phase 4.",
            "note_join_key": "Phase 4 should join these features using application + src_ip + window_start.",
            "output_bytes": int(app_output_bytes),
            "output_gib": float(_gib(app_output_bytes)),
            "seconds": float(app_elapsed),
        }

        with (metrics_dir / f"phase3_probing_summary_{app}.json").open("w", encoding="utf-8") as f:
            json.dump(_json_safe(app_summary), f, indent=2, ensure_ascii=False)

        app_summaries[app] = app_summary

        total_input_rows += int(input_rows)
        total_usable_rows += int(usable_rows)
        total_feature_rows += int(feature_rows)
        total_probe_candidates += int(possible_probe_rows)

        print(f"\n✅ PHASE 3 {app.upper()} COMPLETE")
        print(f"   Input shards       : {len(shards):,}")
        print(f"   Input rows         : {input_rows:,}")
        print(f"   Usable rows        : {usable_rows:,}")
        print(f"   Window feature rows: {feature_rows:,}")
        print(f"   Probe candidates   : {possible_probe_rows:,}")
        print(f"   Output dir         : {app_out_dir}")
        print(f"   Time               : {app_elapsed / 60:.2f} minutes")

        del features, candidates, src_ip_summary
        gc.collect()

    elapsed = (datetime.now() - t0).total_seconds()
    output_bytes = _dir_size_bytes(output_dir)

    # Save an all-app summary CSV for quick report/debug.
    summary_rows: List[dict] = []
    for app, s in app_summaries.items():
        summary_rows.append({
            "application": app,
            "input_shards": int(s.get("input_shards", 0)),
            "input_rows": int(s.get("input_rows", 0)),
            "usable_rows": int(s.get("usable_rows", 0)),
            "feature_rows": int(s.get("feature_rows", 0)),
            "possible_probe_rows": int(s.get("possible_probe_rows", 0)),
            "possible_probe_percentage_of_windows": float(s.get("possible_probe_percentage_of_windows", 0.0)),
            "feature_path": s.get("feature_path"),
            "candidates_path": s.get("candidates_path"),
            "src_ip_summary_path": s.get("src_ip_summary_path"),
        })
    _write_csv(metrics_dir / "phase3_probing_summary_by_app.csv", summary_rows)

    summary_all = {
        "phase": 3,
        "phase_name": "probing_analysis",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "metrics_dir": str(metrics_dir),
        "selected_apps": selected_apps,
        "window_minutes": int(cfg.window_minutes),
        "total_input_rows": int(total_input_rows),
        "total_usable_rows": int(total_usable_rows),
        "total_feature_rows": int(total_feature_rows),
        "total_possible_probe_rows": int(total_probe_candidates),
        "app_summaries": app_summaries,
        "summary_by_app_csv": str(metrics_dir / "phase3_probing_summary_by_app.csv"),
        "unique_count_method": "sum_of_per_shard_nunique_estimate",
        "note_storage": (
            "Phase 3 writes aggregate src_ip/window features, not a full duplicated row-level dataset."
        ),
        "note_target": "Phase 3 does not create final Target. Use Phase 4 for label refinement.",
        "output_bytes": int(output_bytes),
        "output_gib": float(_gib(output_bytes)),
        "seconds": float(elapsed),
    }

    with summary_all_path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(summary_all), f, indent=2, ensure_ascii=False)
    summary_all["summary_path"] = str(summary_all_path)

    print("\n✅ PHASE 3 COMPLETE (ALL APPLICATIONS)")
    print(f"   Apps processed    : {', '.join(selected_apps)}")
    print(f"   Input rows        : {total_input_rows:,}")
    print(f"   Usable rows       : {total_usable_rows:,}")
    print(f"   Feature rows      : {total_feature_rows:,}")
    print(f"   Probe candidates  : {total_probe_candidates:,}")
    print(f"   Output dir        : {output_dir}")
    print(f"   Output size       : {_gib(output_bytes):.2f} GiB")
    print(f"   Summary           : {summary_all_path}")
    print(f"   Time              : {elapsed / 60:.2f} minutes")

    gc.collect()
    return samples_by_app, summary_all




# =========================================================
# PHASE 3 RAM MODE (SMALL-DATA / SEMINAR DATASET)
# ---------------------------------------------------------
# Goal:
# - Receive a single application's Phase 2 DataFrame in RAM.
# - Build source-IP + time-window probing features.
# - Join those features back to the row-level DataFrame.
# - Do NOT read/write Parquet or CSV checkpoints.
# - Return (df_with_probe_features, summary).
# =========================================================

def phase3_probing_analysis_ram(
    df: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase3ProbingConfig] = None,
    window_minutes: int = 5,
    min_event_count: int = 50,
    min_unique_dest_ip: int = 10,
    min_unique_dest_port: int = 5,
    min_alert_count: int = 1,
    min_probe_score: float = 3.0,
    progress_desc: str = "PHASE 3",
) -> Tuple[pd.DataFrame, dict]:
    """
    RAM-mode probing analysis for one already-split application.

    Input:
      df  : Phase 2 DataFrame for exactly one app.
      app : active app name, e.g. "http", "tls", "dns", or "ssh".

    Output:
      df_out:
        Row-level DataFrame with probing/window features appended.
      summary:
        JSON-serializable per-app Phase 3 summary.

    This is intentionally different from the disk-backed function above:
    - no shard scan;
    - no parquet read/write;
    - no aggregate-only output file;
    - features are joined back into the row-level DataFrame so Phase 4 can
      refine labels directly in RAM.
    """
    print(f"\n🟠 {progress_desc}: PROBING ANALYSIS RAM MODE app={app}")

    t0 = datetime.now()
    app = str(app).strip().lower()

    if cfg is not None:
        window_minutes = int(getattr(cfg, "window_minutes", window_minutes))
        min_event_count = int(getattr(cfg, "min_event_count", min_event_count))
        min_unique_dest_ip = int(getattr(cfg, "min_unique_dest_ip", min_unique_dest_ip))
        min_unique_dest_port = int(getattr(cfg, "min_unique_dest_port", min_unique_dest_port))
        min_alert_count = int(getattr(cfg, "min_alert_count", min_alert_count))
        min_probe_score = float(getattr(cfg, "min_probe_score", min_probe_score))

    local_cfg = cfg or Phase3ProbingConfig(
        input_dir=Path("."),
        output_dir=Path("."),
        selected_apps=(app,),
        window_minutes=int(window_minutes),
        min_event_count=int(min_event_count),
        min_unique_dest_ip=int(min_unique_dest_ip),
        min_unique_dest_port=int(min_unique_dest_port),
        min_alert_count=int(min_alert_count),
        min_probe_score=float(min_probe_score),
    )

    if df is None:
        df = pd.DataFrame()

    rows_in = int(len(df))
    if df.empty:
        elapsed = (datetime.now() - t0).total_seconds()
        summary = {
            "phase": 3,
            "phase_name": "probing_analysis",
            "status": "completed",
            "execution_mode": "ram",
            "application": app,
            "rows_in": 0,
            "rows_out": 0,
            "usable_rows": 0,
            "feature_rows": 0,
            "possible_probe_rows": 0,
            "possible_probe_row_percentage": 0.0,
            "seconds": float(elapsed),
            "note": "Input DataFrame is empty.",
        }
        return df.copy(), summary

    out = df.copy()
    out["application"] = app

    # Prepare compact window frame for aggregation.
    work, prep_stats = _prepare_window_frame(out, app=app, window_minutes=int(window_minutes))

    # Temporary row index is used to join aggregate features back to rows.
    ts = _get_timestamp_series(out)
    src_ip = _safe_str_series(out["src_ip"]) if "src_ip" in out.columns else pd.Series("", index=out.index)
    window_start = ts.dt.floor(f"{int(window_minutes)}min")

    row_keys = pd.DataFrame({
        "_row_index": out.index,
        "application": app,
        "src_ip": src_ip.astype(str),
        "window_start": window_start,
    })

    feature_rows = 0
    possible_probe_windows = 0
    possible_probe_rows = 0
    top_src_rows: List[dict] = []
    features = pd.DataFrame()

    if not work.empty:
        keys = ["application", "window_start", "src_ip"]
        gb = work.groupby(keys, sort=False, dropna=False)
        features = gb.agg(
            event_count_window=("src_ip", "size"),
            unique_dest_ip_window=("dest_ip", "nunique"),
            unique_dest_port_window=("dest_port", "nunique"),
            alert_count_window=("has_alert", "sum"),
            target_prelim_malicious_count=("target_prelim_malicious", "sum"),
            total_bytes_window=("total_bytes", "sum"),
            total_pkts_window=("total_pkts", "sum"),
            first_seen=("timestamp", "min"),
            last_seen=("timestamp", "max"),
        ).reset_index()

        features = _add_probe_score(features, local_cfg)
        feature_rows = int(len(features))
        possible_probe_windows = int(features["is_possible_probe"].sum()) if "is_possible_probe" in features.columns else 0

        # _add_probe_score converts window_start to ISO string. Normalize row keys too.
        row_keys["window_start"] = pd.to_datetime(row_keys["window_start"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        feature_cols = [
            "application", "window_start", "src_ip",
            "event_count_window", "unique_dest_ip_window", "unique_dest_port_window",
            "alert_count_window", "target_prelim_malicious_count",
            "total_bytes_window", "total_pkts_window",
            "bytes_per_event_window", "pkts_per_event_window",
            "probe_score", "is_possible_probe", "probe_reason",
            "first_seen", "last_seen",
        ]
        feature_cols = [c for c in feature_cols if c in features.columns]

        joined = row_keys.merge(
            features[feature_cols],
            on=["application", "window_start", "src_ip"],
            how="left",
        ).set_index("_row_index")

        append_cols = [c for c in joined.columns if c not in {"application", "src_ip"}]
        for c in append_cols:
            out[c] = joined[c]

        numeric_fill_cols = [
            "event_count_window", "unique_dest_ip_window", "unique_dest_port_window",
            "alert_count_window", "target_prelim_malicious_count",
            "total_bytes_window", "total_pkts_window",
            "bytes_per_event_window", "pkts_per_event_window",
            "probe_score", "is_possible_probe",
        ]
        for c in numeric_fill_cols:
            if c in out.columns:
                out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

        if "probe_reason" in out.columns:
            out["probe_reason"] = out["probe_reason"].fillna("below_threshold")
        else:
            out["probe_reason"] = "below_threshold"

        if "is_possible_probe" in out.columns:
            out["is_possible_probe"] = (pd.to_numeric(out["is_possible_probe"], errors="coerce").fillna(0) > 0).astype(np.int8)
            # Alias for RAM-mode Phase 4 compatibility.
            out["is_probe_suspicious"] = out["is_possible_probe"].astype(np.int8)
            possible_probe_rows = int(out["is_possible_probe"].sum())
        else:
            out["is_possible_probe"] = 0
            out["is_probe_suspicious"] = 0

        src_ip_summary = _make_src_ip_summary(features)
        if not src_ip_summary.empty:
            for _, row in src_ip_summary.head(30).iterrows():
                top_src_rows.append({
                    "src_ip": str(row.get("src_ip", "")),
                    "windows_seen": int(row.get("windows_seen", 0)),
                    "total_events": int(row.get("total_events", 0)),
                    "possible_probe_windows": int(row.get("possible_probe_windows", 0)),
                    "max_probe_score": float(row.get("max_probe_score", 0.0)),
                    "max_unique_dest_ip_window": int(row.get("max_unique_dest_ip_window", 0)),
                    "max_unique_dest_port_window": int(row.get("max_unique_dest_port_window", 0)),
                    "total_alerts": int(row.get("total_alerts", 0)),
                })
    else:
        out["window_start"] = pd.NaT
        out["event_count_window"] = 0
        out["unique_dest_ip_window"] = 0
        out["unique_dest_port_window"] = 0
        out["alert_count_window"] = 0
        out["target_prelim_malicious_count"] = 0
        out["total_bytes_window"] = 0
        out["total_pkts_window"] = 0
        out["bytes_per_event_window"] = 0.0
        out["pkts_per_event_window"] = 0.0
        out["probe_score"] = 0.0
        out["is_possible_probe"] = 0
        out["is_probe_suspicious"] = 0
        out["probe_reason"] = "below_threshold"

    elapsed = (datetime.now() - t0).total_seconds()
    summary = {
        "phase": 3,
        "phase_name": "probing_analysis",
        "status": "completed",
        "execution_mode": "ram",
        "application": app,
        "rows_in": int(rows_in),
        "rows_out": int(len(out)),
        "usable_rows": int(prep_stats.get("usable_rows", 0)),
        "dropped_no_timestamp": int(prep_stats.get("dropped_no_timestamp", 0)),
        "dropped_no_src_ip": int(prep_stats.get("dropped_no_src_ip", 0)),
        "feature_rows": int(feature_rows),
        "possible_probe_windows": int(possible_probe_windows),
        "possible_probe_rows": int(possible_probe_rows),
        "possible_probe_row_percentage": (possible_probe_rows / rows_in * 100.0) if rows_in else 0.0,
        "window_minutes": int(window_minutes),
        "thresholds": {
            "min_event_count": int(min_event_count),
            "min_unique_dest_ip": int(min_unique_dest_ip),
            "min_unique_dest_port": int(min_unique_dest_port),
            "min_alert_count": int(min_alert_count),
            "min_probe_score": float(min_probe_score),
        },
        "top_src_ip_by_probe": top_src_rows,
        "top_event_type": _counter_from_series(out["event_type"], 20) if "event_type" in out.columns else {},
        "top_label_status": _counter_from_series(out["label_status"], 20) if "label_status" in out.columns else {},
        "df_shape": [int(out.shape[0]), int(out.shape[1])],
        "seconds": float(elapsed),
        "note_target": "Phase 3 creates probing evidence only. Final Target must be created in Phase 4.",
        "note_storage": "RAM mode does not write aggregate probing Parquet/CSV checkpoints.",
    }

    gc.collect()

    print(f"✅ PHASE 3 RAM {app.upper()} COMPLETE")
    print(f"   Rows in/out      : {rows_in:,} -> {len(out):,}")
    print(f"   Usable rows      : {int(prep_stats.get('usable_rows', 0)):,}")
    print(f"   Window groups    : {feature_rows:,}")
    print(f"   Probe rows       : {possible_probe_rows:,}")
    print(f"   Time             : {elapsed / 60:.2f} minutes")

    return out, _json_safe(summary)


# Convenience aliases used by RAM-mode pipeline variants.
def phase3_probing_ram(
    df: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase3ProbingConfig] = None,
    window_minutes: int = 5,
    min_probe_score: float = 3.0,
    progress_desc: str = "PHASE 3",
) -> Tuple[pd.DataFrame, dict]:
    return phase3_probing_analysis_ram(
        df,
        app=app,
        cfg=cfg,
        window_minutes=window_minutes,
        min_probe_score=min_probe_score,
        progress_desc=progress_desc,
    )


def run_phase3_probing_analysis_ram(
    df: pd.DataFrame,
    *,
    app: str,
    window_minutes: int = 5,
    min_probe_score: float = 3.0,
) -> Tuple[pd.DataFrame, dict]:
    return phase3_probing_analysis_ram(
        df,
        app=app,
        window_minutes=window_minutes,
        min_probe_score=min_probe_score,
    )

# Backward-compatible/simple aliases for future pipeline use.
def phase3_probing(
    *,
    cfg: Phase3ProbingConfig,
    progress_desc: str = "PHASE 3",
) -> Tuple[Dict[str, pd.DataFrame], dict]:
    return phase3_probing_analysis(cfg=cfg, progress_desc=progress_desc)


def run_phase3_probing_analysis(
    *,
    input_dir: Path,
    output_dir: Path,
    selected_apps: Sequence[str] = DEFAULT_SELECTED_APPS,
    window_minutes: int = 5,
    min_event_count: int = 50,
    min_unique_dest_ip: int = 10,
    min_unique_dest_port: int = 5,
    min_alert_count: int = 1,
    min_probe_score: float = 3.0,
    write_format: str = "parquet",
    parquet_engine: Optional[str] = None,
    parquet_compression: Optional[str] = "snappy",
    skip_if_exists: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], dict]:
    cfg = Phase3ProbingConfig(
        input_dir=Path(input_dir),
        output_dir=Path(output_dir),
        selected_apps=tuple(selected_apps),
        window_minutes=int(window_minutes),
        min_event_count=int(min_event_count),
        min_unique_dest_ip=int(min_unique_dest_ip),
        min_unique_dest_port=int(min_unique_dest_port),
        min_alert_count=int(min_alert_count),
        min_probe_score=float(min_probe_score),
        write_format=write_format,
        parquet_engine=parquet_engine,
        parquet_compression=parquet_compression,
        skip_if_exists=skip_if_exists,
    )
    return phase3_probing_analysis(cfg=cfg)


if __name__ == "__main__":
    # Example only. In the real run, main.py/pipeline.py should call this function.
    # Adjust paths before running this file directly.
    samples, summary = run_phase3_probing_analysis(
        input_dir=Path("results/phase2_app_dataset"),
        output_dir=Path("results/phase3_probing"),
        selected_apps=("dns", "http", "tls", "ssh"),
        window_minutes=5,
        min_event_count=50,
        min_unique_dest_ip=10,
        min_unique_dest_port=5,
        min_alert_count=1,
        min_probe_score=3.0,
        write_format="parquet",
        parquet_engine="fastparquet",
        parquet_compression="snappy",
        skip_if_exists=False,
    )
    print(json.dumps(_json_safe(summary), indent=2, ensure_ascii=False))
