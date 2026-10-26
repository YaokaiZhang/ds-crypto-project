# Model-service requests, responses and ownership

Serving contract revision: 2026-10-26. The backend and model server run on
different machines. Backend deployment does not include `deploy/`.

## Responsibilities

The Gradio service owns trained binary thresholds, Scam risk/display bands,
Forecast decision thresholds and score-to-label conversion. It returns a score,
categorical outcomes, a display label and provenance. The backend validates the
response, saves it and forwards it unchanged for display. Frontend panels prefer
the returned `label`; they do not apply numeric thresholds.

Backend-owned input schemas/manifests/scalers live in `apps/backend/config/`.
The model service's risk and Forecast policies live in `deploy/registry/` and
are copied into the prepared Space. Provider keys stay on the backend machine.
Neither side imports the other application's source at runtime; both use the
shared graph/model protocol where appropriate.

## Requests

Scam workers build separate frozen canonical graphs using backend-local input
manifests and sampling recipes. The ETH/token packet carries:

- `protocol_version`: `eth-graph-inference-1` or `token-graph-inference-1`.
- `task_id`, `sample_id`, `target`, frozen `cutoff` and `model_version`.
- `graph_recipe`, `feature_names`, `scaler_sha256` and unscaled `graph_sample`.
- The backend sends no duplicate pre-scaled tensors and does not import PyTorch.
  The model service scales the canonical graph exactly once. Older optional
  `inputs` packets remain readable by the service but are ignored.

Forecast keeps `forecast-wallet-observations-1`, a creation-based first-seven-day
wallet/pool/token graph, label-free inference metadata and explicit quality.
The native builder uses the backend-local Forecast v0.2.0 identity and
scaler checksum from `apps/backend/config/forecast_input.json`. Its unscaled
canonical graph is transformed only by the server; the no-USD model selects
14 node / 8 edge columns by name from the full live schema.

## Responses

All successful responses bind `task_id`, `sample_id`, `target`, `cutoff`,
`model_version` and `result_origin` to the submitted input. The backend's
`app/adapters/model_response.py::read_model_response` validates identity and the
following result fields, then projects them into `TaskResult`. Extra server
audit fields do not leak into the strict public DTO.

| Field | Scam | Forecast |
|---|---|---|
| `status` | `ok` for a scored response | `ok` for a scored response |
| `score` | Finite value in [0,1] | Continued-activity score in [0,1] |
| `label` | `Low Risk`, `Medium Risk`, `High Risk` | `Continued activity`, `Low volume` |
| `risk_band` | `low`, `medium`, `high` | Absent |
| `risk_band_policy_version` | Required with a risk band | Absent |
| `decision` | `screen_positive` / `screen_negative` under trained threshold | `continued_activity` / `low_volume_dead` |
| `forecast` | Absent | 7-day observation, following 90-day USD 1000 Swap outcome, matching outcome and policy identity |
| `calibration` | Explicit, currently `uncalibrated` | Explicit, currently `uncalibrated` |
| `result_origin` | `model` for real inference | `model` for real inference |

The trained binary `decision` and the three-band display `label` are distinct
server outputs. The backend checks categorical/identity consistency, not whether
a numeric score crosses a threshold. Changing thresholds requires a model-service
policy update, not a backend policy file.

Missing models or unusable inputs return a null score and no display label.
Malformed responses, missing labels, NaN/out-of-range scores, mismatched samples
or model identities are errors; the backend must not manufacture labels or scores.

## Real remote transport

`ANALYSIS_MODE=eth_live` uses `RemotePredictor` and `ForecastRemotePredictor`.
API and worker receive `INFERENCE_URL` and `INFERENCE_API_KEY` as server-only
configuration, independently of deployment source. HTTPS POST `/predict` sends
`X-Inference-Key`, times out after 180 seconds by default, retries HTTP 429 at most
three times, and validates responses with origin `model`, exact sample/target/
cutoff/model identity and the matching scaler checksum. Server errors and timeouts
use the durable worker's bounded retry path; authentication/input failures remain
unscored errors. No inference failure produces a fabricated score.

The service provides `/models`; backend capabilities/readiness check the loaded
model and scaler identities against backend-local config, caching observations for
60 seconds. Configuration alone never sets `model_available=true`. A remote
outage disables readiness while collected results remain available.

Accepted real jobs use `result_origin=chain_data_model_scores`; task results use
`result_origin=model`. Result caches include the remote protocol and model identity. Workers refuse to
execute unfinished legacy simulated jobs; completed historical records retain
their original provenance. The fixed mock mode, local loopback transport and
synthetic demo code have been removed, including their configuration switches.

Forecast uses `continued_activity-b6140c2fdd0cc2e6` from Release v0.2.0, retrained
without USD features. The model service owns its released threshold
0.5369952122370402. The backend input metadata carries no labeling thresholds.
See [Modal setup and VPS configuration](../../deploy/MODAL.md).
