"""Future provider adapters; constructors do not perform network I/O."""
from typing import Any
from ..domain import AnalysisCommand, EntityResolution, AssessmentContext, CollectedHistory
from ..errors import FeatureNotImplemented
from ..settings import Settings

class EtherscanProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def resolve_entity(self, command: AnalysisCommand) -> EntityResolution:
        """Resolve roles/type at cutoff; verify token/pool mapping separately."""
        raise FeatureNotImplemented('provider.resolve_entity')

    async def collect_history(self, context: AssessmentContext) -> CollectedHistory:
        """Adapt chainrisk collection/normalization with paging and cutoff audits."""
        raise FeatureNotImplemented('provider.collect_history')

class EthereumRpcProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def latest_block_number(self) -> int:
        raise FeatureNotImplemented('rpc.latest_block_number')

    async def block(self, number: int) -> dict[str, Any]:
        raise FeatureNotImplemented('rpc.block')

    async def receipt(self, transaction_hash: str) -> dict[str, Any] | None:
        raise FeatureNotImplemented('rpc.receipt')

class HoneypotEvidenceProvider:
    async def fetch(self, token: str, pool: str | None = None) -> dict[str, Any]:
        """Retain detection time/scope; external evidence is not a model score."""
        raise FeatureNotImplemented('evidence.honeypot')
