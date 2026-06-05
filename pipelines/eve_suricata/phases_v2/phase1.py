from __future__ import annotations

import gc
import json
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm


# =========================================================
# PHASE 1 (HUGE-DATA SAFE / STAGING LABEL ONLY)
# ---------------------------------------------------------
# Goal:
# - Read raw Suricata EVE JSON/JSONL line-by-line.
# - Flatten only the core fields needed by later phases.
# - Extract label evidence, but DO NOT create final Target here.
# - Write staging shards to storage.
# - Return only a small df_sample for report/debug.
#
# Important methodology change:
# - no-alert is NOT treated as final benign.
# - final Target must be created later in label refinement phase.
# =========================================================

OUT_COLS = [
    "timestamp",
    "src_ip", "dest_ip",
    "src_port", "dest_port",
    "proto", "event_type", "app_proto",
    "flow_id", "pkt_src",

    # flow flat
    "has_flow",
    "pkts_toserver", "pkts_toclient",
    "bytes_toserver", "bytes_toclient",
    "duration",
    "total_pkts", "total_bytes",

    # alert evidence fields
    "has_alert",
    "alert_category",
    "alert_severity",
    "alert_signature",
    "alert_signature_id",

    # label evidence fields, not final label
    "label_evidence_alert",
    "label_evidence_compromised_ip",
    "label_status",
    "label_reason",

    # temporary numeric flag for audit only; not final training label
    #  1 = malicious evidence exists
    # -1 = unknown / not finalized
    "Target_prelim",
]

INT_COLS = [
    "src_port", "dest_port",
    "has_flow",
    "pkts_toserver", "pkts_toclient",
    "bytes_toserver", "bytes_toclient",
    "total_pkts", "total_bytes",
    "has_alert", "alert_severity", "alert_signature_id",
    "label_evidence_alert", "label_evidence_compromised_ip",
    "Target_prelim",
]

FLOAT_COLS = ["duration"]

STR_COLS = [
    "timestamp",
    "src_ip", "dest_ip",
    "proto", "event_type", "app_proto",
    "flow_id", "pkt_src",
    "alert_category", "alert_signature",
    "label_status", "label_reason",
]


# -----------------------------
# Fast JSON decoder
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
        if isinstance(x, str) and not x.strip():
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
        if isinstance(x, str) and not x.strip():
            return default
        return float(x)
    except Exception:
        return default


def _norm_text(x: Any, default: str = "") -> str:
    if x is None:
        return default
    try:
        if isinstance(x, float) and np.isnan(x):
            return default
    except Exception:
        pass
    return str(x)


def _is_false_positive_alert_category(category: str, false_positive_alert_category: str) -> bool:
    return category.strip().lower() == false_positive_alert_category.strip().lower()


