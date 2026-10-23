# Task B codebase extension and Vue/FastAPI serving plan

Design date: 2026-10-08; implementation update: 2026-10-15. Task B data pipelines
and offline training code are implemented for all four tasks. Honeypot/Rug Pull
use the versioned [token training pipeline](TOKEN_SCAM_TRAINING_PIPELINE.md). Only synthetic engineering checks have run;
no real training dataset, formal training or online service is delivered.

The earlier layout migration created deployment responsibility guides and moved
the Vue reference to `apps/frontend/`. Runnable commands are in the
[implementation guide](TASK_B_IMPLEMENTATION.md) and
[Task B README](../research/task_b/README.md). Website services, the Task A checkpoint adapter and historical simulation
remain future work; the shared package and Task B offline entrypoint now exist.
The website design was revised on 2026-10-12: [WEBSITE_ARCHITECTURE.md](../apps/docs/WEBSITE_ARCHITECTURE.md)
supersedes the unimplemented Nuxt/Nitro plan with Vue/Vite, modular FastAPI,
separate analysis/feed workers and replaceable theme/icon adapters. This is an
application architecture contract revision, not an implemented service or a
change to research model definitions.

This plan follows the [project contract](../CONTRACT.md),
[scam contract](SCAM_TASK_CONTRACT.md),
[platform guide](PLATFORM_ENGINEERING_AND_DATA_GUIDE.md) and earlier Canvas and
repository-structure reviews. It refines code/service boundaries without changing
Task A labels, windows, splits or historical experiments. Rug Pull is formally
included, initially limited to malicious Ethereum Uniswap v2 liquidity withdrawal.
Real data and model performance remain unvalidated.

Website skeleton update: the legacy frontend has been removed and replaced
with empty panels/routes, and `apps/backend/` contains a runnable FastAPI shell
plus class/method templates. Real integration remains future work. See
[template development](../apps/docs/TEMPLATE_DEVELOPMENT.md).

## 1. Boundaries established by the existing code

- `scripts/train_graphsage.py` combines MeanSAGE, conversion, training, threshold
  selection and evaluation with fixed `low_volume_dead/continued_activity` labels.
- `graph_tensor()` requires a valid label; `batch_graph_tensors()` assumes the
  first node is root. Evaluation cannot directly serve label-free prediction.
- MeanSAGE consumes node features and adjacency, not stored edge attributes.
  Two layers and a binary root head are specific model choices, not universal rules.
- Checkpoints store state, architecture, mean/std and a native threshold, but
  lack complete graph/feature schemas and provenance. Export must explicitly
  choose and record any separately calibrated threshold.
- `build_wallet_graph.py` builds Task A wallet/pool/token graphs, not address
  funds, calls or LP ownership graphs.
- The Vue reference uses Vite/Vue Router, fixed addresses, timers and result pages.
  Reviewed paths show no real fetch/axios inference calls; live pages also redirect.
- At design review, Git ignore rules excluded tests, dependency/lock definitions,
  `config/*`, data and environments. Targeted exceptions and `git check-ignore`
  are needed; the implemented release now tracks its new configurations and checks.

## 2. Additive layout beside existing research entrypoints

The following is the broader design, not a claim that all components exist.
The release uses flat strategy modules in `packages/chainrisk/`, root
`pyproject.toml`/`uv.lock`, and `research/task_b/cli.py`; application/service paths
below remain future work.

```text
ds-crypto-project/
  scripts/                       # Preserve Task A and Slurm entrypoints
  sql/ config/model_split.json   # Preserve Task A contracts
  packages/chainrisk/             # Installable shared research/inference package
    graph/                       # Protocol, validation, batching, label-free tensors
    models/                      # MeanSAGE, directed/relational SAGE, readout/head
    tasks/
      token_activity/            # Future legacy compatibility adapter
      phishing/
      ponzi/
      honeypot/
      rug_pull/
    prediction/                  # Bundle loading, prediction, statuses/evidence
  research/task_b/
    datasets/                    # Source adapters/admission, not large raw datasets
    configs/                     # Task graph/model/loss/split/evaluation settings
    train.py evaluate.py export.py
  pyproject.toml uv.lock         # Existing shared local uv environment
  apps/
    frontend/                    # Vue/Vite application reconstruction
      src/                       # pages, composed panels, API and presenters
        design/                  # semantic tokens/themes/icon mapping
        components/ui/           # replaceable app UI primitives
    backend/                     # Future FastAPI application source
      app/                       # routes, orchestration, adapters and workers
  deploy/                        # Service launch/container/proxy responsibilities
    inference_service/           # Optional later isolated predictor
    worker/                      # Analysis/feed worker deployment
    registry/                    # Approved manifests and read-only bundle mounts
    requirements.lock Dockerfile compose.yaml
  checks/                        # Tracked compatibility and isolation checks
  reports/task_b/<task>/<run>/
  data/task_b/<task>/<snapshot>/  # Ignored raw/normalized/graph/label artifacts
```

