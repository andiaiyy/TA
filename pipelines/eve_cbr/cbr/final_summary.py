# src/cbr/final_summary.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _fmt_int(x: Any) -> str:
    return f"{_safe_int(x):,}"


def _fmt_float(x: Any, digits: int = 2) -> str:
    return f"{_safe_float(x):,.{digits}f}"


def _mb(p: Path) -> float:
    return p.stat().st_size / (1024 * 1024)


def _path_status(p: str | Path | None) -> str:
    if not p:
        return "N/A"
    pp = Path(p)
    if pp.exists():
        try:
            return f"exists, {_mb(pp):.2f} MB"
        except Exception:
            return "exists"
    return "missing"


def _dist_target(df: Any, target_col: str = "Target") -> Dict[int, int]:
    if pd is None or df is None or not hasattr(df, "columns"):
        return {}
    if target_col not in df.columns:
        return {}
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    vc = y.value_counts().to_dict()
    return {0: int(vc.get(0, 0)), 1: int(vc.get(1, 0))}


def _print_dist(label: str, df: Any, target_col: str = "Target") -> None:
    d = _dist_target(df, target_col=target_col)
    if not d:
        print(f"   ⚠️ {label}: missing df/Target.")
        return
    total = int(len(df))
    b = d.get(0, 0)
    a = d.get(1, 0)
    bp = (b * 100 / total) if total else 0.0
    ap = (a * 100 / total) if total else 0.0
    print(f"   {label}: rows={total:,} | benign(0)={b:,} ({bp:.2f}%) | attack(1)={a:,} ({ap:.2f}%)")


def _get_phase(summaries: Dict[str, Dict[str, Any]], n: int) -> Dict[str, Any]:
    obj = summaries.get(f"phase{int(n)}") or {}
    return obj if isinstance(obj, dict) else {}


def _phase_status(s: Dict[str, Any]) -> str:
    if not s:
        return "missing"
    if s.get("skipped"):
        return "skipped"
    return str(s.get("status") or "available")


def _target_counts_text(d: Any) -> str:
    if not isinstance(d, dict) or not d:
        return "N/A"
    b = d.get("0", d.get(0, 0))
    a = d.get("1", d.get(1, 0))
    return f"benign={_fmt_int(b)}, attack={_fmt_int(a)}"


def _sum_target_counts(summary: Dict[str, Any], key: str = "target_counts") -> Dict[str, int]:
    out = {"0": 0, "1": 0}
    apps = summary.get("apps") or {}
    if not isinstance(apps, dict):
        return out
    for s in apps.values():
        if not isinstance(s, dict):
            continue
        counts = s.get(key) or {}
        if isinstance(counts, dict):
            out["0"] += _safe_int(counts.get("0", counts.get(0, 0)))
            out["1"] += _safe_int(counts.get("1", counts.get(1, 0)))
    return out




