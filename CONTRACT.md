# Project Contract

This is the short governing contract for the whole project. Detailed rules,
schemas, procedures, and run results live in the referenced documents.

## System scope revision: 2026-10-05

The project now combines Task A (token low-volume outcome prediction) and
Task B (classic scam-pattern screening) in a shared data, graph, evaluation,
and eventual serving platform. This is a scope and architecture contract
change; it does not relabel historical experiments or change Task A's
numerical outcome/window/split rules.

The adopted system design is
[SYSTEM_REQUIREMENTS_AND_ARCHITECTURE.md](docs/SYSTEM_REQUIREMENTS_AND_ARCHITECTURE.md).
Task B follows [SCAM_TASK_CONTRACT.md](docs/SCAM_TASK_CONTRACT.md).
Reference-method limitations are documented in
[TRXLLM_REFERENCE_REVIEW.md](docs/TRXLLM_REFERENCE_REVIEW.md).
Task B data and offline training code is implemented as described in
[the implementation guide](docs/TASK_B_IMPLEMENTATION.md). No real Task B
dataset, trained weights, performance results, or online services are released.

The engineering boundary is further specified in
[PLATFORM_ENGINEERING_AND_DATA_GUIDE.md](docs/PLATFORM_ENGINEERING_AND_DATA_GUIDE.md):
a common frontend/platform API routes to independently callable token and
scam backends. They share a versioned graph container and GraphSAGE framework,
not necessarily topology, feature semantics, scalers, or weights. Separate
deployment processes are optional; separate task interfaces, model packages,
data analyses and performance artifacts are required. Preserve historical
reports and keep online assessments distinct from offline benchmarks.

### System-wide rules

Documentation convention revised on 2026-10-09: project Markdown documentation
is written in English, with language-neutral filenames. The former `zh-CN`
guides have been translated and renamed, and their references updated. This
changes documentation language and naming, not task scope or historical results.

Implementation boundaries are further specified in
[TASK_B_CODEBASE_AND_SERVING_PLAN.md](docs/TASK_B_CODEBASE_AND_SERVING_PLAN.md)
(2026-10-08 codebase refinement): additive Task B research modules and a shared
Python runtime package. The website architecture revision adopted on 2026-10-12
is [WEBSITE_ARCHITECTURE.md](apps/docs/WEBSITE_ARCHITECTURE.md): reconstruct the Vue/Vite
frontend, use a modular FastAPI application, a separate analysis worker with
process-local model loading, and a separate single-owned homepage RPC feed.
This supersedes the unimplemented Nuxt/Nitro plan; a separate inference HTTP
process is optional when resources justify it. Theme tokens, UI primitives and
a semantic icon adapter allow later style/icon replacement. Preserve Task A
entrypoints and artifacts until checkpoint/input compatibility is verified.
The website templates are now implemented as recorded in
[TEMPLATE_DEVELOPMENT.md](apps/docs/TEMPLATE_DEVELOPMENT.md); collection, durable
jobs, model serving and the homepage stream remain unimplemented. The 2026-10-08 scope revision admits a fourth Task B
mechanism: Ethereum Uniswap v2 malicious liquidity withdrawal. Honeypot and
rug-pull are data-only branches in this release; their training and historical
execution simulation remain future work.

Task B uses `packages/chainrisk/`, `research/task_b/`, and `checks/`.
TaskSpec, source adapters, graph strategies, backbone and loss registries share
code without sharing task weights. The user-selected local environment is
the existing arm64 Python 3.11 `.venv`, managed by the root `pyproject.toml`
and `uv.lock`. Task A scripts and historical artifacts are preserved; its
previous remote environment is not silently migrated. This release is code
and synthetic engineering checks only: no real training data collection or
formal model training. Applications and deployment were excluded from that
offline release; the separate 2026-10-12 website scaffold supplies only empty
frontend and explicit unimplemented backend integration boundaries.

Repository layout adopted on 2026-10-08: user-facing projects live under
`apps/`; the reference Vue/Vite demo has moved to `apps/frontend/`.
`deploy/` contains documented placeholders for inference_service, worker
and registry. The old demo has been replaced by the Vue/Vite template, and `apps/backend/`
contains a runnable FastAPI shell plus class/method templates. Real model
serving and the homepage feed remain unimplemented. Deployment owns
operations; backend application logic will live in `apps/backend/`. These
design additions do not change Task A training entrypoints or experiment rules.

- Keep activity outcomes and scam labels separate. No inactivity-as-fraud
  mapping, unknown-as-benign mapping, or unvalidated universal risk score.
- Share event provenance and graph/experiment interfaces; version each task's
  entity, window, features, graph semantics, labels, split and model artifacts.
  Shared GraphSAGE code does not imply compatible checkpoints or shared weights.
- Exclude post-cutoff information from inputs. Distinguish event validity,
  external evidence availability, retrieval time, and label maturity.
- Preserve source disagreements and incomplete data. Independent evidence or
  mature outcomes are required for supervised labels; live collection alone
  is not supervised training data.
- Make unlabeled inference independent of training labels. Scores carry task,
  cutoff, quality, model version and calibration status; missing scores remain
  null with an explicit reason.
