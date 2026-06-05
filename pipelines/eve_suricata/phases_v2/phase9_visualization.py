# src/cbr/phases/phase9_visualization.py
from __future__ import annotations

import gc
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

from tqdm import tqdm


# =============================================================================
# PHASE 9: VISUALIZATION (APP-AWARE, SHARDED-SAFE)
# =============================================================================
# Purpose:
#   Generate visual summaries after Phase 7 clean dataset.
#
# Input:
#   results/phase7_clean_dataset/app={app}/part-*.parquet
#
# Output:
#   results/figures/app={app}/
#     visualization_overview_{app}_{tag}.png
#     correlation_heatmap_{app}_{tag}.png
#
#   results/figures/metrics/
#     phase9_visualization_summary_{app}.json
#     phase9_visualization_summary_all.json
#     phase9_visualization_summary_by_app.csv
#
# Important:
#   - This phase no longer receives one in-memory df_clean.
#   - This phase no longer assumes global attacks/benign folders.
#   - It samples from app shards to avoid loading very large data into RAM.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")
RAW_SUFFIX = "_raw"


@dataclass(frozen=True)
class Phase9VisualizationConfig:
    input_dir: Path = Path("results/phase7_clean_dataset")
    output_dir: Path = Path("results/figures")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    n_viz: int = 1_000_000
    n_heatmap: int = 100_000
    max_heatmap_features: int = 80

    target_col: str = "Target"
    stratify_by_target: bool = True
    # Visualization sampling is intentionally approximate/proportional.
    # It should not full-scan huge datasets only to draw figures.
    sample_strategy: str = "proportional"
    sample_oversample_factor: float = 1.25
    seed: int = 42

    filename_tag: str = "run"
    force_rebuild: bool = False

    raw_suffix: str = RAW_SUFFIX
    parquet_engine: Optional[str] = "fastparquet"

    # For very large app datasets, PASS 1 scans all shards only for counts/schema.
    # PASS 2 samples rows.
    gc_each_shard: bool = True
    overwrite_metrics: bool = True


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


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        return pd.Series(np.zeros(len(df), dtype=np.int8), index=df.index)
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


def _counter_to_str_dict(c: Counter) -> Dict[str, int]:
    return {str(k): int(v) for k, v in c.items()}