def _extract_label_evidence(
    event: dict,
    *,
    false_positive_alert_category: str = "generic protocol decode",
    compromised_ips: Optional[Set[str]] = None,
) -> dict:
    """
    Extract evidence only. Do NOT finalize Target here.

    Target_prelim convention:
      1  = clear malicious evidence exists from alert or compromised IP
     -1  = unknown / still needs refinement

    Final Target will be created in phase4_label_refinement.py.
    """
    compromised_ips = compromised_ips or set()

    src_ip = _norm_text(event.get("src_ip"))
    dest_ip = _norm_text(event.get("dest_ip"))

    alert = event.get("alert")
    has_alert = 1 if isinstance(alert, dict) else 0

    alert_category = "none"
    alert_severity = 0
    alert_signature = "none"
    alert_signature_id = 0

    label_evidence_alert = 0
    label_evidence_compromised_ip = 0
    reasons: List[str] = []

    if has_alert:
        alert_category = _norm_text(alert.get("category", "unknown"), "unknown")
        alert_severity = _to_int(alert.get("severity", 0), 0)
        alert_signature = _norm_text(alert.get("signature", "unknown"), "unknown")
        alert_signature_id = _to_int(alert.get("signature_id", 0), 0)

        # Valid alert evidence means alert exists, severity exists, and category is not ignored.
        if (
            alert_severity > 0
            and not _is_false_positive_alert_category(alert_category, false_positive_alert_category)
        ):
            label_evidence_alert = 1
            reasons.append("valid_alert")
        else:
            reasons.append("ignored_or_weak_alert")

    if compromised_ips:
        if (src_ip and src_ip in compromised_ips) or (dest_ip and dest_ip in compromised_ips):
            label_evidence_compromised_ip = 1
            reasons.append("compromised_ip")

    has_malicious_evidence = bool(label_evidence_alert or label_evidence_compromised_ip)

    if has_malicious_evidence:
        label_status = "malicious_evidence"
        target_prelim = 1
    elif has_alert:
        label_status = "weak_or_ignored_alert"
        target_prelim = -1
    else:
        # Key change: this is NOT final benign.
        label_status = "no_alert_unknown"
        target_prelim = -1
        reasons.append("no_alert_not_final_benign")

    return {
        "has_alert": has_alert,
        "alert_category": alert_category,
        "alert_severity": alert_severity,
        "alert_signature": alert_signature,
        "alert_signature_id": alert_signature_id,
        "label_evidence_alert": int(label_evidence_alert),
        "label_evidence_compromised_ip": int(label_evidence_compromised_ip),
        "label_status": label_status,
        "label_reason": ";".join(reasons) if reasons else "unknown",
        "Target_prelim": int(target_prelim),
    }


def _flatten_row(
    event: dict,
    *,
    false_positive_alert_category: str = "generic protocol decode",
    compromised_ips: Optional[Set[str]] = None,
) -> dict:
    # ---- FLOW ----
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

    evidence = _extract_label_evidence(
        event,
        false_positive_alert_category=false_positive_alert_category,
        compromised_ips=compromised_ips,
    )

    return {
        "timestamp": event.get("timestamp"),
        "src_ip": event.get("src_ip"),
        "dest_ip": event.get("dest_ip"),
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

        **evidence,
    }


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


def _counter_top_dict(counter: Counter, n: int = 50, *, stringify_keys: bool = True) -> Dict[str, int]:
    """Return a JSON-safe top-N counter dictionary for metrics/visualization."""
    out: Dict[str, int] = {}
    for k, v in counter.most_common(int(n)):
        key = str(k) if stringify_keys else k
        out[key] = int(v)
    return out


def _phase1_visualization_stats(
    *,
    app: Optional[str],
    stats: Dict[str, Any],
    event_type_counter: Counter,
    app_proto_counter: Counter,
    proto_counter: Counter,
    dest_port_counter: Counter,
    label_status_counter: Counter,
    alert_category_counter: Counter,
) -> Dict[str, Any]:
    """Compact metrics block consumed by Phase 9 visualizations.

    Phase 9 should draw overview charts from these metrics instead of reading
    raw JSONL/Parquet again. This block intentionally stores small top-N
    counters only. Final malicious/benign Target counts are still produced by
    Phase 4/7, not by Phase 1.
    """
    rows = int(stats.get('rows_written', stats.get('total_lines_seen', stats.get('total_lines', 0))) or 0)
    total_lines = int(stats.get('total_lines_seen', stats.get('total_lines', 0)) or 0)
    decoded = int(stats.get('decoded_events', 0) or 0)

    return {
        'app': app,
        'total_lines_seen': total_lines,
        'decoded_events': decoded,
        'rows_after_phase1': rows,
        'malformed': int(stats.get('malformed', 0) or 0),
        'missing_src_ip': int(stats.get('missing_src_ip', 0) or 0),
        'valid_alert_evidence': int(stats.get('valid_alert_evidence', 0) or 0),
        'malicious_evidence': int(stats.get('malicious_evidence', 0) or 0),
        'weak_or_ignored_alert': int(stats.get('weak_or_ignored_alert', 0) or 0),
        'no_alert_unknown': int(stats.get('no_alert_unknown', 0) or 0),
        'event_type_counts_top50': _counter_top_dict(event_type_counter, 50),
        'proto_counts_top20': _counter_top_dict(proto_counter, 20),
        'app_proto_counts_top50': _counter_top_dict(app_proto_counter, 50),
        'dest_port_counts_top50': _counter_top_dict(dest_port_counter, 50),
        'label_status_counts': _counter_top_dict(label_status_counter, 50),
        'alert_category_counts_top50': _counter_top_dict(alert_category_counter, 50),
        'note': (
            'This block is for Phase 9 summary-driven visualization. '
            'It is not final class distribution; final Target counts are generated in Phase 4/7.'
        ),
    }


