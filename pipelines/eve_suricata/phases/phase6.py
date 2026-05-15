# src/cbr/phases/phase6.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import re

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

try:
    import seaborn as sns
    _HAS_SNS = True
except Exception:
    _HAS_SNS = False


@dataclass(frozen=True)
class Phase6Config:
    # Max rows used for visualization sampling (overview figure).
    n_viz: int = 1_000_000

    # Heatmap is much more expensive than the overview plots.
    n_heatmap: int = 100_000

    # Representative sampling
    stratify_by_target: bool = True
    seed: int = 42

    max_heatmap_features: int = 80
    target_col: str = "Target"
    force_rebuild: bool = False
    filename_tag: str = ""  # e.g. "50000000" (sample size)
    out_dir: Path = Path("results/figures")

    # NEW: reference ratio from Phase 1 summary
    ref_attack_total: int = 0
    ref_benign_total: int = 0
    prefer_phase1_ratio: bool = True


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _find_col_by_tokens(df: pd.DataFrame, token_sets) -> Optional[str]:
    cols = list(df.columns)
    norm_map = {c: _norm_name(c) for c in cols}
    for toks in token_sets:
        toks = [t.lower() for t in toks]
        for c in cols:
            nc = norm_map[c]
            if all(t in nc for t in toks):
                return c
    return None


def _add_under_text(ax, lines, x=0.02, y=-0.20, fontsize=8, ha="left"):
    if not lines:
        return
    ax.text(
        x, y, "\n".join(lines),
        transform=ax.transAxes,
        ha=ha, va="top",
        fontsize=fontsize,
        clip_on=False
    )


def _compute_take_counts(
    n_take: int,
    atk_avail: int,
    ben_avail: int,
    ref_attack_total: int,
    ref_benign_total: int,
    prefer_phase1_ratio: bool,
) -> tuple[int, int, str]:
    """
    Decide desired attack/benign sample counts.
    Prefer Phase 1 ratio if available; otherwise use observed df_clean ratio.
    """
    if n_take <= 0:
        return 0, 0, "none"

    use_ref = (
        prefer_phase1_ratio
        and int(ref_attack_total) >= 0
        and int(ref_benign_total) >= 0
        and (int(ref_attack_total) + int(ref_benign_total) > 0)
    )

    if use_ref:
        ref_total = int(ref_attack_total) + int(ref_benign_total)
        p_atk = float(ref_attack_total) / float(ref_total)
        source = "phase1_reference"
    else:
        obs_total = int(atk_avail) + int(ben_avail)
        p_atk = (float(atk_avail) / float(obs_total)) if obs_total > 0 else 0.0
        source = "df_clean_observed"

    atk_take = int(round(p_atk * n_take))
    ben_take = int(n_take - atk_take)

    atk_take = min(max(atk_take, 0), int(atk_avail))
    ben_take = min(max(ben_take, 0), int(ben_avail))

    cur = atk_take + ben_take
    if cur < n_take:
        rem = n_take - cur
        atk_left = int(atk_avail) - atk_take
        ben_left = int(ben_avail) - ben_take

        # Fill remainder from class with more spare capacity
        if ben_left >= atk_left:
            add_b = min(rem, ben_left)
            ben_take += add_b
            rem -= add_b
            if rem > 0:
                atk_take += min(rem, atk_left)
        else:
            add_a = min(rem, atk_left)
            atk_take += add_a
            rem -= add_a
            if rem > 0:
                ben_take += min(rem, ben_left)

    return int(atk_take), int(ben_take), source


