"""
Pipeline input/output contracts.
Importable by any layer — no side effects, no DB, no UI.
"""
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class PipelineInput:
    """Everything a pipeline needs to run."""
    df: pd.DataFrame
    label_column: str
    dataset_type: str
    test_size: float = 0.2
    random_state: int = 42
    dataset_path: str = ""   # raw file path for pipelines that read files directly (e.g. EVE Suricata)
    # Penyesuaian hyperparameter untuk RUN EKSPLORASI. OPSIONAL dan default
    # KOSONG: pemanggilan lama (dan seluruh test yang ada) tetap berjalan persis
    # seperti sebelumnya, dan kosong berarti "pakai nilai terkunci pipeline".
    #
    # Isinya sudah divalidasi orchestrator (orchestrator/run_mode.py): hanya
    # kunci yang benar-benar ada pada get_info()['fixed_params'] pipeline yang
    # bersangkutan, dengan tipe yang sesuai dan nilai di dalam batas aman. Run
    # RESMI selalu mengirim dict kosong — override dibuang di orchestrator,
    # bukan di sini.
    param_overrides: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Everything a pipeline returns after execution."""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    confusion_matrix: list[list[int]]
    model: object
    feature_names: list[str]
    label_mapping: dict[str, int]
    extra_info: dict = field(default_factory=dict)

    def get_extra(self, key: str, default=None):
        """
        Safely get a value from extra_info with a default.
        Treats empty lists as missing (returns default instead).
        """
        value = self.extra_info.get(key, default)
        if isinstance(value, list) and len(value) == 0:
            return default
        return value
