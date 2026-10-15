# Honeypot and Rug Pull offline training pipeline

Revision: 2026-10-15. All four Task B branches now have offline training,
evaluation, bundle export and label-free prediction code. This revision delivers
implementation and synthetic engineering checks, not real data, fitted research
weights, performance results or backend integration.

## Scope and model targets

Each task trains its own binary GraphSAGE model and returns an uncalibrated
pattern-screening score at a specified cutoff. Honeypot uses reviewed,
pair-specific sell-restriction evidence, including API-defined detections. Rug
Pull uses independently reviewed malicious Ethereum Uniswap v2 liquidity
withdrawal incidents and scoped negative observations. The model requires no
known label during prediction. An incident report is a training-label source,
not a prerequisite for querying an unknown token.

These are current/historical pattern classifications. No future incident horizon
is inferred from the word "prediction". There is no self-built buy/sell fork
simulator, universal rug classifier, all-chain pool discovery or v3 support.
Pool addresses are supplied in the offline cohort and verified automatically.
Automatic pool discovery for website inputs belongs to later service work.

The default model is `directed_edge_sage`; `mean_sage` remains a matched baseline.
The two tasks have separate weights, scalers, label meanings and thresholds.
Scalers fit train only; validation AP selects the checkpoint; validation macro-F1
selects the binary threshold. Three website risk bands and calibration remain
separate future policies.

## Input contracts

Every target contains `sample_id`, `task_id`, lowercase Ethereum `target`,
`chain_id: 1`, integer Unix `cutoff`, and a nonempty, duplicate-free `pools` list.
`verify-token-targets` additionally produces:

- `cutoff_block`, `end_block`, and the cutoff block hash;
- `token_metadata`: decimals, verified block and raw-response evidence reference;
- `pool_metadata`: pool, token0, token1, factory, verified block and evidence reference.

Verification queries `eth_chainId`, the historical block, pair getters and the
canonical factory's `getPair`. Calls use the cutoff block hash and require a
canonical state. The provider must support historical `eth_call` and EIP-1898
block-hash selectors. Failure never falls back to latest state. If no cutoff
block was supplied, Etherscan resolves the block before cutoff. Supplied block
numbers must be reviewed as the intended cutoff block. A frozen, reviewed
metadata snapshot with equivalent provenance can also be supplied directly.

The currently admitted factory is Ethereum Uniswap v2
`0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f`. Other factories require an explicit
scope/version extension. Decimals refer to the cutoff state; tokens whose amount
unit changes during the observation window need a separate input version.

## Label preparation

`capture-honeypot` captures `IsHoneypot` with explicit token, `chainID=1` and pair.
It stores raw responses, checksums and capture time in
`honeypot_snapshots.jsonl`, plus one-pair `detection_targets.jsonl` with cutoff
equal to capture time. It does not label an arbitrary old cutoff with today's
API response. Reusing the same capture directory replays its frozen captures;
use a new directory/sample identity for a new observation.

Copy the snapshots to a reviewed file and record `audit_decision: reviewed` only
after checking the source, token, chain, pair and detection. Preserve the raw
response and its checksum. Import with `--source honeypot_is`. Unreviewed results
remain temporally unresolved; absent/non-boolean results and failed negative
simulations remain unlabeled. An explicit positive with unsuccessful simulation
can be reviewed as other-source API evidence. API labels apply only at their
capture time and selected pair. The API reports no verified historical execution
block. API flags, risk levels, tax fields and labels never enter graph features.
Multiple pairs are separate Honeypot samples, grouped by token during splitting;
multi-pool labels require a separate explicit reviewed aggregation decision.

Import curated Rug Pull records with `--source rug_incidents` (JSONL or CSV).
Required common fields are `task_id`, `entity_id`, `chain_id`, `mapped_label`,
`label_status`, `role`, `audit_decision`, `valid_from`, `valid_to`,
`label_available_at`, `pool_addresses`, `evidence_ref`, and
`mechanism: malicious_liquidity_withdrawal_v2`. CSV `pool_addresses` is a JSON
array string. A positive also requires `incident_onset`, a transaction hash in
`incident_tx`, and `controller_evidence_ref`. It must apply at/after incident
onset. Reviewed negative records describe a bounded observation period; include
ordinary withdrawals in the negative cohort rather than treating every Burn as
fraud. TokenScout/CRPWarner imports remain evidence candidates until audited.

The existing `audited` adapter also accepts these pool/incident fields. Labels
must exactly match a target's selected pool scope and have a bounded valid period.
Conflicts, unknown roles, unreviewed decisions and mismatched times stay excluded.
API-defined negatives are not claims that the token is free of all scam types.

## Collection, graph and quality

The default window is `(cutoff-30 days, cutoff]`. Collection requires `getLogs`,
`txlist`, and `txlistinternal` for the target token and each selected pool, with
paging/range coverage and normalization audits. Amounts retain raw integers and
asset identity. Target decimals and canonical v2 LP decimals are applied by the
versioned graph adapter, while normalized raw facts remain independently saved.

`selected-token-pools-1.0` coverage binds the emitter list, verified metadata
digest, exact window, block bounds and each required source. It does not claim
complete histories of participating wallets. `neighborhood_history_complete`
remains false without blocking this explicitly smaller input scope. Missing
requests, pagination gaps, invalid events or mismatched metadata still block
training and prediction. Unknown values remain masked, never fake normal labels.

`token-v2-scoped-2.0` keeps all selected pools within the graph node budget and
prioritizes token/pool membership edges. Participation relations connect the
token to Transfer endpoints and pools to observed DEX event participants. They
do not assert ownership or attacker roles. Pool event endpoints may be routers;
buy/sell direction refers to the target asset entering/leaving the pool, not a
claim that Swap.sender is the beneficial owner.

