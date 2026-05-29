from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import json
import time
from typing import Optional, Dict, Any, Tuple, List
from contextlib import nullcontext

import numpy as np
import pandas as pd


# =============================================================================
# CONFIG
# =============================================================================
@dataclass(frozen=True)
class Phase8Config:
    # column names
    target_col: str = "Target"

    # ---------------------------------------------------------------------
    # PROGRESS / STATUS OUTPUT (sharded mode only)
    # ---------------------------------------------------------------------
    progress_enabled: bool = True
    progress_every_seconds: float = 10.0
    progress_line_width: int = 160

    # Total rows TRAIN yang kamu targetkan (attack+benign).
    # Jika None/0: pakai logic mode normal (balanced/cap).
    train_total_rows_target: Optional[int] = None

    # NEW: shard/disk input (if set, Phase 8 reads from disk instead of df_clean)
    # expected layout:
    #   input_dir/attacks/part-*.parquet (or part-*.csv.gz)
    #   input_dir/benign/part-*.parquet  (or part-*.csv.gz)
    input_dir: Optional[Path] = None

    # take attacks
    attack_fraction: float = 1.0
    min_attack_required: int = 50

    # POOL benign budget (upper bound) before allocating to train/test/stress
    pool_benign_per_attack: float = 10.0

    # split attack only
    train_ratio: float = 0.80
    test_ratio: float = 0.20

    # undersample benign ONLY in TRAIN (cap strategy if train_benign_mode="cap")
    train_benign_per_attack: float = 3.0

    # TEST benign allocation cap (if test_benign_mode="cap")
    test_benign_per_attack: float = 10.0

    # allocation modes
    train_benign_mode: str = "balanced"    # "balanced" or "cap"
    test_benign_mode: str = "remainder"    # "remainder" or "cap"

    # benign-only stress set size
    stress_benign_n: Optional[int] = 0

    # Optional: export pooled dataset? (pool can be HUGE)
    export_pool: bool = False

    # misc
    seed: int = 42

    # === STRATEGY: DROP FOR MODELING HAPPENS HERE (Phase 8) ===
    # pkt_src / app_proto / proto / flow_id are categorical fields that Phase 2
    # hash-encodes in place. In Suricata, alert-records and flow-records have
    # systematically different values for pkt_src ("wire/pcap" vs "stream") and
    # app_proto distributions, which means their hashed forms are near-perfect
    # proxies for Target (Target is derived from alert presence in Phase 1).
    # Leaving them in produced 1.00 metrics on every EVE pipeline.
    drop_leak_cols: Tuple[str, ...] = (
        "is_malicious",
        "event_type", "event_type_h",
        "has_alert", "alert_category", "alert_severity",
        "pkt_src", "app_proto", "proto", "flow_id",
    )

    phase7_drop_json: Optional[Path] = None
    extra_drop_cols: Tuple[str, ...] = ()
    drop_raw_cols_for_model: bool = True

    # KEEP THIS TRUE, but now we coerce first before dropping
    drop_non_numeric_for_model: bool = True

    # NEW: numeric-like coercion controls
    coerce_numeric_like_for_model: bool = True
    numeric_coercion_min_fraction: float = 0.80  # among non-null source values
    schema_sample_files_per_class: int = 3       # shard-mode schema probe
    schema_sample_rows_per_file: int = 2000

    # output controls
    out_dir: Optional[Path] = None
    filename_tag: str = "SAMPLE"
    compress: bool = True

    # export style for disk-based Phase 10
    export_split_attack_benign: bool = True
    export_combined_train_test: bool = True

    # in-memory return caps (pipeline safety)
    return_train_rows: int = 8_000_000
    return_test_rows: int = 2_000_000
    return_pool_rows: int = 200_000

    # NEW: export the returned Phase 8 in-memory dataset ("medium") for Phase 10 reuse.
    # Turn this OFF if return_train_rows / return_test_rows become too large.
    phase_8_export_medium: bool = True
    phase_8_export_medium_dir: Optional[Path] = None
    phase_8_export_medium_format: str = "csv"  # "csv" or "parquet"


