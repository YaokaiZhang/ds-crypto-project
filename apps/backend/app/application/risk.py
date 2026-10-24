"""Display bands are versioned separately from frozen binary model thresholds."""
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
