# Rug Pull TokenScout label preparation

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

Adopted 2026-10-22. This is a source-defined retrospective label cohort, following
the user's completion-first labeling choice. Existing graph processing and
training recipes are unchanged. No transaction collection, graphs or training
are part of this preparation.

## Sources and label policy

Freeze these two author-provided files from the
[TokenScout public folder](https://drive.google.com/drive/folders/1smr3FJHqvaczzhRUMa1pl9sIKgn3PT3S):

- token_labels_processed.csv: `tokens,t1-labels,t2-labels`.
- token-dict.json: the published address-to-integer-ID dictionary; the adapter
  also accepts the inverse orientation and rejects ambiguous ID mappings.

Map t2 rugpull to 1 and truthworthy (the exact source spelling) to 0. Exclude
honeypot, ponzi and unknown subtypes. Normalize addresses; reject missing,
invalid, zero or ambiguous mappings. Collapse repeated same-label addresses and
exclude addresses with conflicting source classes. Source labels are not
independently validated incidents. Never invent incident transactions,
controller evidence, label validity dates or label availability times.

Audit the complete source files before selection. The latest user instruction
uses selection_stage=after_pool_verification, seed 20261022, SHA256 ranking,
exactly 1,500 metadata-valid positives and all metadata-valid negatives. Match
all source tokens to supported pools before imposing the positive cap. Keep a
frozen eligible order and per-round plans/outcomes; advance to the next positive
after a recorded token-metadata exclusion until 1,500 positives pass. Provider
failures never become exclusions. Workspace cleanup on 2026-10-23 removed the
superseded tokenscout-v1, tokenscout-all-v2-v1 and tokenscout-eligible-1500-v1
snapshots, retaining tokenscout-eligible-1500-v2 and its frozen source evidence.
Caps/stage changes require a new snapshot.

## Pool matching

Use the source dataset coverage end, 2023-02-28T23:59:59Z (1677628799), as a
retrospective pool-state anchor. This is not the incident time or labeling time.
Resolve its block through Etherscan and pin the RPC header/hash. Factory getPair
and pool getters validate selected identities at that hash, with requireCanonical.
The initial tokenscout-v1 snapshot used only WETH pairs. The user's same-day
follow-up expands new snapshots to all quote assets in official Uniswap v2.
Read only Factory PairCreated logs through the cutoff to build the pool identity
index; verify contiguous pair sequence and complete source coverage.
The index uses four independent block-range workers under the existing shared
Etherscan quota. Each range has at most ten 1,000-row pages before recursively
splitting blocks, respecting Etherscan's 10,000-result query window.
Match both token sides against the full cleaned source, then retain all memberships of the
selected tokens in pools/token_pool_matches.jsonl. Select one pool per token
using WETH, USDC, USDT, DAI quote priority, then earliest creation and address.
This also permits WETH itself as a target when paired with a different asset.
No-pair results mean no match on this Factory at this cutoff, not no pool on
other DEXes. New default scope is all_v2; legacy scope=weth stays replayable.

The legacy pair_getters mode uses existing verify_token_targets checks for token decimals, pair
token0/token1/factory, canonical Factory membership and historical block identity.
The provider must support historical EIP-1898 eth_call. No latest-state fallback
occurs. Small RPC batches (default 20 calls, 0.5 HTTP starts/second) populate the
standard SnapshotClient single-call cache; the existing verifier replays those
exact responses. Batches and successful single-call evidence retain hashes.
Provider/authentication/quota failures stop the stage; token decimals reverts or
invalid ABI can be recorded as sample exclusions. Honeypot.is is never queried.

The latest cohort uses verification_mode=factory_event_and_rpc. A complete,
verified canonical Factory creation index supplies each pool's immutable token0,
token1 and factory, with original log provenance. Historical factory.getPair
at the frozen hash independently confirms membership; RPC decimals confirm
token units. Store this equivalent metadata snapshot and apply unchanged
token_scope validation. No synthetic eth_call getter responses are generated.

Credentials use existing local_secrets.py/environment configuration:
ETHERSCAN_API_KEY and ETHEREUM_RPC_URL. No keys/URLs enter public recipes/logs.

## Run

From the repository root, using the existing environment:

```bash
uv run --frozen python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 --stage all \
  --settings data/scam/rug_pull/tokenscout-eligible-1500-v2/settings.json \
  --allow-network --progress on
```

For this task only, all/evidence means:

`sources -> audit -> discover -> verify -> prepare`

Individual stages and status are also supported. `addresses` and `label` alias
audit. Dry runs do not write or use the network. Explicit plan, collect,
build-graphs and graphs stages are now available through
[the collection extension](RUG_PULL_COLLECTION_PIPELINE.md); all/evidence keeps
its label-only meaning. prepare-training is available through the
[offline training guide](RUG_PULL_TRAINING_PIPELINE.md); fitting uses the existing
run_pipeline --stage train entry, which calls the same existing trainer.
The direct command `chainrisk-scam prepare-rug-pull` exposes the same stages.
The generic training recipe is unchanged; fitting remains explicit.

Settings example:

```json
{
  "selection": {"positive_count": 1500, "negative_count": null, "selection_stage": "after_pool_verification", "seed": 20261022},
  "pools": {"cutoff": 1677628799, "scope": "all_v2"},
  "rpc": {"verification_mode": "factory_event_and_rpc", "batch_size": 20, "batch_rate_rps": 0.5, "retries": 3},
  "collection": {"rate_limit_rps": 2.5, "retries": 3}
}
```

Offline source overrides use source_files.labels and source_files.mapping.
Sources, selections and pool recipes are immutable; changed inputs require a
new snapshot. Successful preparation resumes from checksummed artifacts and
RPC captures. Snapshot locking and durable stage status use the existing runner.

## Outputs

Under data/scam/rug_pull/tokenscout-eligible-1500-v2/:

- sources/: exact original bytes and source URL/file-ID/SHA256 manifest.
- labels/cleaned_labels.csv/jsonl: all cleaned binary source labels.
- labels/selected_labels.csv/jsonl: complete source candidates in the latest
  post-verification selection mode; pre-query cohorts in the legacy mode.
- labels/pool_matched_candidates.csv/jsonl: all cleaned source labels with a
  canonical pool identity, including tokens outside the selected RPC-verification
  cohort. Those extra candidates still need token metadata verification.
- labels/rejected.jsonl and quality_audit.json: mapping/conflict audit.
- pools/: block, discovery, unmatched roots, cached RPC evidence and verification.
- pools/factory_index/: canonical PairCreated pool metadata and complete paging audit.
- pools/token_pool_matches.jsonl: all discovered official v2 memberships of selected tokens.
- pools/verified_targets.jsonl: label-free targets for a later collection step.
- labels/verified_labels.csv/jsonl: labels whose token/pool metadata passed.
- pools/verification_plan.json and verification_rounds/: fixed eligible order,
  positive quota, all-negative selection and replayable success/exclusion rounds.
- label_quality_summary.md/json: final counts and limitations.

training_eligible remains false here because no graph dataset has been
published. Labels are not passed to the graph or used as chain features.
