"""Linear SVC — EVE/Suricata cbr 14-phase pipeline (TLS)."""
from __future__ import annotations

from pipelines.eve_cbr.cbr_adapter import BaseCbrEvePipeline


class EveCbrLSVCPipeline(BaseCbrEvePipeline):
    ALGORITHM = "LSVC"
    ALGORITHM_LABEL = "Linear SVC"
