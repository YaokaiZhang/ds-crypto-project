# Model API deployment

For Modal, follow [MODAL.md](MODAL.md). It reuses the Release download and bundle
preparation steps below, then starts the existing Gradio Server on a regular
CPU/CUDA container. The remaining hosting instructions on this page describe
Hugging Face Spaces.

One Hugging Face Space runs one `gradio.Server`, with one fixed bundle per task.
The existing backend still owns collection, model graphs, durable jobs and progress.
`ANALYSIS_MODE=eth_live` connects the backend to the deployed service; see
[backend configuration](../apps/backend/README.md).

```text
GitHub Release -> download / verify / extract -> prepare.py -> upload Space
Backend remote predictor -> HTTPS -> Gradio Server -> model -> score + label
```

Phishing, Ponzi, Honeypot and Rug Pull reuse `packages.bundle.load_model_bundle`
and `predict_bundle`. Forecast (`continued_activity`) uses
`packages.forecast.load_forecast_bundle` / `predict_forecast`: a three-seed
edge-aware GCN ensemble over the first-week wallet graph. All models load once,
use frozen training scalers and never train, collect data or generate random
fallback scores. A task omitted from `models.json` returns `model_unavailable`.
There is no version routing: `models.json` selects one bundle directory per task.
Existing manifest identities still bind weights, scaler, inputs and risk bands.
The service owns thresholds and labels. The backend receives and validates
score + label; it never derives a label from the score.

## Reproduce in one command (reviewers)

From a fresh clone, on any machine with Docker (or podman):

```bash
deploy/reproduce.sh
```

It builds `deploy/Dockerfile` (Python 3.11, CPU PyTorch 2.14.1, Gradio 6.30.0),
downloads the bundles pinned in [`release.json`](release.json) from the `Models`
Release, verifies every ZIP and file checksum and every model version, prepares
the same folder that is uploaded to the Space, starts it on port 7860 with a
random API key and runs [`verify_service.py`](../checks/serving/verify_service.py). The check
requires all five pinned model versions to be served, `/predict` to reject a
missing key, and all six [recorded packets](../checks/fixtures/model_api) to
reproduce their expected scores (tolerance 1e-5) and server labels. Four Scam
packets are unlabeled golden-output regressions; two upstream Forecast packets
retain their recorded research scores and outcomes. It prints `PASS`, the URL, the key and the stop command.

- Without a container: `deploy/reproduce.sh local` (needs `python3.11`; set
  `PYTHON=/path/to/python3.11` otherwise) does the same steps in a fresh venv
  under `deploy/.build/`.
- An already running service, such as the Space:
  `INFERENCE_API_KEY=... deploy/reproduce.sh verify https://OWNER-SPACE.hf.space`
  (add `HF_TOKEN` for a Private Space).
- CI: [`.github/workflows/model-api.yml`](../.github/workflows/model-api.yml) runs
  offline checks and `deploy/reproduce.sh` for relevant application, model and
  test changes on pushes and pull requests.
- `verify_service.py` and `fetch_release.py` use only the Python standard library.

### Other hosts (Verda, any VM or container platform)

The image needs no GPU, no secrets other than `INFERENCE_API_KEY`, and no
network access after the build. Inference is CPU-only (about 10-40 ms per
request), so a small CPU instance is enough; a GPU instance adds cost only.

- **Any Linux VM, including a Verda instance:** install Docker, clone the
  repository and run `deploy/reproduce.sh`. Open only port 7860 (or put it behind
  an HTTPS reverse proxy) and pass your own `INFERENCE_API_KEY`.
- **Managed container services** (Verda serverless containers, Cloud Run, Fly.io,
  a Hugging Face Docker Space): build and push the image to a registry, e.g.
  `docker build -f deploy/Dockerfile -t ghcr.io/OWNER/chainrisk-model-api:v0.2.0 .`
  then `docker push ...`, and create a deployment with container port 7860,
  secret environment variable `INFERENCE_API_KEY`, and health check
  `GET /health/ready`. Build with `--platform linux/amd64` when the platform
  requires x86-64.

