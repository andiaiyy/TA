# src/cbr/feature_engineering_advanced.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# =============================================================================
# AdvancedFeatureEngineer
# - Designed to be called from Phase 5 on each chunk/dataframe.
# - MUST NOT drop/shuffle rows.
# - Outputs mostly numeric features.
# - Keeps src_ip/dest_ip until Phase 11 so source_ip_hash split can work.
# - Phase 11 is responsible for dropping src_ip/dest_ip before modeling.
# - Deterministic hashing for categoricals.
# =============================================================================


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


def _stable_hash_series(s: pd.Series, mod: int) -> pd.Series:
    """
    Deterministic across chunks for the same values.
    """
    ss = s.astype("string").fillna("unknown")
    h = pd.util.hash_pandas_object(ss, index=False).astype("uint64")
    return (h % np.uint64(mod)).astype("int64")


def _is_private_ipv4(ip: pd.Series) -> pd.Series:
    s = ip.astype("string").fillna("")
    c10 = s.str.startswith("10.")
    c192 = s.str.startswith("192.168.")
    c172 = s.str.match(r"^172\.(1[6-9]|2\d|3[0-1])\.")
    return (c10 | c192 | c172).astype("int64")


def _subnet24(ip: pd.Series) -> pd.Series:
    """
    Extract IPv4 /24 prefix as string "a.b.c".
    If malformed, returns "0.0.0".
    """
    s = ip.astype("string").fillna("0.0.0.0")
    parts = s.str.split(".", n=3, expand=True)

    if parts.shape[1] >= 3:
        return (
            parts[0].fillna("0")
            + "."
            + parts[1].fillna("0")
            + "."
            + parts[2].fillna("0")
        )

    return pd.Series(["0.0.0"] * len(s), index=s.index, dtype="string")


def _port_class(port: pd.Series) -> pd.Series:
    """
    0: unknown/invalid
    1: well-known        1–1023
    2: registered        1024–49151
    3: dynamic/private   >=49152
    """
    p = _to_numeric_safe(port).astype("int64")

    out = np.select(
        [
            p.between(1, 1023),
            p.between(1024, 49151),
            p >= 49152,
        ],
        [1, 2, 3],
        default=0,
    )

    return pd.Series(out, index=p.index).astype("int64")


