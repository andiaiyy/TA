# src/cbr/phases/phase2.py
from __future__ import annotations

import gc
import re
from datetime import datetime
from typing import Iterable, Optional

import numpy as np
import pandas as pd


RAW_SUFFIX_DEFAULT = "_raw"
RAW_KEEP_COLS_DEFAULT = ("proto", "event_type")


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


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


def _stable_hash_series(s: pd.Series, mod: int = 2**31 - 1) -> pd.Series:
    """
    Fast & stable-in-run hashing for categorical/text columns.
    Deterministic for a given pandas version; stable across chunks.
    """
    s = s.astype("string").fillna("unknown")
    h = pd.util.hash_pandas_object(s, index=False).astype("uint64")
    return (h % np.uint64(mod)).astype("int64")


def _ensure_flow_alert_totals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure canonical columns exist:
      pkts_toserver, pkts_toclient, bytes_toserver, bytes_toclient, duration,
      alert_severity, has_alert, total_pkts, total_bytes
    Works even if columns are named like flow.pkts_toserver, etc.
    """
    out = df

    # --- pkts_toserver ---
    if "pkts_toserver" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("pkts", "toserver"), ("pkt", "toserver"),
            ("flow", "pkts", "toserver"), ("flow", "pkt", "toserver"),
        ])
        out["pkts_toserver"] = _to_numeric_safe(out[c]) if c else 0

    # --- pkts_toclient ---
    if "pkts_toclient" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("pkts", "toclient"), ("pkt", "toclient"),
            ("flow", "pkts", "toclient"), ("flow", "pkt", "toclient"),
        ])
        out["pkts_toclient"] = _to_numeric_safe(out[c]) if c else 0

    # --- bytes_toserver ---
    if "bytes_toserver" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("bytes", "toserver"), ("byte", "toserver"),
            ("flow", "bytes", "toserver"), ("flow", "byte", "toserver"),
        ])
        out["bytes_toserver"] = _to_numeric_safe(out[c]) if c else 0

    # --- bytes_toclient ---
    if "bytes_toclient" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("bytes", "toclient"), ("byte", "toclient"),
            ("flow", "bytes", "toclient"), ("flow", "byte", "toclient"),
        ])
        out["bytes_toclient"] = _to_numeric_safe(out[c]) if c else 0

    # --- duration/age ---
    if "duration" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("duration",), ("age",), ("flow", "age"), ("flow", "duration"),
        ])
        out["duration"] = _to_numeric_safe(out[c]) if c else 0

    # --- alert_severity ---
    if "alert_severity" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("alert", "severity"), ("alert_severity",), ("severity",),
        ])
        out["alert_severity"] = _to_numeric_safe(out[c]) if c else 0

    # --- has_alert ---
    if "has_alert" not in out.columns:
        c = _find_col_by_tokens(out, [
            ("has", "alert"), ("has_alert",),
        ])
        if c:
            out["has_alert"] = _to_numeric_safe(out[c]).astype(int)
        else:
            out["has_alert"] = (_to_numeric_safe(out["alert_severity"]) > 0).astype(int)

    # --- totals ---
    if "total_pkts" not in out.columns:
        out["total_pkts"] = _to_numeric_safe(out["pkts_toserver"]) + _to_numeric_safe(out["pkts_toclient"])
    else:
        out["total_pkts"] = _to_numeric_safe(out["total_pkts"])

    if "total_bytes" not in out.columns:
        out["total_bytes"] = _to_numeric_safe(out["bytes_toserver"]) + _to_numeric_safe(out["bytes_toclient"])
    else:
        out["total_bytes"] = _to_numeric_safe(out["total_bytes"])

    return out


def _inline_encode_dataframe(
    df: pd.DataFrame,
    *,
    raw_keep_cols: tuple[str, ...] = RAW_KEEP_COLS_DEFAULT,
    raw_suffix: str = RAW_SUFFIX_DEFAULT,
    hash_mod: int = 2**31 - 1,
) -> pd.DataFrame:
    """
    In-memory encoder:
    - Ensure canonical flow/alert/totals exist
    - Preserve proto_raw/event_type_raw for viz
    - Convert numeric-like columns to numeric
    - Encode remaining text/categorical columns to stable hash ints
    - Keep Target int (no RNG labeling)
    """
    out = df.reset_index(drop=True).copy()
    out = _ensure_flow_alert_totals(out)

    # preserve raw columns for visualization
    raw_cols = set()
    for c in raw_keep_cols:
        raw_name = f"{c}{raw_suffix}"
        raw_cols.add(raw_name)
        if c in out.columns:
            out[raw_name] = out[c].astype("string").fillna("unknown")
        else:
            out[raw_name] = pd.Series(["unknown"] * len(out), dtype="string")

    if "Target" not in out.columns:
        raise RuntimeError("Target column missing (DO NOT add random labels). Fix Phase 1 output.")

    # encode everything except Target + *_raw
    for col in list(out.columns):
        if col == "Target" or col in raw_cols:
            continue

        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = _to_numeric_safe(out[col])
            continue

        # try numeric conversion if mostly numeric
        num_try = pd.to_numeric(out[col], errors="coerce")
        ratio = float(num_try.notna().mean()) if len(num_try) else 0.0
        if ratio >= 0.98:
            out[col] = _to_numeric_safe(out[col])
        else:
            out[col] = _stable_hash_series(out[col], mod=hash_mod)

    out["Target"] = _to_numeric_safe(out["Target"]).astype(int)

    # safety totals
    if "total_pkts" not in out.columns:
        out["total_pkts"] = _to_numeric_safe(out.get("pkts_toserver", 0)) + _to_numeric_safe(out.get("pkts_toclient", 0))
    if "total_bytes" not in out.columns:
        out["total_bytes"] = _to_numeric_safe(out.get("bytes_toserver", 0)) + _to_numeric_safe(out.get("bytes_toclient", 0))

    return out


def _encode_leftover_categoricals(df: pd.DataFrame, *, raw_suffix: str, hash_mod: int) -> pd.DataFrame:
    """
    Safety net: after advanced engineer runs + reattach backups,
    ensure no unexpected object/string columns remain (except *_raw and Target).
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

    out["Target"] = _to_numeric_safe(out["Target"]).astype(int)
    return out


