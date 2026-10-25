"""Server-owned labels and thresholds; the backend only consumes outcomes."""
from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class RiskPolicy:
    version: str
    models: dict

    @classmethod
    def load(cls, path: str | Path):
        content = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(content.get('policy_version'), str) or not content['policy_version']:
            raise ValueError('Risk policy version is required')
        models = content.get('models', {})
        if set(models) != {'phishing', 'ponzi', 'honeypot', 'rug_pull'}:
            raise ValueError('Risk policy requires exactly the four Scam tasks')
        for entry in models.values():
            low, high = entry.get('L'), entry.get('H')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (low, high)):
                raise ValueError('Risk boundaries must be finite numbers')
            if not 0 <= low < high <= 1 or not isinstance(entry.get('model_version'), str) or not entry['model_version']:
                raise ValueError('Risk boundaries or model version are invalid')
        return cls(content['policy_version'], models)

    def classify(self, task: str, model_version: str, score: float) -> str | None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Score must be a finite value between zero and one')
        entry = self.models.get(task)
        if entry is None or entry['model_version'] != model_version:
            return None
        return 'low' if score < entry['L'] else 'medium' if score < entry['H'] else 'high'


class ForecastPolicy:
    def __init__(self,path):
        self.data = json.loads(Path(path).read_text())
        d = self.data
        threshold = d.get('threshold')
        if (isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold)
                or not 0 <= threshold <= 1 or not d.get('policy_version')
                or not isinstance(d.get('model_version'),str) or not d['model_version'] or d.get('score_target') != 'continued_activity'
                or d.get('positive_outcome') != 'continued_activity' or d.get('negative_outcome') != 'low_volume_dead'
                or d.get('observation_days') != 7 or d.get('horizon_days') != 90 or d.get('swap_volume_threshold_usd') != '1000'):
            raise ValueError('Invalid Forecast decision policy')

    def outcome(self,score):
        if not isinstance(score,(int,float)) or isinstance(score,bool) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid Forecast score')
        return self.data['positive_outcome'] if score >= self.data['threshold'] else self.data['negative_outcome']

    def result(self, score, model_version):
        if model_version != self.data['model_version']:
            raise ValueError('Forecast policy does not match the model')
        decision = self.outcome(score)
        metadata = {key: self.data[key] for key in
                    ('observation_days', 'horizon_days', 'swap_volume_threshold_usd', 'score_target')}
        metadata.update(outcome=decision, decision_policy_version=self.data['policy_version'])
        return {'decision': decision, 'label': 'Continued activity' if decision == 'continued_activity' else 'Low volume',
                'forecast': metadata}
