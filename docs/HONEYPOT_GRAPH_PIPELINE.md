# Honeypot combined graph and training pipeline

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

2026-10-23 diagnostic follow-up: see the offline analysis under
`reports/honeypot/trapdoor-api-v1/all-recent-v1/graph-audit-v1/FINDINGS_zh.md`.
The saved epoch-2 AP is 0.9995396239664611 (not exactly 1); epoch 27 stopped
under the existing patience/min_delta rule. Subsequent progress reports retain
six decimal places. No model, label, split or training-policy revision occurred.
The audit includes source-specific metrics, trivial tabular baselines, source
transfer, a shuffled-label control and partition/scaler checks. These reuse
the selected validation set and are exploratory, not an independent test.

Revision: 2026-10-21. The user adopted both source cohorts for a retrospective
supervised experiment. This supersedes the earlier graph-only/no-admission limit.
The original evidence files remain unchanged. Workspace cleanup on 2026-10-23
removed the unused api-recent-v1 plan and contemporary/historical pilot runs;
the retained training dataset uses all-recent-v1.

## Time and population

Trapdoor positive and negative records use **2023-01-31 23:59:59 UTC**
(**1675209599**) as the common retrospective graph cutoff. This is our chosen
month-end convention, based on the paper's stated May 2020–January 2023 pool/token
coverage (https://arxiv.org/html/2309.04700v4, section 3.3). It is not an exact
source-supplied labeling date, per-token incident timestamp, or proof that the
label was already known. Historical valid_from/valid_to/label_available_at stay
null. Contemporary records use each frozen Honeypot.is checked_at; do not query
again merely because graph collection runs later.

The frozen all-recent-v1 plan has 2,553 historical token/pool records (1,922
positive pool records for 1,859 tokens; 631 negatives) plus 941 contemporary
records (206 positive, 735 negative), totaling 3,494 targets and 3,431 distinct
tokens. The 59 unknown API outcomes are excluded. These are source-defined
labels, not independently revalidated sell-restriction mechanisms. Training
reports must disclose different source years and class proportions; pooled
validation alone does not establish performance on either source separately.

Settings graph_selection selects cohort=both and the historical cutoff for new
plans. An existing frozen plan takes priority on resume. Explicit CLI options
can override defaults only when creating a new graph run. Plans pin exact targets,
pools, source/label hashes and graph budgets. Change these only with a new run.

## RPC and local credentials

An RPC URL is the HTTPS address of a hosted Ethereum node. The provider key is
usually embedded in that address. Etherscan supplies indexed account histories
and logs; the RPC performs read-only contract calls at the cutoff block to verify
decimals, pool token0/token1/factory, and factory.getPair. No wallet/private key,
transaction, or on-chain gas payment is needed. RPC provider quotas still apply.

Keep both credentials in Git-ignored local_secrets.py, with mode 0600:

```python
ETHERSCAN_API_KEY = "YOUR_EXISTING_KEY"
ETHEREUM_RPC_URL = "YOUR_ETHEREUM_MAINNET_HTTPS_RPC_URL"
```

Environment values override local values; an explicitly empty environment value
disables fallback. The loader reads string literals with ast, never executes the
file. URLs and credentials stay out of settings, manifests and reports. Select an
Ethereum **Mainnet** endpoint supporting historical state and EIP-1898 blockHash
with requireCanonical. There is no fallback to latest state. Current Alchemy
endpoint passed a real mainnet/historical/EIP-1898 check on 2026-10-21:

```bash
uv run --frozen python scripts/scam/check_rpc.py
```

The probe validates WETH decimals at historical block 16,500,000. Exact successful
requests are cached; later repetitions replay those captures. Per-target
verification still reads the actual cutoff block, rather than relying solely on
the probe. Missing capabilities/authentication/quota/integrity stop the run.

## Run all data, then train

From the repository root:

```bash
uv run --frozen python scripts/scam/run_pipeline.py \
  --task honeypot --snapshot trapdoor-api-v1 \
  --stage all --run NEW_RUN --graph-run all-recent-v1 \
  --graph-cohort both --historical-cutoff 2023-01-31T23:59:59Z \
  --settings data/scam/honeypot/trapdoor-api-v1/settings.json \
  --allow-network --progress on
```

all reuses frozen source/audit/discovery/API captures, then runs graph
plan -> verify -> collect -> build-graphs -> prepare-training. It does not
resample tokens or relabel them. Successful samples resume without HTTP. Both
cohorts run in one job with independent cutoffs; there are no replacement roots.
Finite-retry sample-local failures may be excluded, as authorized. Provider,
quota, cache-integrity and missing prerequisite failures cannot be dropped.
--strict-collection keeps local failures retryable instead. `collect` includes graph construction; `prepare` publishes the model dataset; `all` also fits the model.

After completion, explicitly fit an independent Honeypot model:

```bash
uv run --frozen python scripts/scam/run_pipeline.py \
  --task honeypot --snapshot trapdoor-api-v1 \
  --stage train --graph-run all-recent-v1 --run sage-v1 --progress on
```

Training validates pinned graph/evidence/outcome hashes first. The generated
training_config.json uses the actual frozen recent graph recipe. All eligible
source labels enter supervised training; unknowns never become negatives. The
split is class-stratified 90/10 train/validation, preserving token and selected
pool groups. Fit scalers/weights on train only. Validation AP controls checkpoint
selection/early stopping; validation is reused for threshold selection, so it is
not an independent test. Unknown historical validity/availability remain null;
training_as_of is null for this explicitly retrospective experiment. Source-based
admission is a user-adopted policy, not a claim of independent manual validation.

`--dry-run` plans without network or writes. A `--graph-limit` pilot must use its
own run name. Do not use it to truncate the frozen full run.

## Concurrency, collection and storage

Default collection.sample_workers=4 runs up to four roots concurrently, including
RPC verification. All Etherscan starts share one 2.5 request/second budget and
persistent 95,000-attempt rolling-24-hour accounting, including retries. RPC
requests share a separately paced client (default 3/second for graph verification)
and exact-request cache with per-key locks. Progress records all active roots.
One collector process per provider account remains the supported arrangement.

The token-v2-recent-1.0 view retains the token node/edge feature orders. It must
not mix with complete-window token-v2-scoped-2.0 graphs. From each cutoff, query
ordinary/internal records descending and logs newest block range first. Full log
ranges are split newest half first; full single-block results are paged before
selecting newest log identities. Validate timestamps, emitters, blocks and order.
Default: 100 records/action/emitter per round, at most three rounds; 32/16
neighbors, at most 512 nodes/4,096 edges. Stop at graph budget, source exhaustion,
or record budget. Sparse graphs need not fill caps. `complete` means this bounded
recipe, never lifetime completeness. API verdicts/scores/taxes are not features.

New successes publish lossless normalized events once as events.jsonl.gz under
data/shared/observations/ethereum/. Token observation identities include exact
selected pools, cutoff block hash, decimals, provider and graph recipe, preventing
accidental reuse of incompatible Phishing/Ponzi observations. Sample manifests
pin the shared manifest checksum. Only after this publication may successful
private collection/raw_requests and redundant local gzip be removed. Failed
scratch, original source/API evidence, and RPC verification evidence remain.
Shared raw Etherscan caches are never deleted. Back up shared observations with
the snapshot; a snapshot alone is not a portable replay archive.

## Outputs and status

Under data/scam/honeypot/trapdoor-api-v1/graph_runs/all-recent-v1/:

- plan.json, targets.jsonl, candidate_labels.jsonl, excluded_labels.jsonl.
- samples/ID/: verified_target.json, stage checksum records, graph.json,
  collection/target.json, coverage/audit and observation_ref.json. Fixture or
  legacy samples may retain one local events.jsonl.gz.
- verify/collect/build-graphs outcome indexes, graphs.jsonl, graph_manifest.json.
- rpc_cache/, progress.json with counts and all active roots.
- prepared/: targets, graphs, supervision, 90/10 splits, dataset_manifest.json,
  generated training_config.json; source/time provenance remains in supervision.
- model output: artifacts/scam/honeypot/trapdoor-api-v1/sage-v1/.

```bash
uv run --frozen python scripts/scam/run_pipeline.py \
  --task honeypot --snapshot trapdoor-api-v1 \
  --graph-run all-recent-v1 --stage status
```

Tests cover parallel shared budgets/clients, historical source anchoring,
per-token API cutoffs, log range ordering/overflow, fixture graph replay, shared
observation reuse/cleanup/integrity, failure exclusions, training admission,
token/pool split grouping, immutable prepared inputs and train dry-run dispatch.


## Network-interruption recovery and two-row terminal progress (2026-10-21)

The first full run completed all 3,494 cutoff-bound verifications, then stopped
at 2026-10-21 13:06:22 UTC (16:06 Helsinki) with a DNS resolution error. At exit,
124 collections had been published. Six legacy transport/cancellation exclusions
were incorrectly treated as bad roots; one separate normalization exclusion was
valid under the selected drop policy. The corrected pre-publication resume
archives the six original outcome files unchanged with a checksum recovery ledger
and retries them from cached scratch. No known source quality exclusion is reopened.

DNS/network-unreachable/reset/disconnect/timeouts receive finite per-request
retries and then propagate as a retryable provider batch error, never as bad
sample labels or data exclusions. The runner retries the graph batch (default
20 attempts with 30-second gaps), replaying existing sample manifests. An aborted
batch cancels other workers without excluding their roots and clears active
sample state. Authentication, quota and integrity failures still stop instead of
being repeatedly retried. If the attempt budget expires, repeat the same all
command after restoring connectivity; no replacement samples are selected.

Honeypot now uses the existing NestedSampleProgress component: outer row counts
processed roots (including frozen data exclusions); inner row follows the oldest
active sample's query count and phase. Log subdivisions and extra pages expand
the known query denominator dynamically, so it is not a promised fixed total.
The display does not serialize collection. Start in an actual terminal/PTY to
see the two fixed rows; redirected `--progress on` output deliberately uses
periodic plain summaries. All active roots remain in progress.json. The runner's
log wrapper forwards terminal geometry and keeps animations out of durable logs.
