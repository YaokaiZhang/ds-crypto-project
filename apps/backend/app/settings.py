"""Server settings; no secrets are sent to browser configuration."""
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    api_prefix: str = '/api/v1'
    database_url: str | None = None
    ethereum_rpc_url: str | None = None
    etherscan_api_key: str | None = None
    model_registry_path: str | None = None

    @classmethod
    def from_environment(cls) -> 'Settings':
        return cls(database_url=os.getenv('DATABASE_URL'),
                   ethereum_rpc_url=os.getenv('ETHEREUM_RPC_URL'),
                   etherscan_api_key=os.getenv('ETHERSCAN_API_KEY'),
                   model_registry_path=os.getenv('MODEL_REGISTRY_PATH'))