def _best_models_by_app_from_summaries(summaries: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Extract best Phase 13 model per app in a stable shape for console/PDF/report."""
    p13 = _get_phase(summaries, 13)
    apps = p13.get("apps") or p13.get("by_app") or {}
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(apps, dict):
        return out
    for app, s in apps.items():
        if not isinstance(s, dict):
            continue
        best = s.get("best_by_cv_f1_attack") or s.get("best") or {}
        if not isinstance(best, dict) or not best:
            continue
        out[str(app).lower()] = {
            "method": best.get("Method") or best.get("method"),
            "model": best.get("Model") or best.get("model"),
            "accuracy": best.get("accuracy"),
            "f1_attack": best.get("f1_attack"),
            "auc": best.get("auc"),
            "holdout_f1_attack": best.get("holdout_f1_attack"),
            "holdout_auc": best.get("holdout_auc"),
            "train_rows": best.get("train_rows") or s.get("train_rows_loaded"),
            "test_rows": best.get("test_rows") or s.get("test_rows_loaded"),
            "train_features": best.get("train_features"),
        }
    return out


def _print_best_model_table(summaries: Dict[str, Dict[str, Any]]) -> None:
    best_by_app = _best_models_by_app_from_summaries(summaries)
    print("\n🏆 Best Model per Application:")
    if not best_by_app:
        print("   N/A - Phase 13 best model summary is not available yet.")
        return
    print("   App   | Method | Model | F1 Attack | AUC      | Holdout F1 | Holdout AUC | Train/Test")
    print("   ------+--------+-------+-----------+----------+------------+-------------+----------------")
    for app, b in best_by_app.items():
        train = _fmt_int(b.get("train_rows"))
        test = _fmt_int(b.get("test_rows"))
        print(
            f"   {app.upper():5s} | "
            f"{str(b.get('method') or 'N/A'):6s} | "
            f"{str(b.get('model') or 'N/A'):5s} | "
            f"{_fmt_float(b.get('f1_attack'), 4):>9s} | "
            f"{_fmt_float(b.get('auc'), 4):>8s} | "
            f"{_fmt_float(b.get('holdout_f1_attack'), 4):>10s} | "
            f"{_fmt_float(b.get('holdout_auc'), 4):>11s} | "
            f"{train}/{test}"
        )


def _print_phase_status_table(summaries: Dict[str, Dict[str, Any]]) -> None:
    titles = {
        1: "Initial parsing + label evidence",
        2: "Application filtering",
        3: "Probing analysis",
        4: "Label refinement",
        5: "Feature engineering",
        6: "Computed features",
        7: "Cleaning",
        8: "Export processed dataset",
        9: "Visualization",
        10: "Correlation + leakage",
        11: "Modeling split",
        12: "Feature selection",
        13: "Training",
        14: "Advanced evaluation",
    }
    print("\n📌 Phase Status:")
    for i in range(1, 15):
        s = _get_phase(summaries, i)
        status = _phase_status(s)
        icon = "✅" if status == "completed" else "⏭️" if status == "skipped" else "❌" if status == "failed" else "ℹ️"
        sec = s.get("seconds")
        time_part = f" | {_fmt_float(sec, 2)}s" if sec is not None else ""
        print(f"   {icon} Phase {i:02d}: {status:24s} | {titles[i]}{time_part}")


def _print_dirs(dirs: Dict[str, str | Path]) -> None:
    order = [
        "phase1", "phase2", "phase3", "phase4", "phase5", "phase6", "phase7", "phase8",
        "figures", "phase10", "modeling", "phase12", "phase13", "phase14",
        "metrics", "reports",
    ]
    print("\n📂 Artifact folders:")
    shown = set()
    for k in order:
        if k in dirs:
            shown.add(k)
            print(f"   - {k:10s}: {Path(dirs[k])}")
    for k, v in dirs.items():
        if k not in shown:
            print(f"   - {k:10s}: {Path(v)}")


def _print_phase1(summaries: Dict[str, Dict[str, Any]]) -> None:
    p1 = _get_phase(summaries, 1)
    print("\n📊 Raw Parsing / Label Evidence (Phase 1):")
    if not p1:
        print("   ⚠️ Phase 1 summary not found.")
        return
    print(f"   Input file         : {p1.get('input_file', 'N/A')}")
    print(f"   Total lines seen   : {_fmt_int(p1.get('total_lines_seen'))}")
    print(f"   Decoded events     : {_fmt_int(p1.get('decoded_events'))}")
    print(f"   Rows written       : {_fmt_int(p1.get('rows_written'))}")
    print(f"   Shards written     : {_fmt_int(p1.get('shards_written'))}")
    print(f"   Malformed JSON     : {_fmt_int(p1.get('malformed'))}")
    print(f"   Missing src_ip     : {_fmt_int(p1.get('missing_src_ip'))}")
    print(f"   Malicious evidence : {_fmt_int(p1.get('malicious_evidence'))}")
    print(f"   No-alert unknown   : {_fmt_int(p1.get('no_alert_unknown'))}")


def _print_app_table(summaries: Dict[str, Dict[str, Any]]) -> None:
    p2 = _get_phase(summaries, 2)
    p4 = _get_phase(summaries, 4)
    p7 = _get_phase(summaries, 7)
    p11 = _get_phase(summaries, 11)
    p13 = _get_phase(summaries, 13)
    p14 = _get_phase(summaries, 14)

    apps = []
    for s in (p2, p4, p7, p11, p13, p14):
        selected = s.get("selected_apps")
        if isinstance(selected, (list, tuple)):
            for a in selected:
                a = str(a).lower()
                if a not in apps:
                    apps.append(a)
        app_block = s.get("apps") or {}
        if isinstance(app_block, dict):
            for a in app_block.keys():
                a = str(a).lower()
                if a not in apps:
                    apps.append(a)
    if not apps:
        apps = ["dns", "http", "tls", "ssh"]

    print("\n📱 Per-Application Summary:")
    print("   App   | Phase2 rows | Final Target        | Clean rows | Train/Test        | Best Phase13")
    print("   ------+-------------+---------------------+------------+-------------------+-------------------------------")
    for app in apps:
        p2_rows = _safe_int(((p2.get("output_rows_by_app") or {}).get(app, 0)))
        p4_app = ((p4.get("apps") or {}).get(app, {}) if isinstance(p4.get("apps"), dict) else {})
        p7_app = ((p7.get("apps") or {}).get(app, {}) if isinstance(p7.get("apps"), dict) else {})
        p11_app = ((p11.get("apps") or {}).get(app, {}) if isinstance(p11.get("apps"), dict) else {})
        p13_app = ((p13.get("apps") or {}).get(app, {}) if isinstance(p13.get("apps"), dict) else {})

        target = _target_counts_text(p4_app.get("target_counts"))
        clean_rows = _fmt_int(p7_app.get("rows_out"))
        train = _fmt_int(p11_app.get("train_rows_written", p11_app.get("train_rows")))
        test = _fmt_int(p11_app.get("test_rows_written", p11_app.get("test_rows")))
        best = p13_app.get("best_by_cv_f1_attack") or {}
        if isinstance(best, dict) and best:
            best_txt = f"{best.get('Method', best.get('method','N/A'))}/{best.get('Model', best.get('model','N/A'))} F1={_fmt_float(best.get('f1_attack'),4)} AUC={_fmt_float(best.get('auc'),4)}"
        else:
            best_txt = "N/A"
        print(f"   {app.upper():5s} | {_fmt_int(p2_rows):>11s} | {target:19s} | {clean_rows:>10s} | {train}/{test:>9s} | {best_txt}")


def _print_key_artifacts(summaries: Dict[str, Dict[str, Any]]) -> None:
    print("\n📌 Key Artifacts:")
    checks = []
    p10 = _get_phase(summaries, 10)
    p11 = _get_phase(summaries, 11)
    p12 = _get_phase(summaries, 12)
    p13 = _get_phase(summaries, 13)
    p14 = _get_phase(summaries, 14)

    for phase_name, summary in [
        ("Phase 10", p10), ("Phase 11", p11), ("Phase 12", p12), ("Phase 13", p13), ("Phase 14", p14),
    ]:
        apps = summary.get("apps") or {}
        if not isinstance(apps, dict):
            continue
        for app, s in apps.items():
            if not isinstance(s, dict):
                continue
            paths = s.get("paths") or {}
            if isinstance(paths, dict):
                for key in ("results_csv", "summary_json", "feature_sets_json", "roc_curves_png", "confusion_matrix_png"):
                    if paths.get(key):
                        checks.append((f"{phase_name} {app} {key}", paths.get(key)))
            for key in ("drop_json", "feature_sets_json", "phase13_results_csv"):
                if s.get(key):
                    checks.append((f"{phase_name} {app} {key}", s.get(key)))

    if not checks:
        print("   No key output paths recorded yet.")
        return

    for name, p in checks[:40]:
        print(f"   - {name:35s}: {p} ({_path_status(p)})")
    if len(checks) > 40:
        print(f"   ... {len(checks) - 40} more paths omitted.")


def print_final_summary(
    *,
    pipeline_start: datetime,
    cfg: Any,
    dirs: Dict[str, str | Path],
    summaries: Dict[str, Dict[str, Any]],
    df_clean: Optional[Any] = None,
    df_sample: Optional[Any] = None,
    df_train: Optional[Any] = None,
    df_test: Optional[Any] = None,
    key_outputs: Optional[Dict[str, str | Path]] = None,
) -> None:
    """
    App-aware final console summary for the 14-phase Suricata EVE pipeline.

    This function is intentionally best-effort and does not assume that all
    phases were executed in the current run. It reads from the phase summaries
    already collected by pipeline.py.
    """
    print("\n" + "=" * 88)
    print("🎉 APP-AWARE SURICATA EVE PIPELINE FINISHED")
    print("=" * 88)

    total_min = (datetime.now() - pipeline_start).total_seconds() / 60.0
    print(f"\n⏱️  Total Processing Time: {total_min:.2f} minutes")

    artifacts_dir = getattr(cfg, "artifacts_dir", None)
    run_id = getattr(cfg, "run_id", None)
    filename_tag = getattr(cfg, "filename_tag", None)
    selected_apps = getattr(cfg, "selected_apps", None)

    if run_id is not None:
        print(f"🔖 Run ID: {run_id}")
    if filename_tag is not None:
        print(f"🏷️  Filename tag: {filename_tag}")
    if selected_apps is not None:
        print("📱 Selected apps: " + ", ".join(str(a).upper() for a in selected_apps))
    if artifacts_dir:
        print(f"📦 Artifacts Root: {Path(artifacts_dir)}")

    _print_dirs(dirs)

    if key_outputs:
        print("\n📌 Explicit Key Outputs:")
        for name, p in key_outputs.items():
            print(f"   - {name:24s}: {Path(p)} ({_path_status(p)})")

    _print_phase_status_table(summaries)
    _print_phase1(summaries)

    p4_counts = _sum_target_counts(_get_phase(summaries, 4), "target_counts")
    print("\n🎯 Final Target Summary (Phase 4):")
    print(f"   Benign(0)   : {_fmt_int(p4_counts['0'])}")
    print(f"   Malicious(1): {_fmt_int(p4_counts['1'])}")

    _print_app_table(summaries)
    _print_best_model_table(summaries)

    if pd is not None and hasattr(df_clean, "columns"):
        mem_mb = df_clean.memory_usage(deep=True).sum() / (1024 * 1024)
        print("\n🧪 In-Memory df_clean sample:")
        print(f"   Rows={len(df_clean):,} | Cols={len(df_clean.columns):,} | Memory={mem_mb:.2f} MB")

    if any(hasattr(x, "columns") for x in (df_sample, df_train, df_test)):
        print("\n🧩 Optional in-memory target distributions:")
        _print_dist("SAMPLE", df_sample, target_col="Target")
        _print_dist("TRAIN ", df_train, target_col="Target")
        _print_dist("TEST  ", df_test, target_col="Target")

    _print_key_artifacts(summaries)

    print("\n✅ Summary finished.")
    print("=" * 88 + "\n")
