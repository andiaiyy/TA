"""
Execution service — pipeline dispatch.
Raises on errors (experiment_service catches).
"""
import logging
from typing import Callable, Optional

import pandas as pd
from contracts.pipeline_contracts import PipelineInput, PipelineResult
from orchestrator.research_registry import schema_for
from orchestrator.dynamic_registry import (
    DynamicRegistryError, get_pipeline_instance_merged,
)
from workers.local_worker import run_pipeline

logger = logging.getLogger(__name__)


def execute_pipeline(
    pipeline_id: str,
    df: pd.DataFrame,
    dataset_type: str,
    dataset_path: str = "",
    progress: Optional[Callable[[str], None]] = None,
    param_overrides: dict | None = None,
) -> PipelineResult:
    """
    Resolve pipeline, build input, execute, return result.
    Raises ValueError if pipeline or schema not found.

    Pipeline bawaan diambil dari registry STATIS; pipeline terunggah yang sudah
    disetujui dimuat dari berkasnya dengan verifikasi SHA-256 lebih dulu
    (orchestrator/dynamic_registry). Karena worker Celery juga masuk lewat
    fungsi ini, verifikasi hash itu berlaku di sisi worker juga; kegagalan
    memuat menjadi ValueError sehingga eksperimen ditandai FAILED dengan pesan
    jelas alih-alih menggantung.

    ``progress`` is an optional callback forwarded to the pipeline for
    coarse stage reporting. Pipelines must run identically when
    ``progress`` is None (default), which is the case for sync execution
    and all tests.

    ``param_overrides`` adalah penyesuaian hyperparameter yang SUDAH lolos
    validasi ``orchestrator/run_mode.resolve_params``. Default None/kosong
    berarti pipeline memakai nilai terkuncinya — itulah jalur run RESMI, dan
    pada jalur itu ``PipelineInput`` yang dibangun di sini persis sama dengan
    sebelum fitur mode eksekusi ada (``param_overrides`` kosong,
    ``random_state`` tidak diisi sehingga tetap memakai default kontrak).
    """
    try:
        instance = get_pipeline_instance_merged(pipeline_id)
    except DynamicRegistryError as e:
        # Hash tidak cocok / berkas hilang / kelas tidak sah. Jadikan kegagalan
        # eksplisit supaya worker menandai eksperimen FAILED dengan alasannya.
        raise ValueError(f"Pipeline tidak dapat dimuat: {e}") from e
    if instance is None:
        raise ValueError(f"Pipeline not found: {pipeline_id}")

    # Bawaan + research pipeline terunggah. Jenis tak dikenal tetap
    # menghasilkan None, jadi penjagaan di bawah tidak berubah.
    schema = schema_for(dataset_type)
    if schema is None:
        raise ValueError(f"Dataset schema not found: {dataset_type}")

    overrides = dict(param_overrides or {})
    extra: dict = {}
    if "random_state" in overrides:
        # Seed dibaca pipeline lewat `pipeline_input.random_state`, bukan lewat
        # dict override — jadi nilainya diteruskan ke field kontraknya sendiri
        # supaya run tetap dapat diulang persis. Hanya diisi bila memang
        # diubah; run resmi tidak pernah menyentuh nilai bawaan kontrak.
        extra["random_state"] = overrides["random_state"]

    pipeline_input = PipelineInput(
        df=df,
        label_column=schema["label_column"],
        dataset_type=dataset_type,
        dataset_path=dataset_path,
        param_overrides=overrides,
        **extra,
    )
    return run_pipeline(instance, pipeline_input, progress=progress)


def get_pipeline_info(pipeline_id: str) -> dict | None:
    """Get pipeline metadata for UI display. Returns None if not found.

    Untuk pipeline terunggah, memanggil ini MEMUAT berkasnya (dengan verifikasi
    hash). Kegagalan dikembalikan sebagai None + log, bukan exception, supaya
    satu pipeline bermasalah tidak merusak halaman.
    """
    try:
        instance = get_pipeline_instance_merged(pipeline_id)
    except DynamicRegistryError:
        logger.warning("Pipeline terunggah %s tidak dapat dimuat", pipeline_id,
                       exc_info=True)
        return None
    if instance is None:
        return None
    return instance.get_info()
