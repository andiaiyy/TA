"""
Pelaksana uji coba pipeline — terbatas waktu dan terbatas baris.

Uji coba memakai **runner yang sama** dengan eksperimen biasa
(``workers.local_worker.run_pipeline``) dan membangun ``PipelineInput`` dengan
kontrak yang sama. Yang ditambahkan hanyalah BATAS, bukan jalan pintas:

* jumlah baris dibatasi sebelum data sampai ke pipeline;
* seluruh pekerjaan berjalan di PROSES ANAK dengan tenggat waktu, sehingga
  pipeline yang menggantung dihentikan alih-alih menahan antarmuka selamanya.

Proses anak memuat ulang kelasnya dari berkas (dengan verifikasi SHA-256 yang
sama), jadi yang menyeberang antar-proses hanya string — bukan objek pipeline
yang tidak dapat diserialkan.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue as queue_mod

logger = logging.getLogger(__name__)

#: Tahap-tahap yang dilaporkan. Namanya dipakai apa adanya pada pesan
#: kegagalan, supaya peninjau tahu DI MANA pipeline berhenti.
STAGE_LOAD = "memuat pipeline"
STAGE_READ = "membaca dataset"
STAGE_RUN = "menjalankan pipeline"
STAGE_TIMEOUT = "batas waktu"


class TrialTimeout(RuntimeError):
    """Uji coba melampaui tenggat waktunya dan dihentikan."""


def read_trial_dataset(dataset_path: str, max_rows: int):
    """Dataset TERBATAS ``max_rows`` baris.

    Pembersihannya mengikuti ``orchestrator.dataset_parser.parse_dataset``
    persis (nama kolom di-strip, inf menjadi NaN) dan memakai
    ``resolve_dataset_path`` yang sama, sehingga pengaman lokasi berkas tetap
    berlaku. Bedanya hanya satu: CSV dibaca dengan ``nrows`` alih-alih penuh —
    uji coba tidak boleh memakai memori sebesar eksperimen sungguhan.
    """
    import numpy as np
    import pandas as pd

    from orchestrator.dataset_parser import parse_dataset, resolve_dataset_path

    resolved = resolve_dataset_path(dataset_path)
    if resolved.suffix.lower() == ".csv":
        df = pd.read_csv(resolved, nrows=max_rows)
        df.columns = df.columns.str.strip()
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df
    # NDJSON/JSON: pembaca yang ada sudah membatasi diri pada ~100 record.
    df = parse_dataset(dataset_path)
    return df.head(max_rows) if len(df) > max_rows else df


def run_trial_pipeline(instance, df, dataset_type: str, *,
                       dataset_path: str = "", progress=None):
    """Jalankan pipeline lewat runner yang SAMA dengan eksperimen biasa.

    ``PipelineInput`` dibangun dengan bentuk yang sama seperti pada
    ``orchestrator.execution_service.execute_pipeline`` pada jalur run RESMI:
    tanpa ``param_overrides`` dan tanpa ``random_state`` — pipeline memakai
    nilai terkuncinya, persis seperti saat dijalankan sungguhan.
    """
    from contracts.dataset_schemas import get_schema
    from contracts.pipeline_contracts import PipelineInput
    from workers.local_worker import run_pipeline

    schema = get_schema(dataset_type)
    if schema is None:
        raise ValueError(f"Dataset schema not found: {dataset_type}")

    pipeline_input = PipelineInput(
        df=df,
        label_column=schema["label_column"],
        dataset_type=dataset_type,
        dataset_path=dataset_path,
        param_overrides={},
    )
    return run_pipeline(instance, pipeline_input, progress=progress)


def _summarise(result) -> dict:
    out = {}
    for name in ("accuracy", "precision", "recall", "f1_score"):
        value = getattr(result, name, None)
        if isinstance(value, (int, float)):
            out[name] = float(value)
    features = getattr(result, "feature_names", None)
    if features:
        out["n_features"] = len(features)
    mapping = getattr(result, "label_mapping", None)
    if isinstance(mapping, dict):
        out["classes"] = sorted(str(k) for k in mapping)
    return out


def _child(entry_file, entry_class, entry_hash, dataset_type, dataset_path,
           max_rows, out_queue):
    """Badan proses anak: muat → baca → jalankan, lalu kirim hasilnya.

    Kegagalan dikirim beserta TAHAP dan JENIS-nya; proses induk tidak pernah
    menebak di mana pipeline berhenti.
    """
    stage = STAGE_LOAD
    rows_used = None
    try:
        from orchestrator.dynamic_registry import load_pipeline_class

        cls = load_pipeline_class(entry_file, entry_class, entry_hash)
        instance = cls()

        stage = STAGE_READ
        df = read_trial_dataset(dataset_path, max_rows)
        rows_used = int(len(df))

        stage = STAGE_RUN
        result = run_trial_pipeline(instance, df, dataset_type,
                                    dataset_path=dataset_path)
        out_queue.put({"ok": True, "metrics": _summarise(result),
                       "rows_used": rows_used})
    except BaseException as exc:             # noqa: BLE001 — dilaporkan utuh
        out_queue.put({"ok": False, "stage": stage,
                       "kind": type(exc).__name__, "message": str(exc),
                       "rows_used": rows_used})


def run_bounded(*, entry_file: str, entry_class: str, entry_hash: str,
                dataset_type: str, dataset_path: str, max_rows: int,
                max_seconds: int) -> dict:
    """Jalankan uji coba dengan tenggat waktu yang benar-benar ditegakkan.

    Dijalankan di proses anak supaya tenggatnya dapat DIPAKSA: pipeline yang
    terjebak di dalam pustaka pihak ketiga tidak dapat dihentikan dari dalam
    proses yang sama, dan uji coba yang menggantung akan menahan peninjauan.

    Mengembalikan dict hasil — tidak pernah melempar untuk kegagalan pipeline;
    kegagalan adalah HASIL yang sah dari sebuah uji coba.
    """
    ctx = mp.get_context("spawn")
    out_queue = ctx.Queue()
    proc = ctx.Process(
        target=_child,
        args=(str(entry_file), entry_class, entry_hash, dataset_type,
              dataset_path, int(max_rows), out_queue),
        daemon=True)
    proc.start()
    proc.join(timeout=max_seconds)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=10)
        if proc.is_alive():                  # pragma: no cover - defensive
            proc.kill()
            proc.join(timeout=5)
        return {
            "ok": False,
            "stage": STAGE_TIMEOUT,
            "kind": "TrialTimeout",
            "message": (f"Uji coba melampaui batas {max_seconds} detik dan "
                        f"dihentikan. Pipeline masih berjalan saat batas "
                        f"tercapai — periksa tahap yang paling lama."),
            "rows_used": None,
        }

    try:
        return out_queue.get_nowait()
    except queue_mod.Empty:
        # Proses berakhir tanpa mengirim apa pun: hampir selalu berarti ia
        # dimatikan sistem (mis. kehabisan memori). Dikatakan apa adanya.
        return {
            "ok": False,
            "stage": STAGE_RUN,
            "kind": "ProcessDied",
            "message": (f"Proses uji berakhir tanpa hasil (exit code "
                        f"{proc.exitcode}). Kemungkinan dihentikan sistem "
                        f"karena kehabisan memori."),
            "rows_used": None,
        }
