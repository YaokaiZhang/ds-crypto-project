# Deployment and inference

This directory owns deployment configuration. Container/proxy/startup files
remain pending. A runnable API, analysis templates and real homepage feed exist
in `apps/backend/`. ETH now has real collection and a durable local worker with
explicit temporary simulated scoring; trained model serving remains pending.
`registry/risk_policies.json` records the user-confirmed per-model
display bands, without activating a live model service. See the
[live backend contract and status](../apps/docs/LIVE_BACKEND_IMPLEMENTATION.md).

| Directory | Planned responsibility |
|---|---|
| `inference_service/` | Optional later isolated Python HTTP predictor; initial inference runs in the analysis worker |
| `worker/` | Deployment/startup configuration for independent analysis and homepage-feed workers |
| `registry/` | Approved model versions, input schemas, thresholds, and calibration information |

Model definitions and deterministic input transformations will be provided by a Python package shared between training and inference. The service will read frozen models and scalers without calling training scripts, refitting parameters, or writing to training data and historical experiment directories.

Dependency lockfiles, containers, and startup configuration will be added when the service is implemented. No nonfunctional placeholder service is included.

The 2026-10-12 [website blueprint](../apps/docs/WEBSITE_ARCHITECTURE.md) places future
FastAPI routes/orchestration/adapters and worker source under `apps/backend/`.
This directory owns container/proxy/startup configuration and bundle mounts,
not duplicate task/model implementations. API, analysis and feed processes are
separate; theme/icon reconstruction belongs to `apps/frontend/`.
