# Model-service requests, responses and ownership

Serving contract revision: 2026-10-25. The backend and model server run on
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
- Existing pre-scaled `inputs` for audit/backward compatibility. The model
  service ignores these tensors and scales the canonical graph exactly once.

Forecast keeps `forecast-wallet-observations-1`, a creation-based first-seven-day
wallet/pool/token graph, label-free inference metadata and explicit quality.
Its current input is unscaled and explicitly awaits the owner's deployment
bundle/scaler. That temporary packet is not admission to a trained Forecast model.

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

## Current fixed mock

`ANALYSIS_MODE=eth_live_mock` still collects real data and persists exact model
inputs. The reserved loopback send remains an explicit test boundary; received
HTTP data is ignored in this mode. Instead, a service-shaped fixture is decoded
through the same response validator:

- All four eligible Scam tasks: `score=0.999`, `label=High Risk`, `risk_band=high`,
  `decision=screen_positive`.
- Eligible Forecast: `score=0.999`, `label=Continued activity`,
  `decision=continued_activity`, matching Forecast metadata, no risk band.
- Fixtures carry `result_origin=simulated`, `simulated:` model identities and
  `mock-fixed-0999-v1` policy identity; capabilities never claim real weights.
- No random generator or backend threshold policy participates. This fixture
  remains independent of both the numeric thresholds and availability of a
  running model service.
- Unsupported, empty, immature or invalid inputs remain Unavailable and unscored.

The fixed response uses a distinct persisted cache identity. In-progress jobs
recovering old random artifacts produce the new fixed response; they do not reuse
an obsolete random score. Completed historical results remain intact.

Real remote transport is a later change. It must replace the explicit mock
fixture with the server response, call the same validator with origin `model`,
and update capabilities. A real transport failure must never fall back to this
mock fixture. Forecast remains unserved until its real bundle/scaler is integrated.
