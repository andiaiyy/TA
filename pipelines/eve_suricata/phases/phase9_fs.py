# src/cbr/phases/phase9_feature_selection.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

import json
import numpy as np
import pandas as pd

from sklearn.feature_selection import mutual_info_classif, RFE
from sklearn.ensemble import RandomForestClassifier
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class Phase9Config:
    # core
    target_col: str = "Target"
    seed: int = 42

    # sampling
    # NOTE: these MUST be dataclass fields (annotated) so pipeline can override.
    fs_sample_n: int = 5_000_000
    mi_max_rows: int = 1_000_000
    rfe_max_rows: int = 1_500_000
    pca_max_rows: int = 3_000_000
    # selection size
    top_k: int = 25

    # drop columns (optional; will be ignored if not present)
    drop_cols: Tuple[str, ...] = (
        "timestamp",
        "src_ip", "dest_ip",
        "src_port", "dest_port",
        "proto", "event_type",
        "alert_category",
        "community_id",
        # guard leakage proxies (safe if absent)
        "event_type_h",
        "has_alert",
        "alert_severity",
        # pkt_src / app_proto / flow_id: hash-encoded by Phase 2; alert-records
        # and flow-records have systematically different values, so the hashes
        # leak Target. Phase 8 already drops them — this is a defensive backstop.
        "pkt_src", "app_proto", "flow_id",
    )

    # outputs (small artifacts only; not used as cache)
    out_dir: Optional[Path] = None
    filename_tag: str = "run"

    # optional outputs
    write_artifacts: bool = True          # write json/csv of rankings + selected sets
    write_sample_csv: bool = False        # WARNING: can be large; default False


# -----------------------------
# small IO helpers
# -----------------------------
def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _to_numeric_frame(X: pd.DataFrame) -> pd.DataFrame:
    Xn = X.select_dtypes(include=[np.number]).copy()
    if Xn.shape[1] == 0:
        return Xn

    for c in Xn.columns:
        Xn[c] = pd.to_numeric(Xn[c], errors="coerce")
        Xn[c] = Xn[c].replace([np.inf, -np.inf], np.nan).fillna(0)
    return Xn


