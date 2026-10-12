# Deployment and inference

This directory is reserved for independent inference and deployment. Deployment configuration remains a placeholder. A runnable API shell and worker class/method templates now exist in `apps/backend/`; real analysis/feed processing and approved Task B model bundles remain unavailable.

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
