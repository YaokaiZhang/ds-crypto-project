from ..domain import AnalysisCommand, AssessmentContext, AnalysisRecord
from ..errors import FeatureNotImplemented
from ..ports.providers import ChainDataProvider
from ..ports.runtime import GraphBuilder, Predictor, GraphPresenter, AnalyticsBuilder
from .strategies import TaskStrategy

class AnalysisPipeline:
    """Worker-only orchestration; each score and graph bind to one frozen sample."""
    def __init__(self, provider: ChainDataProvider, builder: GraphBuilder,
                 predictor: Predictor, presenter: GraphPresenter, analytics: AnalyticsBuilder):
        self.provider = provider
        self.builder = builder
        self.predictor = predictor
        self.presenter = presenter
        self.analytics = analytics

    async def resolve_context(self, command: AnalysisCommand, strategy: TaskStrategy) -> AssessmentContext:
        """Freeze cutoff block/hash, source scope and graph/feature/model versions."""
        raise FeatureNotImplemented('pipeline.resolve_context')

    async def execute(self, record: AnalysisRecord) -> AnalysisRecord:
        """Resolve -> collect -> normalize -> build -> present/predict -> persist.

        Preserve per-task partial failures. Fit/scaler training is never a stage.
        """
        raise FeatureNotImplemented('pipeline.execute')
