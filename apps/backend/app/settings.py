"""Server settings; no secrets are sent to browser configuration."""
import ast
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import tempfile

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
    mock_predictor_url: str = 'http://127.0.0.1:18081/predict'
    demo_database_path: str = os.path.join(tempfile.gettempdir(), 'chainrisk-demo.sqlite3')
    demo_delay_scale: float = 1.0
    feed_enabled: bool = False
    feed_database_path: str = os.path.join(tempfile.gettempdir(), 'chainrisk-feed.sqlite3')

    def __post_init__(self):
        if self.analysis_mode not in ('template', 'demo', 'eth_live_mock'):
            raise ValueError('ANALYSIS_MODE must be template, demo or eth_live_mock')
        if not 1 <= self.analysis_concurrency <= 4 or self.analysis_lease_seconds < 15:
            raise ValueError('Invalid analysis concurrency or lease duration')
        if self.mock_predictor_url != 'http://127.0.0.1:18081/predict':
            raise ValueError('The temporary mock target must be the reserved local predictor address')
        if not 0 <= self.demo_delay_scale <= 10:
            raise ValueError('DEMO_DELAY_SCALE must be between 0 and 10')
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
                   analysis_mode=os.getenv('ANALYSIS_MODE', 'template'),
                   analysis_database_path=os.getenv('ANALYSIS_DATABASE_PATH') or str(PROJECT_ROOT / '.runtime/eth-analysis.sqlite3'),
                   analysis_artifact_path=os.getenv('ANALYSIS_ARTIFACT_PATH') or str(PROJECT_ROOT / '.runtime/eth-artifacts'),
                   analysis_concurrency=int(os.getenv('ANALYSIS_CONCURRENCY', '2')),
                   demo_database_path=os.getenv('DEMO_DATABASE_PATH') or os.path.join(tempfile.gettempdir(), 'chainrisk-demo.sqlite3'),
                   demo_delay_scale=float(os.getenv('DEMO_DELAY_SCALE', '1')),
                   feed_enabled=os.getenv('FEED_ENABLED', 'false').lower() == 'true',
                   feed_database_path=os.getenv('FEED_DATABASE_PATH') or os.path.join(tempfile.gettempdir(), 'chainrisk-feed.sqlite3'))
