from __future__ import annotations

import gc
import json
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
from tqdm import tqdm


# =========================
# PHASE 1 (HUGE-DATA SAFE)
# - PASS 1: count attack/benign totals
# - PASS 2: write ALL attacks to Parquet shards
#           sample benign up to (ratio * attack_total), write to Parquet shards
# - Return only a SMALL df_sample (optional) to keep downstream/report alive
# =========================

OUT_COLS = [
    "timestamp",
    "src_ip", "dest_ip",
    "src_port", "dest_port",
    "proto", "event_type",
    "app_proto",
    "flow_id", "pkt_src",

    # flow flat
    "has_flow",
    "pkts_toserver", "pkts_toclient",
    "bytes_toserver", "bytes_toclient",
    "duration",
    "total_pkts", "total_bytes",

    # alert flat (NOTE: potential leakage if Target derived from alert)
    "has_alert",
    "alert_category",
    "alert_severity",

    # label
    "Target",
]

INT_COLS = [
    "has_flow",
    "pkts_toserver", "pkts_toclient",
    "bytes_toserver", "bytes_toclient",
    "total_pkts", "total_bytes",
    "has_alert",
    "alert_severity",
    "Target",
    "src_port",
    "dest_port",
]
FLOAT_COLS = ["duration"]


# -----------------------------
# Fast JSON (optional: orjson)
# -----------------------------
try:
    import orjson  # type: ignore

    def _safe_decode_json(line: bytes) -> dict | None:
        try:
            obj = orjson.loads(line)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

except Exception:
    def _safe_decode_json(line: bytes) -> dict | None:
        try:
            obj = json.loads(line.decode("utf-8", errors="ignore"))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None


def _to_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        if isinstance(x, (int, np.integer)):
            return int(x)
        if isinstance(x, (float, np.floating)) and np.isnan(x):
            return default
        return int(float(x))
    except Exception:
        return default


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (float, np.floating)) and np.isnan(x):
            return default
        return float(x)
    except Exception:
        return default


def _label_target(event: dict, false_pos_category: str = "generic protocol decode") -> int:
    """
    1 = attack, 0 = benign
    Rule: Attack if alert has severity, except false-positive category.
    """
    alert = event.get("alert")
    if not isinstance(alert, dict):
        return 0

    category = str(alert.get("category", "unknown")).strip().lower()
    if category == false_pos_category.strip().lower():
        return 0

    return 1 if ("severity" in alert) and (alert.get("severity") is not None) else 0


def _flatten_row(event: dict, target: int) -> dict:
    # ---- FLATTEN FLOW ----
    flow = event.get("flow")
    has_flow = 1 if isinstance(flow, dict) else 0

    pkts_toserver = pkts_toclient = 0
    bytes_toserver = bytes_toclient = 0
    duration = 0.0

    if has_flow:
        pkts_toserver = _to_int(flow.get("pkts_toserver", 0), 0)
        pkts_toclient = _to_int(flow.get("pkts_toclient", 0), 0)
        bytes_toserver = _to_int(flow.get("bytes_toserver", 0), 0)
        bytes_toclient = _to_int(flow.get("bytes_toclient", 0), 0)
        duration = _to_float(flow.get("age", 0.0), 0.0)

    total_pkts = pkts_toserver + pkts_toclient
    total_bytes = bytes_toserver + bytes_toclient

    # ---- FLATTEN ALERT ----
    alert = event.get("alert")
    has_alert = 1 if isinstance(alert, dict) else 0

    alert_category = "none"
    alert_severity = 0
    if has_alert:
        alert_category = str(alert.get("category", "unknown"))
        alert_severity = _to_int(alert.get("severity", 0), 0)

    return {
        "timestamp": event.get("timestamp"),

        "src_ip": event.get("src_ip"),
        "dest_ip": event.get("dest_ip"),

        # ✅ FIX: ports must be stable ints for parquet
        "src_port": _to_int(event.get("src_port", 0), 0),
        "dest_port": _to_int(event.get("dest_port", 0), 0),

        "proto": event.get("proto"),
        "event_type": event.get("event_type"),
        "app_proto": event.get("app_proto"),
        "flow_id": event.get("flow_id"),
        "pkt_src": event.get("pkt_src"),

        "has_flow": has_flow,
        "pkts_toserver": pkts_toserver,
        "pkts_toclient": pkts_toclient,
        "bytes_toserver": bytes_toserver,
        "bytes_toclient": bytes_toclient,
        "duration": duration,
        "total_pkts": total_pkts,
        "total_bytes": total_bytes,

        "has_alert": has_alert,
        "alert_category": alert_category,
        "alert_severity": alert_severity,

        "Target": int(target),
    }


