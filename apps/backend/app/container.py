"""Composition root. Adapters can be replaced without rewriting routes."""
from dataclasses import dataclass
from .settings import Settings
from .adapters.providers import EtherscanProvider, EthereumRpcProvider
from .adapters.repositories import PostgresAnalysisRepository, PostgresFeedRepository
from .adapters.chainrisk import ModelRegistry, ChainriskGraphBuilder, ChainriskPredictor, GraphViewPresenter, RootAnalyticsBuilder
from .application.analysis import AnalysisService
from .application.pipeline import AnalysisPipeline
from .application.feed import FeedService, FeedCollector

@dataclass
class Container:
    analysis: AnalysisService
    pipeline: AnalysisPipeline
    feed: FeedService
    collector: FeedCollector
    registry: ModelRegistry

    def close(self) -> None:
        self.registry.close()


def build_container(settings: Settings) -> Container:
    jobs = PostgresAnalysisRepository(settings)
    feed = PostgresFeedRepository(settings)
    registry = ModelRegistry(settings)
    return Container(
        analysis=AnalysisService(jobs),
        pipeline=AnalysisPipeline(EtherscanProvider(settings), ChainriskGraphBuilder(),
                                  ChainriskPredictor(registry), GraphViewPresenter(), RootAnalyticsBuilder()),
        feed=FeedService(feed), collector=FeedCollector(EthereumRpcProvider(settings), feed),
        registry=registry,
    )