def _choose_col(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _add_under_text(ax, lines: Sequence[str], x: float = 0.02, y: float = -0.20, fontsize: int = 8, ha: str = "left") -> None:
    if not lines:
        return
    ax.text(
        x,
        y,
        "\n".join(lines),
        transform=ax.transAxes,
        ha=ha,
        va="top",
        fontsize=fontsize,
        clip_on=False,
    )


# =============================================================================
# Fast representative sampling
# =============================================================================

def _read_json_safe(path: Path) -> Any:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None


def _phase7_summary_for_app(input_dir: Path, app: str) -> Dict[str, Any]:
    """
    Load Phase 7 per-app summary if available.

    Phase 9 is only visualization, so it should not scan the whole clean dataset
    just to know the class ratio. The true per-app Target distribution is already
    stored by Phase 7.
    """
    app = str(app).strip().lower()
    metrics_dir = Path(input_dir) / "metrics"

    per_app = _read_json_safe(metrics_dir / f"phase7_cleaning_summary_{app}.json")
    if isinstance(per_app, dict) and per_app:
        return per_app

    all_summary = _read_json_safe(metrics_dir / "phase7_cleaning_summary_all.json")
    if isinstance(all_summary, dict):
        apps = all_summary.get("apps") or {}
        if isinstance(apps, dict):
            item = apps.get(app) or apps.get(app.upper())
            if isinstance(item, dict):
                return item

    return {}


def _counter_from_mapping(d: Any) -> Counter:
    out: Counter = Counter()
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        try:
            out[int(k)] += int(v)
        except Exception:
            pass
    return out


def _parquet_metadata_rows_cols(path: Path) -> Tuple[Optional[int], Optional[List[str]]]:
    """Return parquet row count and column names without materializing the table."""
    try:
        import pyarrow.parquet as pq  # type: ignore
        pf = pq.ParquetFile(path)
        return int(pf.metadata.num_rows), [str(x) for x in pf.schema_arrow.names]
    except Exception:
        pass

    try:
        import fastparquet  # type: ignore
        pf = fastparquet.ParquetFile(path)
        rows = 0
        for rg in getattr(pf, "row_groups", []) or []:
            try:
                rows += int(rg.num_rows)
            except Exception:
                pass
        cols = [str(c) for c in (getattr(pf, "columns", []) or [])]
        return int(rows), cols
    except Exception:
        return None, None


def _fast_metadata_scan(
    shard_files: List[Path],
    *,
    cfg: Phase9VisualizationConfig,
    app: str,
) -> Dict[str, Any]:
    """
    Lightweight metadata scan for visualization.

    It intentionally avoids reading full Phase 7 shards. Target counts are loaded
    from Phase 7 summary, and row counts are loaded from parquet metadata when
    possible. This mirrors the old Phase 6 behavior: visualize a representative
    sample, not the entire dataset.
    """
    bytes_seen = 0
    rows_seen_meta = 0
    schema_cols: List[str] = []
    metadata_row_count_ok = True

    for fp in shard_files:
        bytes_seen += _file_size_bytes(fp)
        if fp.suffix.lower() == ".parquet":
            rows, cols = _parquet_metadata_rows_cols(fp)
            if rows is None:
                metadata_row_count_ok = False
            else:
                rows_seen_meta += int(rows)
            if not schema_cols and cols:
                schema_cols = cols
        else:
            metadata_row_count_ok = False

    p7 = _phase7_summary_for_app(cfg.input_dir, app)
    target_counter = _counter_from_mapping(p7.get("target_counts"))

    rows_from_summary = 0
    for key in ("rows_out", "rows_written", "rows_seen"):
        try:
            rows_from_summary = int(p7.get(key) or 0)
            if rows_from_summary > 0:
                break
        except Exception:
            rows_from_summary = 0

    rows_seen = rows_from_summary or rows_seen_meta

    return {
        "rows_seen": int(rows_seen),
        "bytes_seen": int(bytes_seen),
        "target_counts": target_counter,
        "event_type_top10": [],
        "proto_counts": Counter(),
        "app_proto_top10": [],
        "dest_port_top10": [],
        "schema_cols": schema_cols,
        "row_count_source": "phase7_summary" if rows_from_summary else ("parquet_metadata" if metadata_row_count_ok else "partial_metadata"),
        "target_count_source": "phase7_summary" if target_counter else "sample_fallback",
    }


def _sample_plan_from_target_counts(target_counts: Counter, n_take: int) -> Dict[int, int]:
    total = int(sum(target_counts.values()))
    n_take = min(max(0, int(n_take)), total if total > 0 else int(n_take))
    if n_take <= 0:
        return {}

    if total <= 0:
        return {0: n_take}

    plan: Dict[int, int] = {}
    for k, v in target_counts.items():
        kk = int(k)
        plan[kk] = int((int(v) / max(1, total)) * n_take)

    # Ensure each existing class appears if the sample budget allows.
    for k, v in target_counts.items():
        kk = int(k)
        if int(v) > 0 and plan.get(kk, 0) == 0 and sum(plan.values()) < n_take:
            plan[kk] = 1

    remaining = n_take - sum(plan.values())
    for k, _v in sorted(target_counts.items(), key=lambda kv: int(kv[1]), reverse=True):
        if remaining <= 0:
            break
        kk = int(k)
        plan[kk] = plan.get(kk, 0) + 1
        remaining -= 1

    while sum(plan.values()) > n_take:
        kmax = max(plan, key=lambda kk: plan[kk])
        plan[kmax] -= 1
        if plan[kmax] <= 0:
            del plan[kmax]

    return {int(k): int(v) for k, v in plan.items() if int(v) > 0}


def _sample_frame(df: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    n = min(max(0, int(n)), len(df))
    if n <= 0:
        return df.iloc[0:0].copy()
    if len(df) <= n:
        return df.copy()
    return df.sample(n=n, random_state=int(rng.integers(0, 2_147_483_647))).copy()


def _collect_visualization_sample(
    shard_files: List[Path],
    *,
    cfg: Phase9VisualizationConfig,
    app: str,
    target_counts: Counter,
) -> pd.DataFrame:
    """
    Collect a representative visualization sample using the old Phase 6 principle:
    read only enough shuffled shards to build a bounded sample.

    If Phase 7 target_counts are available, the sample follows the original Target
    ratio. This avoids full-dataset visualization scans while keeping the plotted
    class ratio aligned with the clean dataset.
    """
    n_take = max(0, int(cfg.n_viz))
    if n_take <= 0 or not shard_files:
        return pd.DataFrame()

    rng = np.random.default_rng(int(cfg.seed) + abs(hash(app)) % 100_000)
    files = list(shard_files)
    rng.shuffle(files)

    parts: List[pd.DataFrame] = []

    if cfg.stratify_by_target and target_counts and len(target_counts) >= 2:
        plan = _sample_plan_from_target_counts(target_counts, n_take)
        remaining: Dict[int, int] = {int(k): int(v) for k, v in plan.items() if int(v) > 0}

        print(
            f"   Sampling      : proportional target ratio | plan={remaining} | n_viz={n_take:,}",
            flush=True,
        )

        for idx, fp in enumerate(tqdm(files, desc=f"PHASE 9 sample app={app}", unit="shard", dynamic_ncols=True), start=1):
            if not remaining or sum(remaining.values()) <= 0:
                break

            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is None or df.empty:
                continue

            y = _target_series(df, cfg.target_col)
            shards_left = max(1, len(files) - idx + 1)

            for cls in list(remaining.keys()):
                need = int(remaining.get(cls, 0))
                if need <= 0:
                    remaining.pop(cls, None)
                    continue

                sub = df[y == int(cls)]
                if sub.empty:
                    continue

                # Spread reads across shuffled shards, but allow later shards to
                # take all remaining quota. This is much faster than row-level
                # reservoir replacement and avoids the iloc enlargement bug.
                fair_take = int(np.ceil((need / float(shards_left)) * float(cfg.sample_oversample_factor)))
                fair_take = max(1, fair_take)
                take = min(len(sub), need, fair_take)

                picked = _sample_frame(sub, take, rng)
                if not picked.empty:
                    parts.append(picked)
                    remaining[cls] = need - len(picked)
                    if remaining[cls] <= 0:
                        remaining.pop(cls, None)

            if cfg.gc_each_shard:
                del df
                gc.collect()

        if parts:
            out = pd.concat(parts, ignore_index=True)
            if len(out) > n_take:
                out = out.sample(n=n_take, random_state=int(cfg.seed)).reset_index(drop=True)
            else:
                out = out.sample(frac=1.0, random_state=int(cfg.seed)).reset_index(drop=True)
            return out

        print("   ⚠️ Proportional sample produced no rows; falling back to random shard sample.", flush=True)

    # Fallback: fast random representative sample without exact class ratio.
    print(f"   Sampling      : fast random shard sample | n_viz={n_take:,}", flush=True)
    got = 0
    per_shard = max(1, int(np.ceil(n_take / max(1, len(files)) * float(cfg.sample_oversample_factor))))

    for fp in tqdm(files, desc=f"PHASE 9 sample app={app}", unit="shard", dynamic_ncols=True):
        if got >= n_take:
            break

        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        need = n_take - got
        picked = _sample_frame(df, min(need, per_shard), rng)
        if not picked.empty:
            parts.append(picked)
            got += len(picked)

        if cfg.gc_each_shard:
            del df
            gc.collect()

    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=int(cfg.seed)).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=int(cfg.seed)).reset_index(drop=True)
    return out


def _sample_distribution_snapshot(df: pd.DataFrame, cfg: Phase9VisualizationConfig) -> Dict[str, Any]:
    if df is None or df.empty:
        return {
            "target_counts": Counter(),
            "event_type_top10": [],
            "proto_counts": Counter(),
            "app_proto_top10": [],
            "dest_port_top10": [],
        }

    y = _target_series(df, cfg.target_col)
    target_counter = Counter(y.astype(int).tolist())

    event_type_counter: Counter = Counter()
    proto_counter: Counter = Counter()
    app_proto_counter: Counter = Counter()
    dest_port_counter: Counter = Counter()

    ev_col = _choose_col(df, ["event_type_raw", "event_type"])
    if ev_col:
        event_type_counter.update(df[ev_col].astype("string").fillna("unknown").str.lower().tolist())

    pr_col = _choose_col(df, ["proto_raw", "proto"])
    if pr_col:
        proto_counter.update(df[pr_col].astype("string").fillna("unknown").str.upper().tolist())

    app_col = _choose_col(df, ["app_proto_raw", "app_proto", "application_raw", "application"])
    if app_col:
        app_proto_counter.update(df[app_col].astype("string").fillna("unknown").str.lower().tolist())

    if "dest_port" in df.columns:
        dest_port_counter.update(pd.to_numeric(df["dest_port"], errors="coerce").fillna(-1).astype(int).tolist())

    return {
        "target_counts": target_counter,
        "event_type_top10": event_type_counter.most_common(10),
        "proto_counts": proto_counter,
        "app_proto_top10": app_proto_counter.most_common(10),
        "dest_port_top10": dest_port_counter.most_common(10),
    }


