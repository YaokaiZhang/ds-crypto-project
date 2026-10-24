from datetime import datetime, timezone
import math
from types import MappingProxyType


# Public text is authored here; upstream exception bodies/URLs are never echoed.
ERRORS = MappingProxyType({
    'invalid_request': (422, False, 'Check the address and analysis scope.'),
    'invalid_address': (422, False, 'Enter a valid Ethereum address.'),
    'unsupported_chain': (422, False, 'Only Ethereum mainnet is supported.'),
    'provider_unavailable': (503, True, 'The chain data provider is temporarily unavailable. Please retry.'),
    'provider_authentication': (503, False, 'The chain data provider requires server configuration.'),
    'provider_rate_limited': (503, True, 'The chain data provider is busy. Please retry shortly.'),
    'provider_response_invalid': (502, True, 'The chain data provider returned an invalid response.'),
    'historical_state_unavailable': (503, False, 'The provider cannot supply state at the required historical block.'),
    'quota_exhausted': (429, True, 'The daily chain data quota is exhausted. New analyses resume at 00:00 UTC.'),
    'quota_store_unavailable': (503, True, 'The chain data quota service is temporarily unavailable.'),
    'analysis_not_found': (404, False, 'Analysis not found. Start a new analysis.'),
    'artifact_not_ready': (409, True, 'This analysis result is not ready yet.'),
    'model_unavailable': (503, False, 'The model is unavailable. Collected data may still be inspected.'),
    'model_input_mismatch': (503, False, 'The collected input is incompatible with this model version.'),
    'model_error': (503, True, 'The model could not complete this assessment.'),
    'internal_error': (500, False, 'The analysis could not be completed. Please retry.'),
    'unsupported_family': (422, False, 'This analysis family is not supported by the live adapter.'),
    'invalid_token': (422, False, 'This address is not a supported ERC-20 token at the observation block.'),
    'invalid_pool': (422, False, 'The selected pool does not match this token and the supported Ethereum Uniswap v2 factory.'),
    'idempotency_conflict': (409, False, 'This idempotency key belongs to a different request.'),
    'invalid_cursor': (400, False, 'The pagination or event cursor does not belong to this analysis.'),
    'data_incomplete': (502, False, 'Chain data is incomplete or inconsistent. No model score was generated.'),
    'cutoff_in_future': (422, False, 'The requested cutoff is later than the latest available chain block.'),
})


class ServiceError(RuntimeError):
    def __init__(self, code: str, *, retry_at: float | None = None):
        status, retryable, message = ERRORS[code]
        self.code, self.status_code = code, status
        self.retryable, self.retry_at = retryable, retry_at
        super().__init__(message)

    def public_body(self) -> dict:
        return {'code': self.code, 'message': str(self), 'retryable': self.retryable,
                'retry_at': datetime.fromtimestamp(self.retry_at, timezone.utc).isoformat().replace('+00:00', 'Z')
                if self.retry_at is not None else None}

    def response_headers(self, now: float) -> dict[str, str]:
        return {'Retry-After': str(max(1, math.ceil(self.retry_at - now)))} if self.retry_at is not None else {}


class QuotaExhausted(ServiceError):
    """Admission rejects new work; workers persist waiting_quota + retry_at."""
    def __init__(self, retry_at: float):
        super().__init__('quota_exhausted', retry_at=retry_at)


class FeatureNotImplemented(NotImplementedError):
    """An explicit template boundary, never a simulated successful result."""
    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(f'{operation} is not implemented in this template')
