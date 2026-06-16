"""Random Forest — EVE/Suricata cbr 14-phase pipeline (TLS)."""
from __future__ import annotations

from pipelines.eve_cbr.cbr_adapter import BaseCbrEvePipeline


class EveCbrRFCPipeline(BaseCbrEvePipeline):
    ALGORITHM = "RFC"
    ALGORITHM_LABEL = "Random Forest"
