from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Iterable

import pandas as pd


@dataclass
class ExportConfig:
    """
    Phase 5 Export configuration (disk artifacts):
    - mode:
        "none"       -> tidak export
        "sample_csv" -> export hanya N baris (aman & kecil)
        "csv_gz"     -> export full tapi gzip (lebih hemat disk, masih bisa besar)
        "csv"        -> export full CSV (paling berat)
    """
    mode: str = "sample_csv"
    sample_rows: int = 200_000

    filename_stem: str = "eve_processed"
    include_columns: Optional[Iterable[str]] = None  # None = semua kolom
    index: bool = False

    # output placement
    out_dir: Optional[Path] = None  # wajib diisi oleh pipeline
    sample_size_tag: str = "NA"     # buat nama file

    # gzip level (untuk csv_gz)
    compression: Optional[str] = "gzip"  # dipakai kalau mode == "csv_gz"

    # NEW: sampling behavior for sample_csv
    seed: int = 42
    stratify_col: str = "Target"          # stratify if exists
    stratify: bool = True                # if True and stratify_col exists -> stratified sampling


def _file_size_mb(p: Path) -> float:
    try:
        return p.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0


def _sample_df(df: pd.DataFrame, n: int, *, seed: int, stratify: bool, stratify_col: str) -> pd.DataFrame:
    """
    Sampling helper:
    - Prefer stratified sampling on stratify_col if enabled and exists.
    - Fallback to random sample.
    """
    n = int(max(0, min(n, len(df))))
    if n == 0:
        return df.iloc[:0].copy()

    if stratify and (stratify_col in df.columns):
        try:
            # keep original class proportions
            vc = df[stratify_col].value_counts(dropna=False)
            total = int(vc.sum())
            parts = []
            remaining = n

            # allocate by proportion (floor), then distribute remainder
            alloc = {}
            for k, v in vc.items():
                alloc[k] = int((int(v) / max(1, total)) * n)

            # ensure at least 1 sample if class exists and n allows
            # (optional; comment out if you prefer pure proportion)
            for k in alloc:
                if alloc[k] == 0 and remaining > 0 and int(vc[k]) > 0:
                    alloc[k] = 1

            used = sum(alloc.values())
            if used > n:
                # trim if overshoot
                # reduce largest classes first
                over = used - n
                for k in sorted(alloc, key=lambda kk: alloc[kk], reverse=True):
                    if over <= 0:
                        break
                    dec = min(over, max(0, alloc[k] - 1))
                    alloc[k] -= dec
                    over -= dec
            else:
                remaining = n - used
                # distribute remainder to largest classes
                for k in sorted(vc.index.tolist(), key=lambda kk: int(vc[kk]), reverse=True):
                    if remaining <= 0:
                        break
                    alloc[k] += 1
                    remaining -= 1

            for k, take in alloc.items():
                take = min(int(take), int((df[stratify_col] == k).sum()))
                if take <= 0:
                    continue
                parts.append(df[df[stratify_col] == k].sample(n=take, random_state=seed))

            if parts:
                out = pd.concat(parts, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)
                return out

        except Exception:
            # fallback random
            pass

    # fallback random sample
    return df.sample(n=n, random_state=seed).reset_index(drop=True)


def phase5_export_dataset(
    df: pd.DataFrame,
    *,
    cfg: ExportConfig,
) -> Dict[str, Any]:
    """
    Phase 5: Export to disk (artifact).
    Return summary dict (paths, size, rows, cols).
    """
    print("\n" + "🟡 " + "="*76 + "\n")
    print("PHASE 5: EXPORT TO DATASET ARTIFACT (CSV/CSV.GZ/SAMPLE)")
    print("\n" + "🟡 " + "="*76)

    if df is None or len(df) == 0:
        raise ValueError("Phase 5 got empty df")

    if cfg.out_dir is None:
        raise ValueError("ExportConfig.out_dir must be set (e.g., ARTIFACTS_DIR/'exports')")

    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mode = (cfg.mode or "none").strip().lower()
    t0 = datetime.now()

    # select columns (optional)
    if cfg.include_columns is not None:
        cols = [c for c in cfg.include_columns if c in df.columns]
        df_out = df[cols].copy()
    else:
        df_out = df

    summary: Dict[str, Any] = {
        "phase": 5,
        "mode": mode,
        "input_rows": int(len(df)),
        "input_cols": int(df.shape[1]),
        "export_rows": None,
        "export_cols": int(df_out.shape[1]),
        "output_path": None,
        "output_size_mb": None,
        "seconds": None,
        "seed": int(cfg.seed),
        "stratify": bool(cfg.stratify),
        "stratify_col": str(cfg.stratify_col),
        "note": (
            "Phase 5 is optional. For huge datasets, prefer sample_csv or csv_gz. "
            "sample_csv uses RANDOM/STRATIFIED sampling (not head) to avoid class/order bias."
        ),
    }

    if mode == "none":
        print("ℹ️  Export mode=none -> skip export.")
        summary["seconds"] = float((datetime.now() - t0).total_seconds())
        return summary

    if mode == "sample_csv":
        n = min(int(cfg.sample_rows), len(df_out))
        df_write = _sample_df(
            df_out, n,
            seed=int(cfg.seed),
            stratify=bool(cfg.stratify),
            stratify_col=str(cfg.stratify_col),
        )
        out_path = out_dir / f"{cfg.filename_stem}_{cfg.sample_size_tag}_sample{n}.csv"
        df_write.to_csv(out_path, index=cfg.index)
        print(f"✓ Exported SAMPLE CSV: {out_path} (rows={n:,})")

        # helpful: print target dist if available
        if cfg.stratify_col in df_write.columns:
            dist = df_write[cfg.stratify_col].value_counts().to_dict()
            dist = {str(k): int(v) for k, v in dist.items()}
            print(f"   Target dist (sample): {dist}")

    elif mode == "csv_gz":
        out_path = out_dir / f"{cfg.filename_stem}_{cfg.sample_size_tag}.csv.gz"
        df_out.to_csv(out_path, index=cfg.index, compression=cfg.compression or "gzip")
        print(f"✓ Exported CSV.GZ: {out_path} (rows={len(df_out):,})")

    elif mode == "csv":
        out_path = out_dir / f"{cfg.filename_stem}_{cfg.sample_size_tag}.csv"
        df_out.to_csv(out_path, index=cfg.index)
        print(f"✓ Exported CSV: {out_path} (rows={len(df_out):,})")

    else:
        raise ValueError(f"Unknown export mode: {cfg.mode}. Use: none | sample_csv | csv_gz | csv")

    elapsed = (datetime.now() - t0).total_seconds()
    summary["export_rows"] = int(len(df_write) if mode == "sample_csv" else len(df_out))
    summary["output_path"] = str(out_path)
    summary["output_size_mb"] = float(_file_size_mb(out_path))
    summary["seconds"] = float(elapsed)

    print(f"   Size: {summary['output_size_mb']:.2f} MB")
    print(f"   Time: {summary['seconds']/60:.2f} minutes\n")
    return summary
