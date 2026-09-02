"""Pipeline yang sengaja gagal saat BERJALAN — bahan uji pesan kegagalan.

Gagalnya terjadi di dalam `run()`, bukan saat diimpor: itulah kegagalan yang
tidak dapat ditemukan pemeriksaan statis, dan justru menjadi alasan fitur uji
coba ini ada.
"""
from pipelines.base import BasePipeline


class BrokenPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise KeyError("kolom 'flow_duration' tidak ada pada dataset uji")

    def get_info(self):
        return {"algorithm": "broken"}
