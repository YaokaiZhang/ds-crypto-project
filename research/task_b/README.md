# Task B offline framework

This release implements code, versioned configurations and synthetic engineering
checks. It has not collected real training data, fitted a research model, or
released weights/performance results. Phishing and Ponzi have training pipelines;
Honeypot and Uniswap v2 liquidity rug pull are **data-only**.

## Environment and checks

Use the existing project uv environment on Apple Silicon, with Python 3.11:

```bash
cd /Users/austin/Documents/Courses/DS-Project/ds-crypto-project
uv sync --frozen --python 3.11
uv run --frozen python -m unittest discover -s checks -v
uv run --frozen chainrisk-task-b --help
```

The root `uv.lock` freezes dependencies. CPU is the reproducible default. Explicit
`--device mps` is supported when PyTorch reports MPS available; it fails clearly
otherwise. `auto` chooses an available device. Task A entrypoints and its
historical experiment artifacts are not migrated or relabeled.

## Synthetic preparation example (no training)

All fixture addresses, transactions and labels are invented, explicitly marked
synthetic, and unsuitable for research conclusions. Run the following for
`phishing`; repeat with `ponzi` for supervised task-specific labels.

```bash
uv run --frozen chainrisk-task-b normalize --task phishing --input checks/fixtures/task_b/raw_events.jsonl --output data/task_b/synthetic/events.jsonl
uv run --frozen chainrisk-task-b import-labels --task phishing --source audited --input checks/fixtures/task_b/audited_labels.csv --output data/task_b/synthetic/phishing-labels.jsonl
uv run --frozen chainrisk-task-b label --task phishing --input data/task_b/synthetic/phishing-labels.jsonl --targets checks/fixtures/task_b/targets.jsonl --output data/task_b/synthetic/phishing-supervision.jsonl
uv run --frozen chainrisk-task-b build-graphs --task phishing --events data/task_b/synthetic/events.jsonl --targets checks/fixtures/task_b/targets.jsonl --output data/task_b/synthetic/phishing-graphs.jsonl
uv run --frozen chainrisk-task-b split --task phishing --supervision data/task_b/synthetic/phishing-supervision.jsonl --output data/task_b/synthetic/phishing-splits.jsonl
uv run --frozen chainrisk-task-b train --task phishing --graphs data/task_b/synthetic/phishing-graphs.jsonl --supervision data/task_b/synthetic/phishing-supervision.jsonl --splits data/task_b/synthetic/phishing-splits.jsonl --dry-run
uv run --frozen chainrisk-task-b predict --task phishing --graphs data/task_b/synthetic/phishing-graphs.jsonl --output data/task_b/synthetic/unavailable-predictions.jsonl
uv run --frozen chainrisk-task-b resolve-transaction --input checks/fixtures/task_b/transaction.json
uv run --frozen chainrisk-task-b train --task honeypot
```

The last training command returns `data_only`. Prediction without a bundle returns
`model_unavailable` and null scores; it never fabricates demo output. Transaction
resolution returns related entities and candidate tasks, not a transaction score.
All commands support `--dry-run` without output writes or network requests.

## Real data preparation (future user execution)

A targets JSONL record requires `sample_id`, `task_id`, Ethereum `target`, integer
Unix `cutoff`, and `chain_id=1`. Token tasks additionally require verified v2 pool
addresses in `pools`. Choose a historical cutoff applicable to the source label;
old incident lists do not establish a valid present-day positive sample.

```bash
uv run --frozen chainrisk-task-b collect --task ponzi --targets targets.jsonl --output data/task_b/ponzi/snapshot --dry-run
# Set ETHERSCAN_API_KEY in the process environment before explicit collection.
uv run --frozen chainrisk-task-b collect --task ponzi --targets targets.jsonl --output data/task_b/ponzi/snapshot --allow-network
uv run --frozen chainrisk-task-b build-graphs --task ponzi --events data/task_b/ponzi/snapshot/events.jsonl --targets data/task_b/ponzi/snapshot/targets_with_coverage.jsonl --output data/task_b/ponzi/graphs.jsonl
```

Etherscan external/internal address histories are the ETH mainline. Complete call
trees are not claimed. `tokentx` is opt-in; missing log identities require receipts.
The default graph is 30 days, 2 hops, fanouts 32/16, 512 nodes, 4096 aggregate
edges. Root and selected first-hop histories are collected; boundary-node
statistics describe the sampled observed subgraph. Request gaps fail coverage;
intentional graph-budget sampling is separately recorded. Token collection covers
the target and explicit pools, with limitations recorded; it is not a trained
Honeypot/Rug detector or a historical fork simulator.

