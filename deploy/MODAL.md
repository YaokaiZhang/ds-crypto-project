# Deploy the model API on Modal

The Modal entrypoint starts the existing Gradio Server in a regular CPU/CUDA
container. Model loading, input validation and score/label responses are shared
with the Hugging Face deployment. The backend uses `ANALYSIS_MODE=eth_live` for authenticated real inference.
It requires only its own input configuration and credentials, without `deploy/`.

## 1. Authenticate the local client

```bash
uv pip install --python .venv/bin/python 'modal==1.6.2' python-dotenv
.venv/bin/python -m modal setup
```

Complete browser authorization and select the intended workspace. If setup has
already succeeded, continue to step 2. Keep the existing `.venv`; no agent-skill
installation is required to deploy this Python application.

In Modal Settings -> Usage & Billing, confirm the credits and configure your
spend limit. A $0 spend limit caps out-of-pocket charges after applicable credits;
the usage budget caps usage before credits. Limits apply to the workspace.

## 2. Download the five Release bundles and prepare the service

Follow sections 1 and 2 of [README.md](README.md) to download the five ZIPs plus
`SHA256SUMS` from the explicit `Models` Release, verify them and create
`deploy/.build/release-models/models.json`. Select all five tasks there, including
`continued_activity`. Then prepare a new Modal package:

```bash
.venv/bin/python deploy/inference_service/prepare.py \
  --config deploy/.build/release-models/models.json \
  --output deploy/.build/modal
```

The package includes only the inference runtime, dependencies, shared model
source, model bundles and server-owned labeling policies. No backend source,
provider keys or local Modal token configuration is included. `prepare.py` fails
for missing/corrupt bundles and never overwrites an existing output folder.
Use a new output directory when rebuilding, and set `MODAL_PACKAGE_DIR` to it.

`deploy/modal_app.py` uploads this prepared directory to `/srv/chainrisk` in the
image. Automatic source-directory mounting is disabled; the small server launcher
is serialized separately. Weights are baked into the image, so runtime requests
do not download Release assets or require GitHub credentials.

## 3. Create the API key Secret

Generate a local ignored environment file without printing the key. The file is
outside the directory uploaded in step 2:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import os
import secrets

