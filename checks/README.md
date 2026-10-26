# Repository regression checks

All regression source, fixtures and explicit live validation tools live here.
They are version controlled. Production frontend/backend deployments and the
prepared Modal model package do not need this directory.

```text
checks/
  run.py                 # One offline regression command
  test_*.py              # Research, data, graph, training, I/O and CLI contracts
  backend/               # API, providers, durable worker and model responses
  frontend/              # Node tests using the frontend's existing TypeScript
  serving/               # Model API, Release/Modal packaging and verifier tests
    verify_service.py    # One explicit deployed-model verifier
  fixtures/model_api/    # Four real Scam packets and two upstream Forecast packets
  fixtures/scam/         # Synthetic generator documentation, no static data dump
  live/                  # Explicit provider/mainnet tools; never auto-discovered
  .runtime/              # Ignored local acceptance reports/generated examples
```

## Offline regression

Use the existing root Python 3.11 uv environment and installed frontend packages:

```bash
.venv/bin/python checks/run.py
.venv/bin/python checks/run.py --suite backend
.venv/bin/python checks/run.py --suite frontend
.venv/bin/python checks/run.py --suite serving -v
.venv/bin/python checks/run.py --suite research
# Equivalent frontend-only entry from its directory:
npm --prefix apps/frontend test
```

The root `serving` extra supplies API test dependencies; model API checks also
need `deploy/inference_service/requirements.txt`. The four Modal declaration
checks need the Modal SDK. Existing environments are reused, not recreated or
deleted. The ordinary suite does not invoke Modal, query real chain providers,
submit jobs, or fit production models. Controlled HTTP fixtures remain test-only;
small temporary synthetic training runs verify research code.

Numerical serving checks need the pinned Release weights. `run.py` uses an
existing `deploy/.build/release-pinned/models.json` or `release-models/models.json`.
For another location:

```bash
TEST_MODEL_CONFIG=/absolute/path/to/models.json .venv/bin/python checks/run.py --suite serving
```

Absent default local weights or optional Gradio/Modal dependencies are reported
as skips. An explicitly configured missing/corrupt bundle is a failure. No test
downloads weights automatically. Python-only discovery also works with
`python -m unittest discover -s checks -t . -v`.

## Deployed service verification

This single standard-library command replaces the former `smoke.py` and verifier:

```bash
# Supply INFERENCE_API_KEY in the environment; add HF_TOKEN only for a private Space.
.venv/bin/python checks/serving/verify_service.py https://YOUR-SERVICE.modal.run
# Optional extra backend packet and cold-start timeout:
.venv/bin/python checks/serving/verify_service.py https://YOUR-SERVICE.modal.run \
  --payload /absolute/path/to/model-input.json --timeout 180
```

It checks liveness, readiness, all pinned model versions, missing-key rejection,
packet/model/scaler binding, finite scores, returned labels and all six recorded
fixtures. The four Scam packets are unlabeled golden-output regressions, not
holdout/accuracy evidence. The two Forecast packets retain upstream-recorded
research values. See [fixture provenance](fixtures/model_api/README.md).

`deploy/reproduce.sh` calls this same verifier after starting its independent
Docker/local service. CI runs offline regressions and the Docker reproduction;
it never needs Modal credentials. The verifier and fixtures stay outside the
model image. `deploy/` retains runtime/build/deployment code only.

CI also runs `python -m unittest checks.test_io -v` on Windows with Python 3.13
to cover atomic cache publication, gzip replacement and exclusive feed ownership.

## Explicit live checks

These tools are never part of the offline runner. Provider diagnostics require
configured credentials and perform real network requests. Acceptance reporting
reads existing local jobs; only `--submit` creates new provider-consuming work.

```bash
.venv/bin/python checks/live/check_rpc.py
.venv/bin/python checks/live/check_etherscan.py --snapshot forta-2022-v2
.venv/bin/python checks/live/verify_analysis.py --family token_scam
.venv/bin/python checks/live/verify_analysis.py --family forecast
```

Default reports and generated synthetic examples go under ignored
`checks/.runtime/`. No provider or inference keys belong in committed fixtures.

## Restored coverage

The research suite previously existed locally while `/checks/` was Git-ignored;
that blanket ignore has been removed. The historical fixture directory name
`task_b` was already superseded by `scam`; duplicate copies are not restored.
The deleted demo tests were reviewed: Forecast lifecycle, idempotency,
pagination/SSE, template unavailability and outcome-window/Scam-band separation
are retained against current API/worker behavior. Tests solely asserting the
removed demo adapter or its large canned datasets are retired with that feature.
The frontend's synthetic graph preview has also been removed; graph/state
regressions remain under `frontend/` without a public preview entry.