# =============================================================================
# PROGRESS HELPERS
# =============================================================================
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = seconds - (m * 60)
    if m < 60:
        return f"{m}m{s:04.1f}s"
    h = int(m // 60)
    m2 = m - (h * 60)
    return f"{h}h{m2:02d}m{s:04.1f}s"


class _ProgressThrottle:
    def __init__(self, enabled: bool, every_seconds: float):
        self.enabled = bool(enabled)
        try:
            self.every = float(every_seconds)
        except Exception:
            self.every = 10.0
        if self.every <= 0:
            self.every = 1.0
        self._last = 0.0

    def should_print(self) -> bool:
        if not self.enabled:
            return False
        now = time.time()
        if (now - self._last) >= self.every:
            self._last = now
            return True
        return False

    def force(self) -> None:
        self._last = 0.0


def _progress_line(msg: str, *, width: int = 160) -> None:
    print("\r" + msg.ljust(width), end="", flush=True)


def _progress_done() -> None:
    print("")


def _count_rows_fast(fp: Path) -> int:
    """
    Fast row count:
    - Parquet: use metadata if pyarrow available
    - CSV.GZ: counts lines (IO heavy) - avoid if possible
    """
    try:
        suf = fp.suffix.lower()

        if suf == ".parquet":
            try:
                import pyarrow.parquet as pq  # type: ignore
                pf = pq.ParquetFile(fp)
                md = pf.metadata
                return int(md.num_rows) if md is not None else 0
            except Exception:
                return int(len(pd.read_parquet(fp)))

        if suf == ".gz":
            import gzip
            n = 0
            with gzip.open(fp, "rt", encoding="utf-8", errors="ignore") as f:
                for n, _ in enumerate(f, start=1):
                    pass
            return max(0, n - 1)

        if suf == ".csv":
            n = 0
            with open(fp, "rt", encoding="utf-8", errors="ignore") as f:
                for n, _ in enumerate(f, start=1):
                    pass
            return max(0, n - 1)

    except Exception:
        return 0

    return 0


# =============================================================================
# SMALL HELPERS
# =============================================================================
def _save_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _load_phase7_drop_list(path: Path) -> List[str]:
    """
    Supports:
    - list[str]
    - dict with keys like 'features_to_drop_for_modeling'
    """
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(obj, list):
        return [str(x) for x in obj if str(x).strip()]

    if isinstance(obj, dict):
        for key in ("features_to_drop_for_modeling", "features_to_drop", "drop_cols"):
            v = obj.get(key)
            if isinstance(v, list):
                return [str(x) for x in v if str(x).strip()]

    return []


def _ensure_target_binary_inplace(df: pd.DataFrame, target_col: str) -> None:
    if target_col not in df.columns:
        raise RuntimeError(
            f"Target column missing: {target_col}. Fix upstream phases. DO NOT synthesize labels."
        )
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    df[target_col] = (y == 1).astype(int)


def _maybe_drop_raw_cols(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    raw_cols = [c for c in df.columns if str(c).endswith("_raw")]
    if not raw_cols:
        return df, []
    return df.drop(columns=raw_cols, errors="ignore"), raw_cols


def _read_shard(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _read_shard_sample(path: Path, nrows: int) -> pd.DataFrame:
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
                return pd.read_parquet(path).head(nrows)
            except Exception:
                return pd.DataFrame()

    try:
        return pd.read_csv(path, nrows=nrows)
    except Exception:
        return pd.DataFrame()


def _iter_shard_files(root: Path, sub: str) -> List[Path]:
    d = Path(root) / sub
    return sorted(d.glob("part-*.parquet")) + sorted(d.glob("part-*.csv.gz"))


class _StreamCSVWriter:
    """
    Streaming CSV writer (supports gzip) that writes in chunks without holding all data in RAM.
    """
    def __init__(self, path: Path, *, compress: bool):
        self.path = Path(path)
        self.compress = bool(compress)
        self._fh = None
        self._header_written = False

    def __enter__(self):
        if self.compress:
            import gzip
            self._fh = gzip.open(self.path, "wt", encoding="utf-8", newline="")
        else:
            self._fh = open(self.path, "w", encoding="utf-8", newline="")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass

    def write_df(self, df: pd.DataFrame):
        if df is None or len(df) == 0:
            return
        df.to_csv(self._fh, index=False, header=(not self._header_written))
        self._header_written = True


def _rng_choice_rows(df: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    if n <= 0 or df is None or len(df) == 0:
        return df.iloc[:0].copy()
    if n >= len(df):
        return df.copy()
    idx = rng.choice(len(df), size=n, replace=False)
    return df.iloc[idx].copy()


def _split_attack_counts(attack_take: int, train_ratio: float, test_ratio: float) -> tuple[int, int]:
    tr = float(train_ratio)
    te = float(test_ratio)
    if tr < 0:
        tr = 0.0
    if te < 0:
        te = 0.0

    if attack_take <= 1:
        return attack_take, 0

    n_atk_train = int(round(attack_take * tr))
    n_atk_train = min(max(n_atk_train, 1), attack_take - 1)
    n_atk_test = attack_take - n_atk_train

    n_atk_test_exp = int(round(attack_take * te))
    n_atk_test_exp = min(max(n_atk_test_exp, 1), attack_take - 1)

    if abs(n_atk_test_exp - n_atk_test) >= max(2, int(0.01 * attack_take)):
        n_atk_test = n_atk_test_exp
        n_atk_train = attack_take - n_atk_test

    return n_atk_train, n_atk_test


def _allocate_benign_counts(
    cfg: Phase8Config,
    n_atk_train: int,
    n_atk_test: int,
    benign_pool_take: int,
) -> tuple[int, int, int, int]:
    """
    Returns (ben_train_keep, ben_test_keep, ben_stress_keep, unused_benign)

    If cfg.train_total_rows_target is set (>0), override TRAIN benign so that:
      train_total_rows ~= train_total_rows_target
    while keeping:
      - attack split unchanged (train/test driven by attacks)
      - test_benign_mode="remainder" => test gets ALL remaining benign in pool
    """
    train_total_target = getattr(cfg, "train_total_rows_target", None)
    try:
        train_total_target = int(train_total_target) if train_total_target is not None else None
    except Exception:
        train_total_target = None
    if train_total_target is not None and train_total_target <= 0:
        train_total_target = None

    test_mode = str(getattr(cfg, "test_benign_mode", "cap")).lower().strip()

    # ---- TRAIN ----
    if train_total_target is not None:
        if train_total_target <= n_atk_train:
            raise RuntimeError(
                f"train_total_rows_target must be > attack_train. "
                f"Got target={train_total_target:,}, attack_train={n_atk_train:,}."
            )

        desired_ben_train = int(train_total_target - n_atk_train)

        if test_mode == "remainder" and n_atk_test > 0 and benign_pool_take > 0:
            desired_ben_train = min(desired_ben_train, benign_pool_take - 1)

        desired_ben_train = max(0, desired_ben_train)
        ben_train_keep = min(desired_ben_train, benign_pool_take)

        if benign_pool_take > 0 and n_atk_train > 0 and ben_train_keep == 0:
            ben_train_keep = 1

    else:
        train_mode = str(getattr(cfg, "train_benign_mode", "cap")).lower().strip()
        if train_mode == "balanced":
            desired_ben_train = int(n_atk_train)
        else:
            tr_ratio = float(cfg.train_benign_per_attack)
            if tr_ratio < 0:
                tr_ratio = 0.0
            desired_ben_train = int(np.ceil(tr_ratio * n_atk_train))

        if test_mode == "remainder" and n_atk_test > 0 and benign_pool_take > 0:
            desired_ben_train = min(int(desired_ben_train), benign_pool_take - 1)

        ben_train_keep = min(int(desired_ben_train), benign_pool_take)

        if benign_pool_take > 0 and n_atk_train > 0 and ben_train_keep == 0:
            ben_train_keep = 1

    rem = max(0, benign_pool_take - ben_train_keep)

    # ---- TEST ----
    if n_atk_test <= 0:
        ben_test_keep = 0
    elif test_mode == "remainder":
        ben_test_keep = rem
    else:
        te_ratio = float(cfg.test_benign_per_attack)
        if te_ratio < 0:
            te_ratio = 0.0
        desired_ben_test = int(np.ceil(te_ratio * n_atk_test))
        ben_test_keep = min(desired_ben_test, rem)

    rem2 = max(0, rem - ben_test_keep)

    # ---- STRESS ----
    stress_n = 0
    if cfg.stress_benign_n is not None:
        try:
            stress_n = int(cfg.stress_benign_n)
        except Exception:
            stress_n = 0
    if stress_n < 0:
        stress_n = 0

    ben_stress_keep = min(stress_n, rem2)
    unused = int(max(0, benign_pool_take - (ben_train_keep + ben_test_keep + ben_stress_keep)))
    return int(ben_train_keep), int(ben_test_keep), int(ben_stress_keep), unused


# =============================================================================
# MODELING / NUMERIC COERCION HELPERS
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
    """
    Convert bool / boolean-like string / numeric-like object to numeric Series.
    Non-convertible values become NaN.
    """
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


def _coerce_or_drop_feature_columns(
    df: pd.DataFrame,
    cfg: Phase8Config,
) -> tuple[pd.DataFrame, dict]:
    """
    Coerce numeric-like columns first, then optionally drop truly non-numeric columns.
    This is the key fix: DO NOT drop object/category/bool columns before coercion.
    """
    out = df.copy()

    coerced_numeric: list[str] = []
    dropped_non_numeric: list[str] = []
    kept_numeric: list[str] = []
    all_nan_after_coercion: list[str] = []
    conversion_details: dict[str, dict[str, Any]] = {}

    min_fraction = float(getattr(cfg, "numeric_coercion_min_fraction", 0.80))
    min_fraction = min(max(min_fraction, 0.0), 1.0)
    do_coerce = bool(getattr(cfg, "coerce_numeric_like_for_model", True))
    drop_non_numeric = bool(getattr(cfg, "drop_non_numeric_for_model", True))

    for c in list(out.columns):
        if c == cfg.target_col:
            continue

        s = out[c]

        # Always force bool -> numeric, because downstream Phase 9/10/11 often use np.number filtering
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
            kept_numeric.append(c)
            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": "kept_numeric",
                "src_non_null": int(s.notna().sum()),
                "numeric_non_null": int(s.notna().sum()),
                "numeric_fraction": 1.0,
            }
            continue

        if not do_coerce:
            if drop_non_numeric:
                dropped_non_numeric.append(c)
                out = out.drop(columns=[c], errors="ignore")
            continue

        src_non_null = int(s.notna().sum())
        coerced = _series_to_numeric_like(s)
        numeric_non_null = int(coerced.notna().sum())
        frac = float(numeric_non_null / src_non_null) if src_non_null > 0 else 0.0

        if src_non_null > 0 and numeric_non_null == 0:
            all_nan_after_coercion.append(c)

        if numeric_non_null > 0 and frac >= min_fraction:
            out[c] = coerced
            coerced_numeric.append(c)
            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": "coerced_numeric",
                "src_non_null": src_non_null,
                "numeric_non_null": numeric_non_null,
                "numeric_fraction": round(frac, 6),
            }
        else:
            conversion_details[c] = {
                "source_dtype": str(s.dtype),
                "action": "dropped_non_numeric" if drop_non_numeric else "left_as_is",
                "src_non_null": src_non_null,
                "numeric_non_null": numeric_non_null,
                "numeric_fraction": round(frac, 6),
            }

            if drop_non_numeric:
                dropped_non_numeric.append(c)
                out = out.drop(columns=[c], errors="ignore")

    info = {
        "kept_numeric": kept_numeric,
        "coerced_numeric": coerced_numeric,
        "dropped_non_numeric": dropped_non_numeric,
        "all_nan_after_coercion": all_nan_after_coercion,
        "conversion_details": conversion_details,
        "final_columns_count_after_numeric_handling": int(len(out.columns)),
    }
    return out, info


def _prepare_drop_plan(cfg: Phase8Config) -> dict:
    drop_cols = set(cfg.drop_leak_cols) | set(cfg.extra_drop_cols)
    drop_cols.discard(cfg.target_col)

    phase7_drop_used: list[str] = []
    if cfg.phase7_drop_json is not None:
        p = Path(cfg.phase7_drop_json)
        if p.exists():
            phase7_drop_used = _load_phase7_drop_list(p)
            for c in phase7_drop_used:
                if c != cfg.target_col:
                    drop_cols.add(c)

    return {
        "drop_cols": sorted(list(drop_cols)),
        "drop_raw_cols_for_model": bool(cfg.drop_raw_cols_for_model),
        "drop_non_numeric_for_model": bool(cfg.drop_non_numeric_for_model),
        "coerce_numeric_like_for_model": bool(cfg.coerce_numeric_like_for_model),
        "numeric_coercion_min_fraction": float(cfg.numeric_coercion_min_fraction),
        "phase7_drop_used": phase7_drop_used,
        "phase7_drop_json": str(cfg.phase7_drop_json) if cfg.phase7_drop_json else None,
        "drop_leak_cols": list(cfg.drop_leak_cols),
        "extra_drop_cols": list(cfg.extra_drop_cols),
    }


def _apply_modeling_plan(
    df: pd.DataFrame,
    cfg: Phase8Config,
    plan: dict,
    *,
    final_feature_cols: Optional[List[str]] = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Unified transform used by both in-memory mode and shard mode.
    If final_feature_cols is provided, enforce stable schema/order across shards.
    """
    out = df.copy()
    _ensure_target_binary_inplace(out, cfg.target_col)

    before_cols = list(out.columns)

    drop_cols: List[str] = plan.get("drop_cols", [])
    if drop_cols:
        out = out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")

    raw_dropped: list[str] = []
    if plan.get("drop_raw_cols_for_model", True):
        out, raw_dropped = _maybe_drop_raw_cols(out)

    out, num_info = _coerce_or_drop_feature_columns(out, cfg)

    # enforce stable feature schema across shards
    if final_feature_cols is not None:
        desired = [cfg.target_col] + [c for c in final_feature_cols if c != cfg.target_col]

        # add missing feature columns as NaN
        for c in desired:
            if c not in out.columns:
                if c == cfg.target_col:
                    continue
                out[c] = np.nan

        # drop extras not in final schema
        extra_cols = [c for c in out.columns if c not in desired]
        if extra_cols:
            out = out.drop(columns=extra_cols, errors="ignore")

        # reorder
        out = out[desired]

    after_cols = list(out.columns)

    info = {
        "drop_cols_applied_count": int(len(set(before_cols) - set(after_cols))),
        "drop_leak_cols": list(plan.get("drop_leak_cols", [])),
        "extra_drop_cols": list(plan.get("extra_drop_cols", [])),
        "phase7_drop_json": plan.get("phase7_drop_json"),
        "phase7_drop_used": list(plan.get("phase7_drop_used", [])),
        "raw_dropped": raw_dropped,
        "drop_non_numeric_for_model": bool(plan.get("drop_non_numeric_for_model", True)),
        "coerce_numeric_like_for_model": bool(plan.get("coerce_numeric_like_for_model", True)),
        "numeric_coercion_min_fraction": float(plan.get("numeric_coercion_min_fraction", 0.80)),
        "non_numeric_dropped": list(num_info.get("dropped_non_numeric", [])),
        "coerced_numeric": list(num_info.get("coerced_numeric", [])),
        "kept_numeric": list(num_info.get("kept_numeric", [])),
        "all_nan_after_coercion": list(num_info.get("all_nan_after_coercion", [])),
        "final_columns_count": int(len(after_cols)),
        "final_feature_columns": [c for c in after_cols if c != cfg.target_col],
    }
    return out, info


def _infer_final_feature_cols_from_shards(
    cfg: Phase8Config,
    plan: dict,
    atk_files: List[Path],
    ben_files: List[Path],
) -> tuple[List[str], dict]:
    """
    Probe a few shard samples to infer a stable final modeling schema.
    This avoids per-shard dtype-driven column drift in streamed CSV outputs.
    """
    n_files = max(1, int(getattr(cfg, "schema_sample_files_per_class", 3)))
    n_rows = max(50, int(getattr(cfg, "schema_sample_rows_per_file", 2000)))

    probe_files = list(atk_files[:n_files]) + list(ben_files[:n_files])

    ordered_cols: list[str] = []
    seen_cols: set[str] = set()

    probe_info = {
        "probe_files": [str(p) for p in probe_files],
        "probe_rows_per_file": int(n_rows),
        "probed_files_count": int(len(probe_files)),
        "kept_from_probe": [],
        "coerced_from_probe": [],
        "dropped_non_numeric_from_probe": [],
    }

    kept_accum: set[str] = set()
    coerced_accum: set[str] = set()
    dropped_accum: set[str] = set()

    for fp in probe_files:
        sample = _read_shard_sample(fp, n_rows)
        if sample is None or len(sample) == 0:
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

    probe_info["kept_from_probe"] = sorted(list(kept_accum))
    probe_info["coerced_from_probe"] = sorted(list(coerced_accum))
    probe_info["dropped_non_numeric_from_probe"] = sorted(list(dropped_accum))

    if not ordered_cols:
        raise RuntimeError(
            "Failed to infer final modeling feature columns from shard samples. "
            "All probed shards became empty after drop/coercion."
        )

    return ordered_cols, probe_info


def _normalize_phase8_export_medium_format(fmt: str) -> str:
    x = str(fmt or "csv").strip().lower()
    return "parquet" if x == "parquet" else "csv"


def _resolve_phase8_export_medium_dir(cfg: Phase8Config) -> Path:
    if cfg.phase_8_export_medium_dir is not None:
        return Path(cfg.phase_8_export_medium_dir)

    if cfg.out_dir is not None:
        out_dir = Path(cfg.out_dir)
        if "phase8" in out_dir.name.lower():
            return out_dir.parent / "phase8_dataset_for_p10"
        return out_dir / "phase8_dataset_for_p10"

    return Path("results/eve_json/phase8_dataset_for_p10")


def _export_phase8_medium_dataset(
    df_train_medium: pd.DataFrame,
    df_test_medium: pd.DataFrame,
    cfg: Phase8Config,
) -> dict:
    paths = {
        "format": None,
        "dir": None,
        "train_csv": None,
        "test_csv": None,
        "train_parquet": None,
        "test_parquet": None,
        "train_rows": int(len(df_train_medium)),
        "test_rows": int(len(df_test_medium)),
    }

    if not bool(getattr(cfg, "phase_8_export_medium", False)):
        return paths

    out_dir = _resolve_phase8_export_medium_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt = _normalize_phase8_export_medium_format(getattr(cfg, "phase_8_export_medium_format", "csv"))
    paths["format"] = fmt
    paths["dir"] = str(out_dir)

    if fmt == "parquet":
        p_train = out_dir / "train.parquet"
        p_test = out_dir / "test.parquet"
        df_train_medium.to_parquet(p_train, index=False)
        df_test_medium.to_parquet(p_test, index=False)
        paths["train_parquet"] = str(p_train)
        paths["test_parquet"] = str(p_test)
    else:
        p_train = out_dir / "train.csv"
        p_test = out_dir / "test.csv"
        df_train_medium.to_csv(p_train, index=False)
        df_test_medium.to_csv(p_test, index=False)
        paths["train_csv"] = str(p_train)
        paths["test_csv"] = str(p_test)

    return paths


# =============================================================================
# PHASE 8 (MAIN)
# =============================================================================
def phase8_build_model_splits(df_clean: Optional[pd.DataFrame], cfg: Phase8Config) -> Dict[str, Any]:
    """
    Phase 8:
    - If cfg.input_dir is None: use in-memory df_clean.
    - If cfg.input_dir is set: read attacks/benign shards from disk and stream-write outputs.
    """
    if cfg.input_dir is None:
        return _phase8_in_memory(df_clean, cfg)
    return _phase8_from_shards(cfg)


def _phase8_in_memory(df_clean: Optional[pd.DataFrame], cfg: Phase8Config) -> Dict[str, Any]:
    """
    In-memory Phase 8 (drop/coerce-for-modeling + split).
    """
    t0 = datetime.now()
    if df_clean is None or len(df_clean) == 0:
        raise RuntimeError("Empty df_clean. Upstream phases produced no data.")

    plan = _prepare_drop_plan(cfg)
    df, drop_info = _apply_modeling_plan(df_clean, cfg, plan, final_feature_cols=None)

    y = df[cfg.target_col].to_numpy()
    atk_idx = np.where(y == 1)[0]
    ben_idx = np.where(y == 0)[0]

    atk_src = int(len(atk_idx))
    ben_src = int(len(ben_idx))
    rows_src = int(len(df))

    if atk_src == 0:
        raise RuntimeError("No attack rows found (Target==1). Check labeling rules upstream.")

    rng = np.random.default_rng(cfg.seed)

    attack_take_raw = int(round(atk_src * float(cfg.attack_fraction)))
    attack_take = min(max(attack_take_raw, 0), atk_src)

    if attack_take < cfg.min_attack_required:
        raise RuntimeError(f"Attack too small for modeling: attack_take={attack_take} (available={atk_src}).")

    atk_pick = atk_idx if attack_take == atk_src else rng.choice(atk_idx, size=attack_take, replace=False)

    pool_ratio = float(cfg.pool_benign_per_attack)
    if pool_ratio < 0:
        pool_ratio = 0.0

    desired_ben_pool = int(np.ceil(pool_ratio * attack_take))
    benign_pool_take = min(desired_ben_pool, ben_src)
    ben_pool_pick = rng.choice(ben_idx, size=benign_pool_take, replace=False) if benign_pool_take > 0 else np.array([], dtype=int)

    n_atk_train, n_atk_test = _split_attack_counts(attack_take, cfg.train_ratio, cfg.test_ratio)

    atk_perm = rng.permutation(atk_pick)
    atk_test_pick = atk_perm[:n_atk_test]
    atk_train_pick = atk_perm[n_atk_test:]

    atk_train_n = int(len(atk_train_pick))
    atk_test_n = int(len(atk_test_pick))

    if atk_train_n < cfg.min_attack_required:
        raise RuntimeError(
            f"Attack too small in TRAIN after split: atk_train={atk_train_n} (attack_take={attack_take})"
        )

    ben_train_keep, ben_test_keep, ben_stress_keep, unused_benign = _allocate_benign_counts(
        cfg=cfg,
        n_atk_train=atk_train_n,
        n_atk_test=atk_test_n,
        benign_pool_take=benign_pool_take,
    )
    stress_enabled = ben_stress_keep > 0

    ben_pool_perm = rng.permutation(ben_pool_pick) if len(ben_pool_pick) else np.array([], dtype=int)

    offset = 0
    ben_train_pick = ben_pool_perm[offset:offset + ben_train_keep] if ben_train_keep > 0 else np.array([], dtype=int)
    offset += ben_train_keep

    ben_test_pick = ben_pool_perm[offset:offset + ben_test_keep] if ben_test_keep > 0 else np.array([], dtype=int)
    offset += ben_test_keep

    ben_stress_pick = ben_pool_perm[offset:offset + ben_stress_keep] if ben_stress_keep > 0 else np.array([], dtype=int)

    train_pick = np.concatenate([atk_train_pick, ben_train_pick]) if ben_train_keep else atk_train_pick
    test_pick = np.concatenate([atk_test_pick, ben_test_pick]) if ben_test_keep else atk_test_pick

    rng.shuffle(train_pick)
    rng.shuffle(test_pick)

    df_train = df.iloc[train_pick].reset_index(drop=True)
    df_test_fair = df.iloc[test_pick].reset_index(drop=True)

    df_stress_benign = None
    if stress_enabled:
        df_stress_benign = df.iloc[ben_stress_pick].reset_index(drop=True)

    df_pool = None
    if cfg.export_pool:
        pool_pick = np.concatenate([atk_pick, ben_pool_pick]) if benign_pool_take else atk_pick
        rng.shuffle(pool_pick)
        df_pool = df.iloc[pool_pick].reset_index(drop=True)

    medium_paths = _export_phase8_medium_dataset(df_train, df_test_fair, cfg)

    def _dist(dfx: pd.DataFrame) -> Dict[int, int]:
        vc = dfx[cfg.target_col].value_counts().to_dict()
        return {int(k): int(v) for k, v in vc.items()}

    meta = {
        "phase": 8,
        "mode": "in_memory",
        "created_at": datetime.now().isoformat(),
        "rows_source": rows_src,
        "attack_source": atk_src,
        "benign_source": ben_src,
        "attack_fraction": float(cfg.attack_fraction),
        "attack_take": int(attack_take),
        "pool_benign_per_attack": float(cfg.pool_benign_per_attack),
        "benign_pool_take": int(benign_pool_take),
        "train_ratio_cfg": float(cfg.train_ratio),
        "test_ratio_cfg": float(cfg.test_ratio),
        "attack_train": int(atk_train_n),
        "attack_test": int(atk_test_n),
        "train_benign_mode": str(cfg.train_benign_mode),
        "test_benign_mode": str(cfg.test_benign_mode),
        "train_benign_per_attack": float(cfg.train_benign_per_attack),
        "test_benign_per_attack": float(cfg.test_benign_per_attack),
        "stress_benign_n": int(cfg.stress_benign_n or 0),
        "train_total_rows_target": int(cfg.train_total_rows_target) if cfg.train_total_rows_target else None,
        "benign_train_keep": int(ben_train_keep),
        "benign_test_keep": int(ben_test_keep),
        "benign_test_fair_keep": int(ben_test_keep),
        "benign_stress_keep": int(ben_stress_keep),
        "unused_benign_in_pool": int(unused_benign),
        "dist_train": _dist(df_train),
        "dist_test_fair": _dist(df_test_fair),
        "dist_stress_benign": {0: int(len(df_stress_benign))} if isinstance(df_stress_benign, pd.DataFrame) else None,
        "drop_strategy": drop_info,
        "seed": int(cfg.seed),
        "export_pool": bool(cfg.export_pool),
        "phase_8_export_medium": bool(cfg.phase_8_export_medium),
        "paths_medium_for_phase10": medium_paths,
    }

    paths: Dict[str, Optional[str]] = {
        "pool_csv": None,
        "train_csv": None,
        "test_fair_csv": None,
        "stress_benign_csv": None,
        "meta_json": None,
    }
    paths_extra: Dict[str, Optional[str]] = {}

    if cfg.out_dir is not None:
        cfg.out_dir.mkdir(parents=True, exist_ok=True)

        key = (
            f"atk{attack_take}_benPOOL{benign_pool_take}"
            f"_tr{int(cfg.train_ratio*100)}_te{int(cfg.test_ratio*100)}"
            f"_trainMODE{cfg.train_benign_mode}_testMODE{cfg.test_benign_mode}"
            f"_trainUB{cfg.train_benign_per_attack}_testUB{cfg.test_benign_per_attack}"
            f"_stress{ben_stress_keep}_seed{cfg.seed}"
        )
        stem = f"model_{cfg.filename_tag}_{key}"

        suffix = ".csv.gz" if cfg.compress else ".csv"
        comp = "gzip" if cfg.compress else None

        p_train = cfg.out_dir / f"{stem}__train{suffix}"
        p_test = cfg.out_dir / f"{stem}__testFAIR{suffix}"
        p_meta = cfg.out_dir / f"{stem}__meta.json"

        df_train.to_csv(p_train, index=False, compression=comp)
        df_test_fair.to_csv(p_test, index=False, compression=comp)

        paths["train_csv"] = str(p_train)
        paths["test_fair_csv"] = str(p_test)
        paths["meta_json"] = str(p_meta)

        if isinstance(df_stress_benign, pd.DataFrame):
            p_stress = cfg.out_dir / f"{stem}__stressBENIGN{suffix}"
            df_stress_benign.to_csv(p_stress, index=False, compression=comp)
            paths["stress_benign_csv"] = str(p_stress)

        if cfg.export_pool and isinstance(df_pool, pd.DataFrame):
            p_pool = cfg.out_dir / f"{stem}__pool{suffix}"
            df_pool.to_csv(p_pool, index=False, compression=comp)
            paths["pool_csv"] = str(p_pool)

        meta["paths"] = paths
        meta["paths_extra"] = paths_extra
        _save_json(meta, p_meta)

    dt = (datetime.now() - t0).total_seconds()
    summary = {
        "phase": 8,
        "seconds": dt,
        "meta": meta,
        "paths": paths,
        "paths_extra": paths_extra,
        "paths_medium_for_phase10": medium_paths,
    }

    print("\n✅ PHASE 8 COMPLETE (Split + Drop/Coerce-for-Modeling)")
    print(f"   Mode        : in_memory")
    print(f"   Source rows : {rows_src:,} | atk={atk_src:,} | ben={ben_src:,}")
    print(f"   Attack take : {attack_take:,} (fraction={cfg.attack_fraction:g})")
    print(f"   Benign pool : {benign_pool_take:,} (pool_benign_per_attack={cfg.pool_benign_per_attack:g})")
    print(f"   Train       : rows={len(df_train):,} | dist={_dist(df_train)}")
    print(f"   Test (fair) : rows={len(df_test_fair):,} | dist={_dist(df_test_fair)}")
    print(f"   Stress      : benign={ben_stress_keep:,} (file={'ON' if stress_enabled else 'OFF'})")
    print(f"   Final cols  : {drop_info.get('final_columns_count', 0)}")
    if medium_paths.get("dir"):
        print(f"   Medium exp  : {medium_paths.get('dir')}")

    return {
        "df_train": df_train,
        "df_test_fair": df_test_fair,
        "df_stress_benign": df_stress_benign,
        "df_pool": df_pool,
        "summary": summary,
    }


def _phase8_from_shards(cfg: Phase8Config) -> Dict[str, Any]:
    """
    Sharded mode (disk):
    - reads attacks/benign shards from cfg.input_dir
    - writes split outputs (ATTACK/BENIGN) for train/test (recommended)
    - writes combined outputs (optional)
    - returns only small/medium samples for downstream pipeline safety
    """
    t0 = datetime.now()
    t0_perf = time.perf_counter()

    prog_enabled = bool(getattr(cfg, "progress_enabled", True))
    prog_every = float(getattr(cfg, "progress_every_seconds", 10.0))
    width = int(getattr(cfg, "progress_line_width", 160))
    prog = _ProgressThrottle(prog_enabled, prog_every)

    if cfg.input_dir is None:
        raise RuntimeError("cfg.input_dir is None in shard mode.")
    if cfg.out_dir is None:
        raise RuntimeError("cfg.out_dir must be set for shard mode (we stream outputs to disk).")

    in_dir = Path(cfg.input_dir)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    atk_files = _iter_shard_files(in_dir, "attacks")
    ben_files = _iter_shard_files(in_dir, "benign")
    if not atk_files:
        raise RuntimeError(f"No attack shards found under: {in_dir / 'attacks'}")
    if not ben_files:
        print(f"⚠️  No benign shards found under: {in_dir / 'benign'} (benign_pool may be 0)")

    print("\n" + "=" * 80)
    print("🚧 PHASE 8 START (Sharded Split + Drop/Coerce-for-Modeling)")
    print("=" * 80)
    print(f"[{_ts()}] Input dir: {in_dir}")
    print(f"[{_ts()}] Shards   : attacks={len(atk_files):,} | benign={len(ben_files):,}")
    print(f"[{_ts()}] Params   : attack_fraction={cfg.attack_fraction:g} | train_ratio={cfg.train_ratio:g} | test_ratio={cfg.test_ratio:g}")
    print(f"[{_ts()}] Pool     : pool_benign_per_attack={cfg.pool_benign_per_attack:g}")
    if cfg.train_total_rows_target:
        print(f"[{_ts()}] Train cap: train_total_rows_target={int(cfg.train_total_rows_target):,}")
    print("=" * 80, flush=True)

    rng = np.random.default_rng(cfg.seed)
    drop_plan = _prepare_drop_plan(cfg)

    # ------------------------------------------------------------------
    # COUNT SOURCES
    # ------------------------------------------------------------------
    print(f"\n[{_ts()}] 🔢 Counting rows (fast parquet metadata) ...", flush=True)

    atk_src = 0
    prog.force()
    for i, fp in enumerate(atk_files, start=1):
        atk_src += _count_rows_fast(fp)
        if prog.should_print():
            elapsed = time.perf_counter() - t0_perf
            _progress_line(
                f"[{_ts()}] counting ATTACK  | file {i:,}/{len(atk_files):,} | rows={atk_src:,} | elapsed={_fmt_elapsed(elapsed)}",
                width=width,
            )
    if prog_enabled:
        _progress_done()

    ben_src = 0
    prog.force()
    for i, fp in enumerate(ben_files, start=1):
        ben_src += _count_rows_fast(fp)
        if prog.should_print():
            elapsed = time.perf_counter() - t0_perf
            _progress_line(
                f"[{_ts()}] counting BENIGN  | file {i:,}/{len(ben_files):,} | rows={ben_src:,} | elapsed={_fmt_elapsed(elapsed)}",
                width=width,
            )
    if prog_enabled:
        _progress_done()

    if atk_src <= 0:
        raise RuntimeError("No attack rows found in shard input (attacks shards empty).")

    # ------------------------------------------------------------------
    # INFER STABLE FINAL FEATURE SCHEMA
    # ------------------------------------------------------------------
    print(f"\n[{_ts()}] 🧪 Probing shard samples to infer stable model schema ...", flush=True)
    final_feature_cols, schema_probe_info = _infer_final_feature_cols_from_shards(
        cfg=cfg,
        plan=drop_plan,
        atk_files=atk_files,
        ben_files=ben_files,
    )
    print(f"[{_ts()}] ✅ Stable feature schema inferred: {len(final_feature_cols):,} features", flush=True)

    # ---- decide plan ----
    attack_fraction = float(cfg.attack_fraction)
    attack_fraction = min(max(attack_fraction, 0.0), 1.0)
    attack_take = int(round(atk_src * attack_fraction))
    attack_take = min(max(attack_take, 0), atk_src)

    if attack_take < cfg.min_attack_required:
        raise RuntimeError(f"Attack too small for modeling: attack_take={attack_take} (available={atk_src}).")

    pool_ratio = float(cfg.pool_benign_per_attack)
    if pool_ratio < 0:
        pool_ratio = 0.0
    desired_ben_pool = int(np.ceil(pool_ratio * attack_take))
    benign_pool_take = min(desired_ben_pool, ben_src)

    n_atk_train, n_atk_test = _split_attack_counts(attack_take, cfg.train_ratio, cfg.test_ratio)

    ben_train_keep, ben_test_keep, ben_stress_keep, unused_benign = _allocate_benign_counts(
        cfg=cfg,
        n_atk_train=n_atk_train,
        n_atk_test=n_atk_test,
        benign_pool_take=benign_pool_take,
    )
    stress_enabled = (ben_stress_keep > 0)

    print(f"\n[{_ts()}] ✅ Plan decided:")
    print(f"   attack_src={atk_src:,} -> attack_take={attack_take:,}")
    print(f"   attack split: train={n_atk_train:,} | test={n_atk_test:,}")
    print(f"   benign_src={ben_src:,} -> benign_pool_take={benign_pool_take:,}")
    print(f"   benign alloc: train={ben_train_keep:,} | test={ben_test_keep:,} | stress={ben_stress_keep:,} | unused_in_pool={unused_benign:,}")
    print(f"   stable_feature_cols={len(final_feature_cols):,}")

    key = (
        f"atk{attack_take}_benPOOL{benign_pool_take}"
        f"_tr{int(cfg.train_ratio*100)}_te{int(cfg.test_ratio*100)}"
        f"_trainMODE{cfg.train_benign_mode}_testMODE{cfg.test_benign_mode}"
        f"_trainUB{cfg.train_benign_per_attack}_testUB{cfg.test_benign_per_attack}"
        f"_stress{ben_stress_keep}_seed{cfg.seed}"
    )
    stem = f"model_{cfg.filename_tag}_{key}"
    suffix = ".csv.gz" if cfg.compress else ".csv"

    # split outputs (recommended)
    p_train_atk = out_dir / f"{stem}__train_ATTACK{suffix}"
    p_train_ben = out_dir / f"{stem}__train_BENIGN{suffix}"
    p_test_atk  = out_dir / f"{stem}__testFAIR_ATTACK{suffix}"
    p_test_ben  = out_dir / f"{stem}__testFAIR_BENIGN{suffix}"

    # combined outputs (optional)
    p_train = out_dir / f"{stem}__train{suffix}"
    p_test  = out_dir / f"{stem}__testFAIR{suffix}"

    p_meta   = out_dir / f"{stem}__meta.json"
    p_stress = out_dir / f"{stem}__stressBENIGN{suffix}"

    # in-memory return samples (pipeline safety)
    train_total = max(0, int(cfg.return_train_rows))
    test_total = max(0, int(cfg.return_test_rows))

    train_atk_left = max(1, train_total // 2) if train_total > 1 else train_total
    train_ben_left = max(0, train_total - train_atk_left)

    test_atk_left = max(1, test_total // 2) if test_total > 1 else test_total
    test_ben_left = max(0, test_total - test_atk_left)

    df_train_sample_parts_atk: List[pd.DataFrame] = []
    df_train_sample_parts_ben: List[pd.DataFrame] = []
    df_test_sample_parts_atk: List[pd.DataFrame] = []
    df_test_sample_parts_ben: List[pd.DataFrame] = []

    pool_left = max(0, int(cfg.return_pool_rows)) if cfg.export_pool else 0
    df_pool_sample_parts: List[pd.DataFrame] = []

    atk_files_shuffled = list(atk_files)
    rng.shuffle(atk_files_shuffled)
    ben_files_shuffled = list(ben_files)
    rng.shuffle(ben_files_shuffled)

    atk_taken = 0
    atk_train_written = 0
    atk_test_written = 0

    ben_taken_into_pool = 0
    ben_train_written = 0
    ben_test_written = 0
    ben_stress_written = 0

    # optional combined writers
    ctx_train_comb = _StreamCSVWriter(p_train, compress=cfg.compress) if cfg.export_combined_train_test else nullcontext()
    ctx_test_comb  = _StreamCSVWriter(p_test,  compress=cfg.compress) if cfg.export_combined_train_test else nullcontext()
    ctx_stress     = _StreamCSVWriter(p_stress, compress=cfg.compress) if stress_enabled else nullcontext()

    print(f"\n[{_ts()}] ✍️  Writing outputs ...", flush=True)

    with (
        _StreamCSVWriter(p_train_atk, compress=cfg.compress) as w_train_atk,
        _StreamCSVWriter(p_test_atk,  compress=cfg.compress) as w_test_atk,
        _StreamCSVWriter(p_train_ben, compress=cfg.compress) as w_train_ben,
        _StreamCSVWriter(p_test_ben,  compress=cfg.compress) as w_test_ben,
        ctx_train_comb as w_train,
        ctx_test_comb as w_test,
        ctx_stress as w_stress,
    ):
        # -------------------------
        # ATTACK PASS
        # -------------------------
        print(f"[{_ts()}] ▶ ATTACK pass ...", flush=True)
        prog.force()

        for fp in atk_files_shuffled:
            if atk_taken >= attack_take:
                break

            df = _read_shard(fp)
            if df is None or len(df) == 0:
                continue

            df, _ = _apply_modeling_plan(df, cfg, drop_plan, final_feature_cols=final_feature_cols)

            if cfg.target_col in df.columns:
                df = df[df[cfg.target_col] == 1]
            if len(df) == 0:
                continue

            need = attack_take - atk_taken
            take_n = min(need, len(df))
            df_take = _rng_choice_rows(df, take_n, rng)

            # split: test then train
            if atk_test_written < n_atk_test:
                test_need = n_atk_test - atk_test_written
                df_test_part = df_take.iloc[:min(test_need, len(df_take))].copy()
                df_train_part = df_take.iloc[len(df_test_part):].copy()
            else:
                df_test_part = df_take.iloc[:0].copy()
                df_train_part = df_take

            if len(df_test_part) > 1:
                df_test_part = df_test_part.sample(frac=1.0, random_state=int(cfg.seed), replace=False).reset_index(drop=True)
            if len(df_train_part) > 1:
                df_train_part = df_train_part.sample(frac=1.0, random_state=int(cfg.seed), replace=False).reset_index(drop=True)

            w_test_atk.write_df(df_test_part)
            w_train_atk.write_df(df_train_part)

            if cfg.export_combined_train_test:
                w_test.write_df(df_test_part)   # type: ignore
                w_train.write_df(df_train_part) # type: ignore

            atk_taken += int(len(df_take))
            atk_test_written += int(len(df_test_part))
            atk_train_written += int(len(df_train_part))

            if test_atk_left > 0 and len(df_test_part) > 0:
                take = min(test_atk_left, len(df_test_part))
                df_test_sample_parts_atk.append(df_test_part.iloc[:take].copy())
                test_atk_left -= take
            if train_atk_left > 0 and len(df_train_part) > 0:
                take = min(train_atk_left, len(df_train_part))
                df_train_sample_parts_atk.append(df_train_part.iloc[:take].copy())
                train_atk_left -= take

            if cfg.export_pool and pool_left > 0 and len(df_take) > 0:
                take = min(pool_left, len(df_take))
                df_pool_sample_parts.append(df_take.iloc[:take].copy())
                pool_left -= take

            if prog.should_print():
                elapsed = time.perf_counter() - t0_perf
                pct = (atk_taken / max(1, attack_take)) * 100.0
                _progress_line(
                    f"[{_ts()}] ATTACK  {pct:5.1f}% | taken {atk_taken:,}/{attack_take:,} | "
                    f"train {atk_train_written:,}/{n_atk_train:,} | test {atk_test_written:,}/{n_atk_test:,} | elapsed {_fmt_elapsed(elapsed)}",
                    width=width,
                )

            del df, df_take, df_test_part, df_train_part

        if prog_enabled:
            _progress_done()

        if atk_train_written < cfg.min_attack_required:
            raise RuntimeError(
                f"Attack too small in TRAIN after shard split: atk_train_written={atk_train_written} "
                f"(attack_take={attack_take})."
            )

        print(f"[{_ts()}] ✅ ATTACK done | train={atk_train_written:,} test={atk_test_written:,}", flush=True)

        # -------------------------
        # BENIGN PASS
        # -------------------------
        print(f"\n[{_ts()}] ▶ BENIGN pass ...", flush=True)
        prog.force()

        for fp in ben_files_shuffled:
            if ben_taken_into_pool >= benign_pool_take:
                break
            if (ben_train_written >= ben_train_keep) and (ben_test_written >= ben_test_keep) and (ben_stress_written >= ben_stress_keep):
                break

            dfb = _read_shard(fp)
            if dfb is None or len(dfb) == 0:
                continue

            dfb, _ = _apply_modeling_plan(dfb, cfg, drop_plan, final_feature_cols=final_feature_cols)

            if cfg.target_col in dfb.columns:
                dfb = dfb[dfb[cfg.target_col] == 0]
            if len(dfb) == 0:
                continue

            need_pool = benign_pool_take - ben_taken_into_pool
            take_n = min(need_pool, len(dfb))
            df_take = _rng_choice_rows(dfb, take_n, rng)
            ben_taken_into_pool += int(len(df_take))

            # allocate: train -> test -> stress
            if ben_train_written < ben_train_keep and len(df_take) > 0:
                need = ben_train_keep - ben_train_written
                part = df_take.iloc[:min(need, len(df_take))].copy()
                if len(part) > 1:
                    part = part.sample(frac=1.0, random_state=int(cfg.seed), replace=False).reset_index(drop=True)

                w_train_ben.write_df(part)
                if cfg.export_combined_train_test:
                    w_train.write_df(part)  # type: ignore

                ben_train_written += int(len(part))

                if train_ben_left > 0 and len(part) > 0:
                    take = min(train_ben_left, len(part))
                    df_train_sample_parts_ben.append(part.iloc[:take].copy())
                    train_ben_left -= take

                df_take = df_take.iloc[len(part):].copy()

            if ben_test_written < ben_test_keep and len(df_take) > 0:
                need = ben_test_keep - ben_test_written
                part = df_take.iloc[:min(need, len(df_take))].copy()
                if len(part) > 1:
                    part = part.sample(frac=1.0, random_state=int(cfg.seed), replace=False).reset_index(drop=True)

                w_test_ben.write_df(part)
                if cfg.export_combined_train_test:
                    w_test.write_df(part)  # type: ignore

                ben_test_written += int(len(part))

                if test_ben_left > 0 and len(part) > 0:
                    take = min(test_ben_left, len(part))
                    df_test_sample_parts_ben.append(part.iloc[:take].copy())
                    test_ben_left -= take

                df_take = df_take.iloc[len(part):].copy()

            if stress_enabled and ben_stress_written < ben_stress_keep and len(df_take) > 0:
                need = ben_stress_keep - ben_stress_written
                part = df_take.iloc[:min(need, len(df_take))].copy()
                if len(part) > 1:
                    part = part.sample(frac=1.0, random_state=int(cfg.seed), replace=False).reset_index(drop=True)

                w_stress.write_df(part)  # type: ignore
                ben_stress_written += int(len(part))
                df_take = df_take.iloc[len(part):].copy()

            if cfg.export_pool and pool_left > 0 and len(dfb) > 0:
                take = min(pool_left, len(dfb))
                df_pool_sample_parts.append(dfb.iloc[:take].copy())
                pool_left -= take

            if prog.should_print():
                elapsed = time.perf_counter() - t0_perf
                pct = (ben_taken_into_pool / max(1, benign_pool_take)) * 100.0 if benign_pool_take > 0 else 100.0
                _progress_line(
                    f"[{_ts()}] BENIGN  {pct:5.1f}% | pool {ben_taken_into_pool:,}/{benign_pool_take:,} | "
                    f"train {ben_train_written:,}/{ben_train_keep:,} | test {ben_test_written:,}/{ben_test_keep:,} | "
                    f"stress {ben_stress_written:,}/{ben_stress_keep:,} | elapsed {_fmt_elapsed(elapsed)}",
                    width=width,
                )

            del dfb, df_take

        if prog_enabled:
            _progress_done()

        print(
            f"[{_ts()}] ✅ BENIGN done | train={ben_train_written:,} test={ben_test_written:,} stress={ben_stress_written:,}",
            flush=True
        )

    # build in-memory samples
    df_train_sample = (
        pd.concat(df_train_sample_parts_atk + df_train_sample_parts_ben, ignore_index=True)
        if (df_train_sample_parts_atk or df_train_sample_parts_ben)
        else pd.DataFrame(columns=[cfg.target_col] + final_feature_cols)
    )
    df_test_sample = (
        pd.concat(df_test_sample_parts_atk + df_test_sample_parts_ben, ignore_index=True)
        if (df_test_sample_parts_atk or df_test_sample_parts_ben)
        else pd.DataFrame(columns=[cfg.target_col] + final_feature_cols)
    )
    if len(df_train_sample) > 1 and cfg.target_col in df_train_sample.columns:
        df_train_sample = df_train_sample.sample(frac=1.0, random_state=int(cfg.seed)).reset_index(drop=True)
    if len(df_test_sample) > 1 and cfg.target_col in df_test_sample.columns:
        df_test_sample = df_test_sample.sample(frac=1.0, random_state=int(cfg.seed)).reset_index(drop=True)

    df_pool_sample = pd.concat(df_pool_sample_parts, ignore_index=True) if df_pool_sample_parts else None

    medium_paths = _export_phase8_medium_dataset(df_train_sample, df_test_sample, cfg)

    def _dist_counts(atk: int, ben: int) -> Dict[int, int]:
        return {1: int(atk), 0: int(ben)}

    paths = {
        "train_csv": str(p_train) if cfg.export_combined_train_test else None,
        "test_fair_csv": str(p_test) if cfg.export_combined_train_test else None,
        "stress_benign_csv": str(p_stress) if stress_enabled else None,
        "meta_json": str(p_meta),
    }
    paths_extra = {
        "train_attack_csv": str(p_train_atk) if cfg.export_split_attack_benign else None,
        "train_benign_csv": str(p_train_ben) if cfg.export_split_attack_benign else None,
        "test_attack_csv": str(p_test_atk) if cfg.export_split_attack_benign else None,
        "test_benign_csv": str(p_test_ben) if cfg.export_split_attack_benign else None,
    }

    meta = {
        "phase": 8,
        "mode": "sharded",
        "created_at": datetime.now().isoformat(),
        "input_dir": str(in_dir),
        "attack_source": int(atk_src),
        "benign_source": int(ben_src),
        "attack_fraction": float(cfg.attack_fraction),
        "attack_take": int(attack_take),
        "pool_benign_per_attack": float(cfg.pool_benign_per_attack),
        "benign_pool_take": int(benign_pool_take),
        "train_ratio_cfg": float(cfg.train_ratio),
        "test_ratio_cfg": float(cfg.test_ratio),
        "attack_train_target": int(n_atk_train),
        "attack_test_target": int(n_atk_test),
        "attack_train_written": int(atk_train_written),
        "attack_test_written": int(atk_test_written),
        "train_benign_mode": str(cfg.train_benign_mode),
        "test_benign_mode": str(cfg.test_benign_mode),
        "train_benign_per_attack": float(cfg.train_benign_per_attack),
        "test_benign_per_attack": float(cfg.test_benign_per_attack),
        "train_total_rows_target": int(cfg.train_total_rows_target) if cfg.train_total_rows_target else None,
        "benign_train_keep": int(ben_train_keep),
        "benign_test_keep": int(ben_test_keep),
        "benign_test_fair_keep": int(ben_test_keep),
        "benign_stress_keep": int(ben_stress_keep),
        "benign_train_written": int(ben_train_written),
        "benign_test_written": int(ben_test_written),
        "benign_test_fair_written": int(ben_test_written),
        "benign_stress_written": int(ben_stress_written),
        "unused_benign_in_pool": int(unused_benign),
        "dist_train_target": _dist_counts(atk_train_written, ben_train_written),
        "dist_test_fair_target": _dist_counts(atk_test_written, ben_test_written),
        "drop_strategy": {
            "drop_leak_cols": drop_plan.get("drop_leak_cols"),
            "extra_drop_cols": drop_plan.get("extra_drop_cols"),
            "phase7_drop_json": drop_plan.get("phase7_drop_json"),
            "phase7_drop_used": drop_plan.get("phase7_drop_used"),
            "drop_raw_cols_for_model": drop_plan.get("drop_raw_cols_for_model"),
            "drop_non_numeric_for_model": drop_plan.get("drop_non_numeric_for_model"),
            "coerce_numeric_like_for_model": drop_plan.get("coerce_numeric_like_for_model"),
            "numeric_coercion_min_fraction": drop_plan.get("numeric_coercion_min_fraction"),
        },
        "stable_model_feature_count": int(len(final_feature_cols)),
        "stable_model_feature_columns": final_feature_cols,
        "schema_probe": schema_probe_info,
        "paths": paths,
        "paths_extra": paths_extra,
        "seed": int(cfg.seed),
        "export_pool": bool(cfg.export_pool),
        "export_split_attack_benign": bool(cfg.export_split_attack_benign),
        "export_combined_train_test": bool(cfg.export_combined_train_test),
        "phase_8_export_medium": bool(cfg.phase_8_export_medium),
        "paths_medium_for_phase10": medium_paths,
        "note": (
            "Shard mode writes split outputs (ATTACK/BENIGN) with stable coerced numeric schema. "
            "Combined outputs are optional. Medium export contains the returned Phase 8 dataset "
            "for fast Phase 10 reuse."
        ),
    }

    _save_json(meta, p_meta)

    dt = (datetime.now() - t0).total_seconds()
    summary = {
        "phase": 8,
        "seconds": dt,
        "meta": meta,
        "paths": paths,
        "paths_extra": paths_extra,
        "paths_medium_for_phase10": medium_paths,
    }

    train_rows = int(atk_train_written + ben_train_written)
    test_rows = int(atk_test_written + ben_test_written)
    elapsed = time.perf_counter() - t0_perf

    print("\n✅ PHASE 8 COMPLETE (Sharded Split + Drop/Coerce-for-Modeling)")
    print(f"   Elapsed     : {_fmt_elapsed(elapsed)}")
    print(f"   Attack src  : {atk_src:,} | Ben src: {ben_src:,}")
    print(f"   Attack take : {attack_take:,}")
    print(f"   Ben pool    : {benign_pool_take:,}")
    print(f"   Train       : rows={train_rows:,} | atk={atk_train_written:,} | ben={ben_train_written:,}")
    print(f"   Test (fair) : rows={test_rows:,}  | atk={atk_test_written:,} | ben={ben_test_written:,}")
    print(f"   Final feats : {len(final_feature_cols):,}")
    print(f"   Outputs meta: {p_meta.name}")
    if medium_paths.get("dir"):
        print(f"   Medium exp  : {medium_paths.get('dir')}")

    return {
        "df_train": df_train_sample,
        "df_test_fair": df_test_sample,
        "df_stress_benign": None,
        "df_pool": df_pool_sample,
        "summary": summary,
    }