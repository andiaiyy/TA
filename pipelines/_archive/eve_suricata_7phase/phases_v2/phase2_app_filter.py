from __future__ import annotations

import gc
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =========================================================
# PHASE 2: APPLICATION FILTERING (DISK-BACKED / SHARDED)
# ----------------------------------------A-----------------
# Goal:
# - Read Phase 1 staging shards from storage.
# - Split rows into selected network applications: DNS/HTTP/TLS/SSH.
# - Use app_proto first, then port fallback.
# - Write per-application shards to storage.
# - Return only small samples + summary, not full dataset in RAM.
#
# Important:
# - This phase does NOT create final Target.
# - It preserves Phase 1 label evidence columns for later label refinement.
# - Final Target must be created later in phase4_label_refinement.py.
# =========================================================

DEFAULT_APP_PORTS: Dict[str, List[int]] = {
    "dns": [53],
    "http": [80],
    "tls": [443],
    "ssh": [22],
}

DEFAULT_APP_PROTO_ALIASES: Dict[str, List[str]] = {
    "dns": ["dns"],
    "http": ["http"],
    "tls": ["tls", "ssl"],
    "ssh": ["ssh"],
}

DEFAULT_APP_PRIORITY: List[str] = ["dns", "http", "tls", "ssh"]


@dataclass(frozen=True)
class Phase2AppFilterConfig:
    """
    Configuration for Phase 2 application filtering.

    input_dir:
        Usually Phase 1 output directory. The function accepts either:
        - results/phase1_dataset
        - results/phase1_dataset/staging

    output_dir:
        Phase 2 output directory.

    selected_apps:
        Apps to materialize. Default: dns, http, tls, ssh.

    match_src_port:
        If True, port fallback checks both src_port and dest_port.
        If False, only dest_port is used.

    allow_multi_app:
        If False, one row is assigned to at most one app based on priority.
        If True, one row may be duplicated into multiple app datasets when
        it matches multiple app rules. Default False is safer for modeling.

    save_unmatched_sample:
        If True, stores a small sample of rows that match none of the apps.
    """

    input_dir: Path
    output_dir: Path

    selected_apps: Sequence[str] = field(default_factory=lambda: tuple(DEFAULT_APP_PRIORITY))
    app_ports: Dict[str, List[int]] = field(default_factory=lambda: dict(DEFAULT_APP_PORTS))
    app_proto_aliases: Dict[str, List[str]] = field(default_factory=lambda: dict(DEFAULT_APP_PROTO_ALIASES))
    app_priority: Sequence[str] = field(default_factory=lambda: tuple(DEFAULT_APP_PRIORITY))

    write_format: str = "parquet"          # "parquet" or "csv"
    parquet_engine: Optional[str] = None    # "fastparquet" | "pyarrow" | None
    parquet_compression: Optional[str] = "snappy"

    match_src_port: bool = True
    allow_multi_app: bool = False
    save_unmatched_sample: bool = True
    max_unmatched_sample: int = 50_000
    max_return_sample_per_app: int = 20_000

    skip_if_exists: bool = False


class _DataFrameShardWriter:
    """Writes one DataFrame at a time into part files."""

    def __init__(
        self,
        out_dir: Path,
        fmt: str,
        *,
        parquet_engine: Optional[str] = None,
        parquet_compression: Optional[str] = "snappy",
    ) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        fmt = (fmt or "parquet").strip().lower()
        if fmt not in {"parquet", "csv"}:
            fmt = "parquet"

        self.requested_fmt = fmt
        self.actual_fmt = fmt
        self.parquet_engine = parquet_engine
        self.parquet_compression = parquet_compression
        self.part = 0

        if self.actual_fmt == "parquet":
            self._resolve_parquet_engine()

    def _resolve_parquet_engine(self) -> None:
        if self.parquet_engine:
            eng = self.parquet_engine.strip().lower()
            if eng == "pyarrow":
                try:
                    import pyarrow  # noqa: F401
                    self.parquet_engine = "pyarrow"
                    return
                except Exception:
                    self.actual_fmt = "csv"
                    return
            if eng == "fastparquet":
                try:
                    import fastparquet  # noqa: F401
                    self.parquet_engine = "fastparquet"
                    return
                except Exception:
                    self.actual_fmt = "csv"
                    return

            self.parquet_engine = None

        try:
            import pyarrow  # noqa: F401
            self.parquet_engine = None
            self.actual_fmt = "parquet"
            return
        except Exception:
            pass

        try:
            import fastparquet  # noqa: F401
            self.parquet_engine = None
            self.actual_fmt = "parquet"
            return
        except Exception:
            self.actual_fmt = "csv"

    def write(self, df: pd.DataFrame) -> Optional[Path]:
        if df is None or df.empty:
            return None

        self.part += 1
        if self.actual_fmt == "parquet":
            path = self.out_dir / f"part-{self.part:06d}.parquet"
            kwargs: Dict[str, Any] = {"index": False}
            if self.parquet_engine:
                kwargs["engine"] = self.parquet_engine
            if self.parquet_compression:
                kwargs["compression"] = self.parquet_compression
            df.to_parquet(path, **kwargs)
            return path

        path = self.out_dir / f"part-{self.part:06d}.csv.gz"
        df.to_csv(path, index=False, compression="gzip")
        return path


