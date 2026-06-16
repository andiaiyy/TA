from __future__ import annotations

"""
Phase 9 - Summary-Driven Visualization

Purpose:
- Do NOT read raw eve_<app>.jsonl.
- Do NOT read train.csv/test.csv.
- Do NOT read Phase 7/8 full dataset shards.
- Generate figures from:
    1. pre-pipeline split_summary.json
    2. Phase 8 export_summary.json
    3. Phase 8 split_summary.json
    4. Phase 8 label_distribution.csv
    5. Phase 8 feature_group_summary.csv
    6. Phase 8 feature_availability.csv
    7. Phase 8 visualization_sample.csv / corr_leak_sample.csv if available

Important:
- Exact full-data counts should come from Phase 8 summaries because Phase 8
  already full-scans the app JSONL while exporting train/test.
- split_eve_by_app summary is useful for initial/pre-refinement counts, app
  distribution, event_type/app_proto/port summaries.
- Detailed feature plots and heatmap use bounded samples created by Phase 8,
  not a new dataset scan.

Input:
    split_summary.json from pre-pipeline
    phase8/*.json / *.csv summaries

Output:
    phase9_<app>_summary.json
    figures/*.png
    summary.json
"""

import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

from ..io_utils import now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Helpers
# ============================================================

def _normalize_app(app: str) -> str:
    app = str(app).strip().lower()
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app={app!r}. Expected one of {sorted(VALID_APPS)}")
    return app


def _phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _read_optional_json(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _read_csv_df(path: Path, *, max_rows: Optional[int] = None) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, nrows=max_rows)
    except Exception:
        return pd.DataFrame()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _as_int_dict(obj: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        try:
            out[str(k)] = int(v)
        except Exception:
            continue
    return out


def _top_dict(obj: Any, n: int = 10) -> dict[str, int]:
    d = _as_int_dict(obj)
    return dict(sorted(d.items(), key=lambda kv: int(kv[1]), reverse=True)[: int(n)])


def _get_split_summary_path(cfg: Any, app_input_path: Optional[Path]) -> Optional[Path]:
    explicit = getattr(cfg, "prepipeline_summary_path", None)
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p

    storage = getattr(cfg, "storage", None)
    if storage is not None:
        split_app_dir = getattr(storage, "split_app_dir", None)
        if split_app_dir:
            p = Path(split_app_dir) / "split_summary.json"
            if p.exists():
                return p

    if app_input_path is not None:
        p = Path(app_input_path).parent / "split_summary.json"
        if p.exists():
            return p

    return None


def _get_app_block(split_summary: dict[str, Any], app: str) -> dict[str, Any]:
    apps = split_summary.get("apps")
    if isinstance(apps, dict):
        for k, v in apps.items():
            if str(k).strip().lower() == app and isinstance(v, dict):
                return v

    # Legacy flat summary fallback.
    written_counts = split_summary.get("written_counts") if isinstance(split_summary.get("written_counts"), dict) else {}
    detected_counts = split_summary.get("detected_counts") if isinstance(split_summary.get("detected_counts"), dict) else {}
    output_files = split_summary.get("output_files") if isinstance(split_summary.get("output_files"), dict) else {}

    if app in written_counts or app in detected_counts or app in output_files:
        return {
            "app": app,
            "written_rows": written_counts.get(app),
            "matched_rows": detected_counts.get(app),
            "output_file": output_files.get(app),
            "label_counts": {},
            "legacy_summary_format": True,
        }

    return {}


def _initial_counts_from_split(app_block: dict[str, Any]) -> dict[str, int]:
    label_counts = app_block.get("label_counts")
    if isinstance(label_counts, dict) and label_counts:
        benign = _safe_int(label_counts.get("benign"), 0)
        attack = _safe_int(label_counts.get("malicious"), 0)
        return {"benign": benign, "attack": attack, "total": benign + attack}

    rows = _safe_int(app_block.get("written_rows") or app_block.get("matched_rows"), 0)
    return {"benign": 0, "attack": 0, "total": rows}


def _phase8_target_counts(export_summary: dict[str, Any]) -> dict[str, int]:
    d = _as_int_dict(export_summary.get("target_counts"))
    return {
        "benign": int(d.get("0", 0)),
        "attack": int(d.get("1", 0)),
        "total": int(sum(d.values())),
    }


def _phase8_label_source_counts(export_summary: dict[str, Any]) -> dict[str, int]:
    return _top_dict(export_summary.get("label_source_counts"), 20)


def _phase8_split_counts(export_summary: dict[str, Any], split_summary: dict[str, Any]) -> dict[str, int]:
    train = _safe_int(export_summary.get("train_rows"), _safe_int(split_summary.get("train_rows"), 0))
    test = _safe_int(export_summary.get("test_rows"), _safe_int(split_summary.get("test_rows"), 0))
    return {"train": train, "test": test, "total": train + test}


def _port_summary_to_counter(port_summary: Any, *, top_n: int = 15) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(port_summary, dict):
        return out
    for port, info in port_summary.items():
        if isinstance(info, dict):
            out[str(port)] = _safe_int(info.get("total"), 0)
        else:
            out[str(port)] = _safe_int(info, 0)
    return dict(sorted(out.items(), key=lambda kv: int(kv[1]), reverse=True)[: int(top_n)])


def _ensure_fig_dir(phase_dir: Path) -> Path:
    out = Path(phase_dir) / "figures"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _bar_plot(
    data: dict[str, int],
    path: Path,
    *,
    title: str,
    xlabel: str = "",
    ylabel: str = "Count",
    rotation: int = 0,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.text(0.5, 0.5, "No data available", ha="center", va="center")
        ax.axis("off")
        ax.set_title(title, fontsize=14, fontweight="bold")
        plt.tight_layout()
        plt.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return {"path": str(path), "items": 0, "status": "empty"}

    labels = list(data.keys())
    values = [int(v) for v in data.values()]

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(labels, values)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(axis="x", rotation=rotation)

    for i, v in enumerate(values):
        ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=8)

    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"path": str(path), "items": len(data), "status": "completed"}


