# Chainrisk backend

The FastAPI backend collects Ethereum data, builds task inputs and calls the
remote model API. `ANALYSIS_MODE=eth_live` enables real analysis; the default
`template` mode remains unavailable. Failed or unsupported inputs are unscored.
See [model deployment](../../deploy/README.md) and [Modal setup](../../deploy/MODAL.md).

## Install and configure

From the repository root, use the existing Python 3.11 environment:

```bash
uv sync --frozen --extra serving
```

Give API and analysis worker the same server-only configuration, using environment
variables or literal strings in ignored `apps/backend/local_secrets.py`:

```text
ANALYSIS_MODE=eth_live
INFERENCE_URL=https://YOUR-DEPLOYMENT.modal.run
INFERENCE_API_KEY=<same application key as the model service>
INFERENCE_TIMEOUT=180
ETHEREUM_RPC_URL=<provider URL>
ETHERSCAN_API_KEY=<provider key>
```

Environment values take precedence. `.env.example` is a reference and is not
loaded automatically. The literal-only secrets loader does not execute the file;
restrict its filesystem permissions. The application inference key is separate
from the Modal management token. Neither belongs in browser configuration.

## Start

For local development with frontend dependencies already installed:

```bash
.venv/bin/python scripts/start-eth-live.py
```

The launcher starts API, analysis worker and Vite. Use `--restart-backend` to
restart its recorded API/worker while preserving Vite, or `--restart` for all
three. Logs are written under `.runtime/eth-live-*.log`.

For a process manager, run these as separate processes from the repository root:

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000
.venv/bin/python -m apps.backend.app.workers.analysis
```

Check `/api/v1/health/ready` and `/api/v1/capabilities` for `mode=eth_live`,
`score_mode=model` and matching model identities. Cold starts may delay the first
check; model metadata is cached for 60 seconds. OpenAPI is at `/docs` on the API.

## Enable the homepage feed

Set `FEED_ENABLED=true` on the API and feed worker, and give both the same
`FEED_DATABASE_PATH` and mainnet `ETHEREUM_RPC_URL`. Start a separate worker:

```bash
.venv/bin/python -m apps.backend.app.workers.feed
```

The feed is independent of analysis mode. It uses one owner per SQLite database
and resumes through stored cursors/SSE events. The local launcher does not start
this worker. Configure it separately in your process manager.

## Persistence and deployment

- API and analysis worker must share `ANALYSIS_DATABASE_PATH` and
  `ANALYSIS_ARTIFACT_PATH`; defaults are under repository `.runtime/`.
- Share `ETHERSCAN_QUOTA_FILE` across all processes using the same account.
  Defaults cap starts at 3/second and attempts at 99,000 per UTC calendar day,
  including retries. Preserve the ledger, job database and artifacts on restart.
- The implemented queue is single-host SQLite. Keep API/workers on that host;
  provide a reverse proxy for the frontend and allow SSE without buffering.
- Include backend `config/`, required shared `packages/` and `scripts/` graph
  helpers. The backend does not require `deploy/`, weights or Modal management
  credentials. A Windows host can use a standard Python `.venv`.
- The backend sends canonical unscaled graphs with sample/model/scaler identities.
  The model service alone scales inputs and returns scores and labels. Backend
  input manifests must match the served bundles. Invalid responses remain errors.

## Checks

```bash
.venv/bin/python checks/run.py --suite backend
```

See [repository checks](../../checks/README.md) for offline and explicit live
verification. Production scoring has no mock or fixture fallback.
