# Model registry

`forecast_policy.json` is the user-authorized temporary Forecast decision policy:
continued_activity score, threshold 0.5, seven-day observation and following
90-day USD 1000 Swap-volume outcome. `FORECAST_POLICY_PATH` overrides it. The
Forecast input is a real unscaled wallet graph; its deployment bundle/scaler
remains pending. This mock policy does not register trained weights or Scam
risk bands. See [Forecast live adapter](../../apps/docs/FORECAST_LIVE_ADAPTER.md).

`eth_models.json` selects exact input manifest/scaler copies in `eth_inputs/`
for the real-data ETH worker. The temporary scorer validates these and exports
model-compatible inputs without loading weights. This does not activate a
trained model service; see [ETH live adapter](../../apps/docs/ETH_LIVE_ADAPTER.md).

`token_models.json` selects byte-identical Honeypot/Rug Pull manifest and scaler
copies in `token_inputs/`. `TOKEN_MODEL_REGISTRY_PATH` overrides this token
index separately from the existing ETH `MODEL_REGISTRY_PATH`. Inputs retain
the directed edge-aware architecture's five tensors and each frozen recipe;
no weights are copied or loaded. See [ERC-20 live adapter](../../apps/docs/TOKEN_LIVE_ADAPTER.md).

`risk_policies.json` now records the four user-selected display-band boundaries,
bound to exact local model versions. It does not change the bundles' trained
binary thresholds or register model files for live serving. The backend policy
reader validates boundaries and refuses to reuse a policy for different weights.
See [the live backend contract](../../apps/docs/LIVE_BACKEND_IMPLEMENTATION.md).

Reserved for model manifests and an index of approved versions. Records will include the task, architecture, graph and feature schemas, scaler, label polarity, threshold, calibration status, code version, and checksum.

Weights will be provided through external model storage or read-only mounts, rather than the frontend public directory. No models are registered yet.