The input contains 35 node features and 17 edge features. The original 20/11
features are extended with buy/sell event counts, target-asset DEX amounts,
Mint/Burn counts and amounts, LP flow counts/concentration, reserve drop summaries
and explicit missingness. Root/pool mechanism summaries use the admitted emitter
window before node/edge sampling; other base statistics and LP net flows retain
their sampled-subgraph scope. Reserve drops compare observed consecutive Sync
records within each pool, ordered by block and log identity. They are not USD
liquidity values. LP flow concentration is observed raw outgoing flow, not full
LP ownership. Complete wallet fund tracing and failed router sell attempts are
outside this emitter scope.

Ponzi/Phishing keep `scam-egonet-1.0` and their 20/11 input schema. Old descriptive
token graphs require rebuilding; matching tensor dimensions is insufficient.
Token bundle manifests freeze the new graph view, feature order, relation policy
and pool-preserving sampling recipe.

## Commands

Run from the repository root in the existing uv environment. These commands are
instructions for a subsequent data/training run; none ran on real data during
this implementation. Network commands require `--allow-network`.

For Honeypot, start from candidate targets with known selected pool addresses:

```bash
uv run --frozen chainrisk-task-b capture-honeypot --task honeypot --targets candidates.jsonl --output data/task_b/honeypot/evidence --allow-network
uv run --frozen chainrisk-task-b import-labels --task honeypot --source honeypot_is --input reviewed-honeypot-snapshots.jsonl --output honeypot-labels.jsonl
uv run --frozen chainrisk-task-b verify-token-targets --task honeypot --targets data/task_b/honeypot/evidence/detection_targets.jsonl --output data/task_b/honeypot/verification --allow-network
```

For Rug Pull, freeze reviewed incident/negative cutoffs and selected pools:

```bash
uv run --frozen chainrisk-task-b import-labels --task rug_pull --source rug_incidents --input reviewed-rug-incidents.jsonl --output rug-labels.jsonl
uv run --frozen chainrisk-task-b verify-token-targets --task rug_pull --targets rug-targets.jsonl --output data/task_b/rug_pull/verification --allow-network
```

Verification reads the server-only `ETHEREUM_RPC_URL`. Block lookup/chain
collection read `ETHERSCAN_API_KEY`. Honeypot optionally reads `HONEYPOT_API_KEY`
when required by the provider. Never pass credentials in target records or
committed settings. Keep verification, API evidence and chain snapshots in
separate directories so their raw request formats remain unambiguous.

Repeat the following with `rug_pull` and its reviewed label file:

```bash
uv run --frozen chainrisk-task-b collect --task honeypot --targets data/task_b/honeypot/verification/verified_targets.jsonl --output data/task_b/honeypot/chain --allow-network
uv run --frozen chainrisk-task-b prepare --task honeypot --events data/task_b/honeypot/chain/events.jsonl --targets data/task_b/honeypot/chain/targets_with_coverage.jsonl --input honeypot-labels.jsonl --output data/task_b/honeypot/dataset
uv run --frozen chainrisk-task-b train --task honeypot --graphs data/task_b/honeypot/dataset/graphs.jsonl --supervision data/task_b/honeypot/dataset/supervision.jsonl --splits data/task_b/honeypot/dataset/splits.jsonl --dry-run
uv run --frozen chainrisk-task-b train --task honeypot --graphs data/task_b/honeypot/dataset/graphs.jsonl --supervision data/task_b/honeypot/dataset/supervision.jsonl --splits data/task_b/honeypot/dataset/splits.jsonl --output data/task_b/honeypot/run
uv run --frozen chainrisk-task-b evaluate --task honeypot --graphs data/task_b/honeypot/dataset/graphs.jsonl --supervision data/task_b/honeypot/dataset/supervision.jsonl --splits data/task_b/honeypot/dataset/splits.jsonl --bundle data/task_b/honeypot/run/bundle --partition test --output data/task_b/honeypot/evaluation
uv run --frozen chainrisk-task-b export --task honeypot --run-dir data/task_b/honeypot/run --output data/task_b/honeypot/export
uv run --frozen chainrisk-task-b predict --task honeypot --graphs unknown-token-graphs.jsonl --bundle data/task_b/honeypot/export --output predictions.jsonl
```

`prepare` joins quality-approved graphs and reviewed labels, freezes the entity/
pool/evidence-group split, validates trainer admission without fitting, and saves
targets, graphs, supervision, splits and a checksum/count manifest. It keeps
excluded rows with reasons. Insufficient independent class support fails without
searching another split. `--training-as-of` enforces label availability. Every
command supports side-effect-free `--dry-run`; token preparation still requires
enough reviewed samples to validate a split. Prediction uses the frozen graph
recipe and needs no supervision file. Missing weights return `model_unavailable`.

## Verification and follow-up

Synthetic checks cover metadata verification/cache replay, source polarity and
unknowns, temporal/pool admission, collector-to-graph coverage, pair order,
DEX amounts, reserves, foreign/future events, label independence, pool retention,
group isolation, preparation, training dry-run, schema-aware scalers, bundle
roundtrips and frozen-model evaluation for both tasks. Test bundles contain
untrained synthetic smoke models and are created only in temporary directories.
They establish execution compatibility, not research accuracy.

Later work includes real cohort collection/review, formal model fitting and
evaluation, runtime resource measurements and admission, and backend adapters,
workers, persistence, website analytics and live input pool discovery.

Primary interface references: [Honeypot API](https://docs.honeypot.is/ishoneypot),
[Ethereum JSON-RPC](https://ethereum.org/developers/docs/apis/json-rpc/),
[Uniswap v2 Pair](https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2Pair.sol),
[Uniswap v2 ERC20](https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2ERC20.sol).