def _horizontal_bar_plot(
    data: dict[str, int],
    path: Path,
    *,
    title: str,
    xlabel: str = "Count",
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        fig, ax = plt.subplots(figsize=(11, 6))
        ax.text(0.5, 0.5, "No data available", ha="center", va="center")
        ax.axis("off")
        ax.set_title(title, fontsize=14, fontweight="bold")
        plt.tight_layout()
        plt.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return {"path": str(path), "items": 0, "status": "empty"}

    labels = list(data.keys())[::-1]
    values = [int(v) for v in data.values()][::-1]

    fig, ax = plt.subplots(figsize=(12, max(6, len(labels) * 0.38)))
    ax.barh(labels, values)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"path": str(path), "items": len(data), "status": "completed"}


def _summary_text_plot(
    *,
    app: str,
    initial_counts: dict[str, int],
    refined_counts: dict[str, int],
    split_counts: dict[str, int],
    export_summary: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)

    rows_seen = _safe_int(export_summary.get("rows_seen"), 0)
    rows_written = _safe_int(export_summary.get("rows_written"), 0)
    feature_count = _safe_int(export_summary.get("feature_count"), 0)

    lines = [
        f"Application: {app.upper()}",
        "",
        "Initial pre-pipeline label evidence:",
        f"  Benign : {initial_counts.get('benign', 0):,}",
        f"  Attack : {initial_counts.get('attack', 0):,}",
        f"  Total  : {initial_counts.get('total', 0):,}",
        "",
        "Final Phase 8 refined target:",
        f"  Benign : {refined_counts.get('benign', 0):,}",
        f"  Attack : {refined_counts.get('attack', 0):,}",
        f"  Total  : {refined_counts.get('total', 0):,}",
        "",
        "Train/Test split:",
        f"  Train  : {split_counts.get('train', 0):,}",
        f"  Test   : {split_counts.get('test', 0):,}",
        f"  Total  : {split_counts.get('total', 0):,}",
        "",
        "Phase 8 export:",
        f"  Rows seen    : {rows_seen:,}",
        f"  Rows written : {rows_written:,}",
        f"  Features     : {feature_count:,}",
    ]

    fig, ax = plt.subplots(figsize=(10.5, 7))
    ax.axis("off")
    ax.text(0.03, 0.97, "\n".join(lines), ha="left", va="top", fontsize=12, family="monospace")
    ax.set_title("Phase 9 - Summary Overview", fontsize=16, fontweight="bold", pad=16)
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"path": str(path), "status": "completed"}


