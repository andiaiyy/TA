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


# =============================================================================
# PHASE 4: LABEL REFINEMENT
# =============================================================================
# Purpose:
#   Finalize Target label after:
#     1) Phase 2 application filtering
#     2) Phase 3 probing analysis
#
# Important methodological rule:
#   Phase 1/2 labels are NOT final.
#   no-alert rows must NOT be treated as final benign until this phase.
#
# Input:
#   results/phase2_app_dataset/app={app}/part-*.parquet
#   results/phase3_probing/app={app}/src_ip_window_features.parquet
#
# Output:
#   results/phase4_labeled_dataset/app={app}/part-*.parquet
#   results/phase4_labeled_dataset/metrics/phase4_label_refinement_summary_{app}.json
#   results/phase4_labeled_dataset/metrics/phase4_label_refinement_summary_all.json
#   results/phase4_labeled_dataset/metrics/phase4_label_distribution_by_app.csv
#
# Notes:
#   - This phase is disk-backed / shard-based.
#   - It reads one Phase 2 shard at a time.
#   - It joins compact probing features from Phase 3.
#   - It writes labeled shards per application.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")

DEFAULT_FALSE_POSITIVE_ALERT_CATEGORIES: Tuple[str, ...] = (
    "generic protocol decode",
)

REQUIRED_OUTPUT_COLUMNS: Tuple[str, ...] = (
    "Target",
    "label_status_final",
    "label_reason",
    "label_source",
    "label_confidence",
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",
    "probe_score",
    "is_possible_probe",
)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Phase4LabelRefinementConfig:
    # Phase 2 app-filtered input
    phase2_input_dir: Path = Path("results/phase2_app_dataset")

    # Phase 3 probing features input
    phase3_input_dir: Path = Path("results/phase3_probing")

    # Output for final labeled dataset
    output_dir: Path = Path("results/phase4_labeled_dataset")

    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    # Timestamp window must match Phase 3.
    timestamp_col: str = "timestamp"
    window_minutes: int = 5

    # Alert handling
    false_positive_alert_categories: Tuple[str, ...] = DEFAULT_FALSE_POSITIVE_ALERT_CATEGORIES
    require_alert_severity: bool = True

    # Probing evidence handling
    use_probing_evidence: bool = True
    probe_score_threshold: float = 3.0
    use_is_possible_probe_flag: bool = True

    # Optional compromised IP evidence.
    # File may contain one IP per line, or a CSV with one column named ip/src_ip/dest_ip.
    compromised_ip_file: Optional[Path] = None
    use_compromised_ip_evidence: bool = True

    # Output format
    write_format: str = "parquet"  # "parquet" or "csv"
    parquet_engine: Optional[str] = None  # "pyarrow" | "fastparquet" | None
    parquet_compression: Optional[str] = "snappy"

    # If True, delete existing app output before writing new shards.
    overwrite: bool = True

    # Small sample returned in RAM for debugging/report continuity.
    return_df_sample: int = 100_000

    # Memory hygiene
    gc_each_shard: bool = True


# =============================================================================
# Utility helpers
# =============================================================================

def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


def _read_table(path: Path) -> pd.DataFrame:
    suffixes = "".join(path.suffixes).lower()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if suffixes.endswith(".csv.gz"):
        return pd.read_csv(path, compression="gzip")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported input file format: {path}")


def _list_shards(app_dir: Path) -> List[Path]:
    if not app_dir.exists():
        return []

    patterns = [
        "*.parquet",
        "*.csv.gz",
        "*.csv",
    ]

    paths: List[Path] = []
    for pat in patterns:
        paths.extend(sorted(app_dir.glob(pat)))

    # Keep deterministic order and avoid duplicates.
    return sorted(set(paths))


def _ensure_python_str_series(s: pd.Series) -> pd.Series:
    out = s.astype("object")
    out = out.where(pd.notna(out), "")
    return out.astype(str)


def _to_int_series(s: pd.Series, default: int = 0) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(default).astype(np.int32)


