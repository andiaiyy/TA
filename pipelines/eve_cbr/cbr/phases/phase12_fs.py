from __future__ import annotations

"""
Phase 12 - Feature Selection

Purpose:
- Do NOT read raw eve_<app>.jsonl.
- Do NOT read the full train/test dataset.
- Do NOT create a selected-feature dataset copy.
- Read only a bounded sample from Phase 8 train output.
- Use Phase 11 modeling_manifest/modeling_features.txt as the no-leak feature contract.
- Run feature selection on train only:
    1. Mutual Information
    2. RFE / RandomForest importance fallback
    3. PCA metadata
- Write small feature-selection artifacts only.

Input:
    phase11/modeling_manifest.json
    phase11/modeling_features.txt
    phase8/train.csv or train.csv.gz/jsonl/jsonl.gz

Output:
    phase12_<app>_mi_ranking.csv
    phase12_<app>_rfe_ranking.csv
    phase12_<app>_feature_sets.json
    phase12_<app>_selected_features.json
    phase12_<app>_pca_meta.json
    phase12_<app>_summary.json

Generic aliases:
    mi_ranking.csv
    rfe_ranking.csv
    feature_sets.json
    selected_features.json
    pca_meta.json
    summary.json
"""

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
import csv
import gzip
import json
import math
import random

import numpy as np
import pandas as pd

from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import RFE, f_classif, mutual_info_classif
from sklearn.preprocessing import StandardScaler

from ..io_utils import file_size_bytes, file_size_gib, now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Conservative final feature-selection guard
# ============================================================