path = Path('deploy/.build/modal.env')
path.parent.mkdir(parents=True, exist_ok=True)
with open(path, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
    handle.write('INFERENCE_API_KEY=' + secrets.token_hex(32) + '\n')
print('Created deploy/.build/modal.env; keep this key for the backend client.')
PY

.venv/bin/python -m modal secret create chainrisk-inference \
  --from-dotenv deploy/.build/modal.env
```

Reuse an existing `modal.env` instead of generating another key if already
created. If the remote Secret already exists, inspect it in the Modal dashboard;
do not overwrite it unless intentionally rotating the key for every client.
The service refuses to start without a nonempty `INFERENCE_API_KEY`.

## 4. Deploy

```bash
.venv/bin/python -m modal deploy deploy/modal_app.py
```

This command uploads the selected package, builds the Linux image and creates
the remote application. Image builds and invocations use Modal resources.
The deployment prints a persistent HTTPS URL ending in `.modal.run`.

Defaults:

| Setting | Value |
|---|---|
| Application | `chainrisk-inference` |
| GPU | None; CPU inference by default |
| CPU / RAM request | 1 physical core / 4096 MiB |
| Warm / maximum / buffer containers | 0 / 1 / 0 |
| Idle scale-down window | 30 seconds |
| Startup / request timeout | 180 seconds |
| HTTP concurrency | Up to 8 connections; the existing inference lock serializes model execution |
| Container port | 7860 |
| Authentication | Existing `X-Inference-Key` header |

The concurrency allowance permits health checks and Gradio SSE/client connections;
it does not make the models run eight predictions simultaneously. REST calls that
overlap model execution still receive the existing busy response.
Cold starts include importing PyTorch and loading the models. Idle warm time
before scale-down also consumes credits; `min_containers=0` does not make that
window free. The SDK setup/authentication step alone does not deploy this app.

Optional deployment overrides:

```bash
# Optional T4 deployment:
MODAL_GPU=T4 .venv/bin/python -m modal deploy deploy/modal_app.py

# L4 and/or a newly prepared package:
MODAL_GPU=L4 MODAL_PACKAGE_DIR=deploy/.build/modal-next \
  .venv/bin/python -m modal deploy deploy/modal_app.py
```

The choices are deliberately limited to CPU, T4 and L4 for the initial service.
There is no change to model weights, scalers or label thresholds when switching
hardware. Redeploy the same app to apply a configuration/package update.

## 5. Verify the URL

Use the URL printed by Modal as the base URL. Load the ignored local key file,
then run the existing service check:

```bash
set -a
. deploy/.build/modal.env
set +a

.venv/bin/python checks/serving/verify_service.py \
  https://YOUR-DEPLOYMENT.modal.run
```

The verifier checks all five models and replays all six committed regression
packets. To replay an additional compatible backend packet, add:

```bash
.venv/bin/python checks/serving/verify_service.py \
  https://YOUR-DEPLOYMENT.modal.run \
  --payload /absolute/path/to/model-input.json --timeout 180
```

Modal calls use the shared key, not `HF_TOKEN`. The verifier only attaches an
HF token to Hugging Face hosts, so it is not sent to Modal. Model files, labels and existing backend request/response
contracts are shared between hosting targets. Forecast v0.2.0 excludes historical
USD features and accepts the full live schema by selecting columns by name.

## 6. Connect the backend, including a VPS

`modal setup` stores a Modal management token in `~/.modal.toml`. It authenticates
SDK/CLI actions such as building images and deploying apps. It does not create or
inject the application-specific `INFERENCE_API_KEY`. This deployment explicitly
injects that separate key through the `chainrisk-inference` Modal Secret.

On the backend host configure the following server-only environment variables
for **both** API and analysis worker (or literal strings in the ignored
`apps/backend/local_secrets.py`):

```text
ANALYSIS_MODE=eth_live
INFERENCE_URL=https://YOUR-DEPLOYMENT.modal.run
INFERENCE_API_KEY=<same value as deploy/.build/modal.env>
INFERENCE_TIMEOUT=180
ETHEREUM_RPC_URL=<your provider URL>
ETHERSCAN_API_KEY=<your Etherscan key>
```

The settings module does not automatically source `.env` files. For local testing,
restart API and worker with `.venv/bin/python scripts/start-eth-live.py
--restart-backend`. On a VPS, give the variables to your process manager and run
the API plus `python -m apps.backend.app.workers.analysis`. Include
`apps/backend/config/`, shared `packages/` and required `scripts/` graph helpers.
Do not copy `deploy/`, model weights or the Modal management token to the VPS.
The shared inference key is never sent to the browser or written into input artifacts.

Check `/api/v1/health/ready` and `/api/v1/capabilities`: `mode=eth_live`,
`score_mode=model`, and five matching `model_available=true` entries. Metadata is
verified against backend-local model/scaler identities and cached for 60 seconds.
Cold starts can delay the first check. Model outcomes use model-version-bound caches. Mock/demo production scoring has
been removed; historical results remain preserved and unfinished legacy simulated
jobs cannot be resumed as real inference.

The URL stays deployed when the local terminal closes or the backend moves.
A request starts a container when scaled to zero; first use loads the baked-in
weights. No periodic keep-alive is needed. Idle time during the 30-second
scale-down window is billable.

## Verified deployment (2026-10-26)

- Workspace/app: `grand-austin` / `chainrisk-inference`.
- API: `https://grand-austin--chainrisk-inference-serve.us-east.modal.run`.
- Hardware: CPU, 1 physical core / 4096 MiB; no GPU.
- Five model bundles downloaded with both checksum layers verified.
- Real saved backend packets for every task scored through the backend remote
  adapter and matched local model scores within 1e-5, with matching labels.
- First metadata request including wake-up: about 16 seconds. Individual model
  requests: about 1.4–2.2 seconds including network and preprocessing; these are
  sample observations, not a latency guarantee.
- Missing application key: HTTP 401. All five models report ready.
- Local keys, downloaded weights and verification artifacts stay ignored under
  `deploy/.build/`; retain the existing uv/Gradio environment.

## Local verification

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  checks/run.py --suite serving -v
```

These checks declare the app with the local SDK and test package isolation and
the launcher without authenticating, uploading, creating Secrets or allocating
cloud compute. GPU availability and actual cold-start latency require a deployed
service test after downloading the real bundles.

References: [Modal web servers](https://modal.com/docs/sdk/py/latest/web_server),
[images](https://modal.com/docs/sdk/py/latest/Image),
[autoscaling](https://modal.com/docs/guide/scale),
[Secrets](https://modal.com/docs/guide/secrets),
[budgets](https://modal.com/docs/guide/budgets).
