# Chainrisk backend

ETH/ERC-20/Forecast real-data collection and the durable local worker are now available in
`ANALYSIS_MODE=eth_live_mock`, with a temporary random-score adapter explicitly
requested by the user. Run `.venv/bin/python scripts/start-eth-live.py` from the
repository root to start API/worker/frontend. See [ETH live adapter](../docs/ETH_LIVE_ADAPTER.md)
for the model input contract, real-address checks and restart/configuration.
The frontend retains its original text and a recent graph capped at 64 nodes
and at most 30 days. Model provenance stays
explicit in API/artifacts; trained inference remains unavailable.

The [2026-10-24 live backend contract](../docs/LIVE_BACKEND_IMPLEMENTATION.md)
records confirmed serving behavior and the current implementation boundary.
Backend-local credential loading, shared Etherscan pacing (3/sec, 99,000 per
UTC day), HTTP error handling, RPC address classification, risk policies and
progress DTO/UI support are implemented and tested. ETH now connects these
components through a durable local worker. ERC-20 follows the same complete
progressive 30-day ledger/activity and bounded delayed-graph principles; see
[ERC-20 live adapter](../docs/TOKEN_LIVE_ADAPTER.md). Unsupported assets/pools
show Unavailable with a reason and no score. Forecast uses its own real first-week
window and wallet/pool/token graph, with an independently configurable 0.5 mock
decision threshold; see [Forecast live adapter](../docs/FORECAST_LIVE_ADAPTER.md).
Trained model serving remains unimplemented; Forecast's deployment scaler/bundle
is still pending and its temporary input declares unscaled preprocessing.

An explicitly enabled local analysis adapter is now available. Run
`ANALYSIS_MODE=demo .venv/bin/python -m uvicorn app.main:app --app-dir apps/backend`
from the repository root to exercise both workbenches with backend phase delays,
complete synthetic bundles and replayable SSE. Default template behavior described
below remains unchanged. See [analysis adapter integration](../docs/ANALYSIS_ADAPTER_INTEGRATION.md)
for configuration, response boundaries and module removal.

A real Ethereum homepage feed is also available with `FEED_ENABLED=true` and a
separate collector process. See [feed integration](../docs/FEED_INTEGRATION.md)
for startup, the PublicNode default RPC and summary/recovery semantics.

FastAPI application skeleton under `app/`, sharing the root Python 3.11 uv
project. Model inference remains unavailable. With both optional adapters disabled, no
database connections, provider requests or model loads occur on startup.

## Install and start

Run from the `ds-crypto-project` root:

```bash
uv sync --frozen --extra serving
uv run --frozen --extra serving uvicorn app.main:app --app-dir apps/backend --reload
```

API documentation is at `http://127.0.0.1:8000/docs`. Liveness returns 200;
readiness returns 503. Capabilities advertise all integrations as unavailable.
Validated analysis, result and feed requests return structured HTTP 501 until
implemented; no fake queued IDs, data or model scores are returned.

The root optional `serving` group supplies FastAPI/Pydantic/Uvicorn and the
HTTP client needed by endpoint checks. `apps/` remains excluded from the root
research wheel; Uvicorn explicitly loads this source directory. No second
training environment or backend-specific lockfile is created.

## Backend dependency installation

[`../requirement.txt`](../requirement.txt) lists the direct API/demo/feed runtime
dependencies in a format accepted by pip and conda. Package managers resolve
transitive dependencies; versions are not locked, except for the required
Pydantic minimum. The existing root `pyproject.toml` and `uv.lock` remain
authoritative for the shared research/serving environment. SQLite and other standard-library
modules do not need separate pip packages. Real model dependencies are managed
by the root research environment when those adapters are implemented.

For a separate Python 3.11+ backend environment, install from the repository root
using either package manager:

```bash
python -m pip install -r apps/requirement.txt
# Or, in an activated conda environment:
conda install -c conda-forge --file apps/requirement.txt
```

Then run the API or collector from the repository root:

```bash
PYTHONPATH=packages ANALYSIS_MODE=demo python -m uvicorn app.main:app --app-dir apps/backend
# Optional real feed, in a separate terminal with the same environment:
PYTHONPATH=packages FEED_ENABLED=true python -m apps.backend.app.workers.feed
```

The `PYTHONPATH` setting makes the repository's local `chainrisk.tasks` registry
available without installing the root training dependencies. Enable the API feed
with `FEED_ENABLED=true` as documented in the feed guide. Dependency installation
does not start any service.

## Develop through the templates

- `app/api/`: DTOs, routers, request validation and dependency lookup.
- `app/application/`: facade, pipeline, task strategies and feed coordination.
- `app/ports/`: provider, repository, graph, analytics and predictor protocols.
- `app/adapters/`: unimplemented provider/PostgreSQL/chainrisk integration classes.
- `app/container.py`: injection/composition root; replace implementations here.
- `app/workers/`: separate analysis and feed entrypoints.
- `app/domain.py`: framework-independent command/context/result values.

Analysis production methods stop with FeatureNotImplemented until replaced;
the optional demo and live-feed adapters are the documented exceptions. Existing
models and deterministic transformations remain in `packages/chainrisk`; do not
copy research trainers into this app. Freeze graph/sample identity before graph
presentation and prediction. Model loading belongs to the analysis worker.

`.env.example` lists server-only variables and is not automatically loaded.
Provider credentials use process environment first, then literal strings in
Git-ignored `apps/backend/local_secrets.py`; an explicitly empty environment
value disables fallback. The backend-local copy has mode 0600. No file is
executed to read credentials. Keep one `ETHERSCAN_QUOTA_FILE` for each account,
shared by every cooperating API/worker and concurrent local collector process.

## Checks and worker entrypoints

```bash
uv run --frozen --extra serving python -m unittest discover -s apps/backend/checks -v
uv run --frozen --extra serving python -m apps.backend.app.workers.analysis --help
uv run --frozen --extra serving python -m apps.backend.app.workers.feed --help
```

The analysis worker fails fast in template mode; eth_live_mock enables the
documented real ETH/ERC-20 worker. The feed
worker requires `FEED_ENABLED=true`; it then collects real mainnet transactions.
See [template development](../docs/TEMPLATE_DEVELOPMENT.md) and
[website architecture](../docs/WEBSITE_ARCHITECTURE.md).