def _label_comparison_plot(
    *,
    initial_counts: dict[str, int],
    refined_counts: dict[str, int],
    path: Path,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stages = ["Initial\npre-pipeline", "Refined\nPhase 8"]
    benign = [initial_counts.get("benign", 0), refined_counts.get("benign", 0)]
    attack = [initial_counts.get("attack", 0), refined_counts.get("attack", 0)]

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar(stages, benign, label="Benign")
    ax.bar(stages, attack, bottom=benign, label="Attack/Malicious")
    ax.set_title("Initial vs Refined Label Distribution", fontsize=14, fontweight="bold")
    ax.set_ylabel("Rows")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()

    for i, total in enumerate([benign[0] + attack[0], benign[1] + attack[1]]):
        ax.text(i, total, f"{total:,}", ha="center", va="bottom", fontsize=9)

    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"path": str(path), "status": "completed"}


def _feature_group_plot(feature_group_csv: Path, path: Path) -> dict[str, Any]:
    rows = _read_csv_rows(feature_group_csv)
    data: dict[str, int] = {}
    for row in rows:
        group = str(row.get("group", "unknown"))
        count = _safe_int(row.get("feature_count"), 0)
        if group:
            data[group] = count
    return _horizontal_bar_plot(data, path, title="Feature Group Summary")


def _feature_availability_plot(feature_availability_csv: Path, path: Path) -> dict[str, Any]:
    df = _read_csv_df(feature_availability_csv)
    if df.empty or "column" not in df.columns:
        return _horizontal_bar_plot({}, path, title="Lowest Feature Availability")

    if "availability_ratio" in df.columns:
        df["availability_ratio"] = pd.to_numeric(df["availability_ratio"], errors="coerce").fillna(0)
        view = df.sort_values("availability_ratio", ascending=True).head(20)
        data = {
            str(r["column"]): int(round(float(r["availability_ratio"]) * 10000))
            for _, r in view.iterrows()
        }

        # Custom percent axis.
        path.parent.mkdir(parents=True, exist_ok=True)
        labels = list(data.keys())[::-1]
        values = [v / 100.0 for v in data.values()][::-1]

        fig, ax = plt.subplots(figsize=(12, 7))
        ax.barh(labels, values)
        ax.set_title("Lowest Feature Availability", fontsize=14, fontweight="bold")
        ax.set_xlabel("Availability (%)")
        ax.grid(axis="x", alpha=0.3)
        plt.tight_layout()
        plt.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return {"path": str(path), "items": len(data), "status": "completed"}

    return _horizontal_bar_plot({}, path, title="Lowest Feature Availability")


def _numeric_box_plot(sample_path: Path, path: Path, *, target_col: str = "Target_refined") -> dict[str, Any]:
    df = _read_csv_df(sample_path, max_rows=250_000)
    if df.empty:
        return _horizontal_bar_plot({}, path, title="Numeric Feature Overview from Phase 8 Sample")

    if target_col not in df.columns:
        target_col = "Target" if "Target" in df.columns else ""

    numeric_candidates = [c for c in ["total_pkts", "total_bytes", "duration", "pkts_per_sec", "bytes_per_sec"] if c in df.columns]
    if not numeric_candidates:
        return _horizontal_bar_plot({}, path, title="Numeric Feature Overview from Phase 8 Sample")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, len(numeric_candidates), figsize=(max(12, 4 * len(numeric_candidates)), 5))
    if not isinstance(axes, np.ndarray):
        axes = np.array([axes])

    if target_col:
        y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    else:
        y = pd.Series(np.zeros(len(df), dtype=int), index=df.index)

    for ax, col in zip(axes, numeric_candidates):
        x = pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0)
        data = []
        labels = []
        for target_value, label in [(0, "Benign"), (1, "Attack")]:
            vals = x[y == target_value].values
            if len(vals) > 0:
                data.append(vals)
                labels.append(label)
        if data:
            ax.boxplot(data, labels=labels, showfliers=False)
            ax.set_title(col)
            ax.grid(axis="y", alpha=0.3)
        else:
            ax.text(0.5, 0.5, "No data", ha="center", va="center")
            ax.axis("off")

    fig.suptitle("Numeric Feature Overview from Phase 8 Sample", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    return {"path": str(path), "features": numeric_candidates, "sample_rows": int(len(df)), "status": "completed"}


def _correlation_heatmap_from_sample(sample_path: Path, path: Path, *, target_col: str = "Target_refined", max_features: int = 60) -> dict[str, Any]:
    df = _read_csv_df(sample_path, max_rows=200_000)
    if df.empty:
        return _horizontal_bar_plot({}, path, title="Correlation Heatmap from Phase 8 Sample")

    if target_col not in df.columns:
        target_col = "Target" if "Target" in df.columns else target_col

    numeric_df = pd.DataFrame()
    for col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().mean() >= 0.95:
            numeric_df[col] = s.replace([np.inf, -np.inf], np.nan).fillna(0)

    if numeric_df.empty:
        return _horizontal_bar_plot({}, path, title="Correlation Heatmap from Phase 8 Sample")

    numeric_cols = list(numeric_df.columns)

    if len(numeric_cols) > max_features:
        keep = [target_col] if target_col in numeric_cols else []
        variances = numeric_df[numeric_cols].var(numeric_only=True).sort_values(ascending=False)
        for col in variances.index:
            if col == target_col:
                continue
            keep.append(col)
            if len(keep) >= max_features:
                break
        numeric_cols = keep

    corr = numeric_df[numeric_cols].corr(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(corr.values, aspect="auto", vmin=-1, vmax=1)
    fig.colorbar(im, ax=ax, label="Correlation")
    ax.set_title("Correlation Heatmap from Phase 8 Sample", fontsize=14, fontweight="bold")
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.index)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=7)
    ax.set_yticklabels(corr.index, fontsize=7)
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return {
        "path": str(path),
        "sample_rows": int(len(df)),
        "features": [str(c) for c in numeric_cols],
        "feature_count": int(len(numeric_cols)),
        "status": "completed",
    }