# =============================================================================
# Plotting
# =============================================================================

def _make_overview_plot(
    df_viz: pd.DataFrame,
    *,
    cfg: Phase9VisualizationConfig,
    app: str,
    output_path: Path,
) -> Dict[str, Any]:
    if df_viz is None or df_viz.empty:
        raise ValueError(f"Cannot visualize empty sample for app={app}")

    y = _target_series(df_viz, cfg.target_col)
    df_viz = df_viz.copy()
    df_viz[cfg.target_col] = y

    target_dist = y.value_counts().sort_index()

    ev_col = _choose_col(df_viz, ["event_type_raw", "event_type"])
    pr_col = _choose_col(df_viz, ["proto_raw", "proto"])
    app_proto_col = _choose_col(df_viz, ["app_proto_raw", "app_proto", "application_raw", "application"])

    ev_series = (
        df_viz[ev_col].astype("string").fillna("unknown").str.strip().str.lower()
        if ev_col else pd.Series(["unknown"] * len(df_viz), dtype="string")
    )
    pr_series = (
        df_viz[pr_col].astype("string").fillna("unknown").str.strip().str.upper()
        if pr_col else pd.Series(["UNKNOWN"] * len(df_viz), dtype="string")
    )
    app_proto_series = (
        df_viz[app_proto_col].astype("string").fillna("unknown").str.strip().str.lower()
        if app_proto_col else pd.Series([app] * len(df_viz), dtype="string")
    )

    proto_map = {
        "ICMPV6": "IPv6-ICMP",
        "IPV6_ICMP": "IPv6-ICMP",
        "IPV6-ICMP": "IPv6-ICMP",
        "TCP": "TCP",
        "UDP": "UDP",
        "ICMP": "ICMP",
    }
    pr_series = pr_series.replace(proto_map)

    top_events = ev_series.value_counts().head(10)
    proto_counts = pr_series.value_counts()
    app_proto_counts = app_proto_series.value_counts().head(10)

    pkt = _to_num(df_viz["total_pkts"]).fillna(0) if "total_pkts" in df_viz.columns else None
    byt = _to_num(df_viz["total_bytes"]).fillna(0) if "total_bytes" in df_viz.columns else None

    fig = plt.figure(figsize=(17, 12))

    label_map = {0: "BENIGN", 1: "MALICIOUS"}

    ax1 = plt.subplot(2, 3, 1)
    labels = [label_map.get(int(idx), str(idx)) for idx in target_dist.index]
    ax1.pie(target_dist.values, labels=labels, autopct="%1.1f%%", startangle=90)
    ax1.set_title(f"Target Distribution\napp={app}", fontsize=12, fontweight="bold")
    _add_under_text(
        ax1,
        [
            f"Benign: {int(target_dist.get(0, 0)):,}",
            f"Malicious: {int(target_dist.get(1, 0)):,}",
            f"Sample: {len(df_viz):,}",
        ],
        x=0.08,
        y=-0.18,
        fontsize=9,
    )

    ax2 = plt.subplot(2, 3, 2)
    ev_plot = top_events.sort_values(ascending=True)
    ax2.barh(range(len(ev_plot)), ev_plot.values)
    ax2.set_yticks(range(len(ev_plot)))
    ax2.set_yticklabels(ev_plot.index)
    ax2.set_xlabel("Count")
    ax2.set_title("Top Event Types", fontsize=12, fontweight="bold")
    ax2.grid(axis="x", alpha=0.3)

    ax3 = plt.subplot(2, 3, 3)
    pr_plot = proto_counts.sort_values(ascending=False).head(10)
    ax3.bar(range(len(pr_plot)), pr_plot.values)
    ax3.set_xticks(range(len(pr_plot)))
    ax3.set_xticklabels(pr_plot.index, rotation=30, ha="right")
    ax3.set_ylabel("Count")
    ax3.set_title("Protocol Distribution", fontsize=12, fontweight="bold")
    ax3.grid(axis="y", alpha=0.3)

    ax4 = plt.subplot(2, 3, 4)
    if "alert_severity" in df_viz.columns:
        sev = _to_num(df_viz["alert_severity"]).fillna(0).round().astype(int)
        ct = pd.crosstab(sev, y)
        if 0 not in ct.columns:
            ct[0] = 0
        if 1 not in ct.columns:
            ct[1] = 0
        ct = ct.sort_index()
        ax4.bar(ct.index.astype(str), ct[0].values, label="Benign", alpha=0.8)
        ax4.bar(ct.index.astype(str), ct[1].values, bottom=ct[0].values, label="Malicious", alpha=0.8)
        ax4.legend()
        ax4.set_title("Alert Severity\n(stacked by Target)", fontsize=12, fontweight="bold")
        ax4.set_xlabel("Severity")
        ax4.set_ylabel("Count")
        ax4.grid(axis="y", alpha=0.3)
    else:
        ax4.text(0.5, 0.5, "alert_severity not found", ha="center", va="center")
        ax4.axis("off")

    ax5 = plt.subplot(2, 3, 5)
    if pkt is not None and len(pkt) > 0:
        pkt_b = pkt[y == 0].values
        pkt_m = pkt[y == 1].values
        data = []
        labels_box = []
        if len(pkt_b):
            data.append(pkt_b)
            labels_box.append("Benign")
        if len(pkt_m):
            data.append(pkt_m)
            labels_box.append("Malicious")
        if data:
            ax5.boxplot(data, labels=labels_box, patch_artist=True, showfliers=True)
            ax5.set_title("Packet Count Distribution", fontsize=12, fontweight="bold")
            ax5.set_ylabel("total_pkts")
            ax5.grid(axis="y", alpha=0.3)
        else:
            ax5.text(0.5, 0.5, "No packet data", ha="center", va="center")
            ax5.axis("off")
    else:
        ax5.text(0.5, 0.5, "total_pkts not found", ha="center", va="center")
        ax5.axis("off")

    ax6 = plt.subplot(2, 3, 6)
    if byt is not None and len(byt) > 0:
        byt_b = byt[y == 0].values
        byt_m = byt[y == 1].values
        data = []
        labels_box = []
        if len(byt_b):
            data.append(byt_b)
            labels_box.append("Benign")
        if len(byt_m):
            data.append(byt_m)
            labels_box.append("Malicious")
        if data:
            ax6.boxplot(data, labels=labels_box, patch_artist=True, showfliers=True)
            ax6.set_title("Byte Count Distribution", fontsize=12, fontweight="bold")
            ax6.set_ylabel("total_bytes")
            ax6.grid(axis="y", alpha=0.3)
        else:
            ax6.text(0.5, 0.5, "No byte data", ha="center", va="center")
            ax6.axis("off")
    else:
        ax6.text(0.5, 0.5, "total_bytes not found", ha="center", va="center")
        ax6.axis("off")

    fig.suptitle(f"Phase 9 Visualization Overview - {app.upper()}", fontsize=16, fontweight="bold", y=1.02)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=300, bbox_inches="tight")
    plt.close(fig)

    return {
        "target_dist_sample": {str(k): int(v) for k, v in target_dist.to_dict().items()},
        "event_type_source": ev_col or "none",
        "proto_source": pr_col or "none",
        "app_proto_source": app_proto_col or "none",
        "top_events_sample": {str(k): int(v) for k, v in top_events.to_dict().items()},
        "proto_counts_sample": {str(k): int(v) for k, v in proto_counts.to_dict().items()},
        "app_proto_counts_sample": {str(k): int(v) for k, v in app_proto_counts.to_dict().items()},
    }


