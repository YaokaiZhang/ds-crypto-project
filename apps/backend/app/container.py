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
    feed_store: object | None = None
    real: object | None = None

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
    if settings.analysis_mode == 'eth_live':
        from .adapters.analysis_store import AnalysisStore
        from .adapters.etherscan_budget import EtherscanBudget
        from .application.live_analysis import LiveAnalysisService
        store = AnalysisStore(settings.analysis_database_path)
        budget = EtherscanBudget(settings.etherscan_quota_path, rate=settings.etherscan_rate_limit,
                                limit=settings.etherscan_daily_limit)
        services.real = LiveAnalysisService(store, budget, settings)
        services.analysis = services.real
    if settings.feed_enabled:
        from .adapters.feed_store import FeedStore
        from .application.live_feed import LiveFeedService
        services.feed_store = FeedStore(settings.feed_database_path)
        services.feed = LiveFeedService(services.feed_store)
    return services
