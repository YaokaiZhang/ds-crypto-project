# Chainrisk backend template

FastAPI application skeleton under `app/`, sharing the root Python 3.11 uv
project. This is not a functioning chain collector or model inference service.
No database connections, provider requests or model loads occur on startup.

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

## Develop through the templates

- `app/api/`: DTOs, routers, request validation and dependency lookup.
- `app/application/`: facade, pipeline, task strategies and feed coordination.
- `app/ports/`: provider, repository, graph, analytics and predictor protocols.
- `app/adapters/`: unimplemented provider/PostgreSQL/chainrisk integration classes.
- `app/container.py`: injection/composition root; replace implementations here.
- `app/workers/`: separate analysis and feed entrypoints.
- `app/domain.py`: framework-independent command/context/result values.

All business methods stop with FeatureNotImplemented until replaced. Existing
models and deterministic transformations remain in `packages/chainrisk`; do not
copy research trainers into this app. Freeze graph/sample identity before graph
presentation and prediction. Model loading belongs to the analysis worker.

`.env.example` lists server-only variables. The template reads actual process
environment variables; it does not automatically load that example file.

## Checks and worker entrypoints

```bash
uv run --frozen --extra serving python -m unittest discover -s apps/backend/checks -v
uv run --frozen --extra serving python -m apps.backend.app.workers.analysis --help
uv run --frozen --extra serving python -m apps.backend.app.workers.feed --help
```

Running a worker without `--help` currently fails fast with exit code 2 and an
explicit unimplemented operation. It does not run an idle or simulated scanner.
See [template development](../docs/TEMPLATE_DEVELOPMENT.md) and
[website architecture](../docs/WEBSITE_ARCHITECTURE.md).
