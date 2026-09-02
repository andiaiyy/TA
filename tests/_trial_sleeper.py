"""Pipeline yang sengaja menggantung — bahan uji batas waktu.

Dipakai test untuk membuktikan tenggat uji coba benar-benar DIPAKSA: tanpa
pemaksaan, pipeline seperti ini akan menahan peninjauan selamanya.
"""
import time

from pipelines.base import BasePipeline


class SleeperPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        time.sleep(600)                      # jauh melewati tenggat uji

    def get_info(self):
        return {"algorithm": "sleeper"}