# ============================================================
# Runner
# ============================================================

def run_phase9(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    app_input_path: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = _ensure_fig_dir(phase_dir)

    phase8_dir = _phase_dir(phase_dir, "phase8")

    split_summary_path = _get_split_summary_path(cfg, app_input_path)
    split_summary = _read_optional_json(split_summary_path)

    export_summary_path = phase8_dir / "export_summary.json"
    phase8_split_summary_path = phase8_dir / "split_summary.json"
    label_distribution_path = phase8_dir / "label_distribution.csv"
    feature_group_summary_path = phase8_dir / "feature_group_summary.csv"
    feature_availability_path = phase8_dir / "feature_availability.csv"
    visualization_sample_path = phase8_dir / "visualization_sample.csv"
    corr_leak_sample_path = phase8_dir / "corr_leak_sample.csv"

    export_summary = _read_optional_json(export_summary_path)
    phase8_split_summary = _read_optional_json(phase8_split_summary_path)

    app_block = _get_app_block(split_summary, app)
    initial_counts = _initial_counts_from_split(app_block)
    refined_counts = _phase8_target_counts(export_summary)
    split_counts = _phase8_split_counts(export_summary, phase8_split_summary)

    event_type_counts = _top_dict(app_block.get("event_type_counts"), 15)
    app_proto_counts = _top_dict(app_block.get("app_proto_counts"), 15)
    dest_port_counts = _port_summary_to_counter(app_block.get("dest_port_summary"), top_n=15)
    match_reason_counts = _top_dict(app_block.get("match_reason_counts"), 10)
    label_source_counts = _phase8_label_source_counts(export_summary)

    print("\n" + "=" * 72)
    print("Phase 9 - Summary-Driven Visualization")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {export_summary_path}")
    print("Mode        : summary/sample only, no raw/full dataset reread")
    print("=" * 72)

    paths = {
        "summary_overview": fig_dir / f"phase9_{app}_summary_overview.png",
        "initial_vs_refined_labels": fig_dir / f"phase9_{app}_initial_vs_refined_labels.png",
        "train_test_split": fig_dir / f"phase9_{app}_train_test_split.png",
        "label_source": fig_dir / f"phase9_{app}_label_source.png",
        "event_type_initial": fig_dir / f"phase9_{app}_event_type_initial.png",
        "app_proto_initial": fig_dir / f"phase9_{app}_app_proto_initial.png",
        "dest_port_initial": fig_dir / f"phase9_{app}_dest_port_initial.png",
        "match_reason": fig_dir / f"phase9_{app}_match_reason.png",
        "feature_group": fig_dir / f"phase9_{app}_feature_group.png",
        "feature_availability": fig_dir / f"phase9_{app}_feature_availability.png",
        "numeric_overview_sample": fig_dir / f"phase9_{app}_numeric_overview_sample.png",
        "correlation_heatmap_sample": fig_dir / f"phase9_{app}_correlation_heatmap_sample.png",
    }

    figures: dict[str, Any] = {}

    figures["summary_overview"] = _summary_text_plot(
        app=app,
        initial_counts=initial_counts,
        refined_counts=refined_counts,
        split_counts=split_counts,
        export_summary=export_summary,
        path=paths["summary_overview"],
    )

    figures["initial_vs_refined_labels"] = _label_comparison_plot(
        initial_counts=initial_counts,
        refined_counts=refined_counts,
        path=paths["initial_vs_refined_labels"],
    )

    figures["train_test_split"] = _bar_plot(
        {"train": split_counts.get("train", 0), "test": split_counts.get("test", 0)},
        paths["train_test_split"],
        title="Train/Test Split from Phase 8",
    )

    figures["label_source"] = _horizontal_bar_plot(
        label_source_counts,
        paths["label_source"],
        title="Label Source Distribution from Phase 8",
    )

    figures["event_type_initial"] = _horizontal_bar_plot(
        event_type_counts,
        paths["event_type_initial"],
        title="Initial Event Type Distribution from Pre-pipeline Summary",
    )

    figures["app_proto_initial"] = _horizontal_bar_plot(
        app_proto_counts,
        paths["app_proto_initial"],
        title="Initial App Proto Distribution from Pre-pipeline Summary",
    )

    figures["dest_port_initial"] = _horizontal_bar_plot(
        dest_port_counts,
        paths["dest_port_initial"],
        title="Initial Destination Port Distribution from Pre-pipeline Summary",
    )

    figures["match_reason"] = _bar_plot(
        match_reason_counts,
        paths["match_reason"],
        title="Pre-pipeline Match Reason Counts",
        rotation=20,
    )

    figures["feature_group"] = _feature_group_plot(
        feature_group_summary_path,
        paths["feature_group"],
    )

    figures["feature_availability"] = _feature_availability_plot(
        feature_availability_path,
        paths["feature_availability"],
    )

    figures["numeric_overview_sample"] = _numeric_box_plot(
        visualization_sample_path,
        paths["numeric_overview_sample"],
        target_col="Target_refined",
    )

    figures["correlation_heatmap_sample"] = _correlation_heatmap_from_sample(
        corr_leak_sample_path,
        paths["correlation_heatmap_sample"],
        target_col="Target_refined",
        max_features=int(getattr(getattr(cfg, "export", None), "heatmap_max_features", 60) or 60),
    )

    label_distribution_rows = _read_csv_rows(label_distribution_path)

    summary_path = phase_dir / f"phase9_{app}_summary.json"
    summary_alias = phase_dir / "summary.json"

    summary = {
        "phase": 9,
        "title": "Summary-Driven Visualization",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),
        "mode": "summary_driven_no_full_reread",

        "input": {
            "prepipeline_split_summary": str(split_summary_path) if split_summary_path else None,
            "phase8_export_summary": str(export_summary_path),
            "phase8_split_summary": str(phase8_split_summary_path),
            "phase8_label_distribution": str(label_distribution_path),
            "phase8_feature_group_summary": str(feature_group_summary_path),
            "phase8_feature_availability": str(feature_availability_path),
            "phase8_visualization_sample": str(visualization_sample_path),
            "phase8_corr_leak_sample": str(corr_leak_sample_path),
        },

        "source_policy": {
            "exact_final_counts_source": "phase8_export_summary",
            "initial_counts_source": "prepipeline_split_summary",
            "detailed_feature_plot_source": "phase8_samples",
            "raw_jsonl_reread": False,
            "train_test_reread": False,
        },

        "initial_counts": initial_counts,
        "refined_counts": refined_counts,
        "split_counts": split_counts,
        "label_source_counts": label_source_counts,
        "event_type_counts_initial_top": event_type_counts,
        "app_proto_counts_initial_top": app_proto_counts,
        "dest_port_counts_initial_top": dest_port_counts,
        "match_reason_counts": match_reason_counts,
        "label_distribution_rows": label_distribution_rows[:50],

        "figures": figures,
        "output": {
            "summary": str(summary_path),
            "summary_alias": str(summary_alias),
            "figures_dir": str(fig_dir),
        },

        "notes": [
            "Phase 9 does not read raw JSONL, train.csv, test.csv, or full dataset shards.",
            "If a desired chart needs exact full-data statistics not present here, add that aggregation to Phase 8 because Phase 8 already scans the full app JSONL.",
            "split_eve_by_app summary is enough for initial app split counts and raw protocol/event/port context, but not enough for refined labels or feature-engineered summaries.",
        ],
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 9 - Summary-Driven Visualization")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Figures     : {fig_dir}")
    print(f"Output      : {summary_path}")
    print("Read Policy : no raw/full dataset reread")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase9_run = run_phase9
phase9_visualization = run_phase9
phase9_build_from_metrics = run_phase9
phase9_global_visualization_from_metrics = run_phase9
