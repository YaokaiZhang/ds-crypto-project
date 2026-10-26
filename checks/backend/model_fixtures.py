"""Test-only HTTP response fixtures; production always calls the remote service."""


def model_response(payload):
    result = {key: payload[key] for key in ('task_id', 'sample_id', 'target', 'cutoff', 'model_version')}
    result.update(status='ok', score=.73, calibration='uncalibrated', result_origin='model',
                  scaler_sha256=payload.get('scaler_sha256'))
    if payload['task_id'] == 'continued_activity':
        result.update(label='Continued activity', decision='continued_activity', forecast={
            'observation_days':7, 'horizon_days':90, 'swap_volume_threshold_usd':'1000',
            'score_target':'continued_activity', 'outcome':'continued_activity',
            'decision_policy_version':'test-forecast-policy'})
    else:
        result.update(label='High Risk', risk_band='high', risk_band_policy_version='test-risk-policy',
                      decision='screen_positive')
    return result
