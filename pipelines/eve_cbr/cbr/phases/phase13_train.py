from __future__ import annotations

"""
Phase 13 - Model Training and Holdout Evaluation

Purpose:
- Do NOT read raw eve_<app>.jsonl.
- Do NOT load the full train/test files into RAM.
- Do NOT create another modeling dataset.
- Read bounded train/test samples from Phase 8 outputs.
- Use Phase 12 selected_features.json.
- Train/evaluate:
    DT, RFC, LSVC, XGB when available
  using feature sets:
    MI, RFE, PCA

Input:
    phase8/train.csv or train.csv.gz/jsonl/jsonl.gz
    phase8/test.csv or test.csv.gz/jsonl/jsonl.gz
    phase11/modeling_manifest.json
    phase12/selected_features.json

Output:
    phase13_<app>_results_comparison.csv
    phase13_<app>_summary.json
    phase13_<app>_<model>_summary.json

Generic aliases:
    results_comparison.csv
    summary.json
"""


import csv
import gzip
import hashlib
import json
import math
import os
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier

try:
    from xgboost import XGBClassifier  # type: ignore
except Exception:
    XGBClassifier = None

try:
    import joblib  # type: ignore
except Exception:
    joblib = None

try:
    from threadpoolctl import threadpool_limits  # type: ignore
except Exception:
    threadpool_limits = None

from ..io_utils import file_size_bytes, file_size_gib, now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}

_LOGICAL_CPU = max(1, os.cpu_count() or 8)
_RESERVED_THREADS = 2 if _LOGICAL_CPU >= 8 else 1
_WORKER_THREADS = max(1, _LOGICAL_CPU - _RESERVED_THREADS)
_INNER_THREADS = 1