def _make_correlation_heatmap(
    df_viz: pd.DataFrame,
    *,
    cfg: Phase9VisualizationConfig,
    app: str,
    output_path: Path,
) -> Dict[str, Any]:
    if df_viz is None or df_viz.empty:
        raise ValueError(f"Cannot build heatmap from empty sample for app={app}")

    rng = np.random.default_rng(int(cfg.seed))
    n_hm = min(max(1, int(cfg.n_heatmap)), len(df_viz))

    if n_hm < len(df_viz):
        y = _target_series(df_viz, cfg.target_col)
        if cfg.stratify_by_target and y.nunique(dropna=True) >= 2:
            atk_idx = np.where(y.to_numpy() == 1)[0]
            ben_idx = np.where(y.to_numpy() == 0)[0]
            atk_take = max(1, int(round((len(atk_idx) / max(1, len(df_viz))) * n_hm))) if len(atk_idx) else 0
            atk_take = min(atk_take, len(atk_idx))
            ben_take = min(n_hm - atk_take, len(ben_idx))
            if atk_take + ben_take <= 0:
                pick = rng.choice(len(df_viz), size=n_hm, replace=False)
            else:
                parts = []
                if atk_take:
                    parts.append(rng.choice(atk_idx, size=atk_take, replace=False))
                if ben_take:
                    parts.append(rng.choice(ben_idx, size=ben_take, replace=False))
                pick = np.concatenate(parts)
                rng.shuffle(pick)
            df_hm = df_viz.iloc[pick].copy()
        else:
            df_hm = df_viz.sample(n=n_hm, random_state=int(cfg.seed)).copy()
    else:
        df_hm = df_viz.copy()

    numeric_cols = df_hm.select_dtypes(include=[np.number]).columns.tolist()

    if cfg.target_col in df_hm.columns and cfg.target_col not in numeric_cols:
        try:
            df_hm[cfg.target_col] = _target_series(df_hm, cfg.target_col)
            numeric_cols.append(cfg.target_col)
        except Exception:
            pass

    if not numeric_cols:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No numeric columns available for correlation heatmap", ha="center", va="center")
        ax.axis("off")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(output_path), dpi=300, bbox_inches="tight")
        plt.close(fig)
        return {
            "n_heatmap_used": int(len(df_hm)),
            "heatmap_cols_used": [],
            "note": "No numeric columns available.",
        }

    if len(numeric_cols) > int(cfg.max_heatmap_features):
        keep = [cfg.target_col] if cfg.target_col in numeric_cols else []
        var_series = df_hm[numeric_cols].var(numeric_only=True).sort_values(ascending=False)
        for c in var_series.index:
            if c == cfg.target_col:
                continue
            keep.append(c)
            if len(keep) >= int(cfg.max_heatmap_features):
                break
        numeric_cols = keep

    corr_df = df_hm[numeric_cols].corr(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0)

    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(corr_df.values, aspect="auto", vmin=-1, vmax=1)
    fig.colorbar(im, ax=ax, label="Correlation")

    ax.set_title(f"Feature Correlation Matrix - {app.upper()}", fontsize=14, fontweight="bold", pad=16)
    ax.set_xticks(range(len(corr_df.columns)))
    ax.set_yticks(range(len(corr_df.index)))
    ax.set_xticklabels(corr_df.columns, rotation=90, fontsize=7)
    ax.set_yticklabels(corr_df.index, fontsize=7)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=300, bbox_inches="tight")
    plt.close(fig)

    return {
        "n_heatmap_used": int(len(df_hm)),
        "heatmap_cols_used": [str(c) for c in numeric_cols],
        "heatmap_cols_count": int(len(numeric_cols)),
    }


# =============================================================================
# Public API
# =============================================================================

