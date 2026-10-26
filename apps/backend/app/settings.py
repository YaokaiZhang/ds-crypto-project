"""Server settings; no secrets are sent to browser configuration."""
import ast
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parents[1]


def server_credential(name: str, *, path: Path | None = None) -> str | None:
    """Read only literal assignments; never execute a machine-local secrets file."""
    if name in os.environ:
        return os.environ[name].strip() or None
    path = path or BACKEND_ROOT / 'local_secrets.py'
    if not path.is_file():
        return None
    try:
        for node in ast.parse(path.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == name for target in node.targets):
                value = ast.literal_eval(node.value)
                if not isinstance(value, str):
                    raise ValueError
                return value.strip() or None
    except (SyntaxError, ValueError, TypeError):
        raise ValueError(f'Backend local_secrets.py requires a literal {name} string') from None
    return None


@dataclass(frozen=True)
class Settings:
    api_prefix: str = '/api/v1'
    database_url: str | None = field(default=None, repr=False)
    ethereum_rpc_url: str | None = field(default=None, repr=False)
    etherscan_api_key: str | None = field(default=None, repr=False)
    model_registry_path: str | None = None
    token_model_registry_path: str | None = None
    etherscan_rate_limit: float = 3.0
    etherscan_daily_limit: int = 99000
    # One account ledger for both API/workers and concurrent local collection.
    etherscan_quota_path: str = str(PROJECT_ROOT / '.runtime/etherscan/quota.sqlite3')
    analysis_mode: str = 'template'
    analysis_database_path: str = str(PROJECT_ROOT / '.runtime/eth-analysis.sqlite3')
    analysis_artifact_path: str = str(PROJECT_ROOT / '.runtime/eth-artifacts')
    analysis_concurrency: int = 2
    analysis_lease_seconds: int = 60
    inference_url: str | None = None
    inference_api_key: str | None = field(default=None, repr=False)
    inference_timeout: float = 180.0
    feed_enabled: bool = False
    feed_database_path: str = os.path.join(tempfile.gettempdir(), 'chainrisk-feed.sqlite3')

    def __post_init__(self):
        if self.analysis_mode not in ('template', 'eth_live'):
            raise ValueError('ANALYSIS_MODE must be template or eth_live')
        if self.inference_url:
            url = urlsplit(self.inference_url)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('INFERENCE_URL must be an HTTPS service base URL without credentials or query parameters')
        if not math.isfinite(self.inference_timeout) or not 1 <= self.inference_timeout <= 300:
            raise ValueError('INFERENCE_TIMEOUT must be between 1 and 300 seconds')
        if not 1 <= self.analysis_concurrency <= 4 or self.analysis_lease_seconds < 15:
            raise ValueError('Invalid analysis concurrency or lease duration')
        if isinstance(self.etherscan_rate_limit, bool) or not math.isfinite(self.etherscan_rate_limit) or not 0 < self.etherscan_rate_limit <= 3:
            raise ValueError('ETHERSCAN_RATE_LIMIT must be greater than 0 and at most 3')
        if isinstance(self.etherscan_daily_limit, bool) or not isinstance(self.etherscan_daily_limit, int) or not 1 <= self.etherscan_daily_limit <= 99000:
            raise ValueError('ETHERSCAN_DAILY_LIMIT must be between 1 and 99000')

    @classmethod
    def from_environment(cls) -> 'Settings':
        return cls(database_url=os.getenv('DATABASE_URL'),
                   ethereum_rpc_url=server_credential('ETHEREUM_RPC_URL'),
                   etherscan_api_key=server_credential('ETHERSCAN_API_KEY'),
                   model_registry_path=os.getenv('MODEL_REGISTRY_PATH'),
                   token_model_registry_path=os.getenv('TOKEN_MODEL_REGISTRY_PATH'),
                   etherscan_rate_limit=float(os.getenv('ETHERSCAN_RATE_LIMIT', '3')),
                   etherscan_daily_limit=int(os.getenv('ETHERSCAN_DAILY_LIMIT', '99000')),
                   etherscan_quota_path=os.getenv('ETHERSCAN_QUOTA_FILE') or str(PROJECT_ROOT / '.runtime/etherscan/quota.sqlite3'),
                   analysis_mode=server_credential('ANALYSIS_MODE') or 'template',
                   inference_url=server_credential('INFERENCE_URL'),
                   inference_api_key=server_credential('INFERENCE_API_KEY'),
                   inference_timeout=float(os.getenv('INFERENCE_TIMEOUT', '180')),
                   analysis_database_path=os.getenv('ANALYSIS_DATABASE_PATH') or str(PROJECT_ROOT / '.runtime/eth-analysis.sqlite3'),
                   analysis_artifact_path=os.getenv('ANALYSIS_ARTIFACT_PATH') or str(PROJECT_ROOT / '.runtime/eth-artifacts'),
                   analysis_concurrency=int(os.getenv('ANALYSIS_CONCURRENCY', '2')),
                   feed_enabled=os.getenv('FEED_ENABLED', 'false').lower() == 'true',
                   feed_database_path=os.getenv('FEED_DATABASE_PATH') or os.path.join(tempfile.gettempdir(), 'chainrisk-feed.sqlite3'))
