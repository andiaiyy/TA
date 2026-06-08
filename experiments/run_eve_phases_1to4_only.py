"""EVE 14-phase: PHASES 1-4 ONLY — diagnostic for label source breakdown.

Default parameters (window=5min, probe_score_threshold=3.0). Outputs to a
SEPARATE work dir (storage/eve_v2_fulldata_check/) so it does not touch the
TAHAP 1 results under storage/eve_v2_work/.

Stops after phase 4. Does NOT execute phase 5–14. Read-only against the
platform: no DB/artifacts/registry contact.
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_HERE = Path(__file__).resolve().parent
_PROJ = _HERE.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

from pipelines.eve_suricata.phases_v2.phase1 import (
    Phase1DiskConfig, phase1_initial_parsing_label_evidence,
)
from pipelines.eve_suricata.phases_v2.phase2_app_filter import (
    Phase2AppFilterConfig, phase2_filter_applications,
)
from pipelines.eve_suricata.phases_v2.phase3_probing_analysis import (
    Phase3ProbingConfig, phase3_probing_analysis,
)
from pipelines.eve_suricata.phases_v2.phase4_label_refinement import (
    Phase4LabelRefinementConfig, phase4_refine_labels,
)

INPUT_FILE = _PROJ / "storage" / "datasets" / "eve_sample_1000000.jsonl"
WORK_DIR = _PROJ / "storage" / "eve_v2_fulldata_check"
RESULTS = WORK_DIR / "results"

PHASE_DIRS = {
    1: RESULTS / "phase1_dataset",
    2: RESULTS / "phase2_app_dataset",
    3: RESULTS / "phase3_probing",
    4: RESULTS / "phase4_labeled_dataset",
}
PARQUET_ENGINE = "pyarrow"


def _hdr(n: int, name: str) -> None:
    print("\n" + "=" * 78)
    print(f"  PHASE {n}: {name}")
    print("=" * 78)


def _run(label: str, fn, *args, **kwargs) -> Tuple[bool, float, Any, str]:
    t0 = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        print(f"\n[OK]  {label}  elapsed={elapsed:.1f}s")
        return True, elapsed, out, ""
    except Exception:
        elapsed = time.perf_counter() - t0
        tb = traceback.format_exc()
        print(f"\n[FAIL] {label}  elapsed={elapsed:.1f}s\n{tb}")
        return False, elapsed, None, tb


def main() -> int:
    print(f"INPUT_FILE = {INPUT_FILE}")
    print(f"WORK_DIR   = {WORK_DIR}")
    print(f"PARQUET_ENGINE = {PARQUET_ENGINE}")
    if not INPUT_FILE.exists():
        print(f"\nERROR: input file not found at {INPUT_FILE}")
        return 2
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    timings: List[Dict[str, Any]] = []

    _hdr(1, "Initial parsing + label evidence")
    ok, t, _, tb = _run(
        "phase1",
        phase1_initial_parsing_label_evidence,
        INPUT_FILE,
        max_lines=None,
        disk=Phase1DiskConfig(
            output_dir=PHASE_DIRS[1],
            write_format="parquet",
            batch_size=200_000,
            return_df_sample=10_000,
            save_sample_file=True,
            parquet_engine=PARQUET_ENGINE,
            parquet_compression="snappy",
        ),
    )
    timings.append({"phase": 1, "elapsed_sec": t, "ok": ok})
    if not ok:
        return _save_summary(timings, tb, ok=False)

    _hdr(2, "App filter")
    ok, t, _, tb = _run(
        "phase2",
        phase2_filter_applications,
        cfg=Phase2AppFilterConfig(input_dir=PHASE_DIRS[1], output_dir=PHASE_DIRS[2]),
    )
    timings.append({"phase": 2, "elapsed_sec": t, "ok": ok})
    if not ok:
        return _save_summary(timings, tb, ok=False)

    _hdr(3, "Probing analysis")
    ok, t, _, tb = _run(
        "phase3",
        phase3_probing_analysis,
        cfg=Phase3ProbingConfig(input_dir=PHASE_DIRS[2], output_dir=PHASE_DIRS[3]),
    )
    timings.append({"phase": 3, "elapsed_sec": t, "ok": ok})
    if not ok:
        return _save_summary(timings, tb, ok=False)

    _hdr(4, "Label refinement")
    ok, t, _, tb = _run(
        "phase4",
        phase4_refine_labels,
        cfg=Phase4LabelRefinementConfig(
            phase2_input_dir=PHASE_DIRS[2],
            phase3_input_dir=PHASE_DIRS[3],
            output_dir=PHASE_DIRS[4],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 4, "elapsed_sec": t, "ok": ok})

    return _save_summary(timings, tb if not ok else "", ok=ok)


def _save_summary(timings: List[Dict[str, Any]], tb: str, ok: bool) -> int:
    total = sum(t["elapsed_sec"] for t in timings)
    print("\n" + "=" * 78)
    print("  PHASE 1-4 STATUS")
    print("=" * 78)
    for t in timings:
        mark = "OK  " if t["ok"] else "FAIL"
        print(f"  Phase {t['phase']}  [{mark}]  {t['elapsed_sec']:>7.2f}s")
    print(f"  TOTAL                {total:>7.2f}s")

    summary = {
        "input_file": str(INPUT_FILE),
        "work_dir": str(WORK_DIR),
        "timings": timings,
        "total_sec": total,
        "stopped_after_phase": 4,
        "traceback": tb if tb else None,
    }
    p = WORK_DIR / "phases_1to4_summary.json"
    p.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n  Wrote: {p}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