DEFAULT_FORBIDDEN_FEATURES = {
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


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_lines(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(x) for x in lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _is_forbidden_feature(name: Any, target_col: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return True

    if n == target_col:
        return True

    low = n.lower()
    exact = {x.lower() for x in DEFAULT_FORBIDDEN_FEATURES}
    if low in exact:
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


def _target_col_from_manifest(manifest: dict[str, Any]) -> str:
    return str(manifest.get("target_column") or "Target_refined")


def _train_path_from_manifest(manifest: dict[str, Any], phase8_dir: Path) -> Optional[Path]:
    ds = manifest.get("dataset_files")
    if isinstance(ds, dict):
        tr = ds.get("train")
        if isinstance(tr, dict) and tr.get("path"):
            return Path(str(tr["path"]))
        if isinstance(tr, str) and tr:
            return Path(tr)

    nxt = manifest.get("next_phase_contract")
    if isinstance(nxt, dict) and nxt.get("phase12_should_use_train_file"):
        return Path(str(nxt["phase12_should_use_train_file"]))

    split = manifest.get("split")
    if isinstance(split, dict) and split.get("train_path"):
        return Path(str(split["train_path"]))

    export_summary = _read_optional_json(phase8_dir / "export_summary.json")
    if export_summary.get("train_path"):
        return Path(str(export_summary["train_path"]))

    split_summary = _read_optional_json(phase8_dir / "split_summary.json")
    if split_summary.get("train_path"):
        return Path(str(split_summary["train_path"]))

    # Fallback common names.
    for name in ("train.csv", "train.csv.gz", "train.jsonl", "train.jsonl.gz"):
        p = phase8_dir / name
        if p.exists():
            return p

    return None


def _feature_list_from_sources(
    *,
    phase11_dir: Path,
    phase10_dir: Path,
    target_col: str,
) -> tuple[list[str], dict[str, Any]]:
    sources: dict[str, Any] = {}

    phase11_txt = phase11_dir / "modeling_features.txt"
    features = _read_lines(phase11_txt)
    if features:
        sources["source"] = str(phase11_txt)
        clean = [f for f in features if not _is_forbidden_feature(f, target_col)]
        sources["removed_by_guard"] = [f for f in features if f not in clean]
        return _unique_keep_order(clean), sources

    phase10_json = _read_optional_json(phase10_dir / "features_for_modeling.json")
    for key in ("approved_numeric_features", "approved_features", "modeling_features", "features"):
        value = phase10_json.get(key)
        if isinstance(value, list) and value:
            features = [str(x) for x in value if str(x).strip()]
            clean = [f for f in features if not _is_forbidden_feature(f, target_col)]
            sources["source"] = str(phase10_dir / "features_for_modeling.json")
            sources["removed_by_guard"] = [f for f in features if f not in clean]
            return _unique_keep_order(clean), sources

    ranked = phase10_json.get("ranked_by_abs_correlation_noleak")
    if isinstance(ranked, list) and ranked:
        features = [str(x) for x in ranked if str(x).strip()]
        clean = [f for f in features if not _is_forbidden_feature(f, target_col)]
        sources["source"] = str(phase10_dir / "features_for_modeling.json:ranked_by_abs_correlation_noleak")
        sources["removed_by_guard"] = [f for f in features if f not in clean]
        return _unique_keep_order(clean), sources

    corr_path = phase10_dir / "corr_NOLEAK.csv"
    features = []
    if corr_path.exists():
        try:
            df_corr = pd.read_csv(corr_path)
            if "Feature" in df_corr.columns:
                features = df_corr["Feature"].astype(str).tolist()
        except Exception:
            features = []

    clean = [f for f in features if not _is_forbidden_feature(f, target_col)]
    sources["source"] = str(corr_path) if features else None
    sources["removed_by_guard"] = [f for f in features if f not in clean]
    return _unique_keep_order(clean), sources


def _compression_for_path(path: Path) -> Optional[str]:
    suffixes = "".join(path.suffixes).lower()
    return "gzip" if suffixes.endswith(".gz") else None


def _is_jsonl(path: Path) -> bool:
    suffixes = "".join(path.suffixes).lower()
    return ".jsonl" in suffixes or suffixes.endswith(".ndjson") or suffixes.endswith(".ndjson.gz")


def _read_header_columns_csv(path: Path) -> list[str]:
    try:
        compression = _compression_for_path(path)
        df = pd.read_csv(path, nrows=0, compression=compression)
        return [str(c) for c in df.columns]
    except Exception:
        return []


def _iter_train_chunks(
    path: Path,
    *,
    wanted_cols: list[str],
    chunksize: int,
) -> Iterable[pd.DataFrame]:
    chunksize = max(1_000, int(chunksize))
    wanted = set(str(x) for x in wanted_cols if str(x).strip())

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

    # For CSV, use usecols to avoid loading all columns.
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
        # Fallback without usecols if a parser complains.
        try:
            reader = pd.read_csv(path, chunksize=chunksize, compression=compression)
            for chunk in reader:
                cols = [c for c in chunk.columns if str(c) in wanted]
                if cols:
                    yield chunk[cols].copy()
        except Exception:
            return


class _StratifiedReservoir:
    """
    Class-aware streaming reservoir for Phase 12.

    Default policy is balanced quota:
        total 500k rows = 250k benign + 250k attack

    The class quota is explicit so the summary can honestly report:
        requested per class, seen per class, kept per class, and shortfall.
    """
    def __init__(
        self,
        k: int,
        seed: int,
        *,
        per_class_rows: Optional[int] = None,
        sampling_strategy: str = "balanced",
    ) -> None:
        self.k = max(0, int(k))
        self.seed = int(seed)
        self.rng = random.Random(int(seed))
        self.sampling_strategy = str(sampling_strategy or "balanced").strip().lower()

        if self.sampling_strategy not in {"balanced", "stratified", "natural"}:
            self.sampling_strategy = "balanced"

        if self.sampling_strategy in {"balanced", "stratified"}:
            if per_class_rows is None or int(per_class_rows) <= 0:
                per = max(1, self.k // 2)
            else:
                per = max(1, int(per_class_rows))
            self.class_limits: dict[int, int] = {0: per, 1: per}
            self.effective_total_limit = max(self.k, per * 2)
        else:
            # Natural mode is retained for future compatibility, but Phase 12
            # serious-run policy should use balanced.
            self.class_limits = {0: self.k, 1: self.k}
            self.effective_total_limit = self.k

        self.rows_by_class: dict[int, list[pd.DataFrame]] = {0: [], 1: []}
        self.count_seen: Counter = Counter()
        self.count_kept: Counter = Counter()

    def add_chunk(self, df: pd.DataFrame, target_col: str) -> None:
        if self.effective_total_limit <= 0 or df.empty or target_col not in df.columns:
            return

        y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
        y = (y == 1).astype(int)

        for cls in (0, 1):
            sub = df.loc[y == cls]
            if sub.empty:
                continue

            self.count_seen[cls] += int(len(sub))
            limit = max(1, int(self.class_limits.get(cls, self.k)))

            current = pd.concat(self.rows_by_class[cls], ignore_index=True) if self.rows_by_class[cls] else pd.DataFrame()
            combined = pd.concat([current, sub], ignore_index=True)

            if len(combined) > limit:
                combined = combined.sample(
                    n=limit,
                    random_state=self.seed + cls + int(self.count_seen[cls]),
                ).reset_index(drop=True)

            self.rows_by_class[cls] = [combined]
            self.count_kept[cls] = int(len(combined))

    def dataframe(self) -> pd.DataFrame:
        parts = []
        for cls in (0, 1):
            if self.rows_by_class[cls]:
                parts.append(pd.concat(self.rows_by_class[cls], ignore_index=True))
        if not parts:
            return pd.DataFrame()

        out = pd.concat(parts, ignore_index=True)

        # For balanced/stratified mode, keep per-class quotas. For natural mode,
        # cap the combined output to k.
        if self.sampling_strategy == "natural" and len(out) > self.k:
            out = out.sample(n=self.k, random_state=self.seed).reset_index(drop=True)
        else:
            out = out.sample(frac=1.0, random_state=self.seed).reset_index(drop=True)
        return out

    def info(self) -> dict[str, Any]:
        requested = {str(k): int(v) for k, v in self.class_limits.items()}
        seen = {str(k): int(v) for k, v in self.count_seen.items()}
        kept = {str(k): int(v) for k, v in self.count_kept.items()}
        shortfall = {
            str(cls): max(0, int(self.class_limits.get(cls, 0)) - int(self.count_kept.get(cls, 0)))
            for cls in (0, 1)
        }
        quota_satisfied = {
            str(cls): int(self.count_kept.get(cls, 0)) >= int(self.class_limits.get(cls, 0))
            for cls in (0, 1)
        }
        return {
            "sampling_strategy": self.sampling_strategy,
            "requested_total_rows": int(self.effective_total_limit),
            "requested_per_class_rows": int(self.class_limits.get(0, 0)),
            "requested_by_class": requested,
            "sample_seen_by_class": seen,
            "sample_kept_by_class": kept,
            "sample_shortfall_by_class": shortfall,
            "quota_satisfied_by_class": quota_satisfied,
        }


def _collect_train_sample(
    *,
    train_path: Path,
    target_col: str,
    modeling_features: list[str],
    sample_rows: int,
    per_class_rows: Optional[int],
    sampling_strategy: str,
    chunksize: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    wanted = _unique_keep_order([target_col, *modeling_features])

    sampler = _StratifiedReservoir(
        sample_rows,
        seed,
        per_class_rows=per_class_rows,
        sampling_strategy=sampling_strategy,
    )
    rows_scanned = 0
    chunks_read = 0

    for chunk in _iter_train_chunks(train_path, wanted_cols=wanted, chunksize=chunksize):
        chunks_read += 1
        if chunk.empty or target_col not in chunk.columns:
            continue

        rows_scanned += int(len(chunk))
        sampler.add_chunk(chunk, target_col)

    df = sampler.dataframe()

    info = {
        "rows_scanned_from_train": int(rows_scanned),
        "chunks_read": int(chunks_read),
        "sample_rows": int(len(df)),
        **sampler.info(),
    }
    return df, info


def _write_sample_class_summary(path: Path, alias: Path, sample_info: dict[str, Any]) -> list[dict[str, Any]]:
    requested = sample_info.get("requested_by_class") if isinstance(sample_info.get("requested_by_class"), dict) else {}
    seen = sample_info.get("sample_seen_by_class") if isinstance(sample_info.get("sample_seen_by_class"), dict) else {}
    kept = sample_info.get("sample_kept_by_class") if isinstance(sample_info.get("sample_kept_by_class"), dict) else {}
    shortfall = sample_info.get("sample_shortfall_by_class") if isinstance(sample_info.get("sample_shortfall_by_class"), dict) else {}
    satisfied = sample_info.get("quota_satisfied_by_class") if isinstance(sample_info.get("quota_satisfied_by_class"), dict) else {}

    rows: list[dict[str, Any]] = []
    for cls, label in (("0", "benign"), ("1", "attack")):
        rows.append({
            "class": cls,
            "label": label,
            "requested_rows": _safe_int(requested.get(cls), 0),
            "seen_rows": _safe_int(seen.get(cls), 0),
            "kept_rows": _safe_int(kept.get(cls), 0),
            "shortfall_rows": _safe_int(shortfall.get(cls), 0),
            "quota_satisfied": bool(satisfied.get(cls, False)),
        })

    rows.append({
        "class": "total",
        "label": "total",
        "requested_rows": _safe_int(sample_info.get("requested_total_rows"), 0),
        "seen_rows": sum(_safe_int(seen.get(cls), 0) for cls in ("0", "1")),
        "kept_rows": _safe_int(sample_info.get("sample_rows"), 0),
        "shortfall_rows": sum(_safe_int(shortfall.get(cls), 0) for cls in ("0", "1")),
        "quota_satisfied": all(bool(satisfied.get(cls, False)) for cls in ("0", "1")),
    })

    fieldnames = ["class", "label", "requested_rows", "seen_rows", "kept_rows", "shortfall_rows", "quota_satisfied"]
    _write_csv(path, rows, fieldnames)
    _write_csv(alias, rows, fieldnames)
    return rows


def _count_text_lines(path: Path) -> Optional[int]:
    try:
        if not path.exists() or not path.is_file():
            return None
        opener = gzip.open if "".join(path.suffixes).lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="ignore", newline="") as f:
            return sum(1 for _ in f)
    except Exception:
        return None


def _small_file_entry(path: Path, *, data_rows: Optional[int] = None) -> dict[str, Any]:
    return {
        "path": str(path),
        "physical_lines": _count_text_lines(path),
        "data_rows": None if data_rows is None else int(data_rows),
        "size_bytes": int(file_size_bytes(path)),
        "line_count_method": "small_file_line_count",
    }


def _prepare_X_y(
    df_sample: pd.DataFrame,
    *,
    target_col: str,
    modeling_features: list[str],
) -> tuple[pd.DataFrame, pd.Series, dict[str, Any]]:
    if df_sample.empty:
        raise RuntimeError("Feature selection sample is empty.")

    if target_col not in df_sample.columns:
        raise RuntimeError(f"Target column missing from FS sample: {target_col}")

    y = pd.to_numeric(df_sample[target_col], errors="coerce").fillna(0).astype(int)
    y = (y == 1).astype(np.int8)

    available = [f for f in modeling_features if f in df_sample.columns and not _is_forbidden_feature(f, target_col)]

    X_raw = df_sample[available].copy() if available else pd.DataFrame(index=df_sample.index)
    X = pd.DataFrame(index=df_sample.index)

    non_numeric_dropped: list[str] = []
    constant_dropped: list[str] = []

    for col in X_raw.columns:
        s = pd.to_numeric(X_raw[col], errors="coerce")
        numeric_ratio = float(s.notna().mean()) if len(s) else 0.0
        if numeric_ratio <= 0.0:
            non_numeric_dropped.append(col)
            continue

        s = s.replace([np.inf, -np.inf], np.nan).fillna(0)
        if s.nunique(dropna=True) <= 1:
            constant_dropped.append(col)
            continue

        X[col] = s.astype(np.float32)

    if X.empty:
        raise RuntimeError("No usable numeric no-leak feature remains for Phase 12.")

    target_counts = {str(k): int(v) for k, v in y.value_counts(dropna=False).sort_index().to_dict().items()}
    if y.nunique(dropna=True) < 2:
        raise RuntimeError(f"Target has one class in Phase 12 sample: {target_counts}")

    prep_info = {
        "modeling_features_requested": int(len(modeling_features)),
        "modeling_features_available_in_sample": int(len(available)),
        "numeric_features_used": int(X.shape[1]),
        "non_numeric_dropped": non_numeric_dropped,
        "constant_dropped": constant_dropped,
        "target_counts_sample": target_counts,
    }
    return X, y, prep_info


def _safe_mutual_info(X: pd.DataFrame, y: pd.Series, seed: int, max_rows: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Fast and safe MI ranking.

    Important fix:
    - Do not call mutual_info_classif(..., n_jobs=-1).
    - Bound MI rows aggressively.
    - If rows × features is too large, use fast ANOVA F-score fallback.

    Reason:
    mutual_info_classif can become extremely slow on large samples. Phase 12 is
    feature-selection evidence only, so a bounded/fallback ranking is safer than
    freezing the whole pipeline.
    """
    max_mi_rows = min(max(1, int(max_rows)), 50_000)
    n = min(len(X), max_mi_rows)

    if len(X) > n:
        sample_idx = np.random.default_rng(seed).choice(len(X), size=n, replace=False)
        X_fit = X.iloc[sample_idx].reset_index(drop=True)
        y_fit = y.iloc[sample_idx].reset_index(drop=True)
    else:
        X_fit = X.reset_index(drop=True)
        y_fit = y.reset_index(drop=True)

    # If still too large, avoid MI and use fast univariate F-score.
    work_units = int(X_fit.shape[0]) * int(X_fit.shape[1])
    fast_fallback_threshold = 1_500_000

    def _anova_fallback(reason: str, error: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
        try:
            scores, _p = f_classif(X_fit.values, y_fit.values)
            scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
            df_f = (
                pd.DataFrame({"Feature": X.columns.astype(str), "MI_Score": scores})
                .sort_values("MI_Score", ascending=False)
                .reset_index(drop=True)
            )
            info_f = {
                "method": "anova_f_score_fallback",
                "status": "fallback",
                "reason": reason,
                "rows_used": int(len(X_fit)),
                "features_used": int(X_fit.shape[1]),
                "work_units": int(work_units),
            }
            if error:
                info_f["error"] = error
            return df_f, info_f
        except Exception as exc2:
            var = X.var().sort_values(ascending=False)
            df_v = pd.DataFrame({"Feature": var.index.astype(str), "MI_Score": var.values}).reset_index(drop=True)
            info_v = {
                "method": "variance_fallback",
                "status": "fallback",
                "reason": reason,
                "error": error or repr(exc2),
                "rows_used": int(len(X)),
                "features_used": int(X.shape[1]),
            }
            return df_v, info_v

    if work_units > fast_fallback_threshold:
        return _anova_fallback("mi_work_units_too_large")

    try:
        # No n_jobs argument: older sklearn versions do not support it and some
        # environments hang with unrestricted parallelism.
        scores = mutual_info_classif(X_fit.values, y_fit.values, random_state=seed)
        scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)

        df = (
            pd.DataFrame({"Feature": X.columns.astype(str), "MI_Score": scores})
            .sort_values("MI_Score", ascending=False)
            .reset_index(drop=True)
        )
        info = {
            "method": "mutual_information",
            "status": "ok",
            "rows_used": int(len(X_fit)),
            "features_used": int(X_fit.shape[1]),
            "work_units": int(work_units),
            "max_mi_rows": int(max_mi_rows),
        }
    except Exception as exc:
        return _anova_fallback("mutual_information_failed", repr(exc))

    return df, info


def _safe_rfe(X: pd.DataFrame, y: pd.Series, seed: int, top_k: int, max_rows: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    n = min(len(X), max(1, int(max_rows)))
    if len(X) > n:
        sample_idx = np.random.default_rng(seed + 17).choice(len(X), size=n, replace=False)
        X_fit = X.iloc[sample_idx].reset_index(drop=True)
        y_fit = y.iloc[sample_idx].reset_index(drop=True)
    else:
        X_fit = X.reset_index(drop=True)
        y_fit = y.reset_index(drop=True)

    n_select = min(int(top_k), X.shape[1])

    try:
        base = RandomForestClassifier(
            n_estimators=80,
            random_state=seed,
            n_jobs=-1,
            class_weight="balanced_subsample",
        )
        step = max(1, min(5, X.shape[1] // 10))
        rfe = RFE(base, n_features_to_select=n_select, step=step)
        rfe.fit(X_fit, y_fit)

        df = (
            pd.DataFrame({
                "Feature": X.columns.astype(str),
                "RFE_Ranking": rfe.ranking_,
                "Selected": rfe.support_.astype(bool),
            })
            .sort_values(["RFE_Ranking", "Feature"], ascending=[True, True])
            .reset_index(drop=True)
        )
        info = {"method": "rfe_random_forest", "status": "ok", "rows_used": int(len(X_fit)), "step": int(step)}
    except Exception as exc:
        rf = RandomForestClassifier(
            n_estimators=120,
            random_state=seed,
            n_jobs=-1,
            class_weight="balanced_subsample",
        )
        take = min(len(X_fit), 50_000)
        rf.fit(X_fit.head(take), y_fit.head(take))
        imp = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
        df = pd.DataFrame({"Feature": imp.index.astype(str), "Importance": imp.values}).reset_index(drop=True)
        info = {"method": "rf_importance_fallback", "status": "fallback", "error": repr(exc), "rows_used": int(take)}

    return df, info


def _safe_pca(X: pd.DataFrame, seed: int, top_k: int, max_rows: int) -> tuple[dict[str, Any], Optional[StandardScaler], Optional[PCA]]:
    n = min(len(X), max(1, int(max_rows)))
    if len(X) > n:
        sample_idx = np.random.default_rng(seed + 29).choice(len(X), size=n, replace=False)
        X_fit = X.iloc[sample_idx].reset_index(drop=True)
    else:
        X_fit = X.reset_index(drop=True)

    n_components = min(int(top_k), X.shape[1], len(X_fit))
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_fit.values)

    pca = PCA(n_components=n_components, random_state=seed)
    pca.fit(X_scaled)

    evr = [float(x) for x in pca.explained_variance_ratio_]
    cumsum = np.cumsum(evr).tolist()

    meta = {
        "n_components": int(n_components),
        "fit_rows": int(len(X_fit)),
        "feature_columns": [str(c) for c in X.columns],
        "explained_variance_ratio": evr,
        "cumulative_variance_by_component": [float(x) for x in cumsum],
        "cumulative_variance": float(cumsum[-1]) if cumsum else 0.0,
    }
    return meta, scaler, pca


def _selected_from_mi(mi_df: pd.DataFrame, top_k: int) -> list[str]:
    if mi_df.empty or "Feature" not in mi_df.columns:
        return []
    return mi_df.head(int(top_k))["Feature"].astype(str).tolist()


def _selected_from_rfe(rfe_df: pd.DataFrame, top_k: int) -> list[str]:
    if rfe_df.empty or "Feature" not in rfe_df.columns:
        return []
    if "Selected" in rfe_df.columns:
        selected = rfe_df.loc[rfe_df["Selected"].astype(bool), "Feature"].astype(str).tolist()
        if selected:
            return selected[: int(top_k)]
    return rfe_df.head(int(top_k))["Feature"].astype(str).tolist()


def _sample_target_counts(df: pd.DataFrame, target_col: str) -> dict[str, int]:
    if df.empty or target_col not in df.columns:
        return {}
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    y = (y == 1).astype(int)
    return {str(k): int(v) for k, v in y.value_counts(dropna=False).sort_index().to_dict().items()}


def _phase8_label_diagnostics(phase8_dir: Path) -> dict[str, Any]:
    """Read Phase 8 summaries without touching train/test data."""
    export_summary = _read_optional_json(phase8_dir / "export_summary.json")
    split_summary = _read_optional_json(phase8_dir / "split_summary.json")

    return {
        "phase8_export_summary": str(phase8_dir / "export_summary.json"),
        "phase8_split_summary": str(phase8_dir / "split_summary.json"),
        "target_counts": export_summary.get("target_counts", {}),
        "target_alert_counts": export_summary.get("target_alert_counts", {}),
        "label_source_counts": export_summary.get("label_source_counts", {}),
        "train_target_counts": export_summary.get("train_target_counts") or split_summary.get("train_target_counts", {}),
        "test_target_counts": export_summary.get("test_target_counts") or split_summary.get("test_target_counts", {}),
        "target_counts_by_split": export_summary.get("target_counts_by_split") or split_summary.get("target_counts_by_split", {}),
        "alert_policy_counts": export_summary.get("alert_policy_counts", {}),
        "split_warnings": export_summary.get("split_warnings") or split_summary.get("split_warnings", []),
    }


def _empty_feature_sets() -> dict[str, Any]:
    return {
        "MI": [],
        "RFE": [],
        "PCA": {"n_components": 0, "feature_columns": []},
        "intersection_MI_RFE": [],
        "union_MI_RFE": [],
    }


def _empty_selected_features(*, app: str, target_col: str, reason: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "phase": 12,
        "app": app,
        "created_at": now_iso(),
        "target_column": target_col,
        "recommended_default": None,
        "MI": [],
        "RFE": [],
        "PCA_feature_columns": [],
        "intersection_MI_RFE": [],
        "union_MI_RFE": [],
        "status": "skipped",
        "skip_reason": reason,
        "warnings": list(warnings),
        "notes": [
            "Feature selection was skipped safely.",
            "No selected-feature dataset is written.",
            "Phase 13 should skip training for this app/method because no selected features are available.",
        ],
    }


def _write_skip_artifacts(
    *,
    app: str,
    target_col: str,
    reason: str,
    warnings: list[str],
    mi_path: Path,
    mi_alias: Path,
    rfe_path: Path,
    rfe_alias: Path,
    feature_sets_path: Path,
    feature_sets_alias: Path,
    selected_path: Path,
    selected_alias: Path,
    pca_meta_path: Path,
    pca_meta_alias: Path,
) -> dict[str, Any]:
    """Write explicit empty FS artifacts so downstream phases can skip cleanly."""
    _write_csv(mi_path, [], ["Feature", "MI_Score"])
    _write_csv(mi_alias, [], ["Feature", "MI_Score"])
    _write_csv(rfe_path, [], ["Feature", "RFE_Ranking", "Selected"])
    _write_csv(rfe_alias, [], ["Feature", "RFE_Ranking", "Selected"])

    feature_sets = _empty_feature_sets()
    selected_features = _empty_selected_features(
        app=app,
        target_col=target_col,
        reason=reason,
        warnings=warnings,
    )
    pca_meta = {
        "n_components": 0,
        "fit_rows": 0,
        "feature_columns": [],
        "explained_variance_ratio": [],
        "cumulative_variance_by_component": [],
        "cumulative_variance": 0.0,
        "status": "skipped",
        "skip_reason": reason,
    }

    write_json(feature_sets, feature_sets_path)
    write_json(feature_sets, feature_sets_alias)
    write_json(selected_features, selected_path)
    write_json(selected_features, selected_alias)
    write_json(pca_meta, pca_meta_path)
    write_json(pca_meta, pca_meta_alias)

    return {
        "mi_ranking": str(mi_path),
        "rfe_ranking": str(rfe_path),
        "feature_sets": str(feature_sets_path),
        "selected_features": str(selected_path),
        "pca_meta": str(pca_meta_path),
    }


# ============================================================
# Runner
# ============================================================

def run_phase12(
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
    phase10_dir = _phase_dir(phase_dir, "phase10")
    phase11_dir = _phase_dir(phase_dir, "phase11")

    manifest_path = phase11_dir / "modeling_manifest.json"
    modeling_features_txt = phase11_dir / "modeling_features.txt"

    manifest = _read_optional_json(manifest_path)

    target_col = _target_col_from_manifest(manifest)
    train_path = _train_path_from_manifest(manifest, phase8_dir)

    modeling_features, feature_source = _feature_list_from_sources(
        phase11_dir=phase11_dir,
        phase10_dir=phase10_dir,
        target_col=target_col,
    )

    modeling_cfg = getattr(cfg, "modeling", None)
    fs_sample_rows_config = int(getattr(modeling_cfg, "fs_sample_rows", 500_000) or 500_000)
    fs_per_class_rows = int(getattr(modeling_cfg, "fs_per_class_rows", max(1, fs_sample_rows_config // 2)) or max(1, fs_sample_rows_config // 2))
    fs_sampling_strategy = str(getattr(modeling_cfg, "fs_sampling_strategy", "balanced") or "balanced").strip().lower()
    if fs_sampling_strategy not in {"balanced", "stratified", "natural"}:
        fs_sampling_strategy = "balanced"

    fs_sample_rows_effective = int(fs_sample_rows_config)
    config_warnings: list[str] = []
    if fs_sampling_strategy in {"balanced", "stratified"}:
        required_total = int(fs_per_class_rows) * 2
        if required_total > fs_sample_rows_effective:
            config_warnings.append(
                f"fs_sample_rows={fs_sample_rows_effective:,} is smaller than 2*fs_per_class_rows={required_total:,}; "
                f"using {required_total:,} effective rows."
            )
            fs_sample_rows_effective = required_total

    mi_max_rows = int(getattr(modeling_cfg, "mi_max_rows", 50_000) or 50_000)
    rfe_max_rows = int(getattr(modeling_cfg, "rfe_max_rows", 150_000) or 150_000)
    pca_max_rows = int(getattr(modeling_cfg, "pca_max_rows", 300_000) or 300_000)
    top_k = int(getattr(modeling_cfg, "fs_top_k", 25) or 25)
    chunksize = int(getattr(modeling_cfg, "read_chunksize", 100_000) or 100_000)
    seed = int(getattr(modeling_cfg, "seed", getattr(cfg, "seed", 42)) or 42)

    prefix = f"phase12_{app}"

    mi_path = phase_dir / f"{prefix}_mi_ranking.csv"
    rfe_path = phase_dir / f"{prefix}_rfe_ranking.csv"
    feature_sets_path = phase_dir / f"{prefix}_feature_sets.json"
    selected_path = phase_dir / f"{prefix}_selected_features.json"
    pca_meta_path = phase_dir / f"{prefix}_pca_meta.json"
    sample_class_summary_path = phase_dir / f"{prefix}_sample_class_summary.csv"
    summary_path = phase_dir / f"{prefix}_summary.json"

    mi_alias = phase_dir / "mi_ranking.csv"
    rfe_alias = phase_dir / "rfe_ranking.csv"
    feature_sets_alias = phase_dir / "feature_sets.json"
    selected_alias = phase_dir / "selected_features.json"
    pca_meta_alias = phase_dir / "pca_meta.json"
    sample_class_summary_alias = phase_dir / "sample_class_summary.csv"
    summary_alias = phase_dir / "summary.json"

    print("\n" + "=" * 72)
    print("Phase 12 - Feature Selection")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {train_path}")
    print("Mode        : bounded train sample only")
    print(f"FS Policy   : {fs_sampling_strategy} | total={fs_sample_rows_effective:,} | per_class={fs_per_class_rows:,}")
    print("=" * 72)

    warnings: list[str] = list(config_warnings)

    if train_path is None or not train_path.exists():
        warnings.append("Phase 8 train file not found.")
        reason = "missing_phase8_train_file"
        output = _write_skip_artifacts(
            app=app,
            target_col=target_col,
            reason=reason,
            warnings=warnings,
            mi_path=mi_path,
            mi_alias=mi_alias,
            rfe_path=rfe_path,
            rfe_alias=rfe_alias,
            feature_sets_path=feature_sets_path,
            feature_sets_alias=feature_sets_alias,
            selected_path=selected_path,
            selected_alias=selected_alias,
            pca_meta_path=pca_meta_path,
            pca_meta_alias=pca_meta_alias,
        )
        summary = {
            "phase": 12,
            "title": "Feature Selection",
            "status": "skipped_missing_train",
            "current_run": app.upper(),
            "app": app,
            "generated_at": now_iso(),
            "warnings": warnings,
            "train_path": str(train_path) if train_path else None,
            "modeling_feature_count": int(len(modeling_features)),
            "phase8_label_diagnostics": _phase8_label_diagnostics(phase8_dir),
            "output": output,
            "note": "Phase 12 did not run because the Phase 8 train file is missing.",
        }
        write_json(summary, summary_path)
        write_json(summary, summary_alias)
        return summary

    if not modeling_features:
        warnings.append("No modeling features found from Phase 11/10.")
        reason = "empty_modeling_feature_contract"
        output = _write_skip_artifacts(
            app=app,
            target_col=target_col,
            reason=reason,
            warnings=warnings,
            mi_path=mi_path,
            mi_alias=mi_alias,
            rfe_path=rfe_path,
            rfe_alias=rfe_alias,
            feature_sets_path=feature_sets_path,
            feature_sets_alias=feature_sets_alias,
            selected_path=selected_path,
            selected_alias=selected_alias,
            pca_meta_path=pca_meta_path,
            pca_meta_alias=pca_meta_alias,
        )
        summary = {
            "phase": 12,
            "title": "Feature Selection",
            "status": "skipped_no_modeling_features",
            "current_run": app.upper(),
            "app": app,
            "generated_at": now_iso(),
            "warnings": warnings,
            "train_path": str(train_path),
            "target_column": target_col,
            "modeling_feature_count": 0,
            "feature_source": feature_source,
            "phase8_label_diagnostics": _phase8_label_diagnostics(phase8_dir),
            "output": output,
            "note": "Phase 12 did not run because the Phase 11/10 no-leak modeling feature list is empty.",
        }
        write_json(summary, summary_path)
        write_json(summary, summary_alias)
        return summary

    df_sample, sample_info = _collect_train_sample(
        train_path=train_path,
        target_col=target_col,
        modeling_features=modeling_features,
        sample_rows=fs_sample_rows_effective,
        per_class_rows=fs_per_class_rows if fs_sampling_strategy in {"balanced", "stratified"} else None,
        sampling_strategy=fs_sampling_strategy,
        chunksize=chunksize,
        seed=seed,
    )

    sample_class_summary_rows = _write_sample_class_summary(
        sample_class_summary_path,
        sample_class_summary_alias,
        sample_info,
    )

    if fs_sampling_strategy in {"balanced", "stratified"}:
        kept = sample_info.get("sample_kept_by_class") if isinstance(sample_info.get("sample_kept_by_class"), dict) else {}
        for cls, label in (("0", "benign"), ("1", "attack")):
            if _safe_int(kept.get(cls), 0) < fs_per_class_rows:
                warnings.append(
                    f"Phase 12 FS {label} quota not fully satisfied: "
                    f"requested={fs_per_class_rows:,}, kept={_safe_int(kept.get(cls), 0):,}."
                )

    try:
        X, y, prep_info = _prepare_X_y(
            df_sample,
            target_col=target_col,
            modeling_features=modeling_features,
        )
    except Exception as exc:
        err = repr(exc)
        warnings.append(err)
        target_counts_sample = _sample_target_counts(df_sample, target_col)
        one_class = "one class" in str(exc).lower() or len(target_counts_sample) < 2
        reason = "one_class_train_sample" if one_class else "sample_preparation_failed"
        output = _write_skip_artifacts(
            app=app,
            target_col=target_col,
            reason=reason,
            warnings=warnings,
            mi_path=mi_path,
            mi_alias=mi_alias,
            rfe_path=rfe_path,
            rfe_alias=rfe_alias,
            feature_sets_path=feature_sets_path,
            feature_sets_alias=feature_sets_alias,
            selected_path=selected_path,
            selected_alias=selected_alias,
            pca_meta_path=pca_meta_path,
            pca_meta_alias=pca_meta_alias,
        )
        summary = {
            "phase": 12,
            "title": "Feature Selection",
            "status": "skipped_one_class_target" if one_class else "skipped_sample_preparation_failed",
            "current_run": app.upper(),
            "app": app,
            "generated_at": now_iso(),
            "train_path": str(train_path),
            "target_column": target_col,
            "modeling_feature_count": int(len(modeling_features)),
            "feature_source": feature_source,
            "sample_info": sample_info,
            "target_counts_sample": target_counts_sample,
            "phase8_label_diagnostics": _phase8_label_diagnostics(phase8_dir),
            "warnings": warnings,
            "sample_class_summary": sample_class_summary_rows,
            "fs_sampling_policy": {
                "strategy": fs_sampling_strategy,
                "requested_total_rows_config": int(fs_sample_rows_config),
                "effective_total_rows": int(fs_sample_rows_effective),
                "requested_per_class_rows": int(fs_per_class_rows),
            },
            "output": {**output, "sample_class_summary": str(sample_class_summary_path)},
            "root_cause_hint": (
                "The train sample contains only one target class. Feature selection is supervised, "
                "so MI/RFE cannot run. Check Phase 8 target_counts/train_target_counts and the alert "
                "policy alignment with split_eve_by_app."
                if one_class
                else "Sample preparation failed before supervised feature selection could run."
            ),
            "note": "Phase 12 skipped safely and wrote explicit empty selected-feature artifacts for downstream phases.",
        }
        write_json(summary, summary_path)
        write_json(summary, summary_alias)
        return summary

    n_select = min(top_k, X.shape[1])

    mi_df, mi_info = _safe_mutual_info(X, y, seed=seed, max_rows=mi_max_rows)
    rfe_df, rfe_info = _safe_rfe(X, y, seed=seed, top_k=n_select, max_rows=rfe_max_rows)
    pca_meta, scaler, pca = _safe_pca(X, seed=seed, top_k=n_select, max_rows=pca_max_rows)

    mi_selected = _selected_from_mi(mi_df, n_select)
    rfe_selected = _selected_from_rfe(rfe_df, n_select)

    # Final guard after selection.
    mi_removed = [f for f in mi_selected if _is_forbidden_feature(f, target_col)]
    rfe_removed = [f for f in rfe_selected if _is_forbidden_feature(f, target_col)]
    mi_selected = [f for f in mi_selected if f not in mi_removed]
    rfe_selected = [f for f in rfe_selected if f not in rfe_removed]

    intersection = [f for f in mi_selected if f in set(rfe_selected)]
    union = _unique_keep_order([*mi_selected, *rfe_selected])

    feature_sets = {
        "MI": mi_selected,
        "RFE": rfe_selected,
        "PCA": {
            "n_components": int(pca_meta.get("n_components", 0)),
            "feature_columns": [str(c) for c in X.columns],
        },
        "intersection_MI_RFE": intersection,
        "union_MI_RFE": union,
    }

    selected_features = {
        "phase": 12,
        "app": app,
        "created_at": now_iso(),
        "target_column": target_col,
        "recommended_default": "MI",
        "MI": mi_selected,
        "RFE": rfe_selected,
        "PCA_feature_columns": [str(c) for c in X.columns],
        "intersection_MI_RFE": intersection,
        "union_MI_RFE": union,
        "notes": [
            "Feature selection is performed on train sample only.",
            "No selected-feature dataset is written.",
            "Phase 13 should read this file and train using one selected method at a time.",
        ],
    }

    mi_df.to_csv(mi_path, index=False)
    mi_df.to_csv(mi_alias, index=False)

    rfe_df.to_csv(rfe_path, index=False)
    rfe_df.to_csv(rfe_alias, index=False)

    write_json(feature_sets, feature_sets_path)
    write_json(feature_sets, feature_sets_alias)

    write_json(selected_features, selected_path)
    write_json(selected_features, selected_alias)

    write_json(pca_meta, pca_meta_path)
    write_json(pca_meta, pca_meta_alias)

    # Optional small model artifact. Kept local and optional; failure is harmless.
    pca_joblib_path = None
    try:
        import joblib  # type: ignore
        pca_joblib_path = phase_dir / f"{prefix}_pca_scaler.joblib"
        joblib.dump(
            {
                "pca": pca,
                "scaler": scaler,
                "feature_columns": [str(c) for c in X.columns],
                "pca_meta": pca_meta,
            },
            pca_joblib_path,
        )
    except Exception as exc:
        warnings.append(f"PCA joblib not saved: {exc!r}")

    summary = {
        "phase": 12,
        "title": "Feature Selection",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),
        "mode": "bounded_train_sample_only",

        "input": {
            "train_path": str(train_path),
            "train_file_exists": True,
            "train_file_size_bytes": int(file_size_bytes(train_path)),
            "train_file_size_gib": float(file_size_gib(train_path)),
            "phase11_modeling_manifest": str(manifest_path),
            "phase11_modeling_features": str(modeling_features_txt),
            "feature_source": feature_source,
        },

        "phase8_label_diagnostics": _phase8_label_diagnostics(phase8_dir),

        "read_policy": {
            "raw_jsonl_reread": False,
            "test_file_read": False,
            "full_train_read": False,
            "selected_dataset_written": False,
            "source": "Phase 8 train file bounded sample + Phase 11 feature contract",
        },

        "target_column": target_col,
        "fs_sampling_policy": {
            "strategy": fs_sampling_strategy,
            "requested_total_rows_config": int(fs_sample_rows_config),
            "effective_total_rows": int(fs_sample_rows_effective),
            "requested_per_class_rows": int(fs_per_class_rows),
            "source": "config.modeling.fs_sample_rows + config.modeling.fs_per_class_rows",
        },
        "sample_info": sample_info,
        "sample_class_summary": sample_class_summary_rows,
        "prep_info": prep_info,
        "fs_sample_rows": int(len(df_sample)),
        "fs_sample_rows_requested": int(fs_sample_rows_effective),
        "fs_per_class_rows_requested": int(fs_per_class_rows),
        "fs_sampling_strategy": fs_sampling_strategy,
        "numeric_features_used": int(X.shape[1]),
        "top_k": int(n_select),

        "mi_selected_n": int(len(mi_selected)),
        "rfe_selected_n": int(len(rfe_selected)),
        "pca_n_components": int(pca_meta.get("n_components", 0)),
        "pca_cumulative_variance": float(pca_meta.get("cumulative_variance", 0.0)),

        "mi_info": mi_info,
        "rfe_info": rfe_info,
        "pca_meta": pca_meta,

        "removed_by_final_guard": {
            "MI": mi_removed,
            "RFE": rfe_removed,
        },
        "feature_sets": feature_sets,

        "output": {
            "mi_ranking": str(mi_path),
            "rfe_ranking": str(rfe_path),
            "feature_sets": str(feature_sets_path),
            "selected_features": str(selected_path),
            "pca_meta": str(pca_meta_path),
            "sample_class_summary": str(sample_class_summary_path),
            "pca_scaler_joblib": str(pca_joblib_path) if pca_joblib_path else None,
            "summary": str(summary_path),
        },

        "generated_file_line_counts": {
            "mi_ranking": _small_file_entry(mi_path, data_rows=int(len(mi_df))),
            "rfe_ranking": _small_file_entry(rfe_path, data_rows=int(len(rfe_df))),
            "feature_sets": _small_file_entry(feature_sets_path),
            "selected_features": _small_file_entry(selected_path),
            "pca_meta": _small_file_entry(pca_meta_path),
            "sample_class_summary": _small_file_entry(sample_class_summary_path, data_rows=int(len(sample_class_summary_rows))),
        },

        "warnings": warnings,
        "note": (
            "Phase 12 performs feature selection using only training data. It writes rankings and selected "
            "feature lists, not a new selected dataset."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 12 - Feature Selection")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Train Sample: {len(df_sample):,}")
    print(f"Sample Class: {sample_info.get('sample_kept_by_class', {})}")
    print(f"Features    : {X.shape[1]:,}")
    print(f"MI Selected : {len(mi_selected):,}")
    print(f"RFE Selected: {len(rfe_selected):,}")
    print(f"PCA Comp.   : {pca_meta.get('n_components', 0):,}")
    print(f"Output      : {summary_path}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase12_run = run_phase12
phase12_feature_selection = run_phase12
phase12_fs = run_phase12