Vue Router handles SPA routes in the frontend. Vite build output is statically
hosted; the same-origin API is provided by FastAPI, not a frontend server.
The directory examples are target responsibilities, not newly created code.

Deployment owns service entrypoints and operations; the shared package owns
models, deterministic feature conversion and prediction. Services should not
import research training entrypoints.

## 3. Multiple graph views and independent tasks

| Task | Sample and graph | Main evidence | Model/evidence boundary |
|---|---|---|---|
| Phishing | Role-specific address + cutoff; directed transfer/call neighborhood | ETH/ERC20 transfers and calls; optional approvals/DEX context | Root MeanSAGE and directed SAGE; role evidence separate |
| Ponzi | Contract + cutoff; receiving/paying participants | External/internal transfers, calls and historical contract evidence | Shared graph mechanics, independent labels/features/bundles; root or root+summary readout |
| Honeypot sell restriction | Token + cutoff; wallet/pool/token interactions and optional execution view | Swaps, transfers, receipts, state and future fixed-condition simulation | Graph screening and sell-restriction evidence separate |
| Rug Pull v2 | Token/pool + cutoff; wallets, pools, tokens, LP tokens and evidenced control | PairCreated/Mint/Burn/Sync/LP Transfer and outgoing funds | Data/initial graphs delivered; audited malicious-withdrawal evidence; models/simulation deferred |

Phishing/Ponzi share event parsing and local-graph mechanics without requiring
the same labels, features or weights. Honeypot/Rug Pull address different
mechanisms and do not automatically form one model.

Distinguish retrospective event identification, screening at cutoff and warnings
before an incident over a fixed horizon. Ordinary withdrawals, falling volume
or prices are not scam labels. In early warning, post-incident Burn, fund outflows
and reserve declines are label evidence, not inputs. V2 LP tokens and v3 positions
need separate ownership/liquidity parsers; v3 is outside this release.

Budgeted target-local graphs with root classification fit existing sample batching.
Public global-node graphs require a separate offline protocol. Static graphs
without address/time mappings cannot be presented as address-query services.
Global training needs its own sampling and isolation contract.

## 4. A shared container, not one mandatory tensor layout

Shared metadata includes task/sample/target/chain, cutoff and observation start,
source snapshots, feature/graph versions, quality and lineage. Supervision and
partitions remain separate; inference does not require labels.

- Homogeneous view: `x, edge_index, root_index`, optional roles/relations/attributes.
- Heterogeneous view: `x_dict, edge_index_dict, root_type, root_index`, with
  per-type features and normalization.
- Multiple views: funds, DEX and execution features through explicit fusion,
  only when supported by data.

Adapters declare consumed fields. Stored amounts/time are not automatically
model inputs; untyped bidirectional edges lose incoming/outgoing distinctions.
New roots are explicit; the future Task A compatibility adapter preserves root=0.