def _stable_hash_u64(key: str, seed: int) -> int:
    """
    Stable 64-bit hash (deterministic across runs/machines).
    """
    b = (f"{seed}|{key}").encode("utf-8", errors="ignore")
    d = hashlib.blake2b(b, digest_size=8).digest()
    return int.from_bytes(d, byteorder="big", signed=False)


# ---------------------------------------------------------------------------
# CSV input-adapter: reconstruct nested event dicts from flat dotted columns
# ---------------------------------------------------------------------------

def _is_empty(val) -> bool:
    """True for values that should be treated as absent in a CSV row."""
    if val is None or val == "":
        return True
    if isinstance(val, float) and np.isnan(val):
        return True
    if isinstance(val, str) and val.lower() == "nan":
        return True
    return False


def _row_to_event(row: dict) -> dict | None:
    """
    Reconstruct a nested EVE event dict from a flat dotted-column CSV row.

    Nesting rules:
      alert.severity        -> event["alert"]["severity"]
      alert.metadata.foo    -> event["alert"]["metadata"]["foo"]
      a.b.c.d               -> event["a"]["b"]["c.d"]  (remainder joined)

    Sub-dicts are only created when at least one non-empty value is present,
    so non-alert rows have no "alert" key — _label_target returns 0 correctly.
    Returns None if src_ip is absent (caller increments missing_src_ip).
    """
    event: dict = {}

    for col, val in row.items():
        if _is_empty(val):
            continue

        parts = col.split(".", 2)  # at most 3 segments

        if len(parts) == 1:
            event[col] = val
        elif len(parts) == 2:
            prefix, suffix = parts
            if not isinstance(event.get(prefix), dict):
                event[prefix] = {}
            event[prefix][suffix] = val
        else:
            prefix, mid, rest = parts
            if not isinstance(event.get(prefix), dict):
                event[prefix] = {}
            if not isinstance(event[prefix].get(mid), dict):
                event[prefix][mid] = {}
            event[prefix][mid][rest] = val

    src_ip = event.get("src_ip")
    if not src_ip or _is_empty(src_ip):
        return None

    return event


def _iter_csv_events(input_file: Path, stats: dict, max_lines: int | None):
    """
    Yield event dicts (or None for missing-src_ip rows) from a flat EVE CSV.

    Chunked reading with dtype=str keeps memory bounded and avoids DtypeWarning.
    Empty cells become float NaN (not the string "nan") via na_values=[""]).
    Updates stats["total_lines"] and stats["missing_src_ip"] in-place.
    """
    import pandas as _pd

    chunks = _pd.read_csv(
        input_file,
        chunksize=10_000,
        low_memory=False,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
    )
    for chunk in chunks:
        for _, row in chunk.iterrows():
            stats["total_lines"] += 1
            if max_lines and stats["total_lines"] > max_lines:
                return
            event = _row_to_event(row.to_dict())
            if event is None:
                stats["missing_src_ip"] += 1
                yield None
            else:
                yield event


