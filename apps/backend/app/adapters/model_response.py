"""Validate a predictor's score and labels without applying any thresholds."""
from ..api.schemas import TaskResult

FIXED_MOCK_VERSION = 'mock-fixed-0999-v1'


def fixed_mock_response(payload):
    """A service-shaped fixture, never a fallback for real inference errors."""
    response = {key: payload[key] for key in ('task_id', 'sample_id', 'target', 'cutoff')}
    response.update(status='ok', score=0.999, model_version='simulated:' + payload['model_version'],
                    calibration='uncalibrated', result_origin='simulated',
                    explanation='Fixed mock response; no trained model was called.')
    if payload['task_id'] == 'continued_activity':
        response.update(label='Continued activity', decision='continued_activity', forecast={
            'observation_days': 7, 'horizon_days': 90, 'swap_volume_threshold_usd': '1000',
            'score_target': 'continued_activity', 'outcome': 'continued_activity',
            'decision_policy_version': FIXED_MOCK_VERSION})
    else:
        response.update(label='High Risk', risk_band='high', risk_band_policy_version=FIXED_MOCK_VERSION,
                        decision='screen_positive')
    return response


def read_model_response(payload, response, *, origin='model'):
    """Use the same boundary for a future real adapter and current fixed mock."""
    if not isinstance(response, dict) or response.get('result_origin') != origin:
        raise ValueError('Unexpected model response provenance')
    for key in ('task_id', 'sample_id', 'target', 'cutoff'):
        if response.get(key) != payload[key]:
            raise ValueError(f'Model response identity mismatch: {key}')
    expected = payload.get('model_version')
    if expected and response.get('score') is not None:
        expected = 'simulated:' + expected if origin == 'simulated' else expected
        if response.get('model_version') != expected:
            raise ValueError('Model response uses different weights')
    result = TaskResult.model_validate({key: response[key] for key in TaskResult.model_fields if key in response})
    if result.score is not None:
        if not result.label or not result.decision or not result.calibration:
            raise ValueError('Scored model response requires a label, decision and calibration')
        if result.task_id == 'continued_activity':
            label = {'continued_activity': 'Continued activity', 'low_volume_dead': 'Low volume'}.get(result.decision)
        else:
            if result.decision not in ('screen_positive', 'screen_negative'):
                raise ValueError('Unknown Scam binary outcome')
            label = {'low': 'Low Risk', 'medium': 'Medium Risk', 'high': 'High Risk'}.get(result.risk_band)
        if result.label != label:
            raise ValueError('Model label does not match its categorical outcome')
    return result.model_dump(mode='json', exclude_none=True)
