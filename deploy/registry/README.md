# Model-server decision policies

These policies belong to the Gradio service, not the backend deployment.

- `risk_policies.json` stores the four Scam models' Low/Medium/High boundaries,
  tied to exact model identities. `inference_service/policies.py` applies them
  and returns `risk_band`, `label` and policy identity alongside the score.
- `forecast_policy.json` stores Forecast's decision boundary, positive/negative
  meanings and horizon semantics, bound to model version
  `continued_activity-b6140c2fdd0cc2e6`. Its threshold (0.5369952122370402) is the ensemble
  threshold selected on validation predictions and must equal the bundle
  manifest's; startup fails otherwise. It is bound to the no-USD Forecast v0.2.0 bundle.

Trained Scam binary thresholds remain in each Release bundle's `manifest.json`.
The model service returns both the trained binary `decision` and display `label`;
they are distinct outputs. The backend never reclassifies scores.

`prepare.py` includes both policy JSONs and `policies.py` in the Space package.
Backend input-only indexes/manifests/scalers have moved to `apps/backend/config/`.
See [deployment instructions](../README.md) and the
[model-service contract](../../apps/docs/MODEL_SERVICE_CONTRACT.md).