os.environ.setdefault("OMP_NUM_THREADS", str(_INNER_THREADS))
os.environ.setdefault("OPENBLAS_NUM_THREADS", str(_INNER_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(_INNER_THREADS))
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", str(_INNER_THREADS))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(_INNER_THREADS))


# ============================================================
# Final leakage guard
# ============================================================

FORBIDDEN_EXACT = {
    "Target",
    "Target_alert",
    "Target_refined",
    "Target_prelim",
    "is_malicious",

    "timestamp",
    "window_start",
    "src_ip",
    "dest_ip",
    "flow_id",
    "community_id",
    "first_seen",
    "last_seen",

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
    "alert_count_window",
    "valid_alert_count_window",
    "event_type_alert_count_window",
    "base_alert_positive_count_window",

    "label_source",
    "label_source_h",
    "label_reason",
    "label_reason_h",
    "label_status",
    "label_status_h",
    "label_status_final",
    "label_status_final_h",
    "label_confidence",
    "refinement_reason",
    "suspicious_by_probe",

    "probe_score_with_alert",
    "probe_level",
    "probe_reason",
    "probe_reason_h",
    "is_suspicious_window",
    "same_alert_window",
    "near_alert_window",
    "matched_alert_window",
    "minutes_to_alert_window",
}

FORBIDDEN_PREFIXES = ("alert_", "label_", "evidence_")
FORBIDDEN_SUFFIXES = ("_raw",)


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


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


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
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _limit_threads(limit: Optional[int]):
    if threadpool_limits is None or limit is None:
        return nullcontext()
    try:
        lim = int(limit)
    except Exception:
        return nullcontext()
    if lim <= 0:
        return nullcontext()
    return threadpool_limits(limits=lim)


def _is_forbidden_feature(name: Any, target_col: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return True

    if n == target_col:
        return True

    low = n.lower()
    if low in {x.lower() for x in FORBIDDEN_EXACT}:
        return True
    if any(low.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    if any(low.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return True

    return False


def _unique_keep_order(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        s = str(v).strip()
        if not s or s in seen:
            continue
        out.append(s)
        seen.add(s)
    return out


def _normalize_model_name(name: Any) -> str:
    """
    Accept both old config names and compact model names.

    Old config:
        decision_tree, random_forest, linear_svc, xgboost

    Phase 13 internal names:
        DT, RFC, LSVC, XGB
    """
    raw = str(name or "").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")

    mapping = {
        "dt": "DT",
        "decision_tree": "DT",
        "decisiontree": "DT",
        "tree": "DT",

        "rfc": "RFC",
        "rf": "RFC",
        "random_forest": "RFC",
        "randomforest": "RFC",

        "lsvc": "LSVC",
        "linear_svc": "LSVC",
        "linearsvc": "LSVC",
        "linear_svm": "LSVC",

        "xgb": "XGB",
        "xgboost": "XGB",
        "xgbclassifier": "XGB",
    }

    return mapping.get(key, raw.upper())


def _normalize_model_list(values: Iterable[Any]) -> list[str]:
    return _unique_keep_order(_normalize_model_name(v) for v in values)


def _compression_for_path(path: Path) -> Optional[str]:
    suffixes = "".join(path.suffixes).lower()
    return "gzip" if suffixes.endswith(".gz") else None


def _is_jsonl(path: Path) -> bool:
    suffixes = "".join(path.suffixes).lower()
    return ".jsonl" in suffixes or suffixes.endswith(".ndjson") or suffixes.endswith(".ndjson.gz")


def _stable_hash(value: Any, mod: int = 1_000_000) -> int:
    h = hashlib.blake2b(str(value).encode("utf-8", errors="ignore"), digest_size=8).digest()
    return int.from_bytes(h, "big") % int(mod)


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        raise RuntimeError(f"Target column missing: {target_col}")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


def _series_to_numeric(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.astype(np.int8)

    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0)

    low = s.astype("string").str.strip().str.lower()
    bool_map = {"true": 1, "false": 0, "yes": 1, "no": 0, "y": 1, "n": 0}
    mapped = low.map(bool_map)
    coerced = pd.to_numeric(low, errors="coerce")
    mask = coerced.isna() & mapped.notna()
    if mask.any():
        coerced.loc[mask] = mapped.loc[mask]
    return coerced.replace([np.inf, -np.inf], np.nan).fillna(0)


def _numeric_X_y(
    df: pd.DataFrame,
    *,
    target_col: str,
    features: list[str],
) -> tuple[pd.DataFrame, pd.Series, dict[str, Any]]:
    if df.empty:
        raise RuntimeError("Input sample is empty.")
    y = _target_series(df, target_col)
    if y.nunique(dropna=True) < 2:
        raise RuntimeError(f"Target has one class: {y.value_counts().to_dict()}")

    used: list[str] = []
    non_numeric: list[str] = []
    constant: list[str] = []
    forbidden: list[str] = []

    X = pd.DataFrame(index=df.index)

    for feature in features:
        if feature not in df.columns:
            continue

        if _is_forbidden_feature(feature, target_col):
            forbidden.append(feature)
            continue

        s = _series_to_numeric(df[feature])
        if s.notna().mean() <= 0:
            non_numeric.append(feature)
            continue

        s = s.replace([np.inf, -np.inf], np.nan).fillna(0)
        if s.nunique(dropna=True) <= 1:
            constant.append(feature)
            continue

        X[feature] = s.astype(np.float32)
        used.append(feature)

    if X.empty:
        raise RuntimeError("No usable numeric no-leak features remain for training.")

    info = {
        "requested_feature_count": int(len(features)),
        "used_feature_count": int(len(used)),
        "used_features": used,
        "forbidden_removed": forbidden,
        "non_numeric_dropped": non_numeric,
        "constant_dropped": constant,
        "target_counts": {str(k): int(v) for k, v in y.value_counts(dropna=False).sort_index().to_dict().items()},
    }
    return X, y, info


def _align_X_to_train(df: pd.DataFrame, *, target_col: str, train_features: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    y = _target_series(df, target_col)
    X = pd.DataFrame(index=df.index)

    for feature in train_features:
        if feature in df.columns:
            X[feature] = _series_to_numeric(df[feature]).replace([np.inf, -np.inf], np.nan).fillna(0).astype(np.float32)
        else:
            X[feature] = np.float32(0)

    return X, y


def _read_selected_features(path: Path) -> dict[str, Any]:
    data = _read_optional_json(path)
    if not data:
        return {}
    if "feature_sets" in data and isinstance(data.get("feature_sets"), dict):
        return data["feature_sets"]
    return data


def _feature_sets_from_phase12(phase12_dir: Path) -> tuple[dict[str, Any], Optional[Path]]:
    candidates = [
        phase12_dir / "selected_features.json",
        phase12_dir / "feature_sets.json",
    ]
    matches = sorted(phase12_dir.glob("*selected_features*.json")) + sorted(phase12_dir.glob("*feature_sets*.json"))

    for path in [*candidates, *matches]:
        if path.exists():
            return _read_selected_features(path), path

    return {}, None




def _phase12_diagnostics(phase12_dir: Path, feature_sets_path: Optional[Path]) -> dict[str, Any]:
    """Read lightweight Phase 12 status so Phase 13 skip reasons are explainable."""
    summary_candidates = [
        phase12_dir / "summary.json",
        *sorted(phase12_dir.glob("*summary*.json")),
    ]
    selected_candidates = [
        phase12_dir / "selected_features.json",
        phase12_dir / "feature_sets.json",
        *sorted(phase12_dir.glob("*selected_features*.json")),
        *sorted(phase12_dir.glob("*feature_sets*.json")),
    ]

    summary: dict[str, Any] = {}
    summary_path: Optional[Path] = None
    for path in summary_candidates:
        if path.exists():
            data = _read_optional_json(path)
            if data:
                summary = data
                summary_path = path
                break

    selected: dict[str, Any] = {}
    selected_path: Optional[Path] = feature_sets_path
    if selected_path is not None and selected_path.exists():
        selected = _read_optional_json(selected_path)
    else:
        for path in selected_candidates:
            if path.exists():
                data = _read_optional_json(path)
                if data:
                    selected = data
                    selected_path = path
                    break

    # Keep this compact; the full Phase 12 files remain on disk.
    return {
        "summary_path": str(summary_path) if summary_path else None,
        "selected_features_path": str(selected_path) if selected_path else None,
        "status": summary.get("status") or selected.get("status"),
        "skip_reason": summary.get("skip_reason") or selected.get("skip_reason"),
        "warnings": summary.get("warnings") or selected.get("warnings") or [],
        "target_column": summary.get("target_column") or selected.get("target_column"),
        "sample_info": summary.get("sample_info"),
        "prep_info": summary.get("prep_info"),
        "phase8_label_diagnostics": summary.get("phase8_label_diagnostics"),
        "selected_counts": {
            "MI": len(selected.get("MI", [])) if isinstance(selected.get("MI"), list) else 0,
            "RFE": len(selected.get("RFE", [])) if isinstance(selected.get("RFE"), list) else 0,
            "PCA_feature_columns": (
                len(selected.get("PCA_feature_columns", []))
                if isinstance(selected.get("PCA_feature_columns"), list)
                else 0
            ),
        },
    }


def _phase8_label_diagnostics(phase8_dir: Path) -> dict[str, Any]:
    """Read Phase 8 label/split diagnostics without touching train/test data."""
    export_summary_path = phase8_dir / "export_summary.json"
    split_summary_path = phase8_dir / "split_summary.json"
    export_summary = _read_optional_json(export_summary_path)
    split_summary = _read_optional_json(split_summary_path)

    return {
        "export_summary_path": str(export_summary_path) if export_summary_path.exists() else None,
        "split_summary_path": str(split_summary_path) if split_summary_path.exists() else None,
        "target_counts": export_summary.get("target_counts"),
        "target_alert_counts": export_summary.get("target_alert_counts"),
        "train_target_counts": export_summary.get("train_target_counts") or split_summary.get("train_target_counts"),
        "test_target_counts": export_summary.get("test_target_counts") or split_summary.get("test_target_counts"),
        "target_counts_by_split": export_summary.get("target_counts_by_split") or split_summary.get("target_counts_by_split"),
        "target_alert_counts_by_split": export_summary.get("target_alert_counts_by_split") or split_summary.get("target_alert_counts_by_split"),
        "label_source_counts": export_summary.get("label_source_counts"),
        "label_source_counts_by_split": export_summary.get("label_source_counts_by_split") or split_summary.get("label_source_counts_by_split"),
        "alert_policy_counts": export_summary.get("alert_policy_counts") or split_summary.get("alert_policy_counts"),
        "split_warnings": export_summary.get("split_warnings") or split_summary.get("split_warnings") or [],
    }

def _target_col_from_manifest(manifest: dict[str, Any]) -> str:
    return str(manifest.get("target_column") or "Target_refined")


def _split_paths_from_manifest(phase8_dir: Path, phase11_manifest: dict[str, Any]) -> tuple[Optional[Path], Optional[Path]]:
    ds = phase11_manifest.get("dataset_files")
    if isinstance(ds, dict):
        train = ds.get("train")
        test = ds.get("test")
        train_path = Path(train["path"]) if isinstance(train, dict) and train.get("path") else None
        test_path = Path(test["path"]) if isinstance(test, dict) and test.get("path") else None
        if train_path or test_path:
            return train_path, test_path

    export_summary = _read_optional_json(phase8_dir / "export_summary.json")
    train = export_summary.get("train_path")
    test = export_summary.get("test_path")
    if train or test:
        return Path(train) if train else None, Path(test) if test else None

    split_summary = _read_optional_json(phase8_dir / "split_summary.json")
    train = split_summary.get("train_path")
    test = split_summary.get("test_path")
    if train or test:
        return Path(train) if train else None, Path(test) if test else None

    train_path = None
    test_path = None
    for name in ("train.csv", "train.csv.gz", "train.jsonl", "train.jsonl.gz"):
        p = phase8_dir / name
        if p.exists():
            train_path = p
            break

    for name in ("test.csv", "test.csv.gz", "test.jsonl", "test.jsonl.gz"):
        p = phase8_dir / name
        if p.exists():
            test_path = p
            break

    return train_path, test_path


def _method_features(feature_sets: dict[str, Any], method: str) -> list[str]:
    method = method.upper()
    if method in {"MI", "RFE"}:
        value = feature_sets.get(method, [])
        if isinstance(value, list):
            return _unique_keep_order(value)
        return []

    if method == "PCA":
        pca_cfg = feature_sets.get("PCA")
        if isinstance(pca_cfg, dict):
            value = pca_cfg.get("feature_columns") or feature_sets.get("PCA_feature_columns")
            if isinstance(value, list):
                return _unique_keep_order(value)
        value = feature_sets.get("PCA_feature_columns")
        if isinstance(value, list):
            return _unique_keep_order(value)
        return []

    return []


def _all_needed_features(feature_sets: dict[str, Any], methods: list[str], target_col: str) -> list[str]:
    out: list[str] = []
    for method in methods:
        out.extend(_method_features(feature_sets, method))
    return [x for x in _unique_keep_order(out) if not _is_forbidden_feature(x, target_col)]


# ============================================================
# Chunked sample loading
# ============================================================

def _iter_chunks(path: Path, *, wanted_cols: list[str], chunksize: int) -> Iterable[pd.DataFrame]:
    wanted = set(str(x) for x in wanted_cols if str(x).strip())
    chunksize = max(1_000, int(chunksize))

    if _is_jsonl(path):
        compression = _compression_for_path(path)
        try:
            reader = pd.read_json(path, lines=True, chunksize=chunksize, compression=compression)
            for chunk in reader:
                cols = [c for c in chunk.columns if str(c) in wanted]
                if cols:
                    yield chunk[cols].copy()
        except Exception:
            return
        return

    compression = _compression_for_path(path)
    try:
        reader = pd.read_csv(
            path,
            chunksize=chunksize,
            compression=compression,
            usecols=lambda c: str(c) in wanted,
        )
        for chunk in reader:
            if not chunk.empty:
                yield chunk
    except Exception:
        try:
            reader = pd.read_csv(path, chunksize=chunksize, compression=compression)
            for chunk in reader:
                cols = [c for c in chunk.columns if str(c) in wanted]
                if cols:
                    yield chunk[cols].copy()
        except Exception:
            return


def _class_counts_from_df(df: pd.DataFrame, target_col: str) -> dict[str, int]:
    if df.empty or target_col not in df.columns:
        return {}
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    y = (y == 1).astype(int)
    return {str(k): int(v) for k, v in y.value_counts(dropna=False).sort_index().to_dict().items()}


class _BalancedReservoir:
    """Keep up to `per_class` rows for each target class while streaming chunks."""

    def __init__(self, *, per_class: int, seed: int) -> None:
        self.per_class = max(0, int(per_class))
        self.seed = int(seed)
        self.parts: dict[int, pd.DataFrame] = {0: pd.DataFrame(), 1: pd.DataFrame()}
        self.seen: dict[int, int] = {0: 0, 1: 0}

    def add(self, df: pd.DataFrame, target_col: str) -> None:
        if df.empty or self.per_class <= 0 or target_col not in df.columns:
            return

        y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
        y = (y == 1).astype(int)

        for cls in (0, 1):
            sub = df.loc[y == cls]
            if sub.empty:
                continue

            self.seen[cls] += int(len(sub))
            old = self.parts.get(cls, pd.DataFrame())
            combined = pd.concat([old, sub], ignore_index=True) if not old.empty else sub.copy().reset_index(drop=True)

            if len(combined) > self.per_class:
                combined = combined.sample(
                    n=self.per_class,
                    random_state=self.seed + cls + self.seen[cls],
                ).reset_index(drop=True)

            self.parts[cls] = combined

    def dataframe(self, *, seed: Optional[int] = None) -> pd.DataFrame:
        parts = [p for p in self.parts.values() if p is not None and not p.empty]
        if not parts:
            return pd.DataFrame()
        out = pd.concat(parts, ignore_index=True)
        return out.sample(frac=1.0, random_state=self.seed if seed is None else int(seed)).reset_index(drop=True)

    def kept_counts(self, target_col: str) -> dict[str, int]:
        return _class_counts_from_df(self.dataframe(seed=self.seed), target_col)


class _NaturalReservoir:
    """Keep a global random sample while preserving the source distribution approximately."""

    def __init__(self, *, k: int, seed: int) -> None:
        self.k = max(0, int(k))
        self.seed = int(seed)
        self.part = pd.DataFrame()
        self.seen_rows = 0
        self.seen: dict[int, int] = {0: 0, 1: 0}

    def add(self, df: pd.DataFrame, target_col: str) -> None:
        if df.empty or self.k <= 0:
            return

        if target_col in df.columns:
            y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
            y = (y == 1).astype(int)
            counts = y.value_counts(dropna=False).to_dict()
            for cls in (0, 1):
                self.seen[cls] += int(counts.get(cls, 0))

        self.seen_rows += int(len(df))
        combined = pd.concat([self.part, df], ignore_index=True) if not self.part.empty else df.copy().reset_index(drop=True)
        if len(combined) > self.k:
            combined = combined.sample(n=self.k, random_state=self.seed + self.seen_rows).reset_index(drop=True)
        self.part = combined

    def dataframe(self, *, seed: Optional[int] = None) -> pd.DataFrame:
        if self.part.empty:
            return pd.DataFrame()
        return self.part.sample(frac=1.0, random_state=self.seed if seed is None else int(seed)).reset_index(drop=True)


def _collect_sample(
    *,
    path: Path,
    target_col: str,
    features: list[str],
    sample_rows: int,
    chunksize: int,
    seed: int,
    strategy: str = "balanced",
    per_class_rows: Optional[int] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    wanted = _unique_keep_order([target_col, *features])
    strategy = str(strategy or "balanced").strip().lower()
    requested_rows = max(0, int(sample_rows or 0))

    if strategy in {"natural", "random", "source", "original"}:
        sampler: Any = _NaturalReservoir(k=requested_rows, seed=seed)
        per_class_requested = None
        effective_strategy = "natural"
    else:
        per_class_requested = int(per_class_rows) if per_class_rows is not None else max(1, requested_rows // 2)
        sampler = _BalancedReservoir(per_class=per_class_requested, seed=seed)
        effective_strategy = "balanced"

    rows_scanned = 0
    chunks_read = 0

    for chunk in _iter_chunks(path, wanted_cols=wanted, chunksize=chunksize):
        if chunk.empty or target_col not in chunk.columns:
            continue

        chunks_read += 1
        rows_scanned += int(len(chunk))
        sampler.add(chunk, target_col)

    out = sampler.dataframe(seed=seed)
    info = {
        "path": str(path),
        "sampling_strategy": effective_strategy,
        "requested_rows": int(requested_rows),
        "requested_per_class_rows": int(per_class_requested) if per_class_requested is not None else None,
        "rows_scanned_streaming": int(rows_scanned),
        "chunks_read": int(chunks_read),
        "sample_rows": int(len(out)),
        "sample_seen_by_class": {str(k): int(v) for k, v in getattr(sampler, "seen", {}).items()},
        "sample_kept_by_class": _class_counts_from_df(out, target_col),
    }
    return out, info


def _collect_dual_holdout_samples(
    *,
    path: Path,
    target_col: str,
    features: list[str],
    natural_rows: int,
    balanced_rows: int,
    balanced_per_class_rows: int,
    chunksize: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, dict[str, Any]]:
    """Collect natural and balanced holdout samples in a single streaming pass."""
    wanted = _unique_keep_order([target_col, *features])
    natural_rows = max(0, int(natural_rows or 0))
    balanced_rows = max(0, int(balanced_rows or 0))
    balanced_per_class_rows = int(balanced_per_class_rows or max(1, balanced_rows // 2))

    natural_sampler = _NaturalReservoir(k=natural_rows, seed=seed) if natural_rows > 0 else None
    balanced_sampler = (
        _BalancedReservoir(per_class=balanced_per_class_rows, seed=seed + 1000)
        if balanced_rows > 0 and balanced_per_class_rows > 0
        else None
    )

    rows_scanned = 0
    chunks_read = 0

    for chunk in _iter_chunks(path, wanted_cols=wanted, chunksize=chunksize):
        if chunk.empty or target_col not in chunk.columns:
            continue
        chunks_read += 1
        rows_scanned += int(len(chunk))
        if natural_sampler is not None:
            natural_sampler.add(chunk, target_col)
        if balanced_sampler is not None:
            balanced_sampler.add(chunk, target_col)

    df_natural = natural_sampler.dataframe(seed=seed) if natural_sampler is not None else pd.DataFrame()
    df_balanced = balanced_sampler.dataframe(seed=seed + 1000) if balanced_sampler is not None else pd.DataFrame()

    common = {
        "path": str(path),
        "rows_scanned_streaming": int(rows_scanned),
        "chunks_read": int(chunks_read),
        "single_pass_dual_holdout_collection": True,
    }

    natural_info = {
        **common,
        "sampling_strategy": "natural",
        "requested_rows": int(natural_rows),
        "requested_per_class_rows": None,
        "sample_rows": int(len(df_natural)),
        "sample_seen_by_class": {str(k): int(v) for k, v in (getattr(natural_sampler, "seen", {}) if natural_sampler is not None else {}).items()},
        "sample_kept_by_class": _class_counts_from_df(df_natural, target_col),
    }

    balanced_info = {
        **common,
        "sampling_strategy": "balanced",
        "requested_rows": int(balanced_rows),
        "requested_per_class_rows": int(balanced_per_class_rows),
        "sample_rows": int(len(df_balanced)),
        "sample_seen_by_class": {str(k): int(v) for k, v in (getattr(balanced_sampler, "seen", {}) if balanced_sampler is not None else {}).items()},
        "sample_kept_by_class": _class_counts_from_df(df_balanced, target_col),
    }

    return df_natural, natural_info, df_balanced, balanced_info


# ============================================================
# Models and metrics
# ============================================================

def _build_models(seed: int, modeling_cfg: Any) -> dict[str, Any]:
    rfc_estimators = int(getattr(modeling_cfg, "rfc_estimators", 100) or 100)
    rfc_n_jobs = int(getattr(modeling_cfg, "rfc_n_jobs", _WORKER_THREADS) or _WORKER_THREADS)
    rfc_max_depth = getattr(modeling_cfg, "rfc_max_depth", 16)
    rfc_min_samples_leaf = int(getattr(modeling_cfg, "rfc_min_samples_leaf", 2) or 2)

    lsvc_c = float(getattr(modeling_cfg, "lsvc_c", 1.0) or 1.0)
    lsvc_max_iter = int(getattr(modeling_cfg, "lsvc_max_iter", 5000) or 5000)

    models: dict[str, Any] = {
        "DT": DecisionTreeClassifier(random_state=seed, class_weight="balanced"),
        "RFC": RandomForestClassifier(
            n_estimators=rfc_estimators,
            max_depth=rfc_max_depth,
            min_samples_leaf=rfc_min_samples_leaf,
            random_state=seed,
            n_jobs=rfc_n_jobs,
            class_weight="balanced_subsample",
        ),
        "LSVC": LinearSVC(
            C=lsvc_c,
            max_iter=lsvc_max_iter,
            random_state=seed,
            class_weight="balanced",
        ),
    }

    if XGBClassifier is not None:
        models["XGB"] = XGBClassifier(
            n_estimators=int(getattr(modeling_cfg, "xgb_n_estimators", 300) or 300),
            max_depth=int(getattr(modeling_cfg, "xgb_max_depth", 8) or 8),
            learning_rate=float(getattr(modeling_cfg, "xgb_learning_rate", 0.1) or 0.1),
            subsample=float(getattr(modeling_cfg, "xgb_subsample", 0.8) or 0.8),
            colsample_bytree=float(getattr(modeling_cfg, "xgb_colsample_bytree", 0.8) or 0.8),
            reg_lambda=float(getattr(modeling_cfg, "xgb_reg_lambda", 1.0) or 1.0),
            n_jobs=int(getattr(modeling_cfg, "xgb_n_jobs", _WORKER_THREADS) or _WORKER_THREADS),
            tree_method=str(getattr(modeling_cfg, "xgb_tree_method", "hist") or "hist"),
            device=str(getattr(modeling_cfg, "xgb_device", "cpu") or "cpu"),
            random_state=seed,
            eval_metric=str(getattr(modeling_cfg, "xgb_eval_metric", "logloss") or "logloss"),
        )

    return models


def _make_estimator(method: str, model_name: str, base_models: dict[str, Any], n_components: int, seed: int):
    model = clone(base_models[model_name])
    method = method.upper()

    if method in {"MI", "RFE"}:
        if model_name == "LSVC":
            return Pipeline([("scaler", StandardScaler()), ("model", model)])
        return model

    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=int(n_components), random_state=seed)),
        ("model", model),
    ])


def _score_vector(estimator: Any, X: pd.DataFrame) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        proba = estimator.predict_proba(X)
        if isinstance(proba, np.ndarray) and proba.ndim == 2 and proba.shape[1] >= 2:
            return proba[:, 1]
        return np.asarray(proba).ravel()

    if hasattr(estimator, "decision_function"):
        return np.asarray(estimator.decision_function(X)).ravel()

    return np.asarray(estimator.predict(X)).astype(float)


def _prediction_summary(
    *,
    method: str,
    model_name: str,
    y_true: pd.Series,
    y_pred: np.ndarray,
    y_score: np.ndarray,
    holdout_kind: str = "holdout",
) -> dict[str, Any]:
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    try:
        fpr, tpr, _thresholds = roc_curve(y_true, y_score)
        # Store bounded ROC points to keep artifact small.
        if len(fpr) > 500:
            idx = np.linspace(0, len(fpr) - 1, 500).astype(int)
            fpr = fpr[idx]
            tpr = tpr[idx]
        roc_points = {
            "fpr": [float(x) for x in fpr],
            "tpr": [float(x) for x in tpr],
        }
    except Exception:
        roc_points = {"fpr": [0.0, 1.0], "tpr": [0.0, 1.0]}

    return {
        "Method": method,
        "Model": model_name,
        "holdout_kind": holdout_kind,
        "confusion_matrix": cm.astype(int).tolist(),
        "tn": int(cm[0, 0]),
        "fp": int(cm[0, 1]),
        "fn": int(cm[1, 0]),
        "tp": int(cm[1, 1]),
        "roc_points": roc_points,
    }


def _metrics_from_predictions(y_true: pd.Series, y_pred: np.ndarray, y_score: np.ndarray) -> dict[str, float]:
    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, pos_label=1, zero_division=0)
    rec = recall_score(y_true, y_pred, pos_label=1, zero_division=0)
    f1 = f1_score(y_true, y_pred, pos_label=1, zero_division=0)

    try:
        auc = roc_auc_score(y_true, y_score)
    except Exception:
        auc = 0.5

    return {
        "accuracy": float(acc),
        "precision_attack": float(prec),
        "recall_attack": float(rec),
        "f1_attack": float(f1),
        "auc": float(auc),
    }


def _eval_fitted(estimator: Any, X_test: pd.DataFrame, y_test: pd.Series, *, thread_limit: int) -> tuple[dict[str, float], np.ndarray, np.ndarray]:
    with _limit_threads(thread_limit):
        pred = np.asarray(estimator.predict(X_test))
        try:
            scores = _score_vector(estimator, X_test)
        except Exception:
            scores = np.asarray(pred).astype(float)
    return _metrics_from_predictions(y_test, pred, scores), pred, scores


def _eval_once(estimator: Any, X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame, y_test: pd.Series, *, thread_limit: int) -> dict[str, float]:
    with _limit_threads(thread_limit):
        estimator.fit(X_train, y_train)
    metrics, _pred, _scores = _eval_fitted(estimator, X_test, y_test, thread_limit=thread_limit)
    return metrics


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    return float(np.mean(values)), float(np.std(values))


def _choose_best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    def key(row: dict[str, Any]):
        return (
            _safe_float(row.get("holdout_f1_attack"), -1),
            _safe_float(row.get("holdout_auc"), -1),
            _safe_float(row.get("f1_attack"), -1),
            _safe_float(row.get("auc"), -1),
        )

    return sorted(rows, key=key, reverse=True)[0]


def _quality_warnings(rows: list[dict[str, Any]], forbidden_used: list[str]) -> list[str]:
    warnings: list[str] = []
    if forbidden_used:
        warnings.append("Forbidden leakage features were present after preparation: " + ", ".join(forbidden_used[:20]))

    suspicious = []
    for row in rows:
        for metric in (
            "f1_attack",
            "auc",
            "holdout_f1_attack",
            "holdout_auc",
            "natural_holdout_f1_attack",
            "natural_holdout_auc",
            "balanced_holdout_f1_attack",
            "balanced_holdout_auc",
        ):
            value = _safe_float(row.get(metric), 0.0)
            if value >= 0.999:
                suspicious.append(f"{row.get('Method')}/{row.get('Model')} {metric}={value:.4f}")
                break

    if suspicious:
        warnings.append(
            "Near-perfect metrics detected; treat as possible overfitting/shortcut until validated: "
            + "; ".join(suspicious[:10])
        )

    return warnings


# ============================================================
# Runner
# ============================================================

def run_phase13(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    phase8_dir = _phase_dir(phase_dir, "phase8")
    phase11_dir = _phase_dir(phase_dir, "phase11")
    phase12_dir = _phase_dir(phase_dir, "phase12")

    phase11_manifest_path = phase11_dir / "modeling_manifest.json"
    phase11_manifest = _read_optional_json(phase11_manifest_path)

    target_col = _target_col_from_manifest(phase11_manifest)
    train_path, test_path = _split_paths_from_manifest(phase8_dir, phase11_manifest)

    feature_sets, feature_sets_path = _feature_sets_from_phase12(phase12_dir)

    modeling_cfg = getattr(cfg, "modeling", None)
    seed = int(getattr(modeling_cfg, "seed", getattr(cfg, "seed", 42)) or 42)
    train_rows = int(getattr(modeling_cfg, "modeling_train_rows", getattr(modeling_cfg, "train_rows", 800_000)) or 800_000)
    train_per_class_rows = int(
        getattr(modeling_cfg, "modeling_train_per_class_rows", max(1, train_rows // 2))
        or max(1, train_rows // 2)
    )
    train_sampling_strategy = str(getattr(modeling_cfg, "modeling_train_sampling_strategy", "balanced") or "balanced")

    # New serious-run policy:
    # - primary holdout: natural distribution, 2M-5M rows from test.csv
    # - secondary holdout: balanced 1M benign + 1M attack
    legacy_test_rows = int(getattr(modeling_cfg, "modeling_test_rows", getattr(modeling_cfg, "test_rows", 200_000)) or 200_000)
    natural_test_min_rows = int(getattr(modeling_cfg, "modeling_natural_test_min_rows", 0) or 0)
    natural_test_max_rows = int(getattr(modeling_cfg, "modeling_natural_test_max_rows", legacy_test_rows) or legacy_test_rows)
    balanced_test_rows = int(getattr(modeling_cfg, "modeling_balanced_test_rows", legacy_test_rows) or legacy_test_rows)
    balanced_test_per_class_rows = int(
        getattr(modeling_cfg, "modeling_balanced_test_per_class_rows", max(1, balanced_test_rows // 2))
        or max(1, balanced_test_rows // 2)
    )
    chunksize = int(getattr(modeling_cfg, "read_chunksize", 100_000) or 100_000)
    cv_folds_default = int(getattr(modeling_cfg, "cv_folds", 2) or 2)
    thread_limit = int(getattr(modeling_cfg, "blas_thread_limit", _INNER_THREADS) or _INNER_THREADS)
    save_models = bool(getattr(modeling_cfg, "save_fitted_models", False))
    pca_default_n = int(getattr(modeling_cfg, "pca_default_n_components", 20) or 20)

    methods = [str(x).upper() for x in getattr(modeling_cfg, "methods", ("MI", "RFE", "PCA"))]
    models_requested = _normalize_model_list(getattr(modeling_cfg, "models", ("DT", "RFC", "LSVC", "XGB")))

    all_needed_features = _all_needed_features(feature_sets, methods, target_col)

    prefix = f"phase13_{app}"

    results_path = phase_dir / f"{prefix}_results_comparison.csv"
    summary_path = phase_dir / f"{prefix}_summary.json"

    results_alias = phase_dir / "results_comparison.csv"
    summary_alias = phase_dir / "summary.json"

    print("\n" + "=" * 72)
    print("Phase 13 - Model Training")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Train       : {train_path}")
    print(f"Test        : {test_path}")
    print("Mode        : balanced train + natural/balanced holdout samples")
    print("=" * 72)

    warnings: list[str] = []
    phase12_diagnostics = _phase12_diagnostics(phase12_dir, feature_sets_path)
    phase8_label_diagnostics = _phase8_label_diagnostics(phase8_dir)

    def _finish_without_training(
        *,
        status: str,
        skip_reason: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Write consistent empty artifacts when Phase 13 cannot train."""
        empty_fields = ["App", "Method", "Model", "status", "skip_reason"]
        _write_csv(results_path, [], empty_fields)
        _write_csv(results_alias, [], empty_fields)

        prediction_summary_path = phase_dir / f"{prefix}_holdout_prediction_summary.json"
        prediction_summary_alias = phase_dir / "holdout_prediction_summary.json"
        prediction_summary_payload = {
            "phase": 13,
            "app": app,
            "created_at": now_iso(),
            "target_column": target_col,
            "status": "not_available",
            "reason": skip_reason,
            "items": [],
        }
        write_json(prediction_summary_payload, prediction_summary_path)
        write_json(prediction_summary_payload, prediction_summary_alias)

        summary = {
            "phase": 13,
            "title": "Model Training",
            "status": status,
            "app": app,
            "current_run": app.upper(),
            "generated_at": now_iso(),
            "skip_reason": skip_reason,
            "warnings": warnings,
            "input": {
                "train_path": str(train_path) if train_path else None,
                "test_path": str(test_path) if test_path else None,
                "train_exists": bool(train_path is not None and train_path.exists()),
                "test_exists": bool(test_path is not None and test_path.exists()),
                "phase11_modeling_manifest": str(phase11_manifest_path),
                "phase12_feature_sets": str(feature_sets_path) if feature_sets_path else None,
            },
            "read_policy": {
                "raw_jsonl_reread": False,
                "full_train_loaded": False,
                "full_test_loaded": False,
                "selected_dataset_written": False,
                "source": "Phase 8 train/test bounded samples + Phase 12 selected features",
            },
            "target_column": target_col,
            "methods": methods,
            "models_requested": models_requested,
            "feature_sets_available": bool(feature_sets),
            "all_needed_feature_count": int(len(all_needed_features)),
            "phase12_diagnostics": phase12_diagnostics,
            "phase8_label_diagnostics": phase8_label_diagnostics,
            "results_rows": 0,
            "prediction_summary_rows": 0,
            "output": {
                "results_comparison": str(results_path),
                "holdout_prediction_summary": str(prediction_summary_path),
                "summary": str(summary_path),
            },
            "note": (
                "Phase 13 was skipped before model fitting. This usually means Phase 12 did not produce "
                "usable selected features, or the sampled training target did not contain both classes."
            ),
        }
        if extra:
            summary.update(extra)

        write_json(summary, summary_path)
        write_json(summary, summary_alias)
        return summary

    if train_path is None or not train_path.exists():
        warnings.append("Phase 8 train file not found.")
        return _finish_without_training(
            status="skipped_missing_train_file",
            skip_reason="Phase 8 train file was not found, so bounded training sample cannot be collected.",
        )

    if not feature_sets or not all_needed_features:
        phase12_status = str(phase12_diagnostics.get("status") or "").strip()
        phase12_reason = str(phase12_diagnostics.get("skip_reason") or "").strip()
        if not phase12_reason:
            phase12_reason = (
                "Phase 12 selected feature sets are missing or empty. "
                "Common cause: Phase 12 skipped because train split contained one class."
            )
        warnings.append("No usable Phase 12 selected feature sets found.")
        status = "skipped_no_selected_features"
        if "one_class" in phase12_status.lower() or "one class" in phase12_reason.lower():
            status = "skipped_upstream_one_class_target"
        return _finish_without_training(
            status=status,
            skip_reason=phase12_reason,
        )

    df_train, train_sample_info = _collect_sample(
        path=train_path,
        target_col=target_col,
        features=all_needed_features,
        sample_rows=train_rows,
        chunksize=chunksize,
        seed=seed,
        strategy=train_sampling_strategy,
        per_class_rows=train_per_class_rows,
    )

    if df_train.empty:
        warnings.append("Training sample is empty.")
        return _finish_without_training(
            status="skipped_empty_train_sample",
            skip_reason="No rows were collected from Phase 8 train file for the requested target/features.",
            extra={"train_sample_info": train_sample_info},
        )

    for cls in ("0", "1"):
        kept = int(train_sample_info.get("sample_kept_by_class", {}).get(cls, 0) or 0)
        requested = int(train_sample_info.get("requested_per_class_rows") or 0)
        if requested > 0 and kept < requested:
            warnings.append(
                f"Train class {cls} kept {kept:,} rows, below requested per-class quota {requested:,}."
            )

    df_test_natural = pd.DataFrame()
    natural_test_sample_info: dict[str, Any] = {}
    df_test_balanced = pd.DataFrame()
    balanced_test_sample_info: dict[str, Any] = {}

    if test_path is not None and test_path.exists():
        df_test_natural, natural_test_sample_info, df_test_balanced, balanced_test_sample_info = _collect_dual_holdout_samples(
            path=test_path,
            target_col=target_col,
            features=all_needed_features,
            natural_rows=natural_test_max_rows,
            balanced_rows=balanced_test_rows,
            balanced_per_class_rows=balanced_test_per_class_rows,
            chunksize=chunksize,
            seed=seed + 777,
        )

        if 0 < natural_test_min_rows > len(df_test_natural):
            warnings.append(
                f"Natural holdout kept {len(df_test_natural):,} rows, below requested minimum {natural_test_min_rows:,}."
            )

        for cls in ("0", "1"):
            kept = int(balanced_test_sample_info.get("sample_kept_by_class", {}).get(cls, 0) or 0)
            requested = int(balanced_test_sample_info.get("requested_per_class_rows") or 0)
            if requested > 0 and kept < requested:
                warnings.append(
                    f"Balanced holdout class {cls} kept {kept:,} rows, below requested per-class quota {requested:,}."
                )

    # Prepare a full no-leak numeric pool for PCA and method availability.
    try:
        X_all, y_train, prep_all = _numeric_X_y(df_train, target_col=target_col, features=all_needed_features)
    except Exception as exc:
        msg = str(exc)
        warnings.append(f"Training sample preparation failed: {exc!r}")
        status = "skipped_sample_preparation_failed"
        if "one class" in msg.lower():
            status = "skipped_one_class_target"
        elif "no usable numeric" in msg.lower():
            status = "skipped_no_usable_numeric_features"
        return _finish_without_training(
            status=status,
            skip_reason=msg,
            extra={
                "train_sample_info": train_sample_info,
                "natural_test_sample_info": natural_test_sample_info,
                "balanced_test_sample_info": balanced_test_sample_info,
            },
        )

    def _prepare_holdout(df: pd.DataFrame, kind: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": kind,
            "available": False,
            "X": None,
            "y": None,
            "rows": int(len(df)),
            "target_counts": _class_counts_from_df(df, target_col),
            "reason": None,
        }
        if df.empty:
            payload["reason"] = "empty_sample"
            return payload
        try:
            X_h, y_h = _align_X_to_train(df, target_col=target_col, train_features=list(X_all.columns))
            if y_h.nunique(dropna=True) < 2:
                payload["reason"] = f"one_class_target: {y_h.value_counts().to_dict()}"
                return payload
            payload.update({"available": True, "X": X_h, "y": y_h, "rows": int(len(X_h))})
        except Exception as exc:
            payload["reason"] = repr(exc)
            warnings.append(f"{kind.title()} holdout disabled: {exc!r}")
        return payload

    natural_holdout = _prepare_holdout(df_test_natural, "natural")
    balanced_holdout = _prepare_holdout(df_test_balanced, "balanced")
    holdout_available = bool(natural_holdout.get("available") or balanced_holdout.get("available"))

    if not natural_holdout.get("available"):
        warnings.append(f"Natural holdout unavailable: {natural_holdout.get('reason')}")
    if not balanced_holdout.get("available"):
        warnings.append(f"Balanced holdout unavailable: {balanced_holdout.get('reason')}")

    # Backward-compatible aliases: old report code expects test_sample_info/y_test.
    df_test = df_test_natural if not df_test_natural.empty else df_test_balanced
    test_sample_info = natural_test_sample_info if natural_test_sample_info else balanced_test_sample_info
    y_test = natural_holdout.get("y") if natural_holdout.get("available") else balanced_holdout.get("y")

    min_class = int(y_train.value_counts().min())
    n_splits = min(cv_folds_default, min_class)
    if n_splits < 2:
        warnings.append(f"Not enough samples per class for CV. min_class={min_class}.")
        return _finish_without_training(
            status="skipped_insufficient_class_samples",
            skip_reason=f"Not enough samples per class for StratifiedKFold. min_class={min_class}, requested_cv_folds={cv_folds_default}.",
            extra={
                "train_sample_info": train_sample_info,
                "test_sample_info": test_sample_info,
                "prep_info": prep_all,
                "train_target_counts_loaded": prep_all.get("target_counts", {}),
            },
        )

    base_models = _build_models(seed, modeling_cfg)
    models = [m for m in models_requested if m in base_models]
    if "XGB" in models_requested and XGBClassifier is None:
        warnings.append("XGB requested but xgboost is not installed; skipped.")

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    rows: list[dict[str, Any]] = []
    prediction_summaries: list[dict[str, Any]] = []

    t0_all = time.perf_counter()

    def _subset_holdouts(selected_features: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for kind, payload in (("natural", natural_holdout), ("balanced", balanced_holdout)):
            if not payload.get("available"):
                continue
            X_payload = payload.get("X")
            y_payload = payload.get("y")
            if X_payload is None or y_payload is None:
                continue
            cols = [f for f in selected_features if f in X_payload.columns]
            if not cols:
                continue
            out[kind] = {
                "X": X_payload[cols].copy(),
                "y": y_payload,
                "rows": int(len(X_payload)),
                "target_counts": payload.get("target_counts", {}),
            }
        return out

    for method in methods:
        selected = _method_features(feature_sets, method)
        selected = [f for f in selected if f in X_all.columns and not _is_forbidden_feature(f, target_col)]

        if method in {"MI", "RFE"}:
            if not selected:
                warnings.append(f"{method} skipped because no selected feature exists in train columns.")
                continue

            X_method = X_all[selected].copy()
            method_holdouts = _subset_holdouts(selected)
            n_comp = pca_default_n

        elif method == "PCA":
            selected = selected or list(X_all.columns)
            selected = [f for f in selected if f in X_all.columns]
            if len(selected) < 2:
                warnings.append(f"PCA skipped because usable feature count < 2. features={len(selected)}")
                continue

            max_components = min(pca_default_n, len(selected), max(1, len(X_all) - 1))
            if max_components < 2:
                warnings.append(f"PCA skipped because n_components < 2 after sample/feature constraints. n_components={max_components}")
                continue

            X_method = X_all[selected].copy()
            method_holdouts = _subset_holdouts(selected)
            n_comp = int(max_components)
        else:
            warnings.append(f"Unknown method skipped: {method}")
            continue

        print(f"Method={method} | features={X_method.shape[1]:,} | pca_n={n_comp if method == 'PCA' else '-'}")

        for model_name in models:
            print(f"  -> {method}/{model_name}")
            t_job = time.perf_counter()

            metrics_by_fold: list[dict[str, float]] = []

            for fold_idx, (train_idx, valid_idx) in enumerate(cv.split(X_method, y_train), start=1):
                estimator = _make_estimator(method, model_name, base_models, n_comp, seed)
                fold_metrics = _eval_once(
                    estimator,
                    X_method.iloc[train_idx],
                    y_train.iloc[train_idx],
                    X_method.iloc[valid_idx],
                    y_train.iloc[valid_idx],
                    thread_limit=thread_limit,
                )
                metrics_by_fold.append(fold_metrics)
                print(
                    f"    fold {fold_idx}/{n_splits}: "
                    f"acc={fold_metrics['accuracy']:.4f} "
                    f"f1={fold_metrics['f1_attack']:.4f} "
                    f"auc={fold_metrics['auc']:.4f}"
                )

            row: dict[str, Any] = {
                "App": app,
                "Method": method,
                "Model": model_name,
                "cv_folds": int(n_splits),
                "train_rows": int(len(X_method)),
                "train_features": int(X_method.shape[1]),
                "elapsed_seconds": float(time.perf_counter() - t_job),
            }

            for metric in ("accuracy", "precision_attack", "recall_attack", "f1_attack", "auc"):
                values = [float(m[metric]) for m in metrics_by_fold]
                mean, std = _mean_std(values)
                row[metric] = mean
                row[f"{metric}_std"] = std

            model_path = None

            if holdout_available and method_holdouts:
                final_estimator = _make_estimator(method, model_name, base_models, n_comp, seed)
                with _limit_threads(thread_limit):
                    final_estimator.fit(X_method, y_train)

                primary_metrics: Optional[dict[str, float]] = None
                primary_kind: Optional[str] = None

                for holdout_kind in ("natural", "balanced"):
                    payload = method_holdouts.get(holdout_kind)
                    if not payload:
                        continue
                    X_h = payload["X"]
                    y_h = payload["y"]

                    try:
                        holdout_metrics, y_pred_holdout, y_score_holdout = _eval_fitted(
                            final_estimator,
                            X_h,
                            y_h,
                            thread_limit=thread_limit,
                        )
                    except Exception as exc:
                        warnings.append(f"{holdout_kind.title()} holdout evaluation failed for {method}/{model_name}: {exc!r}")
                        continue

                    prefix_metric = f"{holdout_kind}_holdout"
                    row.update({
                        f"{prefix_metric}_accuracy": float(holdout_metrics["accuracy"]),
                        f"{prefix_metric}_precision_attack": float(holdout_metrics["precision_attack"]),
                        f"{prefix_metric}_recall_attack": float(holdout_metrics["recall_attack"]),
                        f"{prefix_metric}_f1_attack": float(holdout_metrics["f1_attack"]),
                        f"{prefix_metric}_auc": float(holdout_metrics["auc"]),
                        f"{holdout_kind}_test_rows": int(len(X_h)),
                    })

                    # Backward-compatible holdout_* columns map to the primary available holdout:
                    # natural first, balanced fallback.
                    if primary_metrics is None:
                        primary_metrics = holdout_metrics
                        primary_kind = holdout_kind
                        row.update({
                            "holdout_kind": holdout_kind,
                            "holdout_accuracy": float(holdout_metrics["accuracy"]),
                            "holdout_precision_attack": float(holdout_metrics["precision_attack"]),
                            "holdout_recall_attack": float(holdout_metrics["recall_attack"]),
                            "holdout_f1_attack": float(holdout_metrics["f1_attack"]),
                            "holdout_auc": float(holdout_metrics["auc"]),
                            "test_rows": int(len(X_h)),
                        })

                    try:
                        pred_summary = _prediction_summary(
                            method=method,
                            model_name=model_name,
                            y_true=y_h,
                            y_pred=y_pred_holdout,
                            y_score=y_score_holdout,
                            holdout_kind=holdout_kind,
                        )
                        pred_summary.update({
                            "holdout_accuracy": float(holdout_metrics["accuracy"]),
                            "holdout_precision_attack": float(holdout_metrics["precision_attack"]),
                            "holdout_recall_attack": float(holdout_metrics["recall_attack"]),
                            "holdout_f1_attack": float(holdout_metrics["f1_attack"]),
                            "holdout_auc": float(holdout_metrics["auc"]),
                            "test_rows": int(len(X_h)),
                        })
                        prediction_summaries.append(pred_summary)
                    except Exception as exc:
                        warnings.append(f"Prediction summary failed for {method}/{model_name}/{holdout_kind}: {exc!r}")

                if save_models and joblib is not None and primary_metrics is not None:
                    model_dir = phase_dir / "models"
                    model_dir.mkdir(parents=True, exist_ok=True)
                    model_path = model_dir / f"{app}_{method}_{model_name}.joblib"
                    try:
                        joblib.dump(final_estimator, model_path)
                    except Exception as exc:
                        warnings.append(f"Failed to save model {method}/{model_name}: {exc!r}")
                        model_path = None

            if model_path is not None:
                row["model_checkpoint"] = str(model_path)

            rows.append(row)

    if rows:
        fieldnames: list[str] = []
        for row in rows:
            for k in row:
                if k not in fieldnames:
                    fieldnames.append(k)

        _write_csv(results_path, rows, fieldnames)
        _write_csv(results_alias, rows, fieldnames)

        # Per-model summary aliases for report generator compatibility.
        for model_name in models:
            model_rows = [r for r in rows if r.get("Model") == model_name]
            if not model_rows:
                continue
            model_payload = {
                "phase": 13,
                "app": app,
                "model": model_name,
                "generated_at": now_iso(),
                "results_rows": len(model_rows),
                "results": model_rows,
            }
            write_json(model_payload, phase_dir / f"{prefix}_{model_name}_summary.json")
    else:
        _write_csv(results_path, [], ["App", "Method", "Model"])
        _write_csv(results_alias, [], ["App", "Method", "Model"])

    best = _choose_best(rows)
    warnings.extend(_quality_warnings(rows, prep_all.get("forbidden_removed", [])))

    prediction_summary_path = phase_dir / f"{prefix}_holdout_prediction_summary.json"
    prediction_summary_alias = phase_dir / "holdout_prediction_summary.json"

    prediction_summary_payload = {
        "phase": 13,
        "app": app,
        "created_at": now_iso(),
        "target_column": target_col,
        "status": "completed" if prediction_summaries else "not_available",
        "reason": None if prediction_summaries else "Holdout was unavailable or prediction summary generation failed.",
        "items": prediction_summaries,
    }
    write_json(prediction_summary_payload, prediction_summary_path)
    write_json(prediction_summary_payload, prediction_summary_alias)

    summary = {
        "phase": 13,
        "title": "Model Training",
        "status": "completed" if rows else "completed_with_warning",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),
        "mode": "balanced_train_dual_holdout_samples",

        "input": {
            "train_path": str(train_path),
            "test_path": str(test_path) if test_path else None,
            "train_size_bytes": int(file_size_bytes(train_path)) if train_path else 0,
            "test_size_bytes": int(file_size_bytes(test_path)) if test_path and test_path.exists() else 0,
            "phase11_modeling_manifest": str(phase11_manifest_path),
            "phase12_feature_sets": str(feature_sets_path) if feature_sets_path else None,
        },

        "read_policy": {
            "raw_jsonl_reread": False,
            "full_train_loaded": False,
            "full_test_loaded": False,
            "selected_dataset_written": False,
            "source": "Phase 8 train/test bounded samples + Phase 12 selected features",
        },

        "target_column": target_col,
        "sampling_policy": {
            "train_strategy": train_sampling_strategy,
            "train_rows_requested": int(train_rows),
            "train_per_class_rows_requested": int(train_per_class_rows),
            "primary_holdout": "natural",
            "natural_test_min_rows_requested": int(natural_test_min_rows),
            "natural_test_max_rows_requested": int(natural_test_max_rows),
            "secondary_holdout": "balanced",
            "balanced_test_rows_requested": int(balanced_test_rows),
            "balanced_test_per_class_rows_requested": int(balanced_test_per_class_rows),
        },
        "phase12_diagnostics": phase12_diagnostics,
        "phase8_label_diagnostics": phase8_label_diagnostics,
        "train_sample_info": train_sample_info,
        "test_sample_info": test_sample_info,
        "natural_test_sample_info": natural_test_sample_info,
        "balanced_test_sample_info": balanced_test_sample_info,
        "prep_info": prep_all,
        "train_rows_loaded": int(len(df_train)),
        "test_rows_loaded": int(len(df_test)),
        "natural_test_rows_loaded": int(len(df_test_natural)),
        "balanced_test_rows_loaded": int(len(df_test_balanced)),
        "train_target_counts_loaded": prep_all.get("target_counts", {}),
        "test_target_counts_loaded": (
            {str(k): int(v) for k, v in y_test.value_counts(dropna=False).sort_index().to_dict().items()}
            if y_test is not None else {}
        ),
        "natural_test_target_counts_loaded": natural_holdout.get("target_counts", {}),
        "balanced_test_target_counts_loaded": balanced_holdout.get("target_counts", {}),

        "methods": methods,
        "models": models,
        "cv_folds": int(n_splits),
        "holdout_available": bool(holdout_available),
        "natural_holdout_available": bool(natural_holdout.get("available")),
        "balanced_holdout_available": bool(balanced_holdout.get("available")),
        "primary_holdout_kind": "natural" if natural_holdout.get("available") else ("balanced" if balanced_holdout.get("available") else None),
        "results_rows": int(len(rows)),
        "prediction_summary_rows": int(len(prediction_summaries)),
        "results_table": rows,
        "best_by_preferred_metric": best,

        "training_quality_warnings": warnings,
        "strict_leakage_guard": True,
        "xgb_available": bool(XGBClassifier is not None),
        "logical_cpu": int(_LOGICAL_CPU),
        "worker_threads": int(_WORKER_THREADS),
        "inner_threads": int(_INNER_THREADS),

        "output": {
            "results_comparison": str(results_path),
            "holdout_prediction_summary": str(prediction_summary_path),
            "summary": str(summary_path),
        },

        "seconds": float(time.perf_counter() - t0_all),
        "note": (
            "Phase 13 trains models using a large balanced training sample, then evaluates on "
            "natural-distribution holdout as the primary test and balanced holdout as a secondary "
            "class-separability test. The full train/test files remain generated in Phase 8."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 13 - Model Training")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Train Sample       : {len(df_train):,}")
    print(f"Natural Test Sample: {len(df_test_natural):,}")
    print(f"Balanced Test Samp.: {len(df_test_balanced):,}")
    print(f"Results Rows: {len(rows):,}")
    print(f"Best        : {best}")
    print(f"Output      : {summary_path}")
    if warnings:
        print(f"Warnings    : {len(warnings)}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase13_run = run_phase13
phase13_train = run_phase13
phase13_train_and_evaluate = run_phase13
