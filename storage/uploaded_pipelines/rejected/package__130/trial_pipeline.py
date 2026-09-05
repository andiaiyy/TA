
from pipelines.base import BasePipeline


class TrialPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {}