def phase9_visualization_for_app(
    app: str,
    *,
    cfg: Phase9VisualizationConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    app = str(app).strip().lower()
    t0 = datetime.now()
    tag = cfg.filename_tag.strip() or "run"

    shard_files = _list_app_shards(cfg.input_dir, app)
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    overview_path = out_app_dir / f"visualization_overview_{app}_{tag}_n{cfg.n_viz}.png"
    heatmap_path = out_app_dir / f"correlation_heatmap_{app}_{tag}_n{cfg.n_heatmap}.png"

    if not shard_files:
        summary = {
            "phase": 9,
            "app": app,
            "status": "skipped_no_input_shards",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "overview_path": None,
            "heatmap_path": None,
            "rows_seen": 0,
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase9_visualization_summary_{app}.json")
        return pd.DataFrame(), summary

    out_app_dir.mkdir(parents=True, exist_ok=True)

    if (not cfg.force_rebuild) and overview_path.exists() and heatmap_path.exists():
        summary = {
            "phase": 9,
            "app": app,
            "status": "skipped_existing_outputs",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "overview_path": str(overview_path),
            "heatmap_path": str(heatmap_path),
            "n_viz": int(cfg.n_viz),
            "n_heatmap": int(cfg.n_heatmap),
            "max_heatmap_features": int(cfg.max_heatmap_features),
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase9_visualization_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\n🟣 PHASE 9: Visualization for app={app}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    scan = _fast_metadata_scan(shard_files, cfg=cfg, app=app)

    df_viz = _collect_visualization_sample(
        shard_files,
        cfg=cfg,
        app=app,
        target_counts=scan["target_counts"],
    )

    if df_viz.empty:
        summary = {
            "phase": 9,
            "app": app,
            "status": "skipped_empty_sample",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": int(scan["rows_seen"]),
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase9_visualization_summary_{app}.json")
        return df_viz, summary

    sample_snapshot = _sample_distribution_snapshot(df_viz, cfg)

    overview_info = _make_overview_plot(
        df_viz,
        cfg=cfg,
        app=app,
        output_path=overview_path,
    )

    heatmap_info = _make_correlation_heatmap(
        df_viz,
        cfg=cfg,
        app=app,
        output_path=heatmap_path,
    )

    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 9,
        "app": app,
        "status": "completed",
        "input_dir": str(cfg.input_dir),
        "output_dir": str(out_app_dir),
        "overview_path": str(overview_path),
        "heatmap_path": str(heatmap_path),
        "rows_seen": int(scan["rows_seen"]),
        "input_bytes": int(scan["bytes_seen"]),
        "input_size": _human_bytes(scan["bytes_seen"]),
        "shards_seen": int(len(shard_files)),
        "n_viz_requested": int(cfg.n_viz),
        "n_viz_used": int(len(df_viz)),
        "n_heatmap_requested": int(cfg.n_heatmap),
        "stratify_by_target": bool(cfg.stratify_by_target),
        "target_counts_input": _counter_to_str_dict(scan["target_counts"] or sample_snapshot["target_counts"]),
        "target_counts_sample": _counter_to_str_dict(sample_snapshot["target_counts"]),
        "event_type_top10_input": {str(k): int(v) for k, v in sample_snapshot["event_type_top10"]},
        "proto_counts_input": _counter_to_str_dict(sample_snapshot["proto_counts"]),
        "app_proto_top10_input": {str(k): int(v) for k, v in sample_snapshot["app_proto_top10"]},
        "dest_port_top10_input": {str(k): int(v) for k, v in sample_snapshot["dest_port_top10"]},
        "row_count_source": scan.get("row_count_source"),
        "target_count_source": scan.get("target_count_source"),
        "distribution_note": "Target ratio is taken from Phase 7 summary when available; event/proto/port distributions are computed from the visualization sample.",
        "sample_shape": [int(df_viz.shape[0]), int(df_viz.shape[1])],
        "schema_cols_count": int(len(scan["schema_cols"])),
        "overview": overview_info,
        "heatmap": heatmap_info,
        "seconds": float(elapsed),
        "note": (
            "Phase 9 visualizes per-application clean datasets from Phase 7. "
            "The overview and heatmap are based on a bounded representative sample, not a full-data scan."
        ),
    }

    _json_dump(summary, metrics_dir / f"phase9_visualization_summary_{app}.json")

    print(f"✅ Phase 9 complete app={app}")
    print(f"   Rows seen : {int(scan['rows_seen']):,}")
    print(f"   Sample    : {df_viz.shape}")
    print(f"   Overview  : {overview_path}")
    print(f"   Heatmap   : {heatmap_path}")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    return df_viz, summary


def phase9_visualization(
    *,
    cfg: Phase9VisualizationConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    print("\n" + "🟣 " + "=" * 76)
    print("PHASE 9: VISUALIZATION (APP-AWARE)")
    print("🟣 " + "=" * 76)

    t0 = datetime.now()
    samples_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        sample_df, summary = phase9_visualization_for_app(app_norm, cfg=cfg)
        samples_by_app[app_norm] = sample_df
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        rows.append({
            "app": app,
            "status": s.get("status"),
            "rows_seen": int(s.get("rows_seen", 0)),
            "shards_seen": int(s.get("shards_seen", 0)),
            "n_viz_used": int(s.get("n_viz_used", 0)),
            "overview_path": s.get("overview_path"),
            "heatmap_path": s.get("heatmap_path"),
            "seconds": float(s.get("seconds", 0.0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase9_visualization_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows_seen = int(sum(int(s.get("rows_seen", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 9,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "input_dir": str(cfg.input_dir),
        "output_dir": str(cfg.output_dir),
        "total_rows_seen": total_rows_seen,
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Phase 9 is app-aware and reads Phase 7 clean app partitions. "
            "It follows the old Phase 6 principle: build a bounded representative sample before plotting."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase9_visualization_summary_all.json")

    print("\n✅ PHASE 9 COMPLETE")
    print(f"   Total rows seen: {total_rows_seen:,}")
    print(f"   Output dir     : {cfg.output_dir}")
    print(f"   Time           : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all


# Compatibility alias.
def build_phase9_visualization(
    *,
    cfg: Phase9VisualizationConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase9_visualization(cfg=cfg)


if __name__ == "__main__":
    samples, summary = phase9_visualization(
        cfg=Phase9VisualizationConfig(
            input_dir=Path("results/phase7_clean_dataset"),
            output_dir=Path("results/figures"),
            selected_apps=("dns", "http", "tls", "ssh"),
            n_viz=1_000_000,
            n_heatmap=100_000,
            max_heatmap_features=80,
            target_col="Target",
            stratify_by_target=True,
            sample_strategy="proportional",
            sample_oversample_factor=1.25,
            seed=42,
            filename_tag="run",
            force_rebuild=False,
            parquet_engine="fastparquet",
        )
    )
    print(json.dumps(summary, indent=2, default=str))


# =============================================================================
# SUMMARY-DRIVEN + RAM-MODE API (SMALL SEMINAR DATASET)
# =============================================================================
# These functions are added for the current ±4GB/10M-line workflow:
# - Global/simple charts are drawn from existing metrics JSON files.
# - Per-app overview/heatmap can use df_clean still in RAM.
# - No raw JSONL re-read and no parquet shard scan is required in RAM mode.


def _read_json_file(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        p = Path(path)
        if not p.exists():
            return {}
        with p.open('r', encoding='utf-8') as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _app_block(summary: Dict[str, Any], app: str) -> Dict[str, Any]:
    app = str(app).strip().lower()
    if not isinstance(summary, dict) or not summary:
        return {}

    # Preferred new incremental summary structure.
    for key in ('by_app', 'apps', 'app_summaries', 'summaries'):
        obj = summary.get(key)
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).strip().lower() == app and isinstance(v, dict):
                    return v

    # Per-app summary file structure.
    if str(summary.get('app', summary.get('application', ''))).strip().lower() == app:
        return summary

    return {}


def _viz_stats(summary: Dict[str, Any], app: str) -> Dict[str, Any]:
    block = _app_block(summary, app)
    if isinstance(block.get('visualization_stats'), dict):
        return block.get('visualization_stats') or {}
    return block


def _as_int_dict(obj: Any) -> Dict[str, int]:
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in obj.items():
        try:
            out[str(k)] = int(v)
        except Exception:
            continue
    return out


def _pick_counter(stats: Dict[str, Any], keys: Sequence[str]) -> Dict[str, int]:
    for key in keys:
        val = stats.get(key)
        d = _as_int_dict(val)
        if d:
            return d
    return {}


def _target_counts_for_app(app: str, phase7_summary: Dict[str, Any], phase4_summary: Dict[str, Any]) -> Dict[str, int]:
    p7 = _viz_stats(phase7_summary, app)
    p4 = _viz_stats(phase4_summary, app)
    return (
        _pick_counter(p7, ('target_counts', 'target_distribution'))
        or _pick_counter(p4, ('target_counts', 'target_distribution'))
    )


def _rows_for_app(app: str, split_summary: Dict[str, Any], phase7_summary: Dict[str, Any], phase4_summary: Dict[str, Any], phase1_summary: Dict[str, Any]) -> int:
    app = str(app).strip().lower()
    for key in ('written_counts', 'detected_counts', 'output_rows_by_app'):
        d = _as_int_dict(split_summary.get(key))
        if app in d:
            return int(d[app])

    for summ in (phase7_summary, phase4_summary, phase1_summary):
        stats = _viz_stats(summ, app)
        for key in ('rows_after_phase7', 'rows_after_phase4', 'rows_after_phase1', 'rows_out', 'rows_written', 'rows', 'total_lines_seen'):
            try:
                v = int(stats.get(key) or 0)
                if v > 0:
                    return v
            except Exception:
                pass
    return 0


def _selected_app_stats(
    *,
    selected_apps: Sequence[str],
    split_summary: Dict[str, Any],
    phase1_summary: Dict[str, Any],
    phase4_summary: Dict[str, Any],
    phase7_summary: Dict[str, Any],
) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for app in selected_apps:
        a = str(app).strip().lower()
        tc = _target_counts_for_app(a, phase7_summary, phase4_summary)
        benign = int(tc.get('0', tc.get(0, 0)) or 0)
        malicious = int(tc.get('1', tc.get(1, 0)) or 0)
        rows = _rows_for_app(a, split_summary, phase7_summary, phase4_summary, phase1_summary)
        if rows <= 0:
            rows = benign + malicious
        out[a] = {'rows': int(rows), 'benign': benign, 'malicious': malicious}
    return out


def _plot_total_text(stats_by_app: Dict[str, Dict[str, int]], output_path: Path) -> Dict[str, Any]:
    total = int(sum(v.get('rows', 0) for v in stats_by_app.values()))
    apps = list(stats_by_app.keys())
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.axis('off')
    lines = [
        'Selected Dataset Summary',
        '',
        f'Total Rows: {total:,}',
        f'Applications: {", ".join(a.upper() for a in apps)}',
        '',
    ]
    for app in apps:
        rows = int(stats_by_app[app].get('rows', 0))
        benign = int(stats_by_app[app].get('benign', 0))
        mal = int(stats_by_app[app].get('malicious', 0))
        lines.append(f'{app.upper():<5}  rows={rows:,} | benign={benign:,} | malicious={mal:,}')
    ax.text(0.5, 0.52, '\n'.join(lines), ha='center', va='center', fontsize=13)
    ax.set_title('Phase 9 - Total Data', fontsize=16, fontweight='bold', pad=16)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
    plt.close(fig)
    return {'total_rows': total, 'apps': apps}


def _plot_app_rows(stats_by_app: Dict[str, Dict[str, int]], output_path: Path) -> Dict[str, Any]:
    apps = list(stats_by_app.keys())
    rows = [int(stats_by_app[a].get('rows', 0)) for a in apps]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(apps, rows)
    ax.set_title('Data Comparison by Application', fontsize=14, fontweight='bold')
    ax.set_xlabel('Application')
    ax.set_ylabel('Rows')
    ax.grid(axis='y', alpha=0.3)
    for i, v in enumerate(rows):
        ax.text(i, v, f'{v:,}', ha='center', va='bottom', fontsize=9)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
    plt.close(fig)
    return {'apps': apps, 'rows': rows}


def _plot_benign_malicious(stats_by_app: Dict[str, Dict[str, int]], output_path: Path) -> Dict[str, Any]:
    apps = list(stats_by_app.keys())
    benign = [int(stats_by_app[a].get('benign', 0)) for a in apps]
    malicious = [int(stats_by_app[a].get('malicious', 0)) for a in apps]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(apps, benign, label='Benign')
    ax.bar(apps, malicious, bottom=benign, label='Malicious')
    ax.set_title('Benign vs Malicious by Application', fontsize=14, fontweight='bold')
    ax.set_xlabel('Application')
    ax.set_ylabel('Rows')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    for i, (b, m) in enumerate(zip(benign, malicious)):
        ax.text(i, b + m, f'{b + m:,}', ha='center', va='bottom', fontsize=9)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
    plt.close(fig)
    return {'apps': apps, 'benign': benign, 'malicious': malicious}


def _plot_counter_multipanel(
    counters_by_app: Dict[str, Dict[str, int]],
    output_path: Path,
    *,
    title: str,
    top_n: int = 10,
) -> Dict[str, Any]:
    apps = list(counters_by_app.keys())
    if not apps:
        return {'apps': [], 'note': 'no counters'}

    n = len(apps)
    cols = 2 if n > 1 else 1
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(14, max(5, rows * 4)))
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])
    axes_flat = axes.ravel()

    for ax, app in zip(axes_flat, apps):
        d = counters_by_app.get(app, {}) or {}
        items = sorted(d.items(), key=lambda kv: int(kv[1]), reverse=True)[:int(top_n)]
        if not items:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
            ax.set_title(app.upper())
            ax.axis('off')
            continue
        labels = [str(k) for k, _ in items][::-1]
        values = [int(v) for _, v in items][::-1]
        ax.barh(labels, values)
        ax.set_title(app.upper(), fontweight='bold')
        ax.set_xlabel('Count')
        ax.grid(axis='x', alpha=0.3)

    for ax in axes_flat[len(apps):]:
        ax.axis('off')

    fig.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
    plt.close(fig)
    return {'apps': apps, 'top_n': int(top_n)}


def _plot_alert_severity_by_target(
    severity_by_app: Dict[str, Dict[str, Dict[str, int]]],
    output_path: Path,
) -> Dict[str, Any]:
    apps = list(severity_by_app.keys())
    if not apps:
        return {'apps': [], 'note': 'no severity data'}
    n = len(apps)
    cols = 2 if n > 1 else 1
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(14, max(5, rows * 4)))
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])
    axes_flat = axes.ravel()

    for ax, app in zip(axes_flat, apps):
        sev_map = severity_by_app.get(app, {}) or {}
        # Expected shape: {target: {severity: count}}
        severity_keys = sorted({str(sev) for tmap in sev_map.values() if isinstance(tmap, dict) for sev in tmap.keys()})
        if not severity_keys:
            ax.text(0.5, 0.5, 'No severity data', ha='center', va='center')
            ax.set_title(app.upper())
            ax.axis('off')
            continue
        benign = [int((sev_map.get('0') or {}).get(k, 0)) for k in severity_keys]
        malicious = [int((sev_map.get('1') or {}).get(k, 0)) for k in severity_keys]
        x = np.arange(len(severity_keys))
        ax.bar(x, benign, label='Benign')
        ax.bar(x, malicious, bottom=benign, label='Malicious')
        ax.set_xticks(x)
        ax.set_xticklabels(severity_keys)
        ax.set_title(app.upper(), fontweight='bold')
        ax.set_xlabel('Alert severity')
        ax.set_ylabel('Rows')
        ax.grid(axis='y', alpha=0.3)
        ax.legend()

    for ax in axes_flat[len(apps):]:
        ax.axis('off')

    fig.suptitle('Alert Severity by Target', fontsize=16, fontweight='bold', y=1.02)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
    plt.close(fig)
    return {'apps': apps}


def phase9_visualization_from_metrics(
    *,
    output_dir: Path = Path('results/figures'),
    selected_apps: Sequence[str] = DEFAULT_APPS,
    split_summary_path: Optional[Path] = None,
    phase1_summary_path: Optional[Path] = None,
    phase4_summary_path: Optional[Path] = None,
    phase7_summary_path: Optional[Path] = None,
    filename_tag: str = 'run',
) -> Dict[str, Any]:
    """
    Summary-driven Phase 9 global visualization.

    This function draws charts from existing metrics JSON files only. It does
    not read raw JSONL, Phase 7 parquet shards, or any large dataset file.
    """
    t0 = datetime.now()
    output_dir = Path(output_dir)
    metrics_dir = output_dir / 'metrics'
    metrics_dir.mkdir(parents=True, exist_ok=True)
    tag = str(filename_tag).strip() or 'run'

    split_summary = _read_json_file(split_summary_path)
    phase1_summary = _read_json_file(phase1_summary_path)
    phase4_summary = _read_json_file(phase4_summary_path)
    phase7_summary = _read_json_file(phase7_summary_path)

    apps = [str(a).strip().lower() for a in selected_apps if str(a).strip()]
    stats_by_app = _selected_app_stats(
        selected_apps=apps,
        split_summary=split_summary,
        phase1_summary=phase1_summary,
        phase4_summary=phase4_summary,
        phase7_summary=phase7_summary,
    )

    paths = {
        'total_data': output_dir / f'total_selected_data_{tag}.png',
        'app_comparison': output_dir / f'app_comparison_{tag}.png',
        'malicious_benign_by_app': output_dir / f'malicious_benign_by_app_{tag}.png',
        'event_type_by_app': output_dir / f'event_type_by_app_{tag}.png',
        'protocol_by_app': output_dir / f'protocol_by_app_{tag}.png',
        'app_proto_by_app': output_dir / f'app_proto_by_app_{tag}.png',
        'alert_severity_by_target': output_dir / f'alert_severity_by_target_{tag}.png',
    }

    total_info = _plot_total_text(stats_by_app, paths['total_data'])
    app_info = _plot_app_rows(stats_by_app, paths['app_comparison'])
    mb_info = _plot_benign_malicious(stats_by_app, paths['malicious_benign_by_app'])

    event_counters: Dict[str, Dict[str, int]] = {}
    proto_counters: Dict[str, Dict[str, int]] = {}
    app_proto_counters: Dict[str, Dict[str, int]] = {}
    severity_by_app: Dict[str, Dict[str, Dict[str, int]]] = {}

    for app in apps:
        p1 = _viz_stats(phase1_summary, app)
        p4 = _viz_stats(phase4_summary, app)
        event_counters[app] = _pick_counter(p1, ('event_type_counts_top50', 'event_type_counter_top10', 'top_event_type'))
        proto_counters[app] = _pick_counter(p1, ('proto_counts_top20', 'proto_counter_top10', 'top_proto', 'proto_counts'))
        app_proto_counters[app] = _pick_counter(p1, ('app_proto_counts_top50', 'app_proto_counter_top10', 'top_app_proto'))
        sev = p4.get('alert_severity_by_target') or {}
        if isinstance(sev, dict):
            severity_by_app[app] = {
                str(t): _as_int_dict(v) for t, v in sev.items() if isinstance(v, dict)
            }

    event_info = _plot_counter_multipanel(event_counters, paths['event_type_by_app'], title='Top Event Types by Application', top_n=10)
    proto_info = _plot_counter_multipanel(proto_counters, paths['protocol_by_app'], title='Protocol Distribution by Application', top_n=10)
    app_proto_info = _plot_counter_multipanel(app_proto_counters, paths['app_proto_by_app'], title='App Proto Distribution by Application', top_n=10)
    sev_info = _plot_alert_severity_by_target(severity_by_app, paths['alert_severity_by_target'])

    elapsed = (datetime.now() - t0).total_seconds()
    summary = {
        'phase': 9,
        'status': 'completed',
        'mode': 'summary_driven',
        'selected_apps': apps,
        'output_dir': str(output_dir),
        'source_paths': {
            'split_summary_path': str(split_summary_path) if split_summary_path else None,
            'phase1_summary_path': str(phase1_summary_path) if phase1_summary_path else None,
            'phase4_summary_path': str(phase4_summary_path) if phase4_summary_path else None,
            'phase7_summary_path': str(phase7_summary_path) if phase7_summary_path else None,
        },
        'paths': {k: str(v) for k, v in paths.items()},
        'by_app': stats_by_app,
        'global': total_info,
        'app_comparison': app_info,
        'malicious_benign_by_app': mb_info,
        'event_type_by_app': event_info,
        'protocol_by_app': proto_info,
        'app_proto_by_app': app_proto_info,
        'alert_severity_by_target': sev_info,
        'seconds': float(elapsed),
        'note': 'Charts were generated from small metrics/summary JSON files. No raw JSONL or parquet shard was read.',
    }
    _json_dump(summary, metrics_dir / 'phase9_summary_driven_visualization_summary.json')
    return summary


def phase9_visualization_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase9VisualizationConfig] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode per-app Phase 9 visualization.

    Use this directly after Phase 7 while df_clean is still in memory. This
    avoids reading Phase 7 parquet shards. It keeps the old per-app overview and
    heatmap behavior, but samples from the in-memory df_clean.
    """
    if cfg is None:
        cfg = Phase9VisualizationConfig()

    t0 = datetime.now()
    app = str(app).strip().lower()
    output_dir = Path(cfg.output_dir)
    out_app_dir = output_dir / f'app={app}'
    metrics_dir = output_dir / 'metrics'
    out_app_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    tag = cfg.filename_tag.strip() or 'run'

    overview_path = out_app_dir / f'visualization_overview_{app}_{tag}_n{cfg.n_viz}.png'
    heatmap_path = out_app_dir / f'correlation_heatmap_{app}_{tag}_n{cfg.n_heatmap}.png'

    if df_clean is None or df_clean.empty:
        summary = {
            'phase': 9,
            'app': app,
            'status': 'skipped_empty_input',
            'mode': 'ram_per_app',
            'rows_seen': 0,
            'overview_path': None,
            'heatmap_path': None,
            'seconds': 0.0,
        }
        _json_dump(summary, metrics_dir / f'phase9_visualization_summary_{app}.json')
        return pd.DataFrame(), summary

    rows_seen = int(len(df_clean))
    n_take = min(rows_seen, max(0, int(cfg.n_viz)))
    if n_take <= 0:
        df_viz = df_clean.iloc[0:0].copy()
    elif rows_seen <= n_take:
        df_viz = df_clean.copy()
    else:
        rng = np.random.default_rng(int(cfg.seed) + abs(hash(app)) % 100_000)
        y = _target_series(df_clean, cfg.target_col)
        if cfg.stratify_by_target and y.nunique(dropna=True) >= 2:
            atk_idx = np.where(y.to_numpy() == 1)[0]
            ben_idx = np.where(y.to_numpy() == 0)[0]
            atk_take = max(1, int(round(len(atk_idx) / max(1, rows_seen) * n_take))) if len(atk_idx) else 0
            atk_take = min(atk_take, len(atk_idx))
            ben_take = min(n_take - atk_take, len(ben_idx))
            picks = []
            if atk_take:
                picks.append(rng.choice(atk_idx, size=atk_take, replace=False))
            if ben_take:
                picks.append(rng.choice(ben_idx, size=ben_take, replace=False))
            if picks:
                pick = np.concatenate(picks)
                rng.shuffle(pick)
                df_viz = df_clean.iloc[pick].copy()
            else:
                df_viz = df_clean.sample(n=n_take, random_state=int(cfg.seed)).copy()
        else:
            df_viz = df_clean.sample(n=n_take, random_state=int(cfg.seed)).copy()

    overview_info = _make_overview_plot(df_viz, cfg=cfg, app=app, output_path=overview_path) if not df_viz.empty else {}
    heatmap_info = _make_correlation_heatmap(df_viz, cfg=cfg, app=app, output_path=heatmap_path) if not df_viz.empty else {}
    snapshot = _sample_distribution_snapshot(df_viz, cfg)

    elapsed = (datetime.now() - t0).total_seconds()
    summary = {
        'phase': 9,
        'app': app,
        'status': 'completed',
        'mode': 'ram_per_app',
        'output_dir': str(out_app_dir),
        'overview_path': str(overview_path) if overview_path.exists() else None,
        'heatmap_path': str(heatmap_path) if heatmap_path.exists() else None,
        'rows_seen': rows_seen,
        'n_viz_requested': int(cfg.n_viz),
        'n_viz_used': int(len(df_viz)),
        'n_heatmap_requested': int(cfg.n_heatmap),
        'target_counts_sample': _counter_to_str_dict(snapshot.get('target_counts', Counter())),
        'event_type_top10_sample': {str(k): int(v) for k, v in snapshot.get('event_type_top10', [])},
        'proto_counts_sample': _counter_to_str_dict(snapshot.get('proto_counts', Counter())),
        'app_proto_top10_sample': {str(k): int(v) for k, v in snapshot.get('app_proto_top10', [])},
        'dest_port_top10_sample': {str(k): int(v) for k, v in snapshot.get('dest_port_top10', [])},
        'overview': overview_info,
        'heatmap': heatmap_info,
        'seconds': float(elapsed),
        'note': 'RAM-mode Phase 9 uses df_clean in memory and does not read parquet/raw input.',
    }
    _json_dump(summary, metrics_dir / f'phase9_visualization_summary_{app}.json')
    return df_viz, summary


# Compatibility aliases for new RAM/summary-driven pipeline.
def phase9_build_from_metrics(**kwargs: Any) -> Dict[str, Any]:
    return phase9_visualization_from_metrics(**kwargs)


def phase9_global_visualization_from_metrics(**kwargs: Any) -> Dict[str, Any]:
    return phase9_visualization_from_metrics(**kwargs)


def phase9_visualization_in_memory(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase9VisualizationConfig] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase9_visualization_ram(df_clean, app=app, cfg=cfg)
