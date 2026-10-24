"""Family dispatch shares durable worker/quota behavior, not model recipes."""
from .eth_pipeline import EthPipeline
from .token_pipeline import TokenPipeline
from .forecast_pipeline import ForecastPipeline


class LivePipeline:
    def __init__(self, settings, store, budget):
        self.pipelines = {'eth_scam': EthPipeline(settings, store, budget),
                          'token_scam': TokenPipeline(settings, store, budget),
                          'forecast': ForecastPipeline(settings, store, budget)}

    async def execute(self, lease):
        await self.pipelines[lease['command']['family']].execute(lease)

    async def close(self):
        for pipeline in self.pipelines.values():
            await pipeline.close()
