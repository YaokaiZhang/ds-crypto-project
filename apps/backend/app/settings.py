"""Server settings; no secrets are sent to browser configuration."""
from dataclasses import dataclass
import os
import tempfile

@dataclass(frozen=True)
class Settings:
    api_prefix: str = '/api/v1'
    database_url: str | None = None
    ethereum_rpc_url: str | None = None
    etherscan_api_key: str | None = None
    model_registry_path: str | None = None
    analysis_mode: str = 'template'
    demo_database_path: str = os.path.join(tempfile.gettempdir(), 'chainrisk-demo.sqlite3')
    demo_delay_scale: float = 1.0
    feed_enabled: bool = False
    feed_database_path: str = os.path.join(tempfile.gettempdir(), 'chainrisk-feed.sqlite3')

    def __post_init__(self):
        if self.analysis_mode not in ('template', 'demo'):
            raise ValueError('ANALYSIS_MODE must be template or demo')
        if not 0 <= self.demo_delay_scale <= 10:
            raise ValueError('DEMO_DELAY_SCALE must be between 0 and 10')

    @classmethod
    def from_environment(cls) -> 'Settings':
        return cls(database_url=os.getenv('DATABASE_URL'),
                   ethereum_rpc_url=os.getenv('ETHEREUM_RPC_URL'),
                   etherscan_api_key=os.getenv('ETHERSCAN_API_KEY'),
                   model_registry_path=os.getenv('MODEL_REGISTRY_PATH'),
                   analysis_mode=os.getenv('ANALYSIS_MODE', 'template'),
                   demo_database_path=os.getenv('DEMO_DATABASE_PATH') or os.path.join(tempfile.gettempdir(), 'chainrisk-demo.sqlite3'),
                   demo_delay_scale=float(os.getenv('DEMO_DELAY_SCALE', '1')),
                   feed_enabled=os.getenv('FEED_ENABLED', 'false').lower() == 'true',
                   feed_database_path=os.getenv('FEED_DATABASE_PATH') or os.path.join(tempfile.gettempdir(), 'chainrisk-feed.sqlite3'))