def phase2_advanced_feature_engineering(
    df_in: pd.DataFrame,
    *,
    use_advanced_module: bool = True,
    raw_keep_cols: tuple[str, ...] = RAW_KEEP_COLS_DEFAULT,
    raw_suffix: str = RAW_SUFFIX_DEFAULT,
    hash_mod: int = 2**31 - 1,
) -> tuple[pd.DataFrame, dict]:
    """
    Phase 2 (in-memory):
      - optional AdvancedFeatureEngineer.process_dataframe(df)
      - fallback inline stable encoding
      - never writes big CSV
    """
    print("\n" + "🟢 " + "="*76 + "\n")
    print("PHASE 2: ADVANCED FEATURE ENGINEERING (IN-MEMORY, NO HEAVY CACHE)")
    print("\n" + "🟢 " + "="*76)

    t0 = datetime.now()
    if df_in is None or len(df_in) == 0:
        raise ValueError("Phase 2 received empty df_in")

    df_work = df_in.copy()

    # Ensure Target exists early
    if "Target" not in df_work.columns:
        raise RuntimeError("Target missing before Phase 2. Fix Phase 1 (no RNG label).")

    # Ensure canonical columns exist pre-processing
    df_work = _ensure_flow_alert_totals(df_work)

    # Backups (raw strings + canon numeric that must exist for Phase 6)
    raw_backup: dict[str, pd.Series] = {}
    for c in raw_keep_cols:
        raw_backup[f"{c}{raw_suffix}"] = (
            df_work[c].astype("string").fillna("unknown").reset_index(drop=True)
            if c in df_work.columns
            else pd.Series(["unknown"] * len(df_work), dtype="string")
        )

    MUST_KEEP_CANON = [
        "pkts_toserver", "pkts_toclient", "bytes_toserver", "bytes_toclient",
        "duration", "total_pkts", "total_bytes", "alert_severity", "has_alert"
    ]
    canon_backup = {
        c: _to_numeric_safe(df_work[c]).reset_index(drop=True)
        if c in df_work.columns
        else pd.Series(np.zeros(len(df_work), dtype=np.float64))
        for c in MUST_KEEP_CANON
    }

    engineer_loaded = False
    engineer_fail = None

    df_proc: Optional[pd.DataFrame]

    if use_advanced_module:
        try:
            from cbr.feature_engineering_advanced import AdvancedFeatureEngineer  # type: ignore

            engineer = AdvancedFeatureEngineer(verbose=True)
            df_proc = engineer.process_dataframe(df_work).reset_index(drop=True)

            # hard guard: advanced engineer must not change row count
            if len(df_proc) != len(df_work):
                raise RuntimeError(f"AdvancedFeatureEngineer changed row count: {len(df_work)} -> {len(df_proc)}")

            engineer_loaded = True

            # ensure Target survives
            if "Target" not in df_proc.columns:
                df_proc["Target"] = df_work["Target"].reset_index(drop=True)

            # re-attach raw + canon (must be aligned by row)
            for k, v in raw_backup.items():
                df_proc[k] = v.values
            for k, v in canon_backup.items():
                df_proc[k] = v.values

            # safety: encode any leftover categoricals created by the engineer
            df_proc = _encode_leftover_categoricals(df_proc, raw_suffix=raw_suffix, hash_mod=hash_mod)

        except Exception as e:
            engineer_fail = repr(e)
            df_proc = None
    else:
        df_proc = None

    if df_proc is None:
        # fallback inline encoding
        df_proc = df_work.reset_index(drop=True)
        for k, v in raw_backup.items():
            df_proc[k] = v.values
        for k, v in canon_backup.items():
            df_proc[k] = v.values

        df_proc = _inline_encode_dataframe(
            df_proc,
            raw_keep_cols=raw_keep_cols,
            raw_suffix=raw_suffix,
            hash_mod=hash_mod,
        )

    # Cleanup numeric columns only (do not touch *_raw)
    for col in df_proc.columns:
        if col == "Target" or col.endswith(raw_suffix):
            continue
        if pd.api.types.is_numeric_dtype(df_proc[col]):
            df_proc[col] = df_proc[col].replace([np.inf, -np.inf], np.nan).fillna(0)

    # enforce Target int
    df_proc["Target"] = _to_numeric_safe(df_proc["Target"]).astype(int)

    # final safety totals
    df_proc = _ensure_flow_alert_totals(df_proc)

    elapsed = (datetime.now() - t0).total_seconds()
    numeric_cols = sum(pd.api.types.is_numeric_dtype(df_proc[c]) for c in df_proc.columns)
    raw_cols = [c for c in df_proc.columns if c.endswith(raw_suffix)]

    summary = {
        "phase": 2,
        "input_shape": [int(df_in.shape[0]), int(df_in.shape[1])],
        "output_shape": [int(df_proc.shape[0]), int(df_proc.shape[1])],
        "engineer_loaded": engineer_loaded,
        "engineer_fail": engineer_fail,
        "raw_cols": raw_cols,
        "numeric_cols_count": int(numeric_cols),
        "seconds": elapsed,
        "note_leakage": (
            "Target uses alert/severity (Phase 1). For modeling, exclude has_alert/alert_category/alert_severity to avoid leakage."
        ),
    }

    print("\n✅ PHASE 2 COMPLETE")
    print(f"   df_encoded: {df_proc.shape}")
    print(f"   engineer_loaded: {engineer_loaded}")
    if engineer_fail:
        print(f"   engineer_fail: {engineer_fail}")
    print(f"   Time: {elapsed/60:.2f} minutes")

    gc.collect()
    return df_proc, summary