def _iter_ndjson_events(input_file: Path, stats: dict, max_lines: int | None):
    """
    Yield event dicts (or None for skipped records) from an NDJSON file.
    Updates stats["total_lines"], stats["malformed"], stats["missing_src_ip"].
    """
    with input_file.open("rb") as infile:
        while True:
            line = infile.readline()
            if not line:
                break
            stats["total_lines"] += 1
            if max_lines and stats["total_lines"] > max_lines:
                break
            event = _safe_decode_json(line)
            if event is None:
                stats["malformed"] += 1
                yield None
                continue
            src_ip = event.get("src_ip")
            if not src_ip:
                stats["missing_src_ip"] += 1
                yield None
                continue
            yield event


def _iter_events(input_file: Path, stats: dict, max_lines: int | None = None):
    """
    Dispatch to the correct event iterator based on file extension.
    Yields event dicts for valid records, None for skipped ones.
    Supported: .csv  .json  .jsonl  .ndjson
    """
    ext = input_file.suffix.lower()
    if ext == ".csv":
        yield from _iter_csv_events(input_file, stats, max_lines)
    elif ext in (".json", ".jsonl", ".ndjson"):
        yield from _iter_ndjson_events(input_file, stats, max_lines)
    else:
        raise ValueError(f"Unsupported EVE input format: {input_file.suffix!r}")


# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class Phase1DiskConfig:
    output_dir: Path
    write_format: str = "parquet"      # "parquet" or "csv" (csv -> csv.gz shards)
    batch_size: int = 200_000          # rows per shard
    return_df_sample: int = 200_000    # small in-RAM sample for reporting/debug

    # engine / compression (optional)
    parquet_engine: Optional[str] = None          # "fastparquet" | "pyarrow" | None
    parquet_compression: Optional[str] = "snappy" # "snappy" | "gzip" | None


class _ShardWriter:
    """
    Writes shards:
      - Parquet if engine available
      - else CSV.gz shards (fallback)
    """
    def __init__(
        self,
        out_dir: Path,
        fmt: str,
        *,
        parquet_engine: Optional[str] = None,
        parquet_compression: Optional[str] = "snappy",
    ):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

        fmt = (fmt or "").strip().lower()
        if fmt not in ("parquet", "csv"):
            fmt = "parquet"

        self.requested_fmt = fmt
        self.actual_fmt = fmt
        self.part = 0

        self.parquet_engine = parquet_engine
        self.parquet_compression = parquet_compression

        if self.requested_fmt == "parquet":
            # If user requested an engine explicitly, validate it.
            if self.parquet_engine:
                eng = self.parquet_engine.strip().lower()
                if eng == "pyarrow":
                    try:
                        import pyarrow  # noqa: F401
                        self.actual_fmt = "parquet"
                    except Exception:
                        self.actual_fmt = "csv"
                elif eng == "fastparquet":
                    try:
                        import fastparquet  # noqa: F401
                        self.actual_fmt = "parquet"
                    except Exception:
                        self.actual_fmt = "csv"
                else:
                    self.parquet_engine = None

            # Auto probe if still parquet
            if self.actual_fmt == "parquet" and self.parquet_engine is None:
                try:
                    import pyarrow  # noqa: F401
                    self.actual_fmt = "parquet"
                except Exception:
                    try:
                        import fastparquet  # noqa: F401
                        self.actual_fmt = "parquet"
                    except Exception:
                        self.actual_fmt = "csv"

    def flush(self, rows: List[dict]) -> Optional[Path]:
        if not rows:
            return None

        self.part += 1
        df = pd.DataFrame.from_records(rows)

        # ensure schema
        for c in OUT_COLS:
            if c not in df.columns:
                df[c] = np.nan
        df = df[OUT_COLS]

        # dtype optimization numeric
        for c in INT_COLS:
            if c in df.columns:
                try:
                    df[c] = df[c].astype(np.int32)
                except Exception:
                    pass
        for c in FLOAT_COLS:
            if c in df.columns:
                try:
                    df[c] = df[c].astype(np.float32)
                except Exception:
                    pass

        # ✅ FIX: fastparquet + ArrowStringArray crash (timestamp etc).
        # Force text columns to python-object strings.
        STR_COLS = [
            "timestamp",
            "src_ip", "dest_ip",
            "proto", "event_type", "app_proto",
            "flow_id", "pkt_src",
            "alert_category",
        ]
        for c in STR_COLS:
            if c in df.columns:
                try:
                    s = df[c].astype("object")
                    s = s.where(pd.notna(s), "")
                    # vectorized conversion to python str
                    s = s.astype(str)
                    df[c] = s
                except Exception:
                    # last resort (slower, but safe)
                    df[c] = df[c].map(lambda x: "" if x is None or (isinstance(x, float) and np.isnan(x)) else str(x))

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