Standard SAGEConv does not directly consume arbitrary edge attributes. Relations
can use separate aggregators or HeteroConv; amount/time messages need explicit,
tested functions. [SAGEConv](https://pytorch-geometric.readthedocs.io/en/latest/generated/torch_geometric.nn.conv.SAGEConv.html),
[HeteroConv](https://pytorch-geometric.readthedocs.io/en/latest/generated/torch_geometric.nn.conv.HeteroConv.html)

This release uses native PyTorch MeanSAGE and directed/edge-aware SAGE, without
PyG. Dependencies are added to existing root `pyproject.toml`/`uv.lock` on Mac
arm64 Python 3.11. Original Task A scripts and historical remote environments
are not rewritten.

## 5. Training, loss, evaluation and prediction

Share seeds/devices, optimization, checkpoints, logging, metrics and export.
Task specifications and registries choose strategies rather than duplicating
complete trainers:

```text
TaskSpec = dataset_adapter + graph_view + feature_schema
         + backbone + readout + head + loss
         + split_policy + evaluation_policy + output_semantics
```

The CLI implements `train --task phishing ...` and
`evaluate --task phishing --bundle ... --splits ...`. Dry runs are checked;
formal training and real performance are unvalidated.

- Backbone: two-layer MeanSAGE baseline, independent directed/relational,
  heterogeneous or fused-view experiments as needed.
- Readout: root, root+summary or target-type pooling with explicit entity meaning.
- Loss: independent binary BCEWithLogitsLoss with train-only weights; optional
  Focal. Unknown multi-label targets require masks, never zeros. PU risk
  estimation needs separate assumptions and admission.
- Evaluation: shared AP, ROC-AUC, precision, recall, macro-F1, FPR and Precision@K;
  independent positives, samples, splits, thresholds and calibration. Validation
  AP checkpoint selection is explicitly configured rather than inherited from Task A.
- Honeypot: future simulation coverage, ambiguity/abstention and independent
  evidence agreement. Rug early warning: lead time, fixed-horizon recall and
  alert burden, reported separately from retrospective detection.
- Prediction: no labels or training split; score, class, status and evidence,
  without accuracy. Evaluation joins frozen predictions to supervision.

Repeated target snapshots stay in one group. Audit clones, known campaigns and
cross-task overlap. Later cohorts test deployment applicability. Unknown-negative
and sampling-prevalence limitations accompany metrics.

## 6. Shared implementations, isolated state

```text
research/task_b -> packages/chainrisk <- apps/backend analysis worker
                         ^
            Future Task A legacy adapter

apps/frontend -> HTTP -> apps/backend FastAPI -> persisted jobs/results
Optional later inference HTTP service uses the same chainrisk runtime.
```

Inference resolves requests, checks quality, builds cutoff-bounded inputs,
validates schemas, loads frozen scalers, runs `eval()`/`inference_mode()`, applies
the approved threshold and returns results.

Future services load/cache models at startup rather than per request. Training
and inference have separate memory/concurrency budgets. Services do not contain
optimizers, scaler fitting or threshold reselection and do not write research
data. Slow collection/simulation can return a worker job id.

Bundles contain architecture/config, weights, ordered features/units/missingness,
graph view, scaler, positive meaning, threshold, calibration, training snapshot,
code/package versions and checksums. Registries point to approved read-only,
rollback-capable versions. Task A exports require the original input contract;
equal input dimensions are insufficient.

Preserve old training scripts until recovered real checkpoints can compare
scores on fixed graphs against a separate legacy adapter. Temporary duplication
must record provenance and compatibility version. Task B models remain defined
only in the shared package, not duplicated in services.

## 7. Vue/Vite and FastAPI service responsibilities

The authoritative application blueprint is
[WEBSITE_ARCHITECTURE.md](../apps/docs/WEBSITE_ARCHITECTURE.md). It defines the selected page
contents, durable job lifecycle, graph/score identity, REST/SSE contracts,
provider/graph/model adapters, frontend composition and future theme/icon swaps.

```text
Vue/Vite SPA -> same-origin FastAPI -> durable jobs/results
                                        ^
                        analysis worker -> chainrisk and approved bundles
                        independent feed worker -> Ethereum RPC
```

The browser submits one analysis request and reads its state/artifacts. It does
not orchestrate individual provider/graph/predict calls. Worker input graphs are
persisted and used both for inference and a readable graph-display adapter.
Current-state enrichment is temporally separate from model input. Independent
per-task failures retain usable results. Source credentials and weights remain
server-side. Frozen models load once per inference process; training entrypoints
are not called by the web application.

Reconstruct Vue routes and shared panels; keep `/analyses/:id` for real state
rather than fixed addresses/timers. Theme tokens and semantic AppIcon mappings
separate appearance from task semantics. Demo fixtures remain explicit; missing
models return unavailable status and never silently substitute fixture scores.

The first deployment uses a modular API plus separate analysis/feed processes;
an extra HTTP inference service is optional. Legacy Task A adapters and accepted
limited Honeypot/v2 Rug training remain subject to their existing input/model
acceptance conditions. No new service has been implemented by this revision.

## 8. Phases and acceptance

| Phase | Change | Acceptance |
|---|---|---|
| P0 | Admit a real dataset; freeze graph/label/split/feature schemas and ignore exceptions | Parseable samples, explicit polarity/unknown/time semantics, tracked configs/locks |
| P1 | Shared package, label-free conversion, future Task A legacy predictor/export | Preserved entrypoints; matching checkpoint/graph scores within registered tolerance |
| P2 | Phishing data/graph/train/evaluate/predict pipeline | Matched tabular/graph samples; evaluation and unlabeled prediction agree |
| P3 | Vue/Vite reconstruction, typed APIs and theme/icon adapters | Independent build/run, explicit demo/unknown/failure states |
| P4 | FastAPI, durable jobs, registry, analysis/feed worker integration | One-time model loading and clear missing/history/timeout/partial states |
| P5 | Ponzi framework and Honeypot/v2 Rug data branches | Independent data cards/evidence; real training and token models need later acceptance |

P3 can proceed independently of P1/P2 data preparation. Establish one rigorous
trainable branch before attempting four model rewrites.

Isolation requires command, dependency, import, I/O and resource checks, not
directories alone. Test nonzero roots, batch offsets, empty edges, schema/order
mismatches, unlabeled prediction, quality failures and service partial failures.
Real Task A checkpoints/data are absent locally, so legacy compatibility and
real inference service claims cannot yet be verified.

## 9. Delivery boundary

Independent research entrypoints and the installable package avoid model drift
across graph/task variants. Task A scripts/results remain intact; its future
inference adapter needs compatibility evidence. Directory layout, model contracts
and isolation checks jointly define the additive extension.