# =============================================================================
# PHASE 2 (SHARDED, DISK-BACKED)
# =============================================================================

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

from tqdm import tqdm


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(max(0, n))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} B"


@dataclass(frozen=True)
class Phase2ShardConfig:
    # input from Phase 1 disk-backed output
    input_phase1_dir: Path               # folder containing attacks/ + benign/
    # output for Phase 2 shards
    out_dir: Path                        # folder to write phase2 shards

    # output format
    write_format: str = "parquet"        # "parquet" or "csv" (csv -> csv.gz)
    parquet_engine: Optional[str] = "fastparquet"  # "fastparquet"/"pyarrow"/None
    parquet_compression: Optional[str] = "snappy"

    # return a small sample in RAM for downstream/debug
    return_df_sample: int = 200_000

    # choose which shards to process
    include_attacks: bool = True
    include_benign: bool = True


def _iter_phase1_shards(phase1_dir: Path, *, include_attacks: bool, include_benign: bool) -> List[Path]:
    phase1_dir = Path(phase1_dir)
    files: List[Path] = []

    if include_attacks:
        files += sorted((phase1_dir / "attacks").glob("part-*.parquet"))
        files += sorted((phase1_dir / "attacks").glob("part-*.csv.gz"))

    if include_benign:
        files += sorted((phase1_dir / "benign").glob("part-*.parquet"))
        files += sorted((phase1_dir / "benign").glob("part-*.csv.gz"))

    return files


