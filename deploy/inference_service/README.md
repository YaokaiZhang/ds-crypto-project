---
title: Chainrisk Model API
emoji: 🔎
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.30.0
python_version: "3.11"
app_file: app.py
pinned: false
---

# Chainrisk Model API

One Gradio Server Mode process loads one fixed bundle for each configured task:
Phishing, Ponzi, Honeypot, Rug Pull and Forecast (`continued_activity`, a
three-seed edge-aware GCN ensemble). The service owns numeric thresholds and
returns a score plus its display label.
No training, provider access or random fallback scores are used.

In the source checkout, follow **deploy/README.md** (copied to
[DEPLOYMENT.md](DEPLOYMENT.md) in the prepared Space) for the full Hugging Face
creation, upload, configuration, call testing and local uv environment guide.
Download and verify the five ZIP bundles plus `SHA256SUMS` from the
[Models Release](https://github.com/YaokaiZhang/ds-crypto-project/releases/tag/Models),
extract them, and pass their mapping to `prepare.py --config` as described in that
guide. Upload the generated folder contents, including shared
`packages/` and `bundles/`, instead of this source directory alone.

## Settings

- Default CPU, listening on `0.0.0.0:7860`.
- `INFERENCE_DEVICE=cuda` is supported on dedicated GPU hardware, not ZeroGPU.
- `INFERENCE_API_KEY` is an optional Secret, sent as `X-Inference-Key` by clients.
- Private Spaces additionally require an authorized HF read token.
- `models.json` maps tasks to bundle directories; invalid bundles fail startup.
- `risk_policies.json` and `forecast_policy.json` hold server-owned label policies;
  `RISK_POLICY_PATH` / `FORECAST_POLICY_PATH` may override them. The backend does
  not load these files or recompute labels.
- No database or RPC/Etherscan credentials are needed. Release bundles are
  downloaded before packaging; the running Space needs no GitHub token/download.

## API

- `GET /health/live`: liveness.
- `GET /health/ready`: successfully loaded tasks.
- `GET /models`: availability and model/input metadata.
- `POST /predict`: JSON with `task_id` and the complete unscaled `graph_sample`
  (Scam canonical graph, or Forecast first-week wallet graph plus `sample_id`).
- Gradio client: `client.predict(payload=packet, api_name="/predict")`.

Existing ETH/token packets are accepted. Supplied identities are checked and
pre-scaled `inputs` are ignored; the training scaler is applied exactly once.
REST busy/invalid/unavailable conditions use HTTP 429/422/503 respectively;
Gradio returns these conditions in the result dictionary. Both routes share
one inference lock and have a 16 MiB request-body limit.

The existing backend remains in its current mode. Connecting a real remote
predictor is intentionally a later backend change.
