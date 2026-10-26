"""Validate a predictor's score and labels without applying any thresholds."""
from ..api.schemas import TaskResult

def read_model_response(payload, response):
    """Validate a real model response without reclassifying its numeric score."""
    if not isinstance(response, dict) or response.get('result_origin') != 'model':
        raise ValueError('Unexpected model response provenance')
    for key in ('task_id', 'sample_id', 'target', 'cutoff'):
        if response.get(key) != payload[key]:
            raise ValueError(f'Model response identity mismatch: {key}')
    expected = payload.get('model_version')
    if expected and response.get('score') is not None:
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