def phase1_load_and_label(
    input_file: Path,
    *,
    max_lines: int | None = None,

    pool_benign_per_attack: float = 3.0,
    benign_reservoir_max: int | None = None,

    false_positive_alert_category: str = "generic protocol decode",
    seed: int = 42,
    progress_desc: str = "PHASE 1",

    disk: Phase1DiskConfig,
) -> Tuple[pd.DataFrame, dict]:
    """
    Disk-backed Phase 1:
    - PASS 1: count only
    - PASS 2: write ALL attacks to disk, benign sampled to target <= ratio*attack
    - Returns ONLY df_sample in RAM (size = disk.return_df_sample)
    """
    print("\n" + "🔵 " + "=" * 76 + "\n")
    print("PHASE 1: DATA LOADING & LABELING (2-PASS, DISK-BACKED)")
    print("\n" + "🔵 " + "=" * 76)

    t0 = datetime.now()

    try:
        pool_benign_per_attack = float(pool_benign_per_attack)
    except Exception:
        pool_benign_per_attack = 3.0
    if pool_benign_per_attack < 0:
        pool_benign_per_attack = 0.0

    if benign_reservoir_max is not None and benign_reservoir_max <= 0:
        benign_reservoir_max = None

    # -------------------------
    # PASS 1: COUNT ONLY
    # -------------------------
    stats1 = {
        "total_lines": 0,
        "malformed": 0,
        "missing_src_ip": 0,
        "attack_total": 0,
        "benign_total": 0,
    }
    event_type_counter = Counter()

    pbar1 = tqdm(desc=f"{progress_desc} (pass1/count)", unit="record", dynamic_ncols=True)
    for event in _iter_events(input_file, stats1, max_lines):
        if event is None:
            pbar1.update(1)
            continue

        et = event.get("event_type", "unknown")
        event_type_counter[et] += 1

        tgt = _label_target(event, false_pos_category=false_positive_alert_category)
        if tgt == 1:
            stats1["attack_total"] += 1
        else:
            stats1["benign_total"] += 1

        if stats1["total_lines"] % 200_000 == 0:
            pbar1.set_postfix({
                "Attack": f"{stats1['attack_total']:,}",
                "Benign": f"{stats1['benign_total']:,}",
                "Malformed": f"{stats1['malformed']:,}",
            })
        pbar1.update(1)
    pbar1.close()

    desired_benign = int(np.ceil(pool_benign_per_attack * max(1, stats1["attack_total"])))
    k_benign = min(desired_benign, int(stats1["benign_total"]))
    if benign_reservoir_max is not None:
        k_benign = min(k_benign, int(benign_reservoir_max))

    p_benign = (k_benign / stats1["benign_total"]) if stats1["benign_total"] > 0 else 0.0

    print("\n📌 Phase 1 pool plan:")
    print(f"   Attack total: {stats1['attack_total']:,}")
    print(f"   Benign total: {stats1['benign_total']:,}")
    print(f"   Desired benign (ratio={pool_benign_per_attack:g}): {desired_benign:,}")
    print(f"   Benign target kept: {k_benign:,}  (p≈{p_benign:.6f})")
    if benign_reservoir_max is not None:
        print(f"   Hard cap benign_reservoir_max: {benign_reservoir_max:,}")

    # -------------------------
    # PASS 2: STREAM WRITE SHARDS
    # -------------------------
    out_dir = Path(disk.output_dir)
    attacks_dir = out_dir / "attacks"
    benign_dir = out_dir / "benign"
    out_dir.mkdir(parents=True, exist_ok=True)

    atk_writer = _ShardWriter(
        attacks_dir,
        disk.write_format,
        parquet_engine=disk.parquet_engine,
        parquet_compression=disk.parquet_compression,
    )
    ben_writer = _ShardWriter(
        benign_dir,
        disk.write_format,
        parquet_engine=disk.parquet_engine,
        parquet_compression=disk.parquet_compression,
    )

    atk_batch: List[dict] = []
    ben_batch: List[dict] = []
    sample_rows: List[dict] = []
    sample_max = max(0, int(disk.return_df_sample))

    stats2 = {
        "total_lines": 0,
        "malformed": 0,
        "missing_src_ip": 0,
        "attack_written": 0,
        "benign_seen": 0,
        "benign_written": 0,
        "attack_shards": 0,
        "benign_shards": 0,
        "dataset_format": atk_writer.actual_fmt,
        "dataset_dir": str(out_dir),
        "attacks_dir": str(attacks_dir),
        "benign_dir": str(benign_dir),
    }

    pbar2 = tqdm(desc=f"{progress_desc} (pass2/write)", unit="record", dynamic_ncols=True)
    for event in _iter_events(input_file, stats2, max_lines):
        if event is None:
            pbar2.update(1)
            continue

        tgt = _label_target(event, false_pos_category=false_positive_alert_category)

        if tgt == 1:
            row = _flatten_row(event, 1)
            atk_batch.append(row)
            stats2["attack_written"] += 1

            if sample_max > 0 and len(sample_rows) < sample_max:
                sample_rows.append(row)

            if len(atk_batch) >= disk.batch_size:
                path = atk_writer.flush(atk_batch)
                atk_batch.clear()
                if path is not None:
                    stats2["attack_shards"] += 1
        else:
            stats2["benign_seen"] += 1

            if stats2["benign_written"] >= k_benign:
                pbar2.update(1)
                continue

            if p_benign > 0.0:
                if event.get("flow_id") is not None:
                    key = str(event.get("flow_id"))
                else:
                    key = (
                        f"{event.get('src_ip')}|{event.get('dest_ip')}|"
                        f"{event.get('src_port')}|{event.get('dest_port')}|{event.get('proto')}"
                    )

                u64 = _stable_hash_u64(key, seed)
                u = u64 / 18446744073709551616.0

                if u < p_benign:
                    row = _flatten_row(event, 0)
                    ben_batch.append(row)
                    stats2["benign_written"] += 1

                    if sample_max > 0 and len(sample_rows) < sample_max:
                        sample_rows.append(row)

                    if len(ben_batch) >= disk.batch_size:
                        path = ben_writer.flush(ben_batch)
                        ben_batch.clear()
                        if path is not None:
                            stats2["benign_shards"] += 1

        if stats2["total_lines"] % 200_000 == 0:
            pbar2.set_postfix({
                "AtkW": f"{stats2['attack_written']:,}",
                "BenW": f"{stats2['benign_written']:,}/{k_benign:,}",
                "ShAtk": f"{stats2['attack_shards']}",
                "ShBen": f"{stats2['benign_shards']}",
            })
        pbar2.update(1)
    pbar2.close()

    if atk_batch:
        path = atk_writer.flush(atk_batch)
        atk_batch.clear()
        if path is not None:
            stats2["attack_shards"] += 1

    if ben_batch:
        path = ben_writer.flush(ben_batch)
        ben_batch.clear()
        if path is not None:
            stats2["benign_shards"] += 1

    # df_sample (small)
    if sample_max > 0 and sample_rows:
        df_sample = pd.DataFrame.from_records(sample_rows)
        for c in OUT_COLS:
            if c not in df_sample.columns:
                df_sample[c] = np.nan
        df_sample = df_sample[OUT_COLS]
        try:
            df_sample["Target"] = df_sample["Target"].astype(int)
        except Exception:
            pass
    else:
        df_sample = pd.DataFrame(columns=OUT_COLS)

    atk_bytes = _dir_size_bytes(attacks_dir)
    ben_bytes = _dir_size_bytes(benign_dir)
    total_bytes = atk_bytes + ben_bytes

    gc.collect()
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 1,
        "input_file": str(input_file),
        "max_lines": max_lines,

        "total_lines_seen": int(stats1["total_lines"]),
        "malformed": int(stats1["malformed"]),
        "missing_src_ip": int(stats1["missing_src_ip"]),
        "attack_total": int(stats1["attack_total"]),
        "benign_total": int(stats1["benign_total"]),

        "pool_benign_per_attack": float(pool_benign_per_attack),
        "desired_benign_pool": int(desired_benign),
        "k_benign_target": int(k_benign),
        "p_benign": float(p_benign),
        "benign_reservoir_max": benign_reservoir_max if benign_reservoir_max is not None else "uncapped",

        "attack_written": int(stats2["attack_written"]),
        "benign_written": int(stats2["benign_written"]),
        "attack_shards": int(stats2["attack_shards"]),
        "benign_shards": int(stats2["benign_shards"]),
        "dataset_format": str(stats2["dataset_format"]),
        "dataset_dir": str(stats2["dataset_dir"]),
        "attacks_dir": str(stats2["attacks_dir"]),
        "benign_dir": str(stats2["benign_dir"]),

        "parquet_engine": disk.parquet_engine,
        "parquet_compression": disk.parquet_compression,

        "attack_bytes": int(atk_bytes),
        "benign_bytes": int(ben_bytes),
        "total_bytes": int(total_bytes),
        "attack_gib": float(_gib(atk_bytes)),
        "benign_gib": float(_gib(ben_bytes)),
        "total_gib": float(_gib(total_bytes)),

        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],

        "false_positive_alert_category": false_positive_alert_category,
        "event_type_counter_top10": dict(event_type_counter.most_common(10)),
        "seconds": float(elapsed),

        "note_leakage": (
            "Target uses alert/severity; avoid using has_alert/alert_category/alert_severity as model features."
        ),
        "note_memory": (
            "Phase 1 is disk-backed (writes shards). It returns only df_sample in RAM."
        ),
        "note_sampling": (
            "Benign sampling uses deterministic hash filter to approximate k_benign_target. "
            "For very large datasets, deviation is typically negligible (but may underfill slightly)."
        ),
    }

    print("\n✅ PHASE 1 COMPLETE (DISK-BACKED)")
    print(f"   Seen lines: {stats1['total_lines']:,}")
    print(f"   Attack total: {stats1['attack_total']:,} | Benign total: {stats1['benign_total']:,}")
    print(f"   Written -> Attack: {stats2['attack_written']:,} | Benign: {stats2['benign_written']:,} (target {k_benign:,})")
    print(f"   Dataset format: {stats2['dataset_format']} | dir: {out_dir}")
    print(f"   Output size   : attacks={_gib(atk_bytes):.2f} GiB | benign={_gib(ben_bytes):.2f} GiB | total={_gib(total_bytes):.2f} GiB")
    print(f"   df_sample: {df_sample.shape}")
    print(f"   Time: {elapsed/60:.2f} minutes")

    return df_sample, summary


if __name__ == "__main__":
    df_sample, summary = phase1_load_and_label(
        input_file=Path(r"G:\path\to\eve.jsonl"),
        pool_benign_per_attack=3.0,
        false_positive_alert_category="generic protocol decode",
        seed=42,
        disk=Phase1DiskConfig(
            output_dir=Path("results/phase1_dataset"),
            write_format="parquet",
            batch_size=200_000,
            return_df_sample=200_000,
            parquet_engine="fastparquet",
            parquet_compression="snappy",
        ),
    )
    print(summary)