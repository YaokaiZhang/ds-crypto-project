# Chainrisk backend

`ANALYSIS_MODE=eth_live` enables real Ethereum collection and authenticated model
inference. The backend collects observations, builds frozen task-specific graphs
and calls the Modal service. It validates and persists returned scores and labels
without applying thresholds. Unsupported/incomplete inputs and failed inference
remain unscored. Mock predictors, the fixed 0.999 mode and the synthetic demo
adapter have been removed; `template` is the default unconfigured mode.

See [the model-service contract](../docs/MODEL_SERVICE_CONTRACT.md),
[deployment and credentials](../../deploy/MODAL.md), and the collection contracts
for [ETH](../docs/ETH_LIVE_ADAPTER.md), [ERC-20](../docs/TOKEN_LIVE_ADAPTER.md) and
[Forecast](../docs/FORECAST_LIVE_ADAPTER.md).

## Install and configure

Use the root Python 3.11 uv environment. The `serving` extra supplies API and
worker dependencies; model inference dependencies are on Modal. Backend request
preparation sends canonical graphs without duplicate tensors and needs no
PyTorch/NumPy installation. The Windows host uses a standard Python `.venv`.

```bash
uv sync --frozen --extra serving
```

Configure the same server-only environment variables for API and worker, or put
literal strings in ignored `apps/backend/local_secrets.py` (environment takes
precedence):

```text
ANALYSIS_MODE=eth_live
INFERENCE_URL=https://YOUR-DEPLOYMENT.modal.run
INFERENCE_API_KEY=<same application key as the Modal Secret>
INFERENCE_TIMEOUT=180
ETHEREUM_RPC_URL=<provider URL>
ETHERSCAN_API_KEY=<provider key>
```

`.env.example` is a reference; settings do not automatically source `.env`.
Credentials are read as literal assignments without executing the file. Use mode
0600. The Modal management token from `modal setup` is separate from the shared
inference key; the backend needs only the latter. Keys never enter browser config.

## Start locally

Run from the repository root with the existing environment:

```bash
.venv/bin/python scripts/start-eth-live.py --restart-backend
```

This starts API/worker/frontend and checks readiness. Manual entrypoints for a
VPS process manager are:

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000
.venv/bin/python -m apps.backend.app.workers.analysis
```

API documentation is at `http://127.0.0.1:8000/docs`. Check
`/api/v1/health/ready` and `/api/v1/capabilities` for `mode=eth_live`,
`score_mode=model` and five verified model identities. Cold starts may delay the
first check. Metadata checks are cached for 60 seconds. Missing configuration or
unavailable model service never advertises model readiness.

Include `apps/backend/config/`, shared `packages/`, and the graph helpers under
`scripts/` on the backend host. No `deploy/`, weights, labeling policies or Modal
management credentials are needed there. Model weights/scalers and label
thresholds live in the separate inference service.

## Durable collection and results

The present queue is single-host SQLite with fenced leases, replayable events,
immutable input artifacts and bounded worker retries. API/worker must share the
same analysis database/artifact paths. Etherscan uses one shared account ledger:
3 request starts/second, 99,000 attempts per UTC day, including retries. Share
`ETHERSCAN_QUOTA_FILE` between all cooperating processes for the same account.
Keep quota pause/recovery and the frozen cutoff when restarting.

The display graph and complete activity ledger remain independent of each
model's frozen sampling recipe. Forecast uses the creation-based first-seven-day
wallet graph and the released no-USD v0.2.0 ensemble. All input metadata is local
to `config/`; the model service alone scales the canonical graph and converts
scores to labels. Responses must match sample, target, cutoff, model and scaler.
Historical results retain their provenance. New workers refuse unfinished legacy
simulated jobs rather than turning them into real model assessments.

The real homepage feed is independent: set `FEED_ENABLED=true` on API and start
`python -m apps.backend.app.workers.feed`. See [feed integration](../docs/FEED_INTEGRATION.md).

## Checks

```bash
.venv/bin/python checks/run.py --suite backend
```

Tests use controlled HTTP/provider fixtures to cover identity validation, auth,
retries, quotas, graph construction, persistence, failure behavior and label
passthrough. Production has no fixture scoring path. Default `template` returns
explicit unavailable/501 responses without fabricated jobs or scores.