def phase6_visualize_phase4(df_clean: pd.DataFrame, cfg: Phase6Config) -> dict[str, Any]:
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tag = cfg.filename_tag.strip() or "run"
    viz_overview_path = out_dir / f"visualization_overview_{tag}_n{cfg.n_viz}.png"
    corr_heatmap_path = out_dir / f"correlation_heatmap_{tag}_n{cfg.n_heatmap}.png"

    if (not cfg.force_rebuild) and viz_overview_path.exists() and corr_heatmap_path.exists():
        print("✅ Phase 6 outputs already exist. Skipping regeneration:")
        print(f"   ├─ {viz_overview_path}")
        print(f"   └─ {corr_heatmap_path}")
        return {
            "viz_overview_path": str(viz_overview_path),
            "corr_heatmap_path": str(corr_heatmap_path),
            "skipped": True,
            "n_viz": cfg.n_viz,
            "n_heatmap": cfg.n_heatmap,
            "max_heatmap_features": cfg.max_heatmap_features,
            "ref_attack_total": int(cfg.ref_attack_total),
            "ref_benign_total": int(cfg.ref_benign_total),
            "prefer_phase1_ratio": bool(cfg.prefer_phase1_ratio),
        }

    n_total = int(len(df_clean))
    n_take = int(min(max(1, int(cfg.n_viz)), n_total))

    if cfg.target_col not in df_clean.columns:
        raise RuntimeError(f"Target column missing in Phase 4 output: '{cfg.target_col}'")

    y_all = pd.to_numeric(df_clean[cfg.target_col], errors="coerce").fillna(0).astype(int)
    y_all = (y_all == 1).astype(int)

    rng = np.random.default_rng(int(cfg.seed))
    ratio_source = "random_fallback"

    atk_idx = np.where(y_all.to_numpy() == 1)[0]
    ben_idx = np.where(y_all.to_numpy() == 0)[0]
    atk_total = int(len(atk_idx))
    ben_total = int(len(ben_idx))

    if (not cfg.stratify_by_target) or (n_take >= n_total):
        pick = np.arange(n_total) if n_take >= n_total else rng.choice(n_total, size=n_take, replace=False)
        ratio_source = "full_input" if n_take >= n_total else "random_no_stratify"
    elif atk_total == 0 or ben_total == 0:
        pick = rng.choice(n_total, size=n_take, replace=False) if n_take < n_total else np.arange(n_total)
        ratio_source = "single_class_fallback"
    else:
        atk_take, ben_take, ratio_source = _compute_take_counts(
            n_take=n_take,
            atk_avail=atk_total,
            ben_avail=ben_total,
            ref_attack_total=int(cfg.ref_attack_total),
            ref_benign_total=int(cfg.ref_benign_total),
            prefer_phase1_ratio=bool(cfg.prefer_phase1_ratio),
        )

        atk_pick = rng.choice(atk_idx, size=atk_take, replace=False) if atk_take > 0 else np.array([], dtype=int)
        ben_pick = rng.choice(ben_idx, size=ben_take, replace=False) if ben_take > 0 else np.array([], dtype=int)

        pick = np.concatenate([atk_pick, ben_pick])
        if len(pick) == 0:
            pick = rng.choice(n_total, size=n_take, replace=False)
            ratio_source = "empty_pick_fallback"
        else:
            rng.shuffle(pick)

    df_viz = df_clean.iloc[pick].copy()
    df_viz[cfg.target_col] = pd.to_numeric(df_viz[cfg.target_col], errors="coerce").fillna(0).astype(int)
    target_dist = df_viz[cfg.target_col].value_counts().sort_index()
    has_both = (0 in target_dist.index) and (1 in target_dist.index)

    # prefer raw categorical if exists
    ev_col = "event_type_raw" if "event_type_raw" in df_viz.columns else ("event_type" if "event_type" in df_viz.columns else None)
    pr_col = "proto_raw" if "proto_raw" in df_viz.columns else ("proto" if "proto" in df_viz.columns else None)

    ev_series = df_viz[ev_col].astype("string").fillna("unknown").str.strip().str.lower() if ev_col else pd.Series(["unknown"] * len(df_viz), dtype="string")
    pr_series = df_viz[pr_col].astype("string").fillna("unknown").str.strip().str.upper() if pr_col else pd.Series(["UNKNOWN"] * len(df_viz), dtype="string")

    PROTO_MAP = {"ICMPV6": "IPv6-ICMP", "IPV6_ICMP": "IPv6-ICMP", "IPV6-ICMP": "IPv6-ICMP", "TCP": "TCP", "UDP": "UDP", "ICMP": "ICMP"}
    pr_series = pr_series.replace(PROTO_MAP)

    top_events = ev_series.value_counts().head(10)
    proto_counts = pr_series.value_counts()
    proto_order = ["TCP", "UDP", "ICMP", "IPv6-ICMP"]
    proto_counts = proto_counts.reindex(proto_order).fillna(0).astype(int)

    # packet/byte totals
    pkt_src = byte_src = ""
    pkt = byt = None

    if "total_pkts" in df_viz.columns:
        pkt = _to_num(df_viz["total_pkts"]).fillna(0)
        pkt_src = "total_pkts"

    if "total_bytes" in df_viz.columns:
        byt = _to_num(df_viz["total_bytes"]).fillna(0)
        byte_src = "total_bytes"

    fig = plt.figure(figsize=(16, 12))
    colors = ["#2ecc71", "#e74c3c"]
    label_map = {0: "🟢 BENIGN", 1: "🔴 ATTACK"}

    ax1 = plt.subplot(2, 3, 1)
    labels = [label_map.get(idx, str(idx)) for idx in target_dist.index]
    chart_colors = [colors[0] if idx == 0 else (colors[1] if idx == 1 else "#95a5a6") for idx in target_dist.index]
    wedges, texts, autotexts = ax1.pie(target_dist.values, labels=labels, autopct="%1.1f%%", colors=chart_colors, startangle=90)
    for t in autotexts:
        t.set_color("white"); t.set_fontweight("bold"); t.set_fontsize(11)
    ax1.set_title("Target Distribution\n(Attack vs Benign)", fontsize=12, fontweight="bold")
    _add_under_text(ax1, [f"Attack: {int(target_dist.get(1, 0)):,}", f"Benign: {int(target_dist.get(0, 0)):,}"], x=0.10, y=-0.18, fontsize=9, ha="left")

    ax2 = plt.subplot(2, 3, 2)
    ev_plot = top_events.sort_values(ascending=True)
    bars = ax2.barh(range(len(ev_plot)), ev_plot.values, color="steelblue")
    ax2.set_yticks(range(len(ev_plot))); ax2.set_yticklabels(ev_plot.index)
    ax2.set_xlabel("Count"); ax2.set_title("Top 10 Event Types", fontsize=12, fontweight="bold")
    for bar in bars:
        w = bar.get_width()
        ax2.text(w, bar.get_y() + bar.get_height() / 2, f" {int(w)}", ha="left", va="center", fontsize=9)

    ax3 = plt.subplot(2, 3, 3)
    if proto_counts.sum() == 0:
        ax3.text(0.5, 0.5, "No protocol data", ha="center", va="center"); ax3.axis("off")
    else:
        ax3.bar(range(len(proto_counts)), proto_counts.values, color="coral", edgecolor="black")
        ax3.set_xticks(range(len(proto_counts))); ax3.set_xticklabels(proto_counts.index, rotation=0)
        ax3.set_ylabel("Count"); ax3.set_title("Protocol Distribution", fontsize=12, fontweight="bold")
        ax3.grid(axis="y", alpha=0.3)
        _add_under_text(ax3, [f"{k}: {int(v):,}" for k, v in proto_counts.items()], x=0.02, y=-0.18, fontsize=9, ha="left")

    ax4 = plt.subplot(2, 3, 4)
    if "alert_severity" in df_viz.columns:
        sev = _to_num(df_viz["alert_severity"]).fillna(0).round().astype(int)
        if has_both:
            ct = pd.crosstab(sev, df_viz[cfg.target_col])
            if 0 not in ct.columns: ct[0] = 0
            if 1 not in ct.columns: ct[1] = 0
            ct = ct.sort_index()
            ax4.bar(ct.index.astype(str), ct[0].values, label="Benign", color=colors[0], alpha=0.8)
            ax4.bar(ct.index.astype(str), ct[1].values, bottom=ct[0].values, label="Attack", color=colors[1], alpha=0.8)
            ax4.legend()
            ax4.set_title("Alert Severity Distribution\n(stacked by Target)", fontsize=12, fontweight="bold")
        else:
            dist = sev.value_counts().sort_index()
            ax4.bar(dist.index.astype(str), dist.values, color="slateblue", edgecolor="black", alpha=0.85)
            ax4.set_title("Alert Severity Distribution", fontsize=12, fontweight="bold")
        ax4.set_xlabel("Severity"); ax4.set_ylabel("Count"); ax4.grid(axis="y", alpha=0.3)
    else:
        ax4.text(0.5, 0.5, "alert_severity not found", ha="center", va="center"); ax4.axis("off")

    ax5 = plt.subplot(2, 3, 5)
    if pkt is None:
        ax5.text(0.5, 0.5, "packet totals not found", ha="center", va="center"); ax5.axis("off")
    else:
        pkt2 = pd.to_numeric(pkt, errors="coerce").fillna(0)
        if has_both:
            pkt_b = pkt2[df_viz[cfg.target_col] == 0].values
            pkt_a = pkt2[df_viz[cfg.target_col] == 1].values
            bp = ax5.boxplot([pkt_b, pkt_a], labels=["Benign", "Attack"], patch_artist=True, showfliers=True)
            for patch, c in zip(bp["boxes"], colors):
                patch.set_facecolor(c); patch.set_alpha(0.7)
            ax5.set_title(f"Packet Count Distribution\n(by Target)\nsrc: {pkt_src}", fontsize=11, fontweight="bold")
            ax5.set_ylabel("Total Packets")
        else:
            ax5.hist(pkt2.values, bins=40, edgecolor="black", alpha=0.7)
            ax5.set_title(f"Packet Count Distribution\nsrc: {pkt_src}", fontsize=11, fontweight="bold")
        ax5.grid(axis="y", alpha=0.3)

    ax6 = plt.subplot(2, 3, 6)
    if byt is None:
        ax6.text(0.5, 0.5, "byte totals not found", ha="center", va="center"); ax6.axis("off")
    else:
        byt2 = pd.to_numeric(byt, errors="coerce").fillna(0)
        if has_both:
            byt_b = byt2[df_viz[cfg.target_col] == 0].values
            byt_a = byt2[df_viz[cfg.target_col] == 1].values
            bp = ax6.boxplot([byt_b, byt_a], labels=["Benign", "Attack"], patch_artist=True, showfliers=True)
            for patch, c in zip(bp["boxes"], colors):
                patch.set_facecolor(c); patch.set_alpha(0.7)
            ax6.set_title(f"Byte Count Distribution\n(by Target)\nsrc: {byte_src}", fontsize=11, fontweight="bold")
            ax6.set_ylabel("Total Bytes")
        else:
            ax6.hist(byt2.values, bins=40, edgecolor="black", alpha=0.7)
            ax6.set_title(f"Byte Count Distribution\nsrc: {byte_src}", fontsize=11, fontweight="bold")
        ax6.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(str(viz_overview_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"\n   ✓ Saved: {viz_overview_path}\n")

    print("   ├─ Computing correlation matrix...")

    n_hm = int(min(max(1, int(cfg.n_heatmap)), len(df_viz)))
    if n_hm < len(df_viz):
        y_v = (pd.to_numeric(df_viz[cfg.target_col], errors="coerce").fillna(0).astype(int) == 1).astype(int)
        if cfg.stratify_by_target and y_v.nunique(dropna=True) >= 2:
            atk_i = np.where(y_v.to_numpy() == 1)[0]
            ben_i = np.where(y_v.to_numpy() == 0)[0]
            atk_t, ben_t = int(len(atk_i)), int(len(ben_i))
            if atk_t > 0 and ben_t > 0:
                p_atk2 = atk_t / float(len(df_viz))
                atk_take2 = min(max(int(round(p_atk2 * n_hm)), 1), atk_t)
                ben_take2 = min(max(n_hm - atk_take2, 1), ben_t)
                pick2 = np.concatenate([
                    rng.choice(atk_i, size=atk_take2, replace=False),
                    rng.choice(ben_i, size=ben_take2, replace=False),
                ])
                rng.shuffle(pick2)
                df_hm = df_viz.iloc[pick2].copy()
            else:
                df_hm = df_viz.sample(n=n_hm, random_state=int(cfg.seed))
        else:
            df_hm = df_viz.sample(n=n_hm, random_state=int(cfg.seed))
    else:
        df_hm = df_viz

    numeric_cols = df_hm.select_dtypes(include=[np.number]).columns.tolist()
    if cfg.target_col in df_hm.columns and cfg.target_col not in numeric_cols:
        numeric_cols.append(cfg.target_col)

    if len(numeric_cols) > cfg.max_heatmap_features:
        keep = [cfg.target_col] if cfg.target_col in numeric_cols else []
        var_series = df_hm[numeric_cols].var(numeric_only=True).sort_values(ascending=False)
        for c in var_series.index:
            if c == cfg.target_col:
                continue
            keep.append(c)
            if len(keep) >= cfg.max_heatmap_features:
                break
        numeric_cols = keep

    corr_df = df_hm[numeric_cols].corr().replace([np.inf, -np.inf], np.nan).fillna(0)

    fig, ax = plt.subplots(figsize=(14, 10))
    if _HAS_SNS:
        sns.heatmap(corr_df, annot=False, center=0, cmap="coolwarm", square=True, ax=ax, cbar_kws={"label": "Correlation"})
    else:
        im = ax.imshow(corr_df.values)
        fig.colorbar(im, ax=ax, label="Correlation")
    ax.set_title("Feature Correlation Matrix", fontsize=14, fontweight="bold", pad=16)

    plt.tight_layout()
    plt.savefig(str(corr_heatmap_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"   ✓ Saved: {corr_heatmap_path}")
    print("\n✅ PHASE 6 COMPLETE - All visualizations generated")

    return {
        "skipped": False,
        "viz_overview_path": str(viz_overview_path),
        "corr_heatmap_path": str(corr_heatmap_path),
        "rows_total": int(n_total),
        "n_viz_used": int(len(df_viz)),
        "n_heatmap_used": int(len(df_hm)),
        "stratify_by_target": bool(cfg.stratify_by_target),
        "target_dist": {str(k): int(v) for k, v in target_dist.to_dict().items()},
        "event_type_source": ev_col or "none",
        "proto_source": pr_col or "none",
        "top_events": {str(k): int(v) for k, v in top_events.to_dict().items()},
        "proto_counts": {str(k): int(v) for k, v in proto_counts.to_dict().items()},
        "max_heatmap_features": int(cfg.max_heatmap_features),
        "heatmap_cols_used": [str(c) for c in numeric_cols],
        "sampling_ratio_source": str(ratio_source),
        "ref_attack_total": int(cfg.ref_attack_total),
        "ref_benign_total": int(cfg.ref_benign_total),
    }