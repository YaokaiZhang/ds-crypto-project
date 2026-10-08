# Deployment and inference

This directory is reserved for independent inference and deployment. Only the directory structure has been created; no runnable service or model bundle is available yet.

| Directory | Planned responsibility |
|---|---|
| `inference_service/` | Python HTTP inference entrypoint, model loading, task routing, and status responses |
| `worker/` | Long-running jobs such as on-demand collection, graph construction, or isolated simulation |
| `registry/` | Approved model versions, input schemas, thresholds, and calibration information |

Model definitions and deterministic input transformations will be provided by a Python package shared between training and inference. The service will read frozen models and scalers without calling training scripts, refitting parameters, or writing to training data and historical experiment directories.

Dependency lockfiles, containers, and startup configuration will be added when the service is implemented. No nonfunctional placeholder service is included.