def _to_float_series(s: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(default).astype(np.float32)


def _normalize_str_value(x: Any) -> str:
    if x is None:
        return ""
    try:
        if isinstance(x, float) and np.isnan(x):
            return ""
    except Exception:
        pass
    return str(x).strip().lower()


def _normalize_categories(categories: Sequence[str]) -> set[str]:
    return {_normalize_str_value(x) for x in categories if _normalize_str_value(x)}


def _clean_output_dir(path: Path) -> None:
    if not path.exists():
        return
    for fp in path.glob("*"):
        if fp.is_file():
            try:
                fp.unlink()
            except Exception:
                pass


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


def _compute_window_start(
    df: pd.DataFrame,
    *,
    timestamp_col: str = "timestamp",
    window_minutes: int = 5,
) -> pd.Series:
    if timestamp_col not in df.columns:
        return pd.Series([""], index=df.index, dtype="object")

    ts = pd.to_datetime(df[timestamp_col], errors="coerce", utc=True)
    try:
        win = ts.dt.floor(f"{int(window_minutes)}min")
    except Exception:
        win = ts.dt.floor("5min")

    # Store as stable string for join compatibility with Phase 3 output.
    return win.dt.strftime("%Y-%m-%d %H:%M:%S%z").fillna("")


def _load_compromised_ips(path: Optional[Path]) -> set[str]:
    if path is None:
        return set()

    path = Path(path)
    if not path.exists():
        print(f"⚠️ compromised_ip_file not found: {path}")
        return set()

    ips: set[str] = set()

    try:
        if path.suffix.lower() in {".csv", ".tsv"}:
            sep = "\t" if path.suffix.lower() == ".tsv" else ","
            df = pd.read_csv(path, sep=sep)
            candidate_cols = [c for c in df.columns if c.lower() in {"ip", "src_ip", "dest_ip", "address", "ioc"}]
            if candidate_cols:
                col = candidate_cols[0]
            else:
                col = df.columns[0]
            for x in df[col].dropna().astype(str):
                val = x.strip()
                if val:
                    ips.add(val)
        else:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    val = line.strip()
                    if not val or val.startswith("#"):
                        continue
                    # allow simple CSV-like line; use first token
                    val = val.split(",")[0].strip()
                    if val:
                        ips.add(val)
    except Exception as e:
        print(f"⚠️ failed to read compromised_ip_file={path}: {e}")
        return set()

    return ips


# =============================================================================
# Shard writer
# =============================================================================

class _ShardWriter:
    """
    Writes output shards:
      - Parquet if engine is available
      - CSV.GZ fallback when parquet engine is unavailable
    """

    def __init__(
        self,
        out_dir: Path,
        fmt: str,
        *,
        parquet_engine: Optional[str] = None,
        parquet_compression: Optional[str] = "snappy",
        overwrite: bool = True,
    ):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        if overwrite:
            _clean_output_dir(self.out_dir)

        fmt = (fmt or "parquet").strip().lower()
        if fmt not in {"parquet", "csv"}:
            fmt = "parquet"

        self.requested_fmt = fmt
        self.actual_fmt = fmt
        self.part = 0
        self.parquet_engine = parquet_engine
        self.parquet_compression = parquet_compression

        if self.requested_fmt == "parquet":
            self.actual_fmt = "parquet"
            if self.parquet_engine:
                eng = self.parquet_engine.strip().lower()
                if eng == "pyarrow":
                    try:
                        import pyarrow  # noqa: F401
                    except Exception:
                        self.actual_fmt = "csv"
                elif eng == "fastparquet":
                    try:
                        import fastparquet  # noqa: F401
                    except Exception:
                        self.actual_fmt = "csv"
                else:
                    self.parquet_engine = None

            if self.actual_fmt == "parquet" and self.parquet_engine is None:
                try:
                    import pyarrow  # noqa: F401
                except Exception:
                    try:
                        import fastparquet  # noqa: F401
                    except Exception:
                        self.actual_fmt = "csv"
        else:
            self.actual_fmt = "csv"

    def flush_df(self, df: pd.DataFrame) -> Optional[Path]:
        if df is None or df.empty:
            return None

        self.part += 1

        # Avoid fastparquet ArrowStringArray issues by normalizing object/string cols.
        for c in df.columns:
            if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == "object":
                try:
                    df[c] = _ensure_python_str_series(df[c])
                except Exception:
                    pass

        if self.actual_fmt == "parquet":
            path = self.out_dir / f"part-{self.part:06d}.parquet"
            kwargs: Dict[str, Any] = {"index": False}
            if self.parquet_engine:
                kwargs["engine"] = self.parquet_engine
            if self.parquet_compression:
                kwargs["compression"] = self.parquet_compression
            df.to_parquet(path, **kwargs)
        else:
            path = self.out_dir / f"part-{self.part:06d}.csv.gz"
            df.to_csv(path, index=False, compression="gzip")

        return path


# =============================================================================
# Probing feature loading
# =============================================================================

def _load_probing_features_for_app(
    cfg: Phase4LabelRefinementConfig,
    app: str,
) -> pd.DataFrame:
    """
    Load compact Phase 3 probing features for one app.

    Expected path:
      phase3_input_dir/app={app}/src_ip_window_features.parquet

    Fallbacks:
      phase3_input_dir/{app}/src_ip_window_features.parquet
      phase3_input_dir/app={app}/src_ip_window_features.csv
      phase3_input_dir/{app}/src_ip_window_features.csv
    """
    candidate_dirs = [
        Path(cfg.phase3_input_dir) / f"app={app}",
        Path(cfg.phase3_input_dir) / app,
    ]

    candidate_files: List[Path] = []
    for d in candidate_dirs:
        candidate_files.extend([
            d / "src_ip_window_features.parquet",
            d / "src_ip_window_features.csv",
            d / "src_ip_window_features.csv.gz",
        ])

    existing = [p for p in candidate_files if p.exists()]
    if not existing:
        return pd.DataFrame(columns=[
            "src_ip", "window_start", "probe_score", "is_possible_probe", "probe_reason"
        ])

    path = existing[0]
    df = _read_table(path)

    if df.empty:
        return pd.DataFrame(columns=[
            "src_ip", "window_start", "probe_score", "is_possible_probe", "probe_reason"
        ])

    # Normalize columns from possible Phase 3 variations.
    rename_map: Dict[str, str] = {}
    lower_to_actual = {c.lower(): c for c in df.columns}

    if "src_ip" not in df.columns and "source_ip" in lower_to_actual:
        rename_map[lower_to_actual["source_ip"]] = "src_ip"

    if "window_start" not in df.columns:
        for candidate in ("time_window", "window", "ts_window", "timestamp_window"):
            if candidate in lower_to_actual:
                rename_map[lower_to_actual[candidate]] = "window_start"
                break

    if "probe_score" not in df.columns:
        for candidate in ("probing_score", "score"):
            if candidate in lower_to_actual:
                rename_map[lower_to_actual[candidate]] = "probe_score"
                break

    if "is_possible_probe" not in df.columns:
        for candidate in ("possible_probe", "is_probe", "probe_flag"):
            if candidate in lower_to_actual:
                rename_map[lower_to_actual[candidate]] = "is_possible_probe"
                break

    if rename_map:
        df = df.rename(columns=rename_map)

    for c in ["src_ip", "window_start", "probe_score", "is_possible_probe", "probe_reason"]:
        if c not in df.columns:
            if c in {"probe_score", "is_possible_probe"}:
                df[c] = 0
            else:
                df[c] = ""

    df = df[["src_ip", "window_start", "probe_score", "is_possible_probe", "probe_reason"]].copy()
    df["src_ip"] = _ensure_python_str_series(df["src_ip"])
    df["window_start"] = _ensure_python_str_series(df["window_start"])
    df["probe_score"] = _to_float_series(df["probe_score"], 0.0)
    df["is_possible_probe"] = _to_int_series(df["is_possible_probe"], 0)
    df["probe_reason"] = _ensure_python_str_series(df["probe_reason"])

    # Deduplicate just in case.
    # If multiple rows exist per key, keep the strongest evidence.
    if not df.empty:
        df = (
            df.sort_values(["src_ip", "window_start", "probe_score"], ascending=[True, True, False])
              .drop_duplicates(subset=["src_ip", "window_start"], keep="first")
              .reset_index(drop=True)
        )

    return df


# =============================================================================
# Label refinement logic
# =============================================================================

def _build_evidence_columns(
    df: pd.DataFrame,
    *,
    cfg: Phase4LabelRefinementConfig,
    compromised_ips: set[str],
) -> pd.DataFrame:
    out = df.copy()

    # -------------------------------------------------------------------------
    # Alert evidence
    # -------------------------------------------------------------------------
    false_pos = _normalize_categories(cfg.false_positive_alert_categories)

    if "has_alert" in out.columns:
        has_alert = _to_int_series(out["has_alert"], 0) == 1
    else:
        has_alert = pd.Series(False, index=out.index)

    if "alert_category" in out.columns:
        cat_norm = out["alert_category"].map(_normalize_str_value)
        is_false_pos = cat_norm.isin(false_pos)
    else:
        is_false_pos = pd.Series(False, index=out.index)

    if "alert_severity" in out.columns and cfg.require_alert_severity:
        sev_valid = _to_int_series(out["alert_severity"], 0) > 0
    else:
        sev_valid = pd.Series(True, index=out.index)

    # Also support Phase 1 modified columns when available.
    prelim_malicious = pd.Series(False, index=out.index)
    if "Target_prelim" in out.columns:
        prelim_malicious = prelim_malicious | (_to_int_series(out["Target_prelim"], -1) == 1)
    elif "Target" in out.columns:
        # Legacy compatibility: old Phase 1 used Target directly.
        # In this phase, legacy Target is treated only as preliminary evidence.
        prelim_malicious = prelim_malicious | (_to_int_series(out["Target"], 0) == 1)

    if "label_status" in out.columns:
        label_status_norm = out["label_status"].map(_normalize_str_value)
        prelim_malicious = prelim_malicious | label_status_norm.isin({
            "malicious_evidence",
            "confirmed_attack",
            "suspicious",
            "alert_evidence",
        })

    evidence_alert = (has_alert & sev_valid & ~is_false_pos) | prelim_malicious
    out["evidence_alert"] = evidence_alert.astype(np.int8)

    # -------------------------------------------------------------------------
    # Compromised IP evidence
    # -------------------------------------------------------------------------
    if cfg.use_compromised_ip_evidence and compromised_ips:
        src_match = (
            out["src_ip"].astype(str).isin(compromised_ips)
            if "src_ip" in out.columns else pd.Series(False, index=out.index)
        )
        dest_match = (
            out["dest_ip"].astype(str).isin(compromised_ips)
            if "dest_ip" in out.columns else pd.Series(False, index=out.index)
        )
        evidence_compromised = src_match | dest_match
    else:
        evidence_compromised = pd.Series(False, index=out.index)

    out["evidence_compromised_ip"] = evidence_compromised.astype(np.int8)

    # -------------------------------------------------------------------------
    # Probe evidence
    # -------------------------------------------------------------------------
    if "probe_score" not in out.columns:
        out["probe_score"] = 0.0
    if "is_possible_probe" not in out.columns:
        out["is_possible_probe"] = 0
    if "probe_reason" not in out.columns:
        out["probe_reason"] = ""

    probe_score = _to_float_series(out["probe_score"], 0.0)
    is_possible_probe = _to_int_series(out["is_possible_probe"], 0) == 1

    if cfg.use_probing_evidence:
        evidence_probe = probe_score >= float(cfg.probe_score_threshold)
        if cfg.use_is_possible_probe_flag:
            evidence_probe = evidence_probe | is_possible_probe
    else:
        evidence_probe = pd.Series(False, index=out.index)

    out["probe_score"] = probe_score
    out["is_possible_probe"] = is_possible_probe.astype(np.int8)
    out["evidence_probe"] = evidence_probe.astype(np.int8)

    return out


def _finalize_labels(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    alert = _to_int_series(out.get("evidence_alert", pd.Series(0, index=out.index)), 0) == 1
    comp = _to_int_series(out.get("evidence_compromised_ip", pd.Series(0, index=out.index)), 0) == 1
    probe = _to_int_series(out.get("evidence_probe", pd.Series(0, index=out.index)), 0) == 1

    malicious = alert | comp | probe
    out["Target"] = malicious.astype(np.int8)

    # Source priority: compromised IP > alert > probe > benign.
    source = np.select(
        [
            comp & alert & probe,
            comp & alert,
            comp & probe,
            alert & probe,
            comp,
            alert,
            probe,
        ],
        [
            "compromised_ip+alert+probe",
            "compromised_ip+alert",
            "compromised_ip+probe",
            "alert+probe",
            "compromised_ip",
            "alert",
            "probe",
        ],
        default="no_malicious_evidence",
    )

    status = np.where(malicious, "malicious", "benign")
    out["label_status_final"] = status
    out["label_source"] = source

    # Confidence is not a probability; it is an evidence-strength indicator.
    confidence = np.select(
        [
            comp & alert & probe,
            comp & alert,
            comp & probe,
            alert & probe,
            comp,
            alert,
            probe,
        ],
        [
            0.99,
            0.97,
            0.95,
            0.93,
            0.92,
            0.90,
            0.80,
        ],
        default=0.70,
    )
    out["label_confidence"] = confidence.astype(np.float32)

    reason = np.select(
        [
            comp & alert & probe,
            comp & alert,
            comp & probe,
            alert & probe,
            comp,
            alert,
            probe,
        ],
        [
            "matched compromised IP list, valid alert evidence, and probing evidence",
            "matched compromised IP list and valid alert evidence",
            "matched compromised IP list and probing evidence",
            "valid alert evidence and probing evidence",
            "matched compromised IP list",
            "valid alert evidence",
            "probing evidence from source-IP/time-window behavior",
        ],
        default="no alert, compromised-IP, or probing evidence after refinement",
    )
    out["label_reason"] = reason

    # Keep output columns stable near the end while preserving all original features.
    for c in REQUIRED_OUTPUT_COLUMNS:
        if c not in out.columns:
            if c in {"Target", "evidence_alert", "evidence_compromised_ip", "evidence_probe", "is_possible_probe"}:
                out[c] = 0
            elif c in {"probe_score", "label_confidence"}:
                out[c] = 0.0
            else:
                out[c] = ""

    return out




# =============================================================================
# Visualization summary helpers
# =============================================================================

def _counter_dict_from_series(s: pd.Series, top_n: Optional[int] = None) -> Dict[str, int]:
    if s is None or s.empty:
        return {}
    try:
        vc = s.astype("object").where(pd.notna(s), "unknown").astype(str).value_counts(dropna=False)
        if top_n is not None and int(top_n) > 0:
            vc = vc.head(int(top_n))
        return {str(k): int(v) for k, v in vc.items()}
    except Exception:
        return {}


def _alert_severity_by_target(df: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """
    Build crosstab data for Phase 9 stacked alert-severity chart.

    Shape:
      {
        "0": {"0": benign_sev0, "1": benign_sev1, ...},
        "1": {"0": malicious_sev0, "1": malicious_sev1, ...}
      }
    """
    if df is None or df.empty or "Target" not in df.columns:
        return {}

    target = _to_int_series(df["Target"], 0).astype(int).astype(str)
    if "alert_severity" in df.columns:
        sev = _to_int_series(df["alert_severity"], 0).astype(int).astype(str)
    else:
        sev = pd.Series(["0"] * len(df), index=df.index, dtype="object")

    ct = pd.crosstab(target, sev)
    out: Dict[str, Dict[str, int]] = {}
    for tgt in ct.index:
        out[str(tgt)] = {str(sev_key): int(ct.loc[tgt, sev_key]) for sev_key in ct.columns}
    return out


def _merge_nested_count_dict(dst: Dict[str, Counter], src: Dict[str, Dict[str, int]]) -> None:
    for outer_key, inner in (src or {}).items():
        if outer_key not in dst:
            dst[outer_key] = Counter()
        for inner_key, value in (inner or {}).items():
            try:
                dst[str(outer_key)][str(inner_key)] += int(value)
            except Exception:
                pass


def _nested_counter_to_dict(src: Dict[str, Counter]) -> Dict[str, Dict[str, int]]:
    return {str(k): {str(kk): int(vv) for kk, vv in counter.items()} for k, counter in src.items()}


def _phase4_visualization_stats(df: pd.DataFrame, app: str) -> Dict[str, Any]:
    """
    Compact stats consumed by Phase 9 so it does not need to re-scan data.
    """
    if df is None or df.empty:
        return {
            "app": app,
            "rows_after_phase4": 0,
            "target_counts": {},
            "label_source_counts": {},
            "evidence_counts": {"alert": 0, "compromised_ip": 0, "probe": 0},
            "alert_severity_by_target": {},
            "alert_severity_counts": {},
            "label_status_final_counts": {},
        }

    target_counts = _counter_dict_from_series(_to_int_series(df["Target"], 0)) if "Target" in df.columns else {}
    label_source_counts = _counter_dict_from_series(df["label_source"]) if "label_source" in df.columns else {}
    alert_severity_counts = _counter_dict_from_series(_to_int_series(df["alert_severity"], 0)) if "alert_severity" in df.columns else {}
    label_status_final_counts = _counter_dict_from_series(df["label_status_final"]) if "label_status_final" in df.columns else {}

    return {
        "app": app,
        "rows_after_phase4": int(len(df)),
        "target_counts": target_counts,
        "label_source_counts": label_source_counts,
        "evidence_counts": {
            "alert": int(_to_int_series(df.get("evidence_alert", pd.Series(0, index=df.index)), 0).sum()),
            "compromised_ip": int(_to_int_series(df.get("evidence_compromised_ip", pd.Series(0, index=df.index)), 0).sum()),
            "probe": int(_to_int_series(df.get("evidence_probe", pd.Series(0, index=df.index)), 0).sum()),
        },
        "alert_severity_by_target": _alert_severity_by_target(df),
        "alert_severity_counts": alert_severity_counts,
        "label_status_final_counts": label_status_final_counts,
    }


def _summarize_labeled_df(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {
            "rows": 0,
            "target_counts": {},
            "label_source_counts": {},
            "evidence_alert_count": 0,
            "evidence_compromised_ip_count": 0,
            "evidence_probe_count": 0,
        }

    target_counts = Counter(_to_int_series(df["Target"], 0).tolist()) if "Target" in df.columns else Counter()
    label_source_counts = Counter(df["label_source"].astype(str).tolist()) if "label_source" in df.columns else Counter()

    return {
        "rows": int(len(df)),
        "target_counts": {str(k): int(v) for k, v in target_counts.items()},
        "label_source_counts": {str(k): int(v) for k, v in label_source_counts.items()},
        "evidence_alert_count": int(_to_int_series(df.get("evidence_alert", pd.Series(0, index=df.index)), 0).sum()),
        "evidence_compromised_ip_count": int(_to_int_series(df.get("evidence_compromised_ip", pd.Series(0, index=df.index)), 0).sum()),
        "evidence_probe_count": int(_to_int_series(df.get("evidence_probe", pd.Series(0, index=df.index)), 0).sum()),
    }


# =============================================================================
# Public API
# =============================================================================

def phase4_refine_labels_for_app(
    app: str,
    *,
    cfg: Phase4LabelRefinementConfig,
    compromised_ips: Optional[set[str]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Refine labels for a single application.

    Returns:
      df_sample, summary
    """
    app = str(app).strip().lower()
    if compromised_ips is None:
        compromised_ips = _load_compromised_ips(cfg.compromised_ip_file)

    t0 = datetime.now()

    # Accept both app={app} and {app} layouts.
    input_candidates = [
        Path(cfg.phase2_input_dir) / f"app={app}",
        Path(cfg.phase2_input_dir) / app,
    ]

    input_dir = None
    shards: List[Path] = []
    for candidate in input_candidates:
        candidate_shards = _list_shards(candidate)
        if candidate_shards:
            input_dir = candidate
            shards = candidate_shards
            break

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    out_metrics_dir = Path(cfg.output_dir) / "metrics"
    out_metrics_dir.mkdir(parents=True, exist_ok=True)

    if not shards:
        summary = {
            "phase": 4,
            "app": app,
            "status": "skipped_no_input_shards",
            "input_dir_candidates": [str(x) for x in input_candidates],
            "output_dir": str(out_app_dir),
            "rows_read": 0,
            "rows_written": 0,
            "shards_read": 0,
            "shards_written": 0,
            "seconds": 0.0,
        }
        _json_dump(summary, out_metrics_dir / f"phase4_label_refinement_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\n🟣 PHASE 4: Label refinement for app={app}")
    print(f"   Input : {input_dir}")
    print(f"   Shards: {len(shards):,}")
    print(f"   Output: {out_app_dir}")

    probing_df = _load_probing_features_for_app(cfg, app)
    has_probing_features = not probing_df.empty

    if has_probing_features:
        print(f"   Probing features loaded: {probing_df.shape[0]:,} src_ip-window rows")
    else:
        print("   Probing features loaded: none")

    writer = _ShardWriter(
        out_app_dir,
        cfg.write_format,
        parquet_engine=cfg.parquet_engine,
        parquet_compression=cfg.parquet_compression,
        overwrite=cfg.overwrite,
    )

    sample_rows: List[pd.DataFrame] = []
    sample_max = max(0, int(cfg.return_df_sample))

    total_rows_read = 0
    total_rows_written = 0
    shards_written = 0
    target_counter: Counter = Counter()
    source_counter: Counter = Counter()
    evidence_counts = Counter()
    alert_severity_by_target_counter: Dict[str, Counter] = defaultdict(Counter)

    pbar = tqdm(shards, desc=f"PHASE 4 app={app}", unit="shard", dynamic_ncols=True)

    for shard_path in pbar:
        df = _read_table(shard_path)
        total_rows_read += int(len(df))

        if df.empty:
            if cfg.gc_each_shard:
                del df
                gc.collect()
            continue

        # Ensure app column exists.
        if "application" not in df.columns:
            df["application"] = app
        else:
            df["application"] = df["application"].where(pd.notna(df["application"]), app).astype(str)

        # Compute join key compatible with Phase 3.
        df["window_start"] = _compute_window_start(
            df,
            timestamp_col=cfg.timestamp_col,
            window_minutes=cfg.window_minutes,
        )

        if "src_ip" in df.columns:
            df["src_ip"] = _ensure_python_str_series(df["src_ip"])
        else:
            df["src_ip"] = ""

        # Join probing feature table.
        if has_probing_features:
            df = df.merge(
                probing_df,
                on=["src_ip", "window_start"],
                how="left",
                suffixes=("", "_probe"),
            )

        # Fill probing columns if no match.
        for c in ["probe_score", "is_possible_probe", "probe_reason"]:
            if c not in df.columns:
                if c in {"probe_score", "is_possible_probe"}:
                    df[c] = 0
                else:
                    df[c] = ""
        df["probe_score"] = _to_float_series(df["probe_score"], 0.0)
        df["is_possible_probe"] = _to_int_series(df["is_possible_probe"], 0)
        df["probe_reason"] = _ensure_python_str_series(df["probe_reason"])

        df = _build_evidence_columns(df, cfg=cfg, compromised_ips=compromised_ips)
        df = _finalize_labels(df)

        # Reorder useful label columns near the end but preserve all fields.
        label_cols = [
            "Target",
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
            "window_start",
        ]
        base_cols = [c for c in df.columns if c not in label_cols]
        ordered_cols = base_cols + [c for c in label_cols if c in df.columns]
        df = df[ordered_cols]

        path = writer.flush_df(df)
        if path is not None:
            shards_written += 1

        total_rows_written += int(len(df))

        # Aggregated counters.
        target_counter.update(_to_int_series(df["Target"], 0).tolist())
        if "label_source" in df.columns:
            source_counter.update(df["label_source"].astype(str).tolist())

        evidence_counts["alert"] += int(_to_int_series(df["evidence_alert"], 0).sum())
        evidence_counts["compromised_ip"] += int(_to_int_series(df["evidence_compromised_ip"], 0).sum())
        evidence_counts["probe"] += int(_to_int_series(df["evidence_probe"], 0).sum())
        _merge_nested_count_dict(alert_severity_by_target_counter, _alert_severity_by_target(df))

        # Keep small sample in RAM.
        if sample_max > 0:
            kept = sum(len(x) for x in sample_rows)
            remaining = sample_max - kept
            if remaining > 0:
                sample_rows.append(df.head(remaining).copy())

        pbar.set_postfix({
            "rows": f"{total_rows_written:,}",
            "mal": f"{target_counter.get(1, 0):,}",
            "ben": f"{target_counter.get(0, 0):,}",
        })

        if cfg.gc_each_shard:
            del df
            gc.collect()

    pbar.close()

    elapsed = (datetime.now() - t0).total_seconds()
    output_bytes = _dir_size_bytes(out_app_dir)

    if sample_rows:
        df_sample = pd.concat(sample_rows, ignore_index=True)
    else:
        df_sample = pd.DataFrame()

    alert_severity_by_target = _nested_counter_to_dict(alert_severity_by_target_counter)
    visualization_stats = {
        "app": app,
        "rows_after_phase4": int(total_rows_written),
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "label_source_counts": {str(k): int(v) for k, v in source_counter.items()},
        "evidence_counts": {str(k): int(v) for k, v in evidence_counts.items()},
        "alert_severity_by_target": alert_severity_by_target,
    }

    summary = {
        "phase": 4,
        "app": app,
        "status": "completed",
        "input_dir": str(input_dir),
        "output_dir": str(out_app_dir),
        "phase3_input_dir": str(cfg.phase3_input_dir),
        "has_probing_features": bool(has_probing_features),
        "probing_feature_rows": int(len(probing_df)),
        "compromised_ip_file": str(cfg.compromised_ip_file) if cfg.compromised_ip_file else None,
        "compromised_ip_count": int(len(compromised_ips)),
        "selected_apps": list(cfg.selected_apps),
        "timestamp_col": cfg.timestamp_col,
        "window_minutes": int(cfg.window_minutes),
        "false_positive_alert_categories": list(cfg.false_positive_alert_categories),
        "require_alert_severity": bool(cfg.require_alert_severity),
        "use_probing_evidence": bool(cfg.use_probing_evidence),
        "probe_score_threshold": float(cfg.probe_score_threshold),
        "use_is_possible_probe_flag": bool(cfg.use_is_possible_probe_flag),
        "use_compromised_ip_evidence": bool(cfg.use_compromised_ip_evidence),
        "shards_read": int(len(shards)),
        "shards_written": int(shards_written),
        "rows_read": int(total_rows_read),
        "rows_written": int(total_rows_written),
        "target_counts": {str(k): int(v) for k, v in target_counter.items()},
        "label_source_counts": {str(k): int(v) for k, v in source_counter.items()},
        "evidence_counts": {str(k): int(v) for k, v in evidence_counts.items()},
        "alert_severity_by_target": alert_severity_by_target,
        "visualization_stats": visualization_stats,
        "output_format": writer.actual_fmt,
        "output_bytes": int(output_bytes),
        "output_gib": float(_gib(output_bytes)),
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "seconds": float(elapsed),
        "note": (
            "Phase 4 is the first phase that finalizes Target. "
            "Earlier labels are treated as evidence/staging, not final ground truth."
        ),
    }

    _json_dump(summary, out_metrics_dir / f"phase4_label_refinement_summary_{app}.json")

    print(f"✅ Phase 4 complete app={app}")
    print(f"   Rows written : {total_rows_written:,}")
    print(f"   Target counts: {summary['target_counts']}")
    print(f"   Sources      : {summary['label_source_counts']}")
    print(f"   Output size  : {_gib(output_bytes):.2f} GiB")
    print(f"   Time         : {elapsed/60:.2f} minutes")

    return df_sample, summary


def phase4_refine_labels(
    *,
    cfg: Phase4LabelRefinementConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """
    Run Phase 4 for all selected apps.

    Returns:
      samples_by_app, summary_all
    """
    print("\n" + "🟣 " + "=" * 76)
    print("PHASE 4: LABEL REFINEMENT / TARGET FINALIZATION")
    print("🟣 " + "=" * 76)

    t0 = datetime.now()

    compromised_ips = _load_compromised_ips(cfg.compromised_ip_file)
    if cfg.compromised_ip_file:
        print(f"Compromised IP evidence loaded: {len(compromised_ips):,} IPs")

    samples_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        df_sample, summary = phase4_refine_labels_for_app(
            str(app).strip().lower(),
            cfg=cfg,
            compromised_ips=compromised_ips,
        )
        samples_by_app[str(app).strip().lower()] = df_sample
        summaries[str(app).strip().lower()] = summary

    # Cross-app summary table.
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        target_counts = s.get("target_counts", {})
        source_counts = s.get("label_source_counts", {})
        rows.append({
            "app": app,
            "status": s.get("status"),
            "rows_written": int(s.get("rows_written", 0)),
            "target_0_benign": int(target_counts.get("0", 0)),
            "target_1_malicious": int(target_counts.get("1", 0)),
            "evidence_alert": int(s.get("evidence_counts", {}).get("alert", 0)),
            "evidence_compromised_ip": int(s.get("evidence_counts", {}).get("compromised_ip", 0)),
            "evidence_probe": int(s.get("evidence_counts", {}).get("probe", 0)),
            "output_gib": float(s.get("output_gib", 0.0)),
            "shards_written": int(s.get("shards_written", 0)),
        })
    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase4_label_distribution_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows = int(sum(int(s.get("rows_written", 0)) for s in summaries.values()))
    total_output_bytes = int(_dir_size_bytes(Path(cfg.output_dir)) - _dir_size_bytes(metrics_dir))

    summary_all = {
        "phase": 4,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "output_dir": str(cfg.output_dir),
        "total_rows_written": total_rows,
        "total_output_bytes": total_output_bytes,
        "total_output_gib": float(_gib(total_output_bytes)),
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Target is finalized per application using alert evidence, optional compromised IP evidence, "
            "and optional probing evidence from Phase 3."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase4_label_refinement_summary_all.json")

    print("\n✅ PHASE 4 COMPLETE")
    print(f"   Total rows written: {total_rows:,}")
    print(f"   Output dir        : {cfg.output_dir}")
    print(f"   Time              : {elapsed/60:.2f} minutes")

    return samples_by_app, summary_all



# =============================================================================
# RAM-mode API (small-data / seminar workflow)
# =============================================================================

def phase4_refine_labels_ram(
    df_phase2: pd.DataFrame,
    df_phase3: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase4LabelRefinementConfig] = None,
    false_positive_alert_categories: Sequence[str] = DEFAULT_FALSE_POSITIVE_ALERT_CATEGORIES,
    require_alert_severity: bool = True,
    use_probing_evidence: bool = True,
    probe_score_threshold: float = 3.0,
    use_is_possible_probe_flag: bool = True,
    compromised_ips: Optional[set[str]] = None,
    compromised_ip_file: Optional[Path] = None,
    use_compromised_ip_evidence: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode Phase 4 for the current small-data workflow.

    Input:
      df_phase2 : row-level DataFrame from Phase 2 RAM mode.
      df_phase3 : optional row-level DataFrame from Phase 3 RAM mode. If provided,
                  it is preferred because it already contains probing columns.

    Output:
      df_labeled : row-level DataFrame with final Target and label evidence columns.
      summary    : JSON-serializable summary for one active app.

    This function does not read/write Parquet or CSV. Persistence is handled by
    pipeline.py through incremental phase summaries.
    """
    t0 = datetime.now()
    app = str(app).strip().lower()

    if cfg is not None:
        false_positive_alert_categories = tuple(cfg.false_positive_alert_categories)
        require_alert_severity = bool(cfg.require_alert_severity)
        use_probing_evidence = bool(cfg.use_probing_evidence)
        probe_score_threshold = float(cfg.probe_score_threshold)
        use_is_possible_probe_flag = bool(cfg.use_is_possible_probe_flag)
        use_compromised_ip_evidence = bool(cfg.use_compromised_ip_evidence)
        compromised_ip_file = cfg.compromised_ip_file

    if compromised_ips is None:
        compromised_ips = _load_compromised_ips(compromised_ip_file)

    # Prefer Phase 3 output when available because it carries row-level probing
    # features in RAM mode. Fall back to Phase 2 if Phase 3 was disabled/skipped.
    if df_phase3 is not None and isinstance(df_phase3, pd.DataFrame) and not df_phase3.empty:
        df = df_phase3.copy()
        input_source = "df_phase3"
    elif df_phase2 is not None and isinstance(df_phase2, pd.DataFrame):
        df = df_phase2.copy()
        input_source = "df_phase2"
    else:
        df = pd.DataFrame()
        input_source = "empty"

    rows_in = int(len(df))

    if df.empty:
        elapsed = (datetime.now() - t0).total_seconds()
        summary = {
            "phase": 4,
            "phase_name": "label_refinement",
            "mode": "ram",
            "application": app,
            "app": app,
            "status": "completed_empty",
            "input_source": input_source,
            "rows_in": 0,
            "rows_out": 0,
            "target_counts": {},
            "label_source_counts": {},
            "evidence_counts": {"alert": 0, "compromised_ip": 0, "probe": 0},
            "alert_severity_by_target": {},
            "visualization_stats": _phase4_visualization_stats(df, app),
            "seconds": float(elapsed),
        }
        return df, summary

    if "application" not in df.columns:
        df["application"] = app
    else:
        df["application"] = df["application"].where(pd.notna(df["application"]), app).astype(str)

    # Ensure window_start exists for report/debug compatibility. In RAM mode,
    # Phase 3 should already have probing columns, so no disk join is needed.
    if "window_start" not in df.columns:
        timestamp_col = cfg.timestamp_col if cfg is not None else "timestamp"
        window_minutes = cfg.window_minutes if cfg is not None else 5
        df["window_start"] = _compute_window_start(
            df,
            timestamp_col=timestamp_col,
            window_minutes=int(window_minutes),
        )

    for c in ["probe_score", "is_possible_probe", "probe_reason"]:
        if c not in df.columns:
            if c in {"probe_score", "is_possible_probe"}:
                df[c] = 0
            else:
                df[c] = ""

    # Build a lightweight config object so the existing evidence/finalization
    # helpers remain the single source of truth.
    ram_cfg = Phase4LabelRefinementConfig(
        selected_apps=(app,),
        false_positive_alert_categories=tuple(false_positive_alert_categories),
        require_alert_severity=bool(require_alert_severity),
        use_probing_evidence=bool(use_probing_evidence),
        probe_score_threshold=float(probe_score_threshold),
        use_is_possible_probe_flag=bool(use_is_possible_probe_flag),
        compromised_ip_file=compromised_ip_file,
        use_compromised_ip_evidence=bool(use_compromised_ip_evidence),
    )

    df = _build_evidence_columns(df, cfg=ram_cfg, compromised_ips=set(compromised_ips or set()))
    df = _finalize_labels(df)

    # Put final label columns near the end while preserving all prior features.
    label_cols = [
        "Target",
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
        "window_start",
    ]
    base_cols = [c for c in df.columns if c not in label_cols]
    df = df[base_cols + [c for c in label_cols if c in df.columns]]

    label_stats = _summarize_labeled_df(df)
    visualization_stats = _phase4_visualization_stats(df, app)
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 4,
        "phase_name": "label_refinement",
        "mode": "ram",
        "application": app,
        "app": app,
        "status": "completed",
        "input_source": input_source,
        "rows_in": int(rows_in),
        "rows_out": int(len(df)),
        "target_counts": label_stats.get("target_counts", {}),
        "label_source_counts": label_stats.get("label_source_counts", {}),
        "evidence_counts": {
            "alert": int(label_stats.get("evidence_alert_count", 0)),
            "compromised_ip": int(label_stats.get("evidence_compromised_ip_count", 0)),
            "probe": int(label_stats.get("evidence_probe_count", 0)),
        },
        "alert_severity_by_target": visualization_stats.get("alert_severity_by_target", {}),
        "visualization_stats": visualization_stats,
        "false_positive_alert_categories": list(false_positive_alert_categories),
        "require_alert_severity": bool(require_alert_severity),
        "use_probing_evidence": bool(use_probing_evidence),
        "probe_score_threshold": float(probe_score_threshold),
        "use_is_possible_probe_flag": bool(use_is_possible_probe_flag),
        "use_compromised_ip_evidence": bool(use_compromised_ip_evidence),
        "compromised_ip_count": int(len(compromised_ips or set())),
        "df_shape": [int(df.shape[0]), int(df.shape[1])],
        "seconds": float(elapsed),
        "note": (
            "RAM-mode Phase 4 finalizes Target from alert evidence, optional compromised-IP evidence, "
            "and probing features already attached by Phase 3 RAM mode. No Parquet checkpoint is written."
        ),
    }

    print(f"✅ PHASE 4 RAM COMPLETE app={app} | rows={len(df):,} | target={summary['target_counts']} | {elapsed/60:.2f} min")
    gc.collect()
    return df, summary


# Backward-friendly RAM aliases for pipeline integration.
def phase4_label_refinement_ram(
    df_phase2: pd.DataFrame,
    df_phase3: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase4LabelRefinementConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase4_refine_labels_ram(df_phase2, df_phase3, app=app, cfg=cfg, **kwargs)


def phase4_refine_labels_in_memory(
    df_phase2: pd.DataFrame,
    df_phase3: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase4LabelRefinementConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase4_refine_labels_ram(df_phase2, df_phase3, app=app, cfg=cfg, **kwargs)


def run_phase4_label_refinement_ram(
    df_phase2: pd.DataFrame,
    df_phase3: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase4LabelRefinementConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase4_refine_labels_ram(df_phase2, df_phase3, app=app, cfg=cfg, **kwargs)

# Backward-friendly alias if pipeline prefers build_* naming.
def build_phase4_label_refinement(
    *,
    cfg: Phase4LabelRefinementConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase4_refine_labels(cfg=cfg)


if __name__ == "__main__":
    samples, summary = phase4_refine_labels(
        cfg=Phase4LabelRefinementConfig(
            phase2_input_dir=Path("results/phase2_app_dataset"),
            phase3_input_dir=Path("results/phase3_probing"),
            output_dir=Path("results/phase4_labeled_dataset"),
            selected_apps=("dns", "http", "tls", "ssh"),
            window_minutes=5,
            false_positive_alert_categories=("generic protocol decode",),
            use_probing_evidence=True,
            probe_score_threshold=3.0,
            use_is_possible_probe_flag=True,
            compromised_ip_file=None,
            write_format="parquet",
            parquet_engine="fastparquet",
            parquet_compression="snappy",
            overwrite=True,
            return_df_sample=100_000,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