## 1. Download the published model bundles

Run all commands from the `ds-crypto-project` repository root. Obtain weights
from the [Models release](https://github.com/YaokaiZhang/ds-crypto-project/releases/tag/Models)
(tag `Models`). Use the explicit tag instead of the GitHub `latest` download URL.

| Task | Release asset | Model version |
|---|---|---|
| phishing | `chainrisk-phishing-v0.1.0.zip` | `phishing-542e0cb0aebaf59c` |
| ponzi | `chainrisk-ponzi-v0.1.0.zip` | `ponzi-0391bc0785180121` |
| honeypot | `chainrisk-honeypot-v0.1.0.zip` | `honeypot-6c18c414ab9f5896` |
| rug_pull | `chainrisk-rug_pull-v0.1.0.zip` | `rug_pull-642ed08bc29e8d3c` |
| continued_activity | `chainrisk-continued_activity-v0.2.0.zip` | `continued_activity-b6140c2fdd0cc2e6` |

Also download the attached `SHA256SUMS`. Each ZIP contains a top-level directory
named after the ZIP (without `.zip`) and an internal `SHA256SUMS`. Scam bundles
hold `model.pt`, `scaler.json` and `manifest.json`; the Forecast bundle holds
`manifest.json`, `scaler.json` and one `member-<seed>.pt` per ensemble member.
Keep the files together. Training reports, datasets and prediction records are
not needed for deployment.

The Forecast bundle is exported from the Task A training runs (pruned temporal
split, `edge_gcn`, seeds 20261001-3) by `scripts/export_forecast_bundle.py`,
which reloads the written bundle and requires it to reproduce the recorded
research ensemble scores on all 2,000 training-dataset graphs.

Download, verify both archive and internal checksums, safely extract and generate
`models.json` with the included helper:

```bash
.venv/bin/python deploy/fetch_release.py \
  --output deploy/.build/release-models --downloads deploy/.build/release-downloads
```

Files stay under `deploy/.build/release-downloads/` and
`deploy/.build/release-models/`. Existing ZIP downloads are revalidated and reused; corrupt files fail verification.
Extraction requires a fresh output directory; use `--output deploy/.build/another-release`
when rebuilding. The model versions come from the shared `deploy/release.json`. Forecast v0.2.0 is selected; the older Forecast asset in
the same Release is retained upstream for rollback and is not downloaded.

For private repository access, first use an authenticated GitHub CLI to download
the same five ZIPs and `SHA256SUMS` into `deploy/.build/release-downloads/`, then
run the helper to verify/extract the local files. GitHub credentials are not
uploaded to the model service.

## 2. Prepare the Space from the downloaded bundles

The download helper generates the relative bundle mapping. Prepare it with:

```bash
.venv/bin/python deploy/inference_service/prepare.py \
  --config deploy/.build/release-models/models.json \
  --output deploy/.build/space
```

Preparation uses existing PyTorch and needs no Gradio or further network access.
`prepare.py` verifies checksums, schemas, state dictionaries and the checked-in
risk policies before copying anything. Original local training directories are
not required for this Release-based path. The checked-in
`inference_service/models.json` remains a convenience for local development using
the original artifacts; the `--config` above explicitly selects downloaded files.
For a smaller deployment, append `--tasks phishing ponzi`.

Choose a new output directory on each run; existing folders are never overwritten.
Only allowlisted source/configuration and selected bundles enter the output:

```text
space/
  README.md                # Space YAML: Gradio 6.30.0, Python 3.11, app.py
  app.py
  runtime.py
  policies.py              # Server-owned score-to-label rules
  DEPLOYMENT.md            # This full deployment guide
  requirements.txt
  models.json              # Relative bundles/<task> paths
  risk_policies.json
  forecast_policy.json
  packages/                # Shared graph, model and bundle source only
  bundles/<task>/
    manifest.json
    scaler.json
    model.pt               # Forecast: member-<seed>.pt files instead
```

The generated folder excludes backend secrets, provider keys, datasets, research,
frontend, job artifacts and local environments. Prepared files are Git-ignored.
Generate this folder when preparing an upload; it does not need to be retained
afterwards. Bundle manifests already include the checksums verified by the loader.

`registry/` now contains only model-server risk/Forecast policies. Backend input
indexes and manifest/scaler copies ship separately in `apps/backend/config/`;
no `deploy/` directory is needed on the backend machine.

## 3. Create and upload to Hugging Face

1. Visit [Create a Space](https://huggingface.co/new-space), choose owner/name,
   select **Gradio**, and select **Private** if source, weights and API should
   only be accessible to authorized accounts. A Public Space publishes uploaded
   weights and source as well as exposing the application.
2. Select CPU hardware initially; these native GraphSAGE models do not require
   CUDA. Measure latency before choosing GPU hardware. Account/plan eligibility
   and pricing are shown by Hugging Face when creating the Space.
3. Upload the **contents** of `deploy/.build/space/` in the Space's Files tab,
   preserving `packages/` and `bundles/` subdirectories. `README.md`, `app.py` and
   `requirements.txt` must sit at the Space repository root, not inside `space/`.
4. Commit the upload. The generated README configures `sdk: gradio`,
   `sdk_version: 6.30.0`, `python_version: "3.11"`, and `app_file: app.py`.
   Each commit automatically rebuilds/restarts the Space.

Alternatively, use the Hugging Face CLI from the existing uv environment:

```bash
uv pip install --python .venv/bin/python 'huggingface_hub>=1.16,<3'
.venv/bin/hf auth login
.venv/bin/hf upload OWNER/SPACE deploy/.build/space . --repo-type space
```

Create the Space first. Use a write token for upload. Upload only the prepared
folder; do not upload the whole project. No script in this directory publishes
anything automatically.

## 4. Space settings and startup

In **Settings -> Variables and secrets**:

| Name | Kind | Meaning |
|---|---|---|
| `INFERENCE_DEVICE` | Variable | Default `cpu`; `cuda` on dedicated CUDA hardware |
| `INFERENCE_API_KEY` | Secret | Optional shared key; callers send `X-Inference-Key` |
| `GRADIO_ANALYTICS_ENABLED` | Variable | Defaults to `False` in the entrypoint |
| `MODEL_CONFIG` | Variable | Normally omit; uses the uploaded `models.json` |
| `RISK_POLICY_PATH` | Variable | Normally omit; uses uploaded risk policies |
| `FORECAST_POLICY_PATH` | Variable | Normally omit; uses uploaded Forecast policy |

The server binds `0.0.0.0:7860`. It needs no Etherscan/RPC credentials, external
model repository or database. Bundles are uploaded with the runtime. Run one
process/replica initially. This implementation supports CPU and ordinary dedicated
GPU Spaces; it does not configure ZeroGPU's `spaces.GPU` lifecycle/authentication.
Release download/extraction happens before upload. The running Space reads the
packaged bundle copies; it does not fetch GitHub assets on every startup and
needs no GitHub token.

For a public Space, set the shared key to restrict inference calls. It does not
hide public source or weights; use a Private Space for that. Private Spaces
require an authorized HF read token. If both protections are enabled, send both
`Authorization: Bearer <HF read token>` and `X-Inference-Key: <shared key>`.

Wait for the Space to show **Running**. Build logs show dependency installation;
runtime logs show port 7860. A configured missing/corrupt bundle fails startup.
Omitted tasks remain unavailable without preventing configured models from loading.

## 5. Verify the deployed service

Use the direct application URL shown by the Space, e.g.
`https://OWNER-SPACE.hf.space`, not its `huggingface.co/spaces/...` web page.

```bash
curl --fail https://OWNER-SPACE.hf.space/health/live
curl --fail https://OWNER-SPACE.hf.space/health/ready
curl --fail https://OWNER-SPACE.hf.space/models
```

For a Private Space and/or configured shared key, add the appropriate headers:

```bash
curl --fail \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "X-Inference-Key: $INFERENCE_API_KEY" \
  https://OWNER-SPACE.hf.space/models
```

`/health/ready` lists successfully loaded tasks. `/models` reports availability,
identity, recipe, features, scaler checksum, decision threshold and calibration.
Liveness and the root service description are public at the application layer;
Hugging Face still protects an entire Private Space.

Use a saved compatible backend packet to test an actual prediction, for example
`.runtime/eth-artifacts/<analysis-id>/model_inputs/<task>-<hash>.json`. Actual
input packets are not included in the public deployment package. For Forecast,
a label-free row of the Task A `graphs.jsonl` wrapped as
`{"task_id": "continued_activity", "sample_id": "...", "graph_sample": <row>}`
is also a valid real input.

```bash
curl --fail --max-time 180 \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $HF_TOKEN" \
  -H "X-Inference-Key: $INFERENCE_API_KEY" \
  --data-binary @/absolute/path/to/model-input.json \
  https://OWNER-SPACE.hf.space/predict
```

Omit authentication headers for an unprotected public Space. The automated check
uses the Python standard library and reads the same authentication
variables without displaying them:

```bash
.venv/bin/python checks/serving/verify_service.py \
  https://OWNER-SPACE.hf.space --payload /absolute/path/to/model-input.json
```

This checks health, pinned model identities and all six recorded regression
packets. `--payload` additionally replays a supplied model input with identity
and returned-label checks.
Cold starts may take longer; adjust `--timeout` (default 180 seconds).

## 6. Calling the API

The minimal `POST /predict` JSON body contains `task_id` and `graph_sample`.
`graph_sample` must be the complete canonical **unscaled model graph**, not the
cropped display graph. Existing full ETH/token packets are accepted. Supplied
protocol/model/scaler/recipe/feature/sample/target/cutoff metadata must match the
loaded bundle and graph. The already-scaled `inputs` field is ignored:
`predict_bundle` applies the training scaler to the canonical graph exactly once.
Tensor-only requests are not supported.

Forecast requests send the backend's `forecast-wallet-observations-1` packet:
`task_id: continued_activity`, `sample_id`, and the unscaled first-week wallet
graph from `scripts.build_wallet_graph.wallet_graph_for_target` as
`graph_sample` (full 18/11-feature or pruned 15/9-feature schema; the model's
columns are selected by name). Supplied `target`/`cutoff` must match the graph.
`model_version` and `scaler_sha256`, when supplied, must match the loaded
bundle. The backend sends those exact identities; the old temporary Forecast
marker is no longer accepted.

A scored response includes `task_id`, `sample_id`, `target`, `cutoff`, `status`,
`score`, `label`, `model_version`, `result_origin: model`, `decision`, `calibration`,
`threshold`, `scaler_sha256`, graph quality and score meaning. The existing
model-bound `risk_band` and `risk_band_policy_version` are also returned.
Labels are `Low Risk`, `Medium Risk` or `High Risk` for Scam. Forecast's contract
uses `Continued activity` / `Low volume`, with matching `decision` and `forecast`
semantics and no Scam risk band. The service holds all decision thresholds.
Unscored responses have no label. Uncalibrated screening scores are not
probabilities of fraud.

| REST outcome | HTTP | Result |
|---|---:|---|
| Valid usable graph | 200 | Real score, `status: ok` |
| Valid but unusable graph | 200 | null score; inspect quality/status |
| Invalid JSON, graph or identity | 422 | Validation failure |
| Missing task model / Forecast | 503 | `model_unavailable`, null score |
| Busy | 429 | null score, `Retry-After: 2` |
| Invalid/missing shared key | 401 | No inference |
| Request body over 16 MiB | 413 | No inference |
| Model execution failure | 500 | `model_error`, null score |

The queued Gradio endpoint is also named `/predict`:

```python
import json
import os
from gradio_client import Client

client = Client(
    "https://OWNER-SPACE.hf.space",
    token=os.getenv("HF_TOKEN"),
    headers={"X-Inference-Key": os.environ["INFERENCE_API_KEY"]}
        if os.getenv("INFERENCE_API_KEY") else {},
)
with open("/absolute/path/to/model-input.json") as handle:
    payload = json.load(handle)
result = client.predict(payload=payload, api_name="/predict")
print(result)
```

Use `submit()` for background jobs/queue status. Gradio handles its two-step
call/SSE protocol; inspect the returned dictionary's `status`, since its errors
are not REST HTTP status codes. The Gradio endpoint queues one call at a time.
REST runs directly; both share a process-wide model lock, so overlapping work
gets a busy result rather than executing multiple models simultaneously.

The backend's `ANALYSIS_MODE=eth_live` uses authenticated REST requests with a
180-second timeout for cold starts, bounded retries for busy responses and strict
sample/model/scaler identity validation. It persists and displays the returned
score and label without loading deployment policies. Failed requests remain
unscored. Production mock/demo scoring and its configuration switches have been
removed; there is no fabricated fallback. Configure the same `INFERENCE_API_KEY` on
both machines; see [MODAL.md](MODAL.md) and the
[backend setup](../apps/backend/README.md).

## 7. Local uv environment and tests

Use the existing `.venv` and add Gradio through uv, as requested. This does not
change root `pyproject.toml` or `uv.lock`; deployment requirements are kept here.
A later `uv sync --frozen` without a Gradio extra may remove this extra package;
rerun the installation when needed.

```bash
uv pip install --python .venv/bin/python -r deploy/inference_service/requirements.txt
MODEL_CONFIG=deploy/.build/release-models/models.json \
  .venv/bin/python deploy/inference_service/app.py
```

In another terminal, run `checks/serving/verify_service.py http://127.0.0.1:7860 --payload ...` using that
environment. Stop the server with Ctrl-C. Retain the existing environment and
Gradio after testing; no cleanup/delete command is required.

The full regression suite uses the original local training bundles selected by
`inference_service/models.json`, or the downloaded Release bundles through
`TEST_MODEL_CONFIG`. `TEST_FORECAST_GRAPHS` optionally selects research wallet graphs; otherwise the
checks use saved real Forecast packets when present:

```bash
TEST_MODEL_CONFIG=deploy/.build/release-models/models.json \
GRADIO_ANALYTICS_ENABLED=False .venv/bin/python \
  checks/run.py --suite serving -v
```

## Updates and operation

To adopt a new Release, download its explicit tag, verify/extract its assets and
update the temporary bundle mapping. Model identities must still match input
metadata and risk policies; do not bypass those checks for different weights.
Commit a newly prepared folder to update a Space. Preserve the previous Space
commit for rollback and keep backend input metadata matched to that bundle.
Do not overwrite historical training artifacts or add runtime version routing.

Idle/free hardware can sleep; its first request can include a cold start. Choose
always-running paid hardware if needed. HF authentication/startup failures may
occur before the application can return JSON. Local disk is ephemeral; weights
are reloaded from the Space repository on restart. The inference service stores
no jobs/results. Deployment does not establish additional model-quality claims.
Forecast v0.2.0 was retrained without historical USD node/edge features; it
selects the 14 node and 8 edge columns by name from the full live graph schema.
Missing historical USD is retained as missing in observations; no price
substitution is used. The released validation threshold is 0.5369952122370402.


References: [Gradio Server Mode](https://www.gradio.app/guides/server-mode),
[Spaces configuration](https://huggingface.co/docs/hub/spaces-config-reference),
[Spaces overview](https://huggingface.co/docs/hub/spaces-overview).