def _safe_int_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(np.int64)


def _safe_str_series(s: pd.Series) -> pd.Series:
    out = s.astype("object")
    out = out.where(pd.notna(out), "")
    return out.astype(str).str.strip().str.lower()


def _resolve_staging_dir(input_dir: Path) -> Path:
    input_dir = Path(input_dir)
    if (input_dir / "staging").exists():
        return input_dir / "staging"
    return input_dir


def _iter_shards(input_dir: Path) -> List[Path]:
    input_dir = _resolve_staging_dir(input_dir)
    patterns = ["*.parquet", "*.csv.gz", "*.csv"]
    files: List[Path] = []
    for pat in patterns:
        files.extend(sorted(input_dir.glob(pat)))
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


def _normalize_apps(apps: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    for app in apps:
        a = str(app).strip().lower()
        if a and a not in normalized:
            normalized.append(a)
    return normalized


def _make_app_masks(df: pd.DataFrame, cfg: Phase2AppFilterConfig) -> Tuple[Dict[str, pd.Series], Dict[str, pd.Series], Dict[str, pd.Series]]:
    """
    Returns:
      selected_masks[app]     : final selected rows for app
      proto_masks[app]        : rows matching app_proto aliases
      port_masks[app]         : rows matching port rule
    """
    selected_apps = _normalize_apps(cfg.selected_apps)
    priority = [a for a in _normalize_apps(cfg.app_priority) if a in selected_apps]
    for app in selected_apps:
        if app not in priority:
            priority.append(app)

    n = len(df)
    false_mask = pd.Series(False, index=df.index)

    app_proto = _safe_str_series(df["app_proto"]) if "app_proto" in df.columns else pd.Series("", index=df.index)
    src_port = _safe_int_series(df["src_port"]) if "src_port" in df.columns else pd.Series(0, index=df.index)
    dest_port = _safe_int_series(df["dest_port"]) if "dest_port" in df.columns else pd.Series(0, index=df.index)

    proto_masks: Dict[str, pd.Series] = {}
    port_masks: Dict[str, pd.Series] = {}
    selected_masks: Dict[str, pd.Series] = {}

    for app in selected_apps:
        aliases = [str(x).strip().lower() for x in cfg.app_proto_aliases.get(app, [app])]
        aliases = [x for x in aliases if x]
        ports = set(int(p) for p in cfg.app_ports.get(app, []))

        if aliases:
            proto_mask = app_proto.isin(aliases)
        else:
            proto_mask = false_mask.copy()

        if ports:
            if cfg.match_src_port:
                port_mask = dest_port.isin(ports) | src_port.isin(ports)
            else:
                port_mask = dest_port.isin(ports)
        else:
            port_mask = false_mask.copy()

        proto_masks[app] = proto_mask
        port_masks[app] = port_mask

    if cfg.allow_multi_app:
        for app in selected_apps:
            selected_masks[app] = proto_masks[app] | port_masks[app]
        return selected_masks, proto_masks, port_masks

    # Single-app assignment:
    # 1) app_proto match wins first.
    # 2) port fallback only for rows not already assigned.
    already = pd.Series(False, index=df.index)
    for app in priority:
        selected_masks[app] = pd.Series(False, index=df.index)

    for app in priority:
        m = proto_masks[app] & (~already)
        selected_masks[app] = selected_masks[app] | m
        already = already | m

    for app in priority:
        m = port_masks[app] & (~already)
        selected_masks[app] = selected_masks[app] | m
        already = already | m

    return selected_masks, proto_masks, port_masks


def _add_app_columns(
    df_sub: pd.DataFrame,
    *,
    app: str,
    proto_mask: pd.Series,
    port_mask: pd.Series,
) -> pd.DataFrame:
    out = df_sub.copy()
    out["application"] = app

    # Align masks to selected rows.
    pm = proto_mask.loc[out.index]
    qm = port_mask.loc[out.index]

    reason = np.where(
        pm & qm,
        "app_proto+port",
        np.where(pm, "app_proto", np.where(qm, "port", "unknown")),
    )
    out["app_filter_reason"] = reason
    return out


def _write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def phase2_filter_applications(
    *,
    cfg: Phase2AppFilterConfig,
    progress_desc: str = "PHASE 2",
) -> Tuple[Dict[str, pd.DataFrame], dict]:
    """
    Disk-backed application filtering.

    Expected input:
      cfg.input_dir/staging/part-*.parquet
      or cfg.input_dir/part-*.parquet

    Output:
      cfg.output_dir/app=dns/part-*.parquet
      cfg.output_dir/app=http/part-*.parquet
      cfg.output_dir/app=tls/part-*.parquet
      cfg.output_dir/app=ssh/part-*.parquet
      cfg.output_dir/metrics/phase2_app_filter_summary.json

    Returns:
      samples_by_app: small DataFrame sample per app
      summary: JSON-serializable summary dict
    """
    print("\n" + "🟣 " + "=" * 76 + "\n")
    print("PHASE 2: APPLICATION FILTERING (DISK-BACKED / SHARDED)")
    print("\n" + "🟣 " + "=" * 76)

    t0 = datetime.now()

    input_dir = Path(cfg.input_dir)
    staging_dir = _resolve_staging_dir(input_dir)
    output_dir = Path(cfg.output_dir)
    metrics_dir = output_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    selected_apps = _normalize_apps(cfg.selected_apps)
    if not selected_apps:
        raise ValueError("selected_apps is empty. Provide at least one app, e.g. ['dns','http','tls','ssh'].")

    input_files = _iter_shards(input_dir)
    if not input_files:
        raise FileNotFoundError(
            f"No Phase 1 staging shards found in {staging_dir}. Expected *.parquet, *.csv.gz, or *.csv."
        )

    summary_path = metrics_dir / "phase2_app_filter_summary.json"
    if cfg.skip_if_exists and summary_path.exists():
        with summary_path.open("r", encoding="utf-8") as f:
            summary = json.load(f)
        print(f"⚠️  Phase 2 skipped because summary exists: {summary_path}")
        return {app: pd.DataFrame() for app in selected_apps}, summary

    writers: Dict[str, _DataFrameShardWriter] = {}
    for app in selected_apps:
        writers[app] = _DataFrameShardWriter(
            output_dir / f"app={app}",
            cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
        )

    samples_by_app_rows: Dict[str, List[dict]] = {app: [] for app in selected_apps}
    unmatched_sample_rows: List[dict] = []

    rows_seen = 0
    rows_matched_any = 0
    unmatched_rows = 0
    output_rows_by_app: Counter = Counter()
    shards_by_app: Counter = Counter()
    reason_by_app: Dict[str, Counter] = {app: Counter() for app in selected_apps}
    dest_port_by_app: Dict[str, Counter] = {app: Counter() for app in selected_apps}
    app_proto_by_app: Dict[str, Counter] = {app: Counter() for app in selected_apps}
    event_type_by_app: Dict[str, Counter] = {app: Counter() for app in selected_apps}
    label_status_by_app: Dict[str, Counter] = {app: Counter() for app in selected_apps}

    pbar = tqdm(input_files, desc=f"{progress_desc} (filter shards)", unit="shard", dynamic_ncols=True)
    for shard_path in pbar:
        df = _read_shard(shard_path)
        if df.empty:
            continue

        # Ensure important columns exist so masks do not fail.
        for c in ["app_proto", "src_port", "dest_port", "event_type", "label_status"]:
            if c not in df.columns:
                df[c] = "" if c in {"app_proto", "event_type", "label_status"} else 0

        n = len(df)
        rows_seen += n

        selected_masks, proto_masks, port_masks = _make_app_masks(df, cfg)
        matched_any = pd.Series(False, index=df.index)

        for app in selected_apps:
            mask = selected_masks.get(app)
            if mask is None or not bool(mask.any()):
                continue

            matched_any = matched_any | mask
            df_sub = df.loc[mask]
            df_sub = _add_app_columns(
                df_sub,
                app=app,
                proto_mask=proto_masks[app],
                port_mask=port_masks[app],
            )

            out_path = writers[app].write(df_sub)
            if out_path is not None:
                shards_by_app[app] += 1

            row_count = int(len(df_sub))
            output_rows_by_app[app] += row_count

            if "app_filter_reason" in df_sub.columns:
                reason_by_app[app].update(df_sub["app_filter_reason"].astype(str).value_counts().to_dict())

            if "dest_port" in df_sub.columns:
                dest_port_by_app[app].update(_safe_int_series(df_sub["dest_port"]).value_counts().head(50).to_dict())
            if "app_proto" in df_sub.columns:
                app_proto_by_app[app].update(_safe_str_series(df_sub["app_proto"]).value_counts().head(50).to_dict())
            if "event_type" in df_sub.columns:
                event_type_by_app[app].update(_safe_str_series(df_sub["event_type"]).value_counts().head(50).to_dict())
            if "label_status" in df_sub.columns:
                label_status_by_app[app].update(df_sub["label_status"].astype(str).value_counts().head(50).to_dict())

            # Keep small samples only.
            sample_max = int(cfg.max_return_sample_per_app)
            if sample_max > 0 and len(samples_by_app_rows[app]) < sample_max:
                need = sample_max - len(samples_by_app_rows[app])
                samples_by_app_rows[app].extend(df_sub.head(need).to_dict(orient="records"))

            del df_sub

        if cfg.allow_multi_app:
            # In multi-app mode matched_any is still useful for unmatched count.
            pass

        matched_count = int(matched_any.sum())
        rows_matched_any += matched_count
        unmatched_count = int(n - matched_count)
        unmatched_rows += unmatched_count

        if cfg.save_unmatched_sample and unmatched_count > 0 and len(unmatched_sample_rows) < cfg.max_unmatched_sample:
            need = cfg.max_unmatched_sample - len(unmatched_sample_rows)
            unmatched_sample_rows.extend(df.loc[~matched_any].head(need).to_dict(orient="records"))

        pbar.set_postfix({
            "rows": f"{rows_seen:,}",
            "matched": f"{rows_matched_any:,}",
            "unmatched": f"{unmatched_rows:,}",
        })

        del df
        gc.collect()

    # Save samples.
    samples_by_app: Dict[str, pd.DataFrame] = {}
    sample_dir = output_dir / "sample"
    sample_dir.mkdir(parents=True, exist_ok=True)

    for app in selected_apps:
        sample_df = pd.DataFrame.from_records(samples_by_app_rows[app])
        samples_by_app[app] = sample_df
        if not sample_df.empty:
            sample_path = sample_dir / f"phase2_sample_{app}.csv"
            sample_df.to_csv(sample_path, index=False)

    unmatched_sample_path: Optional[Path] = None
    if cfg.save_unmatched_sample and unmatched_sample_rows:
        unmatched_sample_path = sample_dir / "phase2_unmatched_sample.csv"
        pd.DataFrame.from_records(unmatched_sample_rows).to_csv(unmatched_sample_path, index=False)

    # Save distribution CSVs for quick report/debug.
    app_distribution_rows: List[dict] = []
    for app in selected_apps:
        count = int(output_rows_by_app[app])
        app_distribution_rows.append({
            "application": app,
            "rows": count,
            "percentage_of_input_rows": (count / rows_seen * 100.0) if rows_seen else 0.0,
            "shards": int(shards_by_app[app]),
            "output_dir": str(output_dir / f"app={app}"),
        })
    app_distribution_rows.append({
        "application": "unmatched",
        "rows": int(unmatched_rows),
        "percentage_of_input_rows": (unmatched_rows / rows_seen * 100.0) if rows_seen else 0.0,
        "shards": 0,
        "output_dir": None,
    })
    _write_csv(metrics_dir / "app_distribution.csv", app_distribution_rows)

    app_dest_port_rows: List[dict] = []
    for app in selected_apps:
        for port, count in dest_port_by_app[app].most_common(30):
            app_dest_port_rows.append({"application": app, "dest_port": int(port), "count": int(count)})
    _write_csv(metrics_dir / "app_dest_port_distribution.csv", app_dest_port_rows)

    app_proto_rows: List[dict] = []
    for app in selected_apps:
        for app_proto, count in app_proto_by_app[app].most_common(30):
            app_proto_rows.append({"application": app, "app_proto": str(app_proto), "count": int(count)})
    _write_csv(metrics_dir / "app_proto_distribution_by_app.csv", app_proto_rows)

    app_event_type_rows: List[dict] = []
    for app in selected_apps:
        for event_type, count in event_type_by_app[app].most_common(30):
            app_event_type_rows.append({"application": app, "event_type": str(event_type), "count": int(count)})
    _write_csv(metrics_dir / "app_event_type_distribution.csv", app_event_type_rows)

    label_status_rows: List[dict] = []
    for app in selected_apps:
        for label_status, count in label_status_by_app[app].most_common(30):
            label_status_rows.append({"application": app, "label_status": str(label_status), "count": int(count)})
    _write_csv(metrics_dir / "app_label_status_distribution.csv", label_status_rows)

    elapsed = (datetime.now() - t0).total_seconds()
    output_bytes = _dir_size_bytes(output_dir)

    summary = {
        "phase": 2,
        "phase_name": "application_filtering",
        "input_dir": str(input_dir),
        "staging_dir": str(staging_dir),
        "output_dir": str(output_dir),
        "metrics_dir": str(metrics_dir),
        "selected_apps": selected_apps,
        "app_ports": {k: [int(x) for x in v] for k, v in cfg.app_ports.items()},
        "app_proto_aliases": {k: [str(x) for x in v] for k, v in cfg.app_proto_aliases.items()},
        "app_priority": list(cfg.app_priority),
        "match_src_port": bool(cfg.match_src_port),
        "allow_multi_app": bool(cfg.allow_multi_app),
        "input_shards": int(len(input_files)),
        "rows_seen": int(rows_seen),
        "rows_matched_any": int(rows_matched_any),
        "unmatched_rows": int(unmatched_rows),
        "unmatched_percentage": (unmatched_rows / rows_seen * 100.0) if rows_seen else 0.0,
        "output_rows_by_app": {app: int(output_rows_by_app[app]) for app in selected_apps},
        "shards_by_app": {app: int(shards_by_app[app]) for app in selected_apps},
        "reason_by_app": {app: {str(k): int(v) for k, v in reason_by_app[app].items()} for app in selected_apps},
        "top_dest_ports_by_app": {
            app: {str(k): int(v) for k, v in dest_port_by_app[app].most_common(20)}
            for app in selected_apps
        },
        "top_app_proto_by_app": {
            app: {str(k): int(v) for k, v in app_proto_by_app[app].most_common(20)}
            for app in selected_apps
        },
        "top_event_type_by_app": {
            app: {str(k): int(v) for k, v in event_type_by_app[app].most_common(20)}
            for app in selected_apps
        },
        "label_status_by_app": {
            app: {str(k): int(v) for k, v in label_status_by_app[app].most_common(20)}
            for app in selected_apps
        },
        "dataset_format": next(iter(writers.values())).actual_fmt if writers else cfg.write_format,
        "output_bytes": int(output_bytes),
        "output_gib": float(_gib(output_bytes)),
        "unmatched_sample_path": str(unmatched_sample_path) if unmatched_sample_path else None,
        "seconds": float(elapsed),
        "note_target": (
            "Phase 2 only filters by application. It preserves Phase 1 label evidence and does not create final Target."
        ),
        "note_filter_rule": (
            "Application assignment uses app_proto aliases first, then port fallback. "
            "If allow_multi_app=False, each row is assigned to at most one app based on app_priority."
        ),
    }

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    summary["summary_path"] = str(summary_path)

    gc.collect()

    print("\n✅ PHASE 2 COMPLETE (APPLICATION FILTERING)")
    print(f"   Input shards   : {len(input_files):,}")
    print(f"   Rows seen      : {rows_seen:,}")
    print(f"   Matched rows   : {rows_matched_any:,}")
    print(f"   Unmatched rows : {unmatched_rows:,}")
    for app in selected_apps:
        print(f"   {app.upper():<5} rows    : {int(output_rows_by_app[app]):,} | shards: {int(shards_by_app[app]):,}")
    print(f"   Output dir     : {output_dir}")
    print(f"   Output size    : {_gib(output_bytes):.2f} GiB")
    print(f"   Summary        : {summary_path}")
    print(f"   Time           : {elapsed / 60:.2f} minutes")

    return samples_by_app, summary


# Backward-compatible/simple aliases for future pipeline use.
def phase2_app_filter(
    *,
    cfg: Phase2AppFilterConfig,
    progress_desc: str = "PHASE 2",
) -> Tuple[Dict[str, pd.DataFrame], dict]:
    return phase2_filter_applications(cfg=cfg, progress_desc=progress_desc)


def run_phase2_app_filter(
    *,
    input_dir: Path,
    output_dir: Path,
    selected_apps: Sequence[str] = ("dns", "http", "tls", "ssh"),
    write_format: str = "parquet",
    parquet_engine: Optional[str] = None,
    parquet_compression: Optional[str] = "snappy",
    match_src_port: bool = True,
    allow_multi_app: bool = False,
    skip_if_exists: bool = False,
) -> Tuple[Dict[str, pd.DataFrame], dict]:
    cfg = Phase2AppFilterConfig(
        input_dir=Path(input_dir),
        output_dir=Path(output_dir),
        selected_apps=tuple(selected_apps),
        write_format=write_format,
        parquet_engine=parquet_engine,
        parquet_compression=parquet_compression,
        match_src_port=match_src_port,
        allow_multi_app=allow_multi_app,
        skip_if_exists=skip_if_exists,
    )
    return phase2_filter_applications(cfg=cfg)


if __name__ == "__main__":
    # Example only. In the real run, main.py/pipeline.py should call this function.
    # Adjust paths before running this file directly.
    samples, summary = run_phase2_app_filter(
        input_dir=Path("results/phase1_dataset"),
        output_dir=Path("results/phase2_app_dataset"),
        selected_apps=("dns", "http", "tls", "ssh"),
        write_format="parquet",
        parquet_engine="fastparquet",
        parquet_compression="snappy",
        match_src_port=True,
        allow_multi_app=False,
        skip_if_exists=False,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


# =============================================================================
# RAM MODE API (SMALL DATA / ALREADY SPLIT BY APPLICATION)
# =============================================================================

@dataclass(frozen=True)
class Phase2RAMConfig:
    """
    RAM-mode Phase 2 configuration.

    This mode is intended for the current small seminar/PPT dataset where the
    raw EVE JSONL has already been split into per-application files such as
    eve_http.jsonl, eve_tls.jsonl, eve_dns.jsonl, and eve_ssh.jsonl.

    Phase 2 therefore does NOT perform heavy filtering and does NOT write
    Parquet/checkpoint shards. It only validates the active app, annotates the
    DataFrame with lightweight application columns, and returns the same
    DataFrame for Phase 3.
    """

    app: str
    app_ports: Dict[str, Sequence[int]] = field(default_factory=lambda: dict(DEFAULT_APP_PORTS))
    app_proto_aliases: Dict[str, Sequence[str]] = field(default_factory=lambda: dict(DEFAULT_APP_PROTO_ALIASES))
    match_src_port: bool = True
    strict_validation: bool = False
    add_application_columns: bool = True


def _ram_counter_top(series: pd.Series, n: int = 10) -> Dict[str, int]:
    try:
        s = series.astype("object")
        s = s.where(pd.notna(s), "")
        vc = s.astype(str).value_counts(dropna=False).head(int(n))
        return {str(k): int(v) for k, v in vc.items()}
    except Exception:
        return {}


def _ram_expected_app_masks(
    df: pd.DataFrame,
    *,
    app: str,
    app_ports: Dict[str, Sequence[int]],
    app_proto_aliases: Dict[str, Sequence[str]],
    match_src_port: bool = True,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Return (proto_mask, port_mask, any_mask) for the active app.
    """
    app = str(app).strip().lower()
    idx = df.index
    false_mask = pd.Series(False, index=idx)

    if "app_proto" in df.columns:
        app_proto = _safe_str_series(df["app_proto"])
    else:
        app_proto = pd.Series("", index=idx)

    aliases = [str(x).strip().lower() for x in app_proto_aliases.get(app, [app])]
    aliases = [x for x in aliases if x]
    proto_mask = app_proto.isin(aliases) if aliases else false_mask.copy()

    ports = set(int(p) for p in app_ports.get(app, []) if p is not None)
    if ports:
        dest_port = _safe_int_series(df["dest_port"]) if "dest_port" in df.columns else pd.Series(0, index=idx)
        if match_src_port:
            src_port = _safe_int_series(df["src_port"]) if "src_port" in df.columns else pd.Series(0, index=idx)
            port_mask = dest_port.isin(ports) | src_port.isin(ports)
        else:
            port_mask = dest_port.isin(ports)
    else:
        port_mask = false_mask.copy()

    return proto_mask, port_mask, proto_mask | port_mask


def phase2_validate_app_ram(
    df: pd.DataFrame,
    *,
    cfg: Phase2RAMConfig,
    progress_desc: str = "PHASE 2",
) -> Tuple[pd.DataFrame, dict]:
    """
    RAM-mode Phase 2: app validation + pass-through.

    Input:
      df from Phase 1 RAM mode for exactly one active app.

    Output:
      the same DataFrame object, optionally annotated with:
        - application
        - app_filter_reason

    This function intentionally does not write Parquet or split rows into app
    folders. The app loop is controlled by pipeline.py/main.py.
    """
    print("\n" + "🟣 " + "=" * 76 + "\n")
    print(f"{progress_desc}: APP VALIDATION / PASS-THROUGH (RAM MODE) | app={cfg.app}")
    print("\n" + "🟣 " + "=" * 76)

    t0 = datetime.now()
    app = str(cfg.app).strip().lower()
    if not app:
        raise ValueError("Phase2RAMConfig.app is empty.")

    if df is None:
        raise ValueError("Phase 2 RAM received df=None.")
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Phase 2 RAM expects pandas DataFrame, got {type(df)!r}.")

    rows_in = int(len(df))
    cols_in = int(len(df.columns))

    # Ensure basic columns exist for later phases. Do not filter/drop rows.
    for c in ["app_proto", "event_type", "src_port", "dest_port", "label_status"]:
        if c not in df.columns:
            df[c] = "" if c in {"app_proto", "event_type", "label_status"} else 0

    proto_mask, port_mask, any_mask = _ram_expected_app_masks(
        df,
        app=app,
        app_ports=dict(cfg.app_ports),
        app_proto_aliases=dict(cfg.app_proto_aliases),
        match_src_port=bool(cfg.match_src_port),
    )

    proto_hits = int(proto_mask.sum())
    port_hits = int(port_mask.sum())
    any_hits = int(any_mask.sum())
    unexpected_rows = int(rows_in - any_hits)

    if cfg.strict_validation and rows_in > 0 and any_hits == 0:
        raise ValueError(
            f"Phase 2 strict validation failed for app={app}: no rows matched app_proto/port rules."
        )

    if cfg.add_application_columns:
        df["application"] = app
        reason = np.where(
            proto_mask.to_numpy() & port_mask.to_numpy(),
            "app_proto+port",
            np.where(proto_mask.to_numpy(), "app_proto", np.where(port_mask.to_numpy(), "port", "pre_split_unverified")),
        )
        df["app_filter_reason"] = reason

    elapsed = (datetime.now() - t0).total_seconds()

    expected_ports = [int(x) for x in cfg.app_ports.get(app, [])]
    expected_aliases = [str(x) for x in cfg.app_proto_aliases.get(app, [app])]

    summary = {
        "phase": 2,
        "phase_name": "app_validation_pass_through",
        "status": "completed",
        "app": app,
        "input_mode": "dataframe_ram",
        "output_mode": "dataframe_ram",
        "filter_mode": "pass_through_no_row_drop",
        "rows_in": rows_in,
        "rows_out": int(len(df)),
        "cols_in": cols_in,
        "cols_out": int(len(df.columns)),
        "expected_ports": expected_ports,
        "expected_app_proto_aliases": expected_aliases,
        "match_src_port": bool(cfg.match_src_port),
        "strict_validation": bool(cfg.strict_validation),
        "proto_rule_hits": proto_hits,
        "port_rule_hits": port_hits,
        "any_rule_hits": any_hits,
        "pre_split_unverified_rows": unexpected_rows,
        "pre_split_unverified_percentage": (unexpected_rows / rows_in * 100.0) if rows_in else 0.0,
        "top_dest_ports": _ram_counter_top(_safe_int_series(df["dest_port"]), 20) if "dest_port" in df.columns else {},
        "top_src_ports": _ram_counter_top(_safe_int_series(df["src_port"]), 20) if "src_port" in df.columns else {},
        "top_app_proto": _ram_counter_top(_safe_str_series(df["app_proto"]), 20) if "app_proto" in df.columns else {},
        "top_event_type": _ram_counter_top(_safe_str_series(df["event_type"]), 20) if "event_type" in df.columns else {},
        "label_status_counter": _ram_counter_top(df["label_status"], 20) if "label_status" in df.columns else {},
        "df_shape": [int(df.shape[0]), int(df.shape[1])],
        "seconds": float(elapsed),
        "note": (
            "RAM mode assumes the raw input file was already split by application. "
            "Phase 2 validates/annotates the active app and passes the DataFrame through without heavy filtering."
        ),
        "note_target": "Phase 2 does not create final Target. Final Target is created in Phase 4.",
    }

    print("\n✅ PHASE 2 COMPLETE (RAM PASS-THROUGH)")
    print(f"   App          : {app}")
    print(f"   Rows in/out  : {rows_in:,} / {len(df):,}")
    print(f"   Proto hits   : {proto_hits:,}")
    print(f"   Port hits    : {port_hits:,}")
    print(f"   Unverified   : {unexpected_rows:,}")
    print(f"   Time         : {elapsed / 60:.2f} minutes")

    return df, summary


# Additional aliases used by different pipeline drafts.
def phase2_app_filter_ram(
    df: pd.DataFrame,
    *,
    app: str,
    app_ports: Optional[Dict[str, Sequence[int]]] = None,
    app_proto_aliases: Optional[Dict[str, Sequence[str]]] = None,
    match_src_port: bool = True,
    strict_validation: bool = False,
    progress_desc: str = "PHASE 2",
) -> Tuple[pd.DataFrame, dict]:
    cfg = Phase2RAMConfig(
        app=app,
        app_ports=app_ports or dict(DEFAULT_APP_PORTS),
        app_proto_aliases=app_proto_aliases or dict(DEFAULT_APP_PROTO_ALIASES),
        match_src_port=match_src_port,
        strict_validation=strict_validation,
    )
    return phase2_validate_app_ram(df, cfg=cfg, progress_desc=progress_desc)


def phase2_filter_applications_ram(
    df: pd.DataFrame,
    *,
    app: str,
    app_ports: Optional[Dict[str, Sequence[int]]] = None,
    app_proto_aliases: Optional[Dict[str, Sequence[str]]] = None,
    match_src_port: bool = True,
    strict_validation: bool = False,
    progress_desc: str = "PHASE 2",
) -> Tuple[pd.DataFrame, dict]:
    return phase2_app_filter_ram(
        df,
        app=app,
        app_ports=app_ports,
        app_proto_aliases=app_proto_aliases,
        match_src_port=match_src_port,
        strict_validation=strict_validation,
        progress_desc=progress_desc,
    )


def phase2_validate_split_app_ram(
    df: pd.DataFrame,
    *,
    app: str,
    app_ports: Optional[Dict[str, Sequence[int]]] = None,
    progress_desc: str = "PHASE 2",
) -> Tuple[pd.DataFrame, dict]:
    return phase2_app_filter_ram(
        df,
        app=app,
        app_ports=app_ports,
        progress_desc=progress_desc,
    )