def _read_shard(path: Path, *, parquet_engine: Optional[str]) -> pd.DataFrame:
    if path.suffix == ".parquet":
        kwargs = {}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        return pd.read_parquet(path, **kwargs)

    # csv.gz fallback
    return pd.read_csv(path)


def _write_shard(
    df: pd.DataFrame,
    out_path: Path,
    *,
    write_format: str,
    parquet_engine: Optional[str],
    parquet_compression: Optional[str],
) -> int:
    if write_format == "parquet":
        kwargs = {}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        if parquet_compression:
            kwargs["compression"] = parquet_compression
        try:
            df.to_parquet(out_path, index=False, **kwargs)
        except Exception:
            # retry without compression if codec not available
            kwargs.pop("compression", None)
            df.to_parquet(out_path, index=False, **kwargs)
    else:
        df.to_csv(out_path, index=False, compression="gzip")

    return int(out_path.stat().st_size)


def phase2_advanced_feature_engineering_sharded(
    *,
    cfg: Phase2ShardConfig,
    use_advanced_module: bool = True,
    raw_keep_cols: tuple[str, ...] = RAW_KEEP_COLS_DEFAULT,
    raw_suffix: str = RAW_SUFFIX_DEFAULT,
    hash_mod: int = 2**31 - 1,
) -> tuple[pd.DataFrame, dict]:
    """
    Phase 2 (sharded, disk-backed):
    - Read Phase 1 shards from cfg.input_phase1_dir/{attacks,benign}/part-*
    - Apply SAME phase2 processing per shard
    - Write phase2 shards to cfg.out_dir/{attacks,benign}/part-*
    - Return df_sample (small) + summary
    """
    print("\n" + "🟢 " + "="*76 + "\n")
    print("PHASE 2: ADVANCED FEATURE ENGINEERING (SHARDED, DISK-BACKED)")
    print("\n" + "🟢 " + "="*76)

    t0 = datetime.now()

    phase1_dir = Path(cfg.input_phase1_dir)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shard_files = _iter_phase1_shards(
        phase1_dir,
        include_attacks=cfg.include_attacks,
        include_benign=cfg.include_benign,
    )
    if not shard_files:
        raise RuntimeError(f"No Phase 1 shards found under: {phase1_dir}")

    out_attacks = out_dir / "attacks"
    out_benign = out_dir / "benign"
    out_attacks.mkdir(parents=True, exist_ok=True)
    out_benign.mkdir(parents=True, exist_ok=True)

    sample_chunks: List[pd.DataFrame] = []
    sample_left = max(0, int(cfg.return_df_sample))

    total_in_rows = 0
    total_out_rows = 0
    shards_in = 0
    shards_out = 0

    out_bytes_attack = 0
    out_bytes_benign = 0

    engineer_loaded_any = False
    engineer_fail_first: Optional[str] = None

    pbar = tqdm(shard_files, desc="PHASE 2 (shards)", unit="shard", dynamic_ncols=True)

    for fp in pbar:
        shards_in += 1

        df_in = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df_in is None or len(df_in) == 0:
            continue

        total_in_rows += int(len(df_in))

        # =========================
        # REUSE YOUR EXISTING LOGIC PER SHARD
        # =========================
        df_work = df_in.copy()

        if "Target" not in df_work.columns:
            raise RuntimeError(f"Target missing in shard: {fp} (Phase 1 output invalid).")

        df_work = _ensure_flow_alert_totals(df_work)

        # backups (raw strings + canon numeric)
        raw_backup: dict[str, pd.Series] = {}
        for c in raw_keep_cols:
            raw_backup[f"{c}{raw_suffix}"] = (
                df_work[c].astype("string").fillna("unknown").reset_index(drop=True)
                if c in df_work.columns
                else pd.Series(["unknown"] * len(df_work), dtype="string")
            )

        MUST_KEEP_CANON = [
            "pkts_toserver", "pkts_toclient", "bytes_toserver", "bytes_toclient",
            "duration", "total_pkts", "total_bytes", "alert_severity", "has_alert"
        ]
        canon_backup = {
            c: _to_numeric_safe(df_work[c]).reset_index(drop=True)
            if c in df_work.columns
            else pd.Series(np.zeros(len(df_work), dtype=np.float64))
            for c in MUST_KEEP_CANON
        }

        df_proc: Optional[pd.DataFrame] = None

        if use_advanced_module:
            try:
                from cbr.feature_engineering_advanced import AdvancedFeatureEngineer  # type: ignore

                engineer = AdvancedFeatureEngineer(verbose=False)
                tmp = engineer.process_dataframe(df_work).reset_index(drop=True)

                if len(tmp) != len(df_work):
                    raise RuntimeError(f"AdvancedFeatureEngineer changed row count: {len(df_work)} -> {len(tmp)}")

                engineer_loaded_any = True

                if "Target" not in tmp.columns:
                    tmp["Target"] = df_work["Target"].reset_index(drop=True)

                for k, v in raw_backup.items():
                    tmp[k] = v.values
                for k, v in canon_backup.items():
                    tmp[k] = v.values

                tmp = _encode_leftover_categoricals(tmp, raw_suffix=raw_suffix, hash_mod=hash_mod)
                df_proc = tmp

            except Exception as e:
                if engineer_fail_first is None:
                    engineer_fail_first = repr(e)
                df_proc = None

        if df_proc is None:
            tmp = df_work.reset_index(drop=True)
            for k, v in raw_backup.items():
                tmp[k] = v.values
            for k, v in canon_backup.items():
                tmp[k] = v.values

            df_proc = _inline_encode_dataframe(
                tmp,
                raw_keep_cols=raw_keep_cols,
                raw_suffix=raw_suffix,
                hash_mod=hash_mod,
            )

        # cleanup numeric columns only
        for col in df_proc.columns:
            if col == "Target" or col.endswith(raw_suffix):
                continue
            if pd.api.types.is_numeric_dtype(df_proc[col]):
                df_proc[col] = df_proc[col].replace([np.inf, -np.inf], np.nan).fillna(0)

        df_proc["Target"] = _to_numeric_safe(df_proc["Target"]).astype(int)
        df_proc = _ensure_flow_alert_totals(df_proc)
        # =========================

        total_out_rows += int(len(df_proc))

        # decide output folder by origin folder name (NOT string contains)
        origin = fp.parent.name.lower()
        is_attack = (origin == "attacks")
        out_root = out_attacks if is_attack else out_benign

        shards_out += 1
        out_name = fp.name
        if cfg.write_format == "parquet":
            out_name = out_name.replace(".csv.gz", ".parquet")
            if not out_name.endswith(".parquet"):
                out_name = Path(out_name).with_suffix(".parquet").name
        else:
            out_name = out_name.replace(".parquet", ".csv.gz")
            if not out_name.endswith(".csv.gz"):
                out_name = Path(out_name).with_suffix(".csv.gz").name

        out_path = out_root / out_name

        bytes_written = _write_shard(
            df_proc,
            out_path,
            write_format=cfg.write_format,
            parquet_engine=cfg.parquet_engine,
            parquet_compression=cfg.parquet_compression,
        )

        if is_attack:
            out_bytes_attack += bytes_written
        else:
            out_bytes_benign += bytes_written

        # accumulate sample
        if sample_left > 0:
            take_n = min(sample_left, len(df_proc))
            sample_chunks.append(df_proc.iloc[:take_n].copy())
            sample_left -= take_n

        pbar.set_postfix({
            "in_rows": f"{total_in_rows:,}",
            "out_rows": f"{total_out_rows:,}",
            "atk_size": _human_bytes(out_bytes_attack),
            "ben_size": _human_bytes(out_bytes_benign),
        })

        # free memory
        del df_in, df_work, df_proc
        gc.collect()

    pbar.close()

    df_sample = pd.concat(sample_chunks, ignore_index=True) if sample_chunks else pd.DataFrame()

    elapsed = (datetime.now() - t0).total_seconds()
    total_bytes = out_bytes_attack + out_bytes_benign
    total_gib = total_bytes / (1024 ** 3)

    print("\n📦 PHASE 2 OUTPUT SIZE (on disk)")
    print(f"   Attacks : {_human_bytes(out_bytes_attack)}")
    print(f"   Benign  : {_human_bytes(out_bytes_benign)}")
    print(f"   TOTAL   : {_human_bytes(total_bytes)}  ({total_gib:.2f} GiB)")
    print(f"   Output dir: {out_dir.resolve()}")

    summary = {
        "phase": 2,
        "mode": "sharded",
        "input_phase1_dir": str(phase1_dir),
        "out_dir": str(out_dir),
        "write_format": cfg.write_format,
        "parquet_engine": cfg.parquet_engine,
        "parquet_compression": cfg.parquet_compression,
        "shards_in": int(shards_in),
        "shards_out": int(shards_out),
        "total_in_rows": int(total_in_rows),
        "total_out_rows": int(total_out_rows),
        "engineer_loaded_any": bool(engineer_loaded_any),
        "engineer_fail_first": engineer_fail_first,
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "attack_bytes": int(out_bytes_attack),
        "benign_bytes": int(out_bytes_benign),
        "total_bytes": int(total_bytes),
        "total_gib": float(total_gib),
        "seconds": float(elapsed),
        "note_leakage": (
            "Target uses alert/severity (Phase 1). For modeling, exclude has_alert/alert_category/alert_severity."
        ),
    }

    print("\n✅ PHASE 2 COMPLETE (SHARDED)")
    print(f"   shards_in : {shards_in}")
    print(f"   out_rows  : {total_out_rows:,}")
    print(f"   df_sample : {df_sample.shape}")
    print(f"   engineer_loaded_any: {engineer_loaded_any}")
    if engineer_fail_first:
        print(f"   engineer_fail_first: {engineer_fail_first}")
    print(f"   Time: {elapsed/60:.2f} minutes")

    return df_sample, summary