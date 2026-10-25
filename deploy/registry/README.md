# Model-server decision policies

These policies belong to the Gradio service, not the backend deployment.

- `risk_policies.json` stores the four Scam models' Low/Medium/High boundaries,
  tied to exact model identities. `inference_service/policies.py` applies them
  and returns `risk_band`, `label` and policy identity alongside the score.
- `forecast_policy.json` stores Forecast's decision boundary, positive/negative
  meanings and horizon semantics, bound to model version
  `continued_activity-d6a823768005e113`. Its threshold (0.446) is the ensemble
  threshold selected on validation predictions and must equal the bundle
  manifest's; startup fails otherwise. It replaces the temporary 0.5 policy.

Trained Scam binary thresholds remain in each Release bundle's `manifest.json`.
The model service returns both the trained binary `decision` and display `label`;
they are distinct outputs. The backend never reclassifies scores.

`prepare.py` includes both policy JSONs and `policies.py` in the Space package.
Backend input-only indexes/manifests/scalers have moved to `apps/backend/config/`.
See [deployment instructions](../README.md) and the
[model-service contract](../../apps/docs/MODEL_SERVICE_CONTRACT.md).