@dataclass(frozen=True)
class Phase1DiskConfig:
    output_dir: Path
    write_format: str = "parquet"       # "parquet" or "csv"
    batch_size: int = 200_000
    return_df_sample: int = 200_000
    save_sample_file: bool = True

    parquet_engine: Optional[str] = None           # "fastparquet" | "pyarrow" | None
    parquet_compression: Optional[str] = "snappy" # "snappy" | "gzip" | None


class _ShardWriter:
    """
    Writes staging shards:
      - Parquet if available
      - CSV.GZ fallback if parquet engine unavailable
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

    def _normalize_schema(self, rows: List[dict]) -> pd.DataFrame:
        df = pd.DataFrame.from_records(rows)

        for c in OUT_COLS:
            if c not in df.columns:
                df[c] = np.nan
        df = df[OUT_COLS]

        for c in INT_COLS:
            if c in df.columns:
                try:
                    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(np.int32)
                except Exception:
                    pass

        for c in FLOAT_COLS:
            if c in df.columns:
                try:
                    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(np.float32)
                except Exception:
                    pass

        for c in STR_COLS:
            if c in df.columns:
                try:
                    s = df[c].astype("object")
                    s = s.where(pd.notna(s), "")
                    df[c] = s.astype(str)
                except Exception:
                    df[c] = df[c].map(lambda x: "" if x is None else str(x))

        return df

    def flush(self, rows: List[dict]) -> Optional[Path]:
        if not rows:
            return None

        self.part += 1
        df = self._normalize_schema(rows)

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


def _load_compromised_ip_file(path: Optional[Path]) -> Set[str]:
    """
    Optional helper. Accepts a plain text file with one IP per line.
    Lines starting with # are ignored.
    """
    if path is None:
        return set()
    path = Path(path)
    if not path.exists():
        return set()

    ips: Set[str] = set()
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            ips.add(s)
    return ips


def phase1_initial_parsing_label_evidence(
    input_file: Path,
    *,
    max_lines: int | None = None,
    false_positive_alert_category: str = "generic protocol decode",
    compromised_ips: Optional[Set[str]] = None,
    compromised_ip_file: Optional[Path] = None,
    progress_desc: str = "PHASE 1",
    disk: Phase1DiskConfig,
) -> Tuple[pd.DataFrame, dict]:
    """
    Disk-backed Phase 1 for the new pipeline.

    This function:
    - reads raw EVE JSON line-by-line;
    - flattens core fields;
    - stores label evidence only;
    - writes staging shards to disk;
    - does NOT create final Target;
    - returns only a small df_sample in RAM.

    Output:
      disk.output_dir/
        staging/part-*.parquet
        sample/phase1_sample.parquet       optional

    Final Target must be created later by phase4_label_refinement.py.
    """
    print("\n" + "🔵 " + "=" * 76 + "\n")
    print("PHASE 1: INITIAL PARSING + LABEL EVIDENCE (DISK-BACKED, NO FINAL TARGET)")
    print("\n" + "🔵 " + "=" * 76)

    t0 = datetime.now()

    input_file = Path(input_file)
    out_dir = Path(disk.output_dir)
    staging_dir = out_dir / "staging"
    sample_dir = out_dir / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    ip_set: Set[str] = set(compromised_ips or set())
    ip_set.update(_load_compromised_ip_file(compromised_ip_file))

    writer = _ShardWriter(
        staging_dir,
        disk.write_format,
        parquet_engine=disk.parquet_engine,
        parquet_compression=disk.parquet_compression,
    )

    batch: List[dict] = []
    sample_rows: List[dict] = []
    sample_max = max(0, int(disk.return_df_sample))

    stats = {
        "total_lines": 0,
        "decoded_events": 0,
        "malformed": 0,
        "missing_src_ip": 0,
        "rows_written": 0,
        "shards_written": 0,
        "valid_alert_evidence": 0,
        "compromised_ip_evidence": 0,
        "malicious_evidence": 0,
        "weak_or_ignored_alert": 0,
        "no_alert_unknown": 0,
        "dataset_format": writer.actual_fmt,
        "dataset_dir": str(out_dir),
        "staging_dir": str(staging_dir),
    }

    event_type_counter = Counter()
    app_proto_counter = Counter()
    dest_port_counter = Counter()
    proto_counter = Counter()
    label_status_counter = Counter()
    alert_category_counter = Counter()

    pbar = tqdm(desc=f"{progress_desc} (stream/write staging)", unit="record", dynamic_ncols=True)
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
                pbar.update(1)
                continue

            stats["decoded_events"] += 1

            src_ip = event.get("src_ip")
            if not src_ip:
                stats["missing_src_ip"] += 1
                # Keep behavior conservative: skip rows without src_ip because probing/app analysis needs src_ip.
                pbar.update(1)
                continue

            row = _flatten_row(
                event,
                false_positive_alert_category=false_positive_alert_category,
                compromised_ips=ip_set,
            )

            batch.append(row)
            stats["rows_written"] += 1

            if sample_max > 0 and len(sample_rows) < sample_max:
                sample_rows.append(row)

            et = _norm_text(row.get("event_type"), "unknown") or "unknown"
            ap = _norm_text(row.get("app_proto"), "unknown") or "unknown"
            pr = _norm_text(row.get("proto"), "unknown") or "unknown"
            dp = _to_int(row.get("dest_port", 0), 0)
            status = _norm_text(row.get("label_status"), "unknown") or "unknown"
            cat = _norm_text(row.get("alert_category"), "none") or "none"

            event_type_counter[et] += 1
            app_proto_counter[ap] += 1
            proto_counter[pr] += 1
            dest_port_counter[dp] += 1
            label_status_counter[status] += 1
            alert_category_counter[cat] += 1

            if row["label_evidence_alert"] == 1:
                stats["valid_alert_evidence"] += 1
            if row["label_evidence_compromised_ip"] == 1:
                stats["compromised_ip_evidence"] += 1
            if row["label_status"] == "malicious_evidence":
                stats["malicious_evidence"] += 1
            elif row["label_status"] == "weak_or_ignored_alert":
                stats["weak_or_ignored_alert"] += 1
            elif row["label_status"] == "no_alert_unknown":
                stats["no_alert_unknown"] += 1

            if len(batch) >= disk.batch_size:
                path = writer.flush(batch)
                batch.clear()
                if path is not None:
                    stats["shards_written"] += 1
                gc.collect()

            if stats["total_lines"] % 200_000 == 0:
                pbar.set_postfix({
                    "RowsW": f"{stats['rows_written']:,}",
                    "Evid": f"{stats['malicious_evidence']:,}",
                    "Unknown": f"{stats['no_alert_unknown']:,}",
                    "Shards": f"{stats['shards_written']}",
                })
            pbar.update(1)
    pbar.close()

    if batch:
        path = writer.flush(batch)
        batch.clear()
        if path is not None:
            stats["shards_written"] += 1

    # Small df_sample only.
    if sample_max > 0 and sample_rows:
        df_sample = pd.DataFrame.from_records(sample_rows)
        for c in OUT_COLS:
            if c not in df_sample.columns:
                df_sample[c] = np.nan
        df_sample = df_sample[OUT_COLS]
    else:
        df_sample = pd.DataFrame(columns=OUT_COLS)

    # Save sample for quick inspection/report.
    sample_path: Optional[Path] = None
    if disk.save_sample_file and not df_sample.empty:
        if writer.actual_fmt == "parquet":
            sample_path = sample_dir / "phase1_sample.parquet"
            kwargs: Dict[str, Any] = {"index": False}
            if disk.parquet_engine:
                kwargs["engine"] = disk.parquet_engine
            if disk.parquet_compression:
                kwargs["compression"] = disk.parquet_compression
            df_sample.to_parquet(sample_path, **kwargs)
        else:
            sample_path = sample_dir / "phase1_sample.csv.gz"
            df_sample.to_csv(sample_path, index=False, compression="gzip")

    staging_bytes = _dir_size_bytes(staging_dir)
    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 1,
        "phase_name": "initial_parsing_label_evidence",
        "input_file": str(input_file),
        "max_lines": max_lines,

        "total_lines_seen": int(stats["total_lines"]),
        "decoded_events": int(stats["decoded_events"]),
        "malformed": int(stats["malformed"]),
        "missing_src_ip": int(stats["missing_src_ip"]),

        "rows_written": int(stats["rows_written"]),
        "shards_written": int(stats["shards_written"]),
        "dataset_format": str(stats["dataset_format"]),
        "dataset_dir": str(stats["dataset_dir"]),
        "staging_dir": str(stats["staging_dir"]),
        "sample_path": str(sample_path) if sample_path else None,

        "valid_alert_evidence": int(stats["valid_alert_evidence"]),
        "compromised_ip_evidence": int(stats["compromised_ip_evidence"]),
        "malicious_evidence": int(stats["malicious_evidence"]),
        "weak_or_ignored_alert": int(stats["weak_or_ignored_alert"]),
        "no_alert_unknown": int(stats["no_alert_unknown"]),

        "false_positive_alert_category": false_positive_alert_category,
        "compromised_ip_count": int(len(ip_set)),

        "event_type_counter_top10": _counter_top_dict(event_type_counter, 10),
        "app_proto_counter_top10": _counter_top_dict(app_proto_counter, 10),
        "proto_counter_top10": _counter_top_dict(proto_counter, 10),
        "dest_port_counter_top20": _counter_top_dict(dest_port_counter, 20),
        "label_status_counter": _counter_top_dict(label_status_counter, 50),
        "alert_category_counter_top10": _counter_top_dict(alert_category_counter, 10),
        "visualization_stats": _phase1_visualization_stats(
            app=None,
            stats={
                **stats,
                "total_lines_seen": stats.get("total_lines", 0),
            },
            event_type_counter=event_type_counter,
            app_proto_counter=app_proto_counter,
            proto_counter=proto_counter,
            dest_port_counter=dest_port_counter,
            label_status_counter=label_status_counter,
            alert_category_counter=alert_category_counter,
        ),

        "staging_bytes": int(staging_bytes),
        "staging_gib": float(_gib(staging_bytes)),
        "df_sample_shape": [int(df_sample.shape[0]), int(df_sample.shape[1])],
        "seconds": float(elapsed),

        "note_target": (
            "Phase 1 does not create final Target. no-alert rows are stored as no_alert_unknown. "
            "Final Target must be created by the label refinement phase."
        ),
        "note_leakage": (
            "has_alert, alert_category, alert_severity, alert_signature, label_status, "
            "label_reason, and Target_prelim are evidence/audit fields and must not be used "
            "as model features unless explicitly justified."
        ),
        "note_memory": (
            "Phase 1 is disk-backed and writes staging shards. It returns only df_sample in RAM."
        ),
    }

    # Persist summary JSON for pipeline/report use.
    metrics_dir = out_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    summary_path = metrics_dir / "phase1_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    summary["summary_path"] = str(summary_path)

    gc.collect()

    print("\n✅ PHASE 1 COMPLETE (STAGING, NO FINAL TARGET)")
    print(f"   Seen lines     : {stats['total_lines']:,}")
    print(f"   Rows written   : {stats['rows_written']:,}")
    print(f"   Shards written : {stats['shards_written']:,}")
    print(f"   Malicious evid.: {stats['malicious_evidence']:,}")
    print(f"   No-alert unk.  : {stats['no_alert_unknown']:,}")
    print(f"   Dataset format : {stats['dataset_format']}")
    print(f"   Staging dir    : {staging_dir}")
    print(f"   Staging size   : {_gib(staging_bytes):.2f} GiB")
    print(f"   df_sample      : {df_sample.shape}")
    print(f"   Summary        : {summary_path}")
    print(f"   Time           : {elapsed / 60:.2f} minutes")

    return df_sample, summary


# =============================================================================
# RAM MODE HELPERS (SMALL-DATA / SEMINAR DATASET)
# =============================================================================

def _normalize_phase1_dataframe(rows: List[dict]) -> pd.DataFrame:
    """
    Normalize Phase 1 rows into the same schema used by disk mode.

    This is used by RAM mode so downstream phases receive a stable DataFrame
    without writing intermediate Parquet/CSV shards.
    """
    if rows:
        df = pd.DataFrame.from_records(rows)
    else:
        df = pd.DataFrame(columns=OUT_COLS)

    for c in OUT_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[OUT_COLS]

    for c in INT_COLS:
        if c in df.columns:
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(np.int32)
            except Exception:
                pass

    for c in FLOAT_COLS:
        if c in df.columns:
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(np.float32)
            except Exception:
                pass

    for c in STR_COLS:
        if c in df.columns:
            try:
                s = df[c].astype("object")
                s = s.where(pd.notna(s), "")
                df[c] = s.astype(str)
            except Exception:
                df[c] = df[c].map(lambda x: "" if x is None else str(x))

    return df


def phase1_initial_parsing_label_evidence_ram(
    input_file: Path,
    *,
    app: Optional[str] = None,
    max_lines: int | None = None,
    false_positive_alert_category: str = "generic protocol decode",
    compromised_ips: Optional[Set[str]] = None,
    compromised_ip_file: Optional[Path] = None,
    progress_desc: str = "PHASE 1 RAM",
) -> Tuple[pd.DataFrame, dict]:
    """
    RAM-mode Phase 1 for the current small seminar/PPT dataset.

    This function:
    - reads one already-split app JSONL file, e.g. eve_http.jsonl;
    - parses and flattens rows into a pandas DataFrame;
    - extracts label evidence only;
    - DOES NOT write Parquet/CSV staging shards;
    - DOES NOT create final Target;
    - returns the full app DataFrame in RAM plus a summary dict.

    Intended flow:
      app=http  -> Phase 1 RAM -> Phase 2 RAM -> ... -> Phase 14 -> clear RAM
      app=tls   -> Phase 1 RAM -> Phase 2 RAM -> ... -> Phase 14 -> clear RAM
      app=dns   -> Phase 1 RAM -> Phase 2 RAM -> ... -> Phase 14 -> clear RAM
      app=ssh   -> Phase 1 RAM -> Phase 2 RAM -> ... -> Phase 14 -> clear RAM

    Disk-backed mode remains available through phase1_initial_parsing_label_evidence().
    """
    print("\n" + "🔵 " + "=" * 76 + "\n")
    app_label = f" app={app}" if app else ""
    print(f"PHASE 1: INITIAL PARSING + LABEL EVIDENCE{app_label} (RAM MODE, NO PARQUET)")
    print("\n" + "🔵 " + "=" * 76)

    t0 = datetime.now()
    input_file = Path(input_file)

    ip_set: Set[str] = set(compromised_ips or set())
    ip_set.update(_load_compromised_ip_file(compromised_ip_file))

    rows: List[dict] = []

    stats = {
        "total_lines_seen": 0,
        "decoded_events": 0,
        "malformed": 0,
        "missing_src_ip": 0,
        "rows_written": 0,
        "valid_alert_evidence": 0,
        "compromised_ip_evidence": 0,
        "malicious_evidence": 0,
        "weak_or_ignored_alert": 0,
        "no_alert_unknown": 0,
    }

    event_type_counter = Counter()
    app_proto_counter = Counter()
    dest_port_counter = Counter()
    proto_counter = Counter()
    label_status_counter = Counter()
    alert_category_counter = Counter()

    pbar = tqdm(desc=f"{progress_desc}{app_label} (stream to RAM)", unit="record", dynamic_ncols=True)
    with input_file.open("rb") as infile:
        for line_no, line in enumerate(infile, start=1):
            if max_lines is not None and int(max_lines) > 0 and line_no > int(max_lines):
                break

            stats["total_lines_seen"] += 1

            event = _safe_decode_json(line)
            if event is None:
                stats["malformed"] += 1
                pbar.update(1)
                continue

            stats["decoded_events"] += 1

            src_ip = event.get("src_ip")
            if not src_ip:
                stats["missing_src_ip"] += 1
                pbar.update(1)
                continue

            row = _flatten_row(
                event,
                false_positive_alert_category=false_positive_alert_category,
                compromised_ips=ip_set,
            )

            rows.append(row)
            stats["rows_written"] += 1

            et = _norm_text(row.get("event_type"), "unknown") or "unknown"
            ap = _norm_text(row.get("app_proto"), "unknown") or "unknown"
            pr = _norm_text(row.get("proto"), "unknown") or "unknown"
            dp = _to_int(row.get("dest_port", 0), 0)
            status = _norm_text(row.get("label_status"), "unknown") or "unknown"
            cat = _norm_text(row.get("alert_category"), "none") or "none"

            event_type_counter[et] += 1
            app_proto_counter[ap] += 1
            proto_counter[pr] += 1
            dest_port_counter[dp] += 1
            label_status_counter[status] += 1
            alert_category_counter[cat] += 1

            if row["label_evidence_alert"] == 1:
                stats["valid_alert_evidence"] += 1
            if row["label_evidence_compromised_ip"] == 1:
                stats["compromised_ip_evidence"] += 1
            if row["label_status"] == "malicious_evidence":
                stats["malicious_evidence"] += 1
            elif row["label_status"] == "weak_or_ignored_alert":
                stats["weak_or_ignored_alert"] += 1
            elif row["label_status"] == "no_alert_unknown":
                stats["no_alert_unknown"] += 1

            if stats["total_lines_seen"] % 200_000 == 0:
                pbar.set_postfix({
                    "Rows": f"{stats['rows_written']:,}",
                    "Evid": f"{stats['malicious_evidence']:,}",
                    "Unknown": f"{stats['no_alert_unknown']:,}",
                })
            pbar.update(1)
    pbar.close()

    df = _normalize_phase1_dataframe(rows)
    del rows
    gc.collect()

    elapsed = (datetime.now() - t0).total_seconds()
    df_memory_bytes = int(df.memory_usage(deep=True).sum()) if not df.empty else 0

    summary = {
        "phase": 1,
        "phase_name": "initial_parsing_label_evidence",
        "status": "completed",
        "app": app,
        "input_file": str(input_file),
        "input_mode": "split_app_jsonl",
        "output_mode": "dataframe_ram",
        "max_lines": max_lines,

        **{k: int(v) for k, v in stats.items()},

        "dataset_format": "dataframe_ram",
        "shards_written": 0,
        "staging_dir": None,
        "sample_path": None,

        "false_positive_alert_category": false_positive_alert_category,
        "compromised_ip_count": int(len(ip_set)),

        "event_type_counter_top10": _counter_top_dict(event_type_counter, 10),
        "app_proto_counter_top10": _counter_top_dict(app_proto_counter, 10),
        "proto_counter_top10": _counter_top_dict(proto_counter, 10),
        "dest_port_counter_top20": _counter_top_dict(dest_port_counter, 20),
        "label_status_counter": _counter_top_dict(label_status_counter, 50),
        "alert_category_counter_top10": _counter_top_dict(alert_category_counter, 10),
        "visualization_stats": _phase1_visualization_stats(
            app=app,
            stats=stats,
            event_type_counter=event_type_counter,
            app_proto_counter=app_proto_counter,
            proto_counter=proto_counter,
            dest_port_counter=dest_port_counter,
            label_status_counter=label_status_counter,
            alert_category_counter=alert_category_counter,
        ),

        "df_shape": [int(df.shape[0]), int(df.shape[1])],
        "df_memory_bytes": int(df_memory_bytes),
        "df_memory_mib": float(df_memory_bytes / (1024.0 ** 2)),
        "seconds": float(elapsed),

        "note_target": (
            "Phase 1 does not create final Target. no-alert rows are stored as no_alert_unknown. "
            "Final Target must be created by the label refinement phase."
        ),
        "note_leakage": (
            "has_alert, alert_category, alert_severity, alert_signature, label_status, "
            "label_reason, and Target_prelim are evidence/audit fields and must not be used "
            "as model features unless explicitly justified."
        ),
        "note_memory": (
            "RAM mode returns the full app DataFrame and writes no intermediate Parquet/CSV shards."
        ),
    }

    print("\n✅ PHASE 1 COMPLETE (RAM MODE, NO PARQUET)")
    print(f"   App            : {app or '-'}")
    print(f"   Seen lines     : {stats['total_lines_seen']:,}")
    print(f"   Rows in RAM    : {stats['rows_written']:,}")
    print(f"   Malicious evid.: {stats['malicious_evidence']:,}")
    print(f"   No-alert unk.  : {stats['no_alert_unknown']:,}")
    print(f"   DataFrame      : {df.shape} ({summary['df_memory_mib']:.2f} MiB)")
    print(f"   Time           : {elapsed / 60:.2f} minutes")

    return df, summary


# Alias names for pipeline.py RAM mode.
def phase1_load_and_label_ram(
    input_file: Path,
    *,
    app: Optional[str] = None,
    max_lines: int | None = None,
    false_positive_alert_category: str = "generic protocol decode",
    compromised_ips: Optional[Set[str]] = None,
    compromised_ip_file: Optional[Path] = None,
    progress_desc: str = "PHASE 1 RAM",
    **_: Any,
) -> Tuple[pd.DataFrame, dict]:
    return phase1_initial_parsing_label_evidence_ram(
        input_file=input_file,
        app=app,
        max_lines=max_lines,
        false_positive_alert_category=false_positive_alert_category,
        compromised_ips=compromised_ips,
        compromised_ip_file=compromised_ip_file,
        progress_desc=progress_desc,
    )


phase1_initial_parsing_label_evidence_in_memory = phase1_initial_parsing_label_evidence_ram


# Backward-compatible alias for pipeline imports.
# Later, pipeline.py should call phase1_initial_parsing_label_evidence directly.
def phase1_load_and_label(
    input_file: Path,
    *,
    max_lines: int | None = None,
    false_positive_alert_category: str = "generic protocol decode",
    compromised_ips: Optional[Set[str]] = None,
    compromised_ip_file: Optional[Path] = None,
    progress_desc: str = "PHASE 1",
    disk: Phase1DiskConfig,
    **_: Any,
) -> Tuple[pd.DataFrame, dict]:
    return phase1_initial_parsing_label_evidence(
        input_file=input_file,
        max_lines=max_lines,
        false_positive_alert_category=false_positive_alert_category,
        compromised_ips=compromised_ips,
        compromised_ip_file=compromised_ip_file,
        progress_desc=progress_desc,
        disk=disk,
    )


if __name__ == "__main__":
    # Example only. In the real run, main.py/pipeline.py should call this function.
    df_sample, summary = phase1_initial_parsing_label_evidence(
        input_file=Path(r"G:\path\to\eve.jsonl"),
        max_lines=None,
        false_positive_alert_category="generic protocol decode",
        compromised_ip_file=None,
        disk=Phase1DiskConfig(
            output_dir=Path("results/phase1_dataset"),
            write_format="parquet",
            batch_size=200_000,
            return_df_sample=200_000,
            save_sample_file=True,
            parquet_engine="fastparquet",
            parquet_compression="snappy",
        ),
    )
    print(summary)
