"""XGBoost — EVE/Suricata cbr 14-phase pipeline (TLS)."""
from __future__ import annotations

from pipelines.eve_cbr.cbr_adapter import BaseCbrEvePipeline


class EveCbrXGBPipeline(BaseCbrEvePipeline):
    ALGORITHM = "XGB"
    ALGORITHM_LABEL = "XGBoost"
