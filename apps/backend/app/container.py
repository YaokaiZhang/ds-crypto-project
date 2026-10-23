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
    demo: object | None = None
    feed_store: object | None = None

    def close(self) -> None:
        self.registry.close()
        if self.feed_store:
            self.feed_store.close()


def build_container(settings: Settings) -> Container:
    jobs = PostgresAnalysisRepository(settings)
    feed = PostgresFeedRepository(settings)
    registry = ModelRegistry(settings)
    services = Container(
        analysis=AnalysisService(jobs),
        pipeline=AnalysisPipeline(EtherscanProvider(settings), ChainriskGraphBuilder(),
                                  ChainriskPredictor(registry), GraphViewPresenter(), RootAnalyticsBuilder()),
        feed=FeedService(feed), collector=FeedCollector(EthereumRpcProvider(settings), feed),
        registry=registry,
    )
    if settings.analysis_mode == 'demo':
        from .demo.service import DemoAnalysisService
        services.demo = DemoAnalysisService(settings)
        services.analysis = services.demo
    if settings.feed_enabled:
        from .adapters.feed_store import FeedStore
        from .application.live_feed import LiveFeedService
        services.feed_store = FeedStore(settings.feed_database_path)
        services.feed = LiveFeedService(services.feed_store)
    return services