- Audit cross-task entity/campaign/time leakage before fitting shared weights
  or pretraining. Evaluate each task independently against matched baselines.
- Require data/model admission, later-cohort or prospective shadow evidence,
  operating measurements and rollback checks before broad live claims.
  Research and service readiness are separate acceptance decisions.

## Read first

- docs/GRAPH_WALLET_INPUT_CONTRACT.md: wallet-enriched graph input and
  participant-field rules.

- `GOAL.md`: purpose, scope, claims, and deliverables.
- `PLAN.md`: project stages, model sequence, leakage controls, and gates.
- `config/label_specification.json`: primary and sensitivity label rules.
- `config/event_schema.json`: normalized event fields and identifiers.
- `config/market_context_schema.json`: point-in-time market features.
- `config/model_split.json`: primary general split and evaluation rules.
- `docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`: candidate sampling and quotas.
- `docs/DATA_ENGINEERING_WORKFLOW.md`: Parquet, SQL, DuckDB, and data checks.
- `docs/WEEK1_GRAPH_VOLUME_LABELS.md`: label rationale and source evidence.

The label, event and market-context JSON specifications referenced above were
not present in this checkout at the scope review. Recover and version them
with experiment artifacts before claiming reproducibility; do not invent
their past contents. `config/model_split.json` remains the current Task A
split contract. The following sections govern Task A specifically.

## Task A non-negotiable rules

- The wallet-enriched graph is a versioned model-input revision. Its first
  graph is wallet --swap activity--> pool --contains--> target token, with one
  separate target-token graph per token. It requires cutoff-bounded swap
  participant fields; the existing pool-counterparty graph artifacts do not
  satisfy this input contract.

- Study Ethereum token contracts in a fixed, documented set of selected DEX
  pools; use one canonical row per token.
- Define `t0` from the earliest selected-pool creation, with the documented
  activity fallback. Use the first 7 days for features and the following
  complete 90 days for the primary outcome.
- `low_volume_dead` means selected-pool swap volume below USD 1,000;
  `continued_activity` means at least USD 1,000. Swaps alone count toward
  volume. Use historical positive `amountUSD`; do not backfill current prices.
- Mark incomplete or unreliable follow-up, pool scope, retrieval, timestamps,
  or USD evidence as `censored`. Never turn censored rows into a class or use
  them to fill a quota.
- Build candidates label-blind and retain selection probabilities and strata.
  After complete labels exist, use the complete eligible labeled population;
  do not require a fixed 50/50 development quota. Apply the general token-
  level split in `config/model_split.json`: 80% training, 10% validation, and
  10% test within each label and launch-period stratum, keeping overlap groups
  together. A prior 500/500 cohort is a historical pilot artifact, not the
  current sampling contract.
- The split is class-proportional, not a single global row split: with 1,000
  active and 1,000 dead rows, assign 800/800 to training, 100/100 to
  validation, and 100/100 to test, subject to overlap-group adjustments.
- Use only data available by the 7-day cutoff as model input. Follow-up events,
  outcomes, censoring fields, and post-cutoff market data are not features.
- Keep raw bundles, manifests, normalized Parquet tables, SQL/DuckDB outputs,
  outcomes, censoring, splits, features, graphs, and model artifacts auditable
  and traceable to source rows.

## Project flow

The data product and modelling stages must treat the wallet-enriched graph as
a new input version. It keeps the token-level labels and split, but requires
participant-field collection, wallet-pool aggregation, and a separate
leakage audit before it can produce results.

1. **Feasibility:** freeze sources, schemas, windows, labels, sampling, and
   evaluation; verify access, coverage, historical USD, and retrieval quality.
2. **Collection:** discover and screen candidates without labels, collect full
   histories, assign outcomes, and build sampling and split manifests.
3. **Data product:** follow `docs/DATA_ENGINEERING_WORKFLOW.md` to produce
   validated Parquet and DuckDB/SQL model tables.
4. **Modelling:** compare heuristics, market and token baselines, static
   GraphSAGE, and graph/token/market fusion on the same split.
5. **Delivery:** report metrics, figures, reproducibility details, limitations,
   and negative results.

Temporal GNNs and graph pretraining are optional explorations. They require a
separate data contract and leakage audit before being treated as results.

## Evaluation and release gate

Use the general token-level train, validation, and test partitions defined in
`config/model_split.json`. Audit duplicate or related launches and overlapping
graph neighborhoods. Fit transformations, thresholds, and calibration on
training/validation data only; keep the test partition locked until the final
evaluation. Report class support, dataset prevalence, average precision,
precision, recall, macro-F1, false-positive rate, `Precision@K`, and
sampling-weighted metrics where relevant. A chronological partition may be
reported as a secondary stress test when it has adequate class support.

Do not claim final GNN performance until completeness, censoring, source
limitations, class support, split support, and leakage checks pass. Every
released result must record source and retrieval date, code/configuration
versions, counts, uniqueness and time checks, split metadata, model inputs,
seeds, metrics, and resource use. Never expose `.env` secrets.