Token collection also includes external/internal ETH histories for the token
and selected pools to preserve outgoing funds. Optional target `factories`
collect factory logs, including window-bounded PairCreated; this does not perform
all-chain pool discovery. Verified target `pools` and `pool_evidence_ref` preserve
membership when creation predates the window. Historical target-token transfers
connect wallets via a separate `participates` relation, never an ownership or
maliciousness assertion. LP balances remain unknown; observed raw net flows are
stored separately with their sampled scope.

Raw responses/cache checksums, coverage, normalization audits, normalized events,
and targets are saved separately. Graph construction automatically reads adjacent
normalization audits; use `--audit PATH` for a nonstandard audit location. JSONL
and `.parquet` output are supported; Parquet includes lossless record JSON for
heterogeneous nested lineage.

## Evidence and supervision

Local adapters: `forta`, `xblock_ponzi` (CSV or ZIP), `unica`, `tokenscout`
(`--mapping token-dict.json`), `crpwarner` (XLSX/CSV), `xblock_phishing`, `audited`.
They import source evidence without automatically approving unknown roles/time.
See [source_catalog.json](source_catalog.json) for schemas, source links and admission limitations.

An audited CSV contains `task_id,entity_id,mapped_label,label_status,role,
audit_decision,valid_from,valid_to,label_available_at,evidence_ref`. Valid times
are Unix seconds or timezone-aware ISO strings. A reviewed positive/negative
must have matching polarity, task role and period; evidence conflicts stay
disputed. All source records and their checksums remain auditable.

Phishing defaults to `known_positive_vs_unlabeled`: an unlabeled background must
have explicit `data_eligible=true`, `background_selected=true`, and a frozen
`cohort_id`. Canonical unknown labels remain unknown; only experiment records
receive `observed_target=0`. P/U scores and metrics describe that selected
benchmark, not population false-positive rate or verified benignness.

Repeated entities stay together. Verified campaign groups need `group_verified`
and `group_ref`/`group_evidence_ref`; common routers alone do not define groups.
80/10/10 class support is mandatory; insufficient support fails without trying
favorable seeds. `--training-as-of` enforces label-availability time.

## Future training, evaluation and export

After independent real-data admission, supply the frozen artifacts:

```bash
uv run --frozen chainrisk-task-b train --task ponzi --graphs graphs.jsonl --supervision supervision.jsonl --splits splits.jsonl --architecture directed_edge_sage --loss focal --device cpu --output data/task_b/ponzi/run
uv run --frozen chainrisk-task-b evaluate --task ponzi --graphs graphs.jsonl --supervision supervision.jsonl --splits splits.jsonl --bundle data/task_b/ponzi/run/bundle --partition test --output data/task_b/ponzi/evaluation
uv run --frozen chainrisk-task-b export --task ponzi --run-dir data/task_b/ponzi/run --output data/task_b/ponzi/exported-bundle
uv run --frozen chainrisk-task-b predict --task ponzi --graphs unlabeled-graphs.jsonl --bundle data/task_b/ponzi/exported-bundle --output predictions.jsonl
```

These commands are provided, not executed in this release. `train` validates
quality, sample/entity/cutoff joins and frozen split isolation, fits scalers only
on train, selects checkpoint by validation AP and threshold by validation
macro-F1, then reports the locked test. The model bundle freezes task, feature
order, graph recipe, relation semantics, consumed inputs, scaler and checksums.
The model version digest covers the entire manifest including weight/scaler
checksums, threshold and score semantics. Evaluation uses the bundle's frozen
configuration and rejects a different graph recipe; it never selects a threshold.
Export refuses overwrites. Test evaluation is an explicit operation and must not
be repeatedly used to choose models.

`experiment_matrix.json` records MeanSAGE, directed-edge SAGE, focal and depth/
direction/relation/edge-attribute comparisons. It does not run a parameter sweep.
Own-feature Logistic Regression and neighborhood/edge-summary gradient boosting
use the same eligible samples and split. nnPU/shared pretraining remain deferred.

Verification on 2026-10-09: 74 synthetic checks passed in the existing frozen uv
environment (Python 3.11.16, arm64, PyTorch 2.14.1), including CLI integration,
auto-device resolution, missing weights and frozen-recipe rejection. Numerical
checks used CPU; MPS performance and research model quality are unvalidated.

## Architecture

`TaskSpec` is an immutable registry entry. `SourceAdapter` imports evidence;
`GraphBuilder` chooses relation/topology policy; backbone/loss factories choose
model strategies. CLI handlers orchestrate I/O and call these components; they
do not define fraud truth or duplicate model implementations. Add a mechanism
by registering its task specification, audited source mapping, graph policy and
configuration. Data-only tasks cannot be enabled by merely changing a CLI flag.

The implementation guide is
[`TASK_B_IMPLEMENTATION.md`](../../docs/TASK_B_IMPLEMENTATION.md).