def _safe_mutual_info(X: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    try:
        return mutual_info_classif(X, y, random_state=seed, n_jobs=-1)
    except TypeError:
        return mutual_info_classif(X, y, random_state=seed)


def _stratified_sample(df: pd.DataFrame, target_col: str, n: int, seed: int) -> pd.DataFrame:
    if target_col not in df.columns:
        raise RuntimeError(f"Missing target_col={target_col} in df_train.")

    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    vc = y.value_counts().to_dict()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class: {vc}")

    total = int(len(df))
    n = int(min(max(1, n), total))

    n1 = int(round(n * (vc.get(1, 0) / total))) if total else 0
    n0 = n - n1

    if vc.get(1, 0) > 0 and n1 == 0:
        n1 = 1
        n0 = max(0, n - n1)
    if vc.get(0, 0) > 0 and n0 == 0:
        n0 = 1
        n1 = max(0, n - n0)

    df0 = df[y == 0]
    df1 = df[y == 1]

    take0 = min(n0, len(df0))
    take1 = min(n1, len(df1))

    rng = np.random.RandomState(seed)
    parts = []
    if take0 > 0:
        parts.append(df0.sample(n=take0, random_state=int(rng.randint(0, 2**31 - 1))))
    if take1 > 0:
        parts.append(df1.sample(n=take1, random_state=int(rng.randint(0, 2**31 - 1))))

    s = pd.concat(parts, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return s


def phase9_feature_selection(df_train: pd.DataFrame, cfg: Phase9Config) -> dict:
    """
    Phase 9:
    - Input: df_train (Phase 8 output; train only)
    - Output:
      - feature_sets (MI/RFE selected feature names; PCA n_components)
      - rankings (mi_df, rfe_df)
      - pca_meta + scaler/pca objects
      - summary includes ALL selected features (so PDF can render from summary alone)
    """
    t0 = datetime.now()
    print("\n" + "=" * 80)
    print("🔬 PHASE 9: FEATURE SELECTION (MI, RFE, PCA) [NO CACHE]")
    print("=" * 80)

    if cfg.out_dir is not None:
        cfg.out_dir.mkdir(parents=True, exist_ok=True)

    # 1) FS sample from TRAIN (stratified)
    df_fs = _stratified_sample(df_train, cfg.target_col, cfg.fs_sample_n, cfg.seed)

    y = pd.to_numeric(df_fs[cfg.target_col], errors="coerce").fillna(0).astype(int)
    vc = y.value_counts().to_dict()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class in FS sample: {vc}")

    # drop target + known cols, then keep numeric only
    drop_cols = [cfg.target_col, *cfg.drop_cols]
    X_raw = df_fs.drop(columns=drop_cols, errors="ignore")
    X = _to_numeric_frame(X_raw)

    print("\n[DEBUG] df_fs columns:", len(df_fs.columns))
    print("[DEBUG] X_raw columns:", X_raw.shape[1])
    print("[DEBUG] numeric cols:", X.shape[1])
    print("[DEBUG] numeric col names:", list(X.columns)[:50])
    # lihat berapa non-numeric yang kebuang
    non_num = [c for c in X_raw.columns if c not in set(X.columns)]
    print("[DEBUG] dropped non-numeric cols (first 50):", non_num[:50])

    if X.shape[1] == 0:
        raise RuntimeError("No numeric features found for Phase 9. Check Phase 2/3/4/8 outputs.")

    n_select = int(min(cfg.top_k, X.shape[1]))
    print(f"📊 FS input (TRAIN sample): rows={len(X):,}, numeric_features={X.shape[1]}, top_k={n_select}")
    print(f"   Target dist: {vc}")

    if cfg.write_sample_csv and cfg.out_dir is not None:
        sample_path = cfg.out_dir / f"phase9_train_sample_{cfg.filename_tag}_n{len(df_fs)}.csv"
        df_fs.to_csv(sample_path, index=False)
        print(f"💾 (audit) saved sample csv: {sample_path}")

    # 2) MI (capped)
    print("\n📈 Method 1: Mutual Information (MI)")
    n_mi = int(min(cfg.mi_max_rows, len(X)))
    if len(X) > n_mi:
        idx = np.random.RandomState(cfg.seed).choice(len(X), n_mi, replace=False)
        X_mi = X.iloc[idx].values
        y_mi = y.iloc[idx].values
        print(f"   Using MI rows: {n_mi:,}/{len(X):,}")
    else:
        X_mi = X.values
        y_mi = y.values
        print(f"   Using MI rows: {len(X):,}/{len(X):,}")

    try:
        mi_scores = _safe_mutual_info(X_mi, y_mi, cfg.seed)
        mi_df = pd.DataFrame({"Feature": X.columns, "MI_Score": mi_scores}).sort_values("MI_Score", ascending=False)
        mi_selected = mi_df.head(n_select)["Feature"].tolist()
        print(f"   ✓ MI done. selected={len(mi_selected)}")
    except Exception as e:
        print(f"   ⚠️ MI failed ({e}). Fallback: variance ranking.")
        var = X.var().sort_values(ascending=False)
        mi_df = pd.DataFrame({"Feature": var.index, "MI_Score": var.values})
        mi_selected = var.head(n_select).index.tolist()

    # 3) RFE (capped)
    print("\n📉 Method 2: RFE (RandomForest)")
    n_rfe = int(min(cfg.rfe_max_rows, len(X)))
    if len(X) > n_rfe:
        idx = np.random.RandomState(cfg.seed).choice(len(X), n_rfe, replace=False)
        X_rfe = X.iloc[idx].reset_index(drop=True)
        y_rfe = y.iloc[idx].reset_index(drop=True)
        print(f"   Using RFE rows: {n_rfe:,}/{len(X):,}")
    else:
        X_rfe = X.reset_index(drop=True)
        y_rfe = y.reset_index(drop=True)
        print(f"   Using RFE rows: {len(X):,}/{len(X):,}")

    try:
        base_rf = RandomForestClassifier(
            n_estimators=80,
            random_state=cfg.seed,
            n_jobs=-1,
            class_weight=None,
        )
        step = max(1, min(5, X.shape[1] // 10))
        rfe = RFE(estimator=base_rf, n_features_to_select=n_select, step=step)
        rfe.fit(X_rfe, y_rfe)

        rfe_selected = X.columns[rfe.support_].tolist()
        rfe_df = pd.DataFrame({
            "Feature": X.columns,
            "RFE_Ranking": rfe.ranking_,
            "Selected": rfe.support_.astype(bool),
        }).sort_values(["RFE_Ranking", "Feature"], ascending=[True, True])

        print(f"   ✓ RFE done. selected={len(rfe_selected)}")
    except Exception as e:
        print(f"   ⚠️ RFE failed ({e}). Fallback: RF importance.")
        rf = RandomForestClassifier(n_estimators=120, random_state=cfg.seed, n_jobs=-1)
        take = min(20_000, len(X_rfe))
        rf.fit(X_rfe.head(take), y_rfe.head(take))
        imp = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
        rfe_selected = imp.head(n_select).index.tolist()
        rfe_df = pd.DataFrame({"Feature": imp.index, "Importance": imp.values})

    # 4) PCA
    print("\n🔄 Method 3: PCA (StandardScaler + PCA fit on TRAIN sample cap)")
    n_pca = int(min(cfg.pca_max_rows, len(X)))
    if len(X) > n_pca:
        idx = np.random.RandomState(cfg.seed).choice(len(X), n_pca, replace=False)
        X_pca_fit = X.iloc[idx].reset_index(drop=True)
        print(f"   Using PCA fit rows: {n_pca:,}/{len(X):,}")
    else:
        X_pca_fit = X.reset_index(drop=True)
        print(f"   Using PCA fit rows: {len(X):,}/{len(X):,}")

    n_components = int(min(n_select, X.shape[1]))
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_pca_fit.values)

    pca = PCA(n_components=n_components, random_state=cfg.seed)
    pca.fit(X_scaled)

    cumsum = np.cumsum(pca.explained_variance_ratio_)
    pca_meta = {
        "n_components": int(n_components),
        "fit_rows": int(len(X_pca_fit)),
        "cumulative_variance": float(cumsum[-1]) if len(cumsum) else 0.0,
        "explained_variance_ratio": [float(v) for v in pca.explained_variance_ratio_],
    }
    print(f"   ✓ PCA fitted. CumVar({n_components})={pca_meta['cumulative_variance']*100:.2f}%")

    # 5) feature_sets (used by Phase 10)
    feature_sets = {
        "MI": mi_selected,
        "RFE": rfe_selected,
        "PCA": {"n_components": int(n_components)},
    }

    # ✅ IMPORTANT: put selected features inside summary for PDF
    summary = {
        "phase": 9,
        "mode": "no_cache",
        "generated_at": datetime.now().isoformat(),

        "train_rows_in": int(len(df_train)),
        "fs_sample_rows": int(len(df_fs)),
        "target_dist_sample": {str(k): int(v) for k, v in pd.Series(y).value_counts().to_dict().items()},

        "numeric_features_total": int(X.shape[1]),
        "top_k": int(n_select),

        "mi_selected_n": int(len(mi_selected)),
        "rfe_selected_n": int(len(rfe_selected)),
        "pca_n_components": int(n_components),
        "pca_cumvar": float(pca_meta["cumulative_variance"]),

        "dropped_cols_attempted": list(drop_cols),

        # NEW: embed feature lists + PCA meta for downstream PDF
        "feature_sets": feature_sets,
        "pca_meta": pca_meta,
    }

    # 6) write artifacts
    paths: Dict[str, str] = {}
    if cfg.write_artifacts and cfg.out_dir is not None:
        out = cfg.out_dir
        mi_path = out / f"phase9_mi_ranking_{cfg.filename_tag}.csv"
        rfe_path = out / f"phase9_rfe_ranking_{cfg.filename_tag}.csv"
        fs_path = out / f"phase9_feature_sets_{cfg.filename_tag}.json"
        meta_path = out / f"phase9_meta_{cfg.filename_tag}.json"
        pca_meta_path = out / f"phase9_pca_meta_{cfg.filename_tag}.json"

        mi_df.to_csv(mi_path, index=False)
        rfe_df.to_csv(rfe_path, index=False)
        _save_json(fs_path, {"feature_sets": feature_sets})
        _save_json(meta_path, summary)          # <-- now includes full selected features
        _save_json(pca_meta_path, pca_meta)

        paths = {
            "mi_ranking_csv": str(mi_path),
            "rfe_ranking_csv": str(rfe_path),
            "feature_sets_json": str(fs_path),
            "meta_json": str(meta_path),
            "pca_meta_json": str(pca_meta_path),
        }

        print("\n💾 Phase 9 artifacts written:")
        for k, v in paths.items():
            print(f"   - {k}: {v}")

    dt_s = (datetime.now() - t0).total_seconds()
    print(f"\n✅ Phase 9 done in {dt_s:.2f}s ({dt_s/60:.2f} min)")
    print("=" * 80)

    return {
        "feature_sets": feature_sets,
        "mi_df": mi_df,
        "rfe_df": rfe_df,
        "pca": pca,
        "scaler": scaler,
        "pca_meta": pca_meta,
        "summary": summary,
        "paths": paths,
    }