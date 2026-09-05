
from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineResult


class ContribPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        df = pipeline_input.df
        return PipelineResult(
            accuracy=1.0, precision=1.0, recall=1.0, f1_score=1.0,
            confusion_matrix=[[len(df), 0], [0, 0]],
            model=None, feature_names=list(df.columns)[:2],
            label_mapping={"0": "Benign", "1": "Attack"})

    def get_info(self):
        return {"algorithm": "ContribAlgo", "paper": "kontribusi"}

# disunting