def _safe_div(numer: np.ndarray, denom: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    return numer / np.maximum(denom, eps)


@dataclass
class AdvancedFEConfig:
    # Hashing modulus, kept within int32-ish range.
    hash_mod: int = 2**31 - 1

    # High-cardinality identifiers that should not become model features.
    # IMPORTANT:
    # - src_ip and dest_ip are intentionally NOT listed here.
    # - They are preserved until Phase 11 so source_ip_hash split can use them.
    # - Phase 11 must drop src_ip/dest_ip before modeling.
    drop_id_cols: tuple[str, ...] = (
        "flow_id",
        "pkt_src",
        "community_id",
        "tx_id",
    )

    # Keep these suffixes as raw strings.
    raw_suffix: str = "_raw"

    # Encode leftover categorical columns, except preserved split/audit columns.
    encode_leftovers: bool = True

    # Columns to preserve as strings for downstream split/audit.
    preserve_string_cols: tuple[str, ...] = (
        "src_ip",
        "dest_ip",
    )


class AdvancedFeatureEngineer:
    """
    Domain-aware feature engineering for Suricata EVE / network flow context.

    Main outputs:
    - time features
    - IP private/subnet features
    - port class and service flags
    - flow totals, rates, ratios, and log transforms
    - deterministic hashes for protocol/application/event fields
    - deterministic encoding for remaining categoricals

    Important:
    - This class does not relabel Target.
    - This class does not shuffle or drop rows.
    - src_ip/dest_ip are preserved for Phase 11 split strategy.
    """

    def __init__(
        self,
        *,
        verbose: bool = False,
        config: Optional[AdvancedFEConfig] = None,
    ) -> None:
        self.verbose = bool(verbose)
        self.cfg = config or AdvancedFEConfig()

    def process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) == 0:
            return pd.DataFrame()

        out = df.reset_index(drop=True).copy()
        n0 = len(out)

        # ---------------------------------------------------------------------
        # 1) Ensure Target exists if present. Do not relabel here.
        # ---------------------------------------------------------------------
        if "Target" in out.columns:
            out["Target"] = _to_numeric_safe(out["Target"]).astype("int64")

        # ---------------------------------------------------------------------
        # 2) Timestamp features.
        # Keep timestamp until Phase 11? No. Timestamp itself is dropped here
        # because it is usually unique/high-cardinality and not needed for
        # source_ip_hash split.
        # ---------------------------------------------------------------------
        if "timestamp" in out.columns:
            ts = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
            out["ts_hour"] = ts.dt.hour.fillna(0).astype("int64")
            out["ts_dow"] = ts.dt.dayofweek.fillna(0).astype("int64")
            out["ts_is_weekend"] = (out["ts_dow"] >= 5).astype("int64")
        else:
            out["ts_hour"] = 0
            out["ts_dow"] = 0
            out["ts_is_weekend"] = 0

        # ---------------------------------------------------------------------
        # 3) IP-derived features.
        # Keep src_ip/dest_ip raw strings until Phase 11.
        # ---------------------------------------------------------------------
        if "src_ip" in out.columns:
            out["src_ip"] = out["src_ip"].astype("string").fillna("unknown")
            out["src_is_private"] = _is_private_ipv4(out["src_ip"])
            out["src_subnet24_h"] = _stable_hash_series(
                _subnet24(out["src_ip"]),
                self.cfg.hash_mod,
            )
        else:
            out["src_ip"] = "unknown"
            out["src_is_private"] = 0
            out["src_subnet24_h"] = 0

        if "dest_ip" in out.columns:
            out["dest_ip"] = out["dest_ip"].astype("string").fillna("unknown")
            out["dest_is_private"] = _is_private_ipv4(out["dest_ip"])
            out["dest_subnet24_h"] = _stable_hash_series(
                _subnet24(out["dest_ip"]),
                self.cfg.hash_mod,
            )
        else:
            out["dest_ip"] = "unknown"
            out["dest_is_private"] = 0
            out["dest_subnet24_h"] = 0

        out["same_subnet24"] = (
            out["src_subnet24_h"] == out["dest_subnet24_h"]
        ).astype("int64")

        # ---------------------------------------------------------------------
        # 4) Port features.
        # ---------------------------------------------------------------------
        if "src_port" in out.columns:
            out["src_port"] = _to_numeric_safe(out["src_port"]).astype("int64")
            out["src_port_class"] = _port_class(out["src_port"])
        else:
            out["src_port"] = 0
            out["src_port_class"] = 0

        if "dest_port" in out.columns:
            out["dest_port"] = _to_numeric_safe(out["dest_port"]).astype("int64")
            out["dest_port_class"] = _port_class(out["dest_port"])
        else:
            out["dest_port"] = 0
            out["dest_port_class"] = 0

        dport = out["dest_port"]

        out["dport_is_dns"] = (dport == 53).astype("int64")
        out["dport_is_http"] = (dport == 80).astype("int64")
        out["dport_is_https"] = (dport == 443).astype("int64")
        out["dport_is_ssh"] = (dport == 22).astype("int64")

        # ---------------------------------------------------------------------
        # 5) Flow totals, rates, ratios, logs.
        # ---------------------------------------------------------------------
        flow_cols = (
            "pkts_toserver",
            "pkts_toclient",
            "bytes_toserver",
            "bytes_toclient",
            "duration",
            "total_pkts",
            "total_bytes",
        )

        for c in flow_cols:
            if c in out.columns:
                out[c] = _to_numeric_safe(out[c]).astype("float64")
            else:
                out[c] = 0.0

        out["total_pkts"] = np.where(
            out["total_pkts"].to_numpy() != 0,
            out["total_pkts"].to_numpy(),
            (out["pkts_toserver"] + out["pkts_toclient"]).to_numpy(),
        )

        out["total_bytes"] = np.where(
            out["total_bytes"].to_numpy() != 0,
            out["total_bytes"].to_numpy(),
            (out["bytes_toserver"] + out["bytes_toclient"]).to_numpy(),
        )

        pkts = out["total_pkts"].to_numpy(dtype="float64")
        byt = out["total_bytes"].to_numpy(dtype="float64")
        dur = np.maximum(out["duration"].to_numpy(dtype="float64"), 1e-6)

        out["bytes_per_pkt"] = _safe_div(byt, pkts, eps=1.0)
        out["pkts_per_sec"] = _safe_div(pkts, dur)
        out["bytes_per_sec"] = _safe_div(byt, dur)

        b_srv = out["bytes_toserver"].to_numpy(dtype="float64")
        p_srv = out["pkts_toserver"].to_numpy(dtype="float64")

        out["bytes_toserver_ratio"] = _safe_div(b_srv, byt, eps=1.0)
        out["pkts_toserver_ratio"] = _safe_div(p_srv, pkts, eps=1.0)

        out["log_total_bytes"] = np.log1p(np.maximum(byt, 0.0))
        out["log_total_pkts"] = np.log1p(np.maximum(pkts, 0.0))
        out["log_duration"] = np.log1p(np.maximum(dur, 0.0))

        # ---------------------------------------------------------------------
        # 6) Encode protocol/application/event fields.
        # Keep original strings only until drop step below.
        # ---------------------------------------------------------------------
        for c in ("proto", "app_proto", "event_type"):
            if c in out.columns:
                out[f"{c}_h"] = _stable_hash_series(out[c], self.cfg.hash_mod)
            else:
                out[f"{c}_h"] = 0

        # ---------------------------------------------------------------------
        # 7) Drop high-cardinality identifiers.
        # Do not drop src_ip/dest_ip here.
        # Phase 11 uses src_ip for source_ip_hash split, then drops it.
        # ---------------------------------------------------------------------
        drop_cols = list(self.cfg.drop_id_cols)

        # Timestamp has already been transformed to ts_hour/ts_dow/ts_is_weekend.
        drop_cols += ["timestamp"]

        # Original protocol/event strings have hashed versions.
        drop_cols += ["proto", "app_proto", "event_type"]

        out = out.drop(
            columns=[c for c in drop_cols if c in out.columns],
            errors="ignore",
        )

        # ---------------------------------------------------------------------
        # 8) Encode leftover categoricals deterministically.
        # But preserve:
        # - Target
        # - *_raw columns
        # - src_ip/dest_ip for Phase 11 split/audit
        # ---------------------------------------------------------------------
        if self.cfg.encode_leftovers:
            raw_cols = {c for c in out.columns if str(c).endswith(self.cfg.raw_suffix)}
            preserve_cols = set(self.cfg.preserve_string_cols)

            for col in list(out.columns):
                if col == "Target":
                    continue

                if col in raw_cols:
                    continue

                if col in preserve_cols:
                    out[col] = out[col].astype("string").fillna("unknown")
                    continue

                if pd.api.types.is_numeric_dtype(out[col]):
                    out[col] = _to_numeric_safe(out[col])
                    continue

                num_try = pd.to_numeric(out[col], errors="coerce")
                ratio = float(num_try.notna().mean()) if len(num_try) else 0.0

                if ratio >= 0.98:
                    out[col] = _to_numeric_safe(out[col])
                else:
                    out[col] = _stable_hash_series(out[col], self.cfg.hash_mod)

            if "Target" in out.columns:
                out["Target"] = _to_numeric_safe(out["Target"]).astype("int64")

        # ---------------------------------------------------------------------
        # 9) Sanity check: do not change row count.
        # ---------------------------------------------------------------------
        if len(out) != n0:
            raise RuntimeError(
                f"AdvancedFeatureEngineer changed row count: {n0} -> {len(out)}"
            )

        if self.verbose:
            raw_cols = {c for c in out.columns if str(c).endswith(self.cfg.raw_suffix)}
            preserve_cols = set(self.cfg.preserve_string_cols)

            non_numeric = [
                c
                for c in out.columns
                if (
                    c != "Target"
                    and c not in raw_cols
                    and c not in preserve_cols
                    and not pd.api.types.is_numeric_dtype(out[c])
                )
            ]

            if non_numeric:
                suffix = "..." if len(non_numeric) > 10 else ""
                print(
                    f"[AdvancedFE] WARNING: leftover non-numeric cols: "
                    f"{non_numeric[:10]}{suffix}"
                )

        return out