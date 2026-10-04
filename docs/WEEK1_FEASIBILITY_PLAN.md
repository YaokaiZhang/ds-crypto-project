# Week 1 Feasibility Follow-up Plan

The next phase is a data-audit pipeline with a hard stop before modelling.
The objective is to establish a reproducible token-level cohort, labels, and
general 80/10/10 split before implementing a GNN.

The primary label in this document has been superseded by
`config/label_specification.json` version `week1-labels-0.4` and
`docs/WEEK1_GRAPH_VOLUME_LABELS.md`. The Blockscout/RPC collector below remains
useful for raw event and coverage experiments, but it does not provide the
historical `Swap.amountUSD` field required for the primary volume label.
The current split policy is specified in
`docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`.

## 1. Freeze the data contract

The planned wallet-enriched graph is a later model-input revision. It keeps
the token-level prediction unit and this label contract, but requires
source-mapped swap participant addresses and cutoff-bounded wallet-pool
aggregates. The current feasibility pilot did not collect those fields.

Use Ethereum Uniswap V2 and V3 factories initially:

- Uniswap V2: `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f`
- Uniswap V3: `0x1F98431c8aD98523631AE4a59f267346ea31F984`

For the current Graph-based label run, freeze the following before collecting
labels:

- Prediction unit: one token contract.
- Pool scope: every selected pool belonging to the token.
- `t0`: earliest selected-pool creation timestamp, with first selected-DEX
  activity as the fallback.
- Primary observation cutoff: 7 consecutive days after `t0`.
- Follow-up: 90 consecutive days after the cutoff.
- Sensitivity observation cutoffs: 14 and 30 consecutive days after `t0`.
- `low_volume_dead`: total historical `Swap.amountUSD` is less than USD 1,000
  across selected pools during follow-up.
- `continued_activity`: total historical swap volume is at least USD 1,000.
- Trading volume counts swaps only; mints and burns are separate liquidity
  events.
- `censored`: incomplete coverage, retrieval gaps, unreliable follow-up, or
  missing, invalid, or nonpositive historical USD for a follow-up swap.
- Fewer than ten swaps are not excluded by the primary definition.

The old tenth-swap/no-activity rule is retained only as a sensitivity label.

## 2. Build the collector

Use Blockscout as the archival event source unless the terms, rate limits, or
completeness audit fail.

The collector must:

- Enumerate pools from factory events.
- Collect every selected pool for each token.
- Retrieve Swap, Mint, and Burn events.
- Preserve raw JSON responses, URLs, parameters, retrieval timestamps, and
  checksums.
- Deduplicate using transaction hash plus log index.
- Resolve block timestamps consistently.
- Enforce rate limits, retries, exponential backoff, and resumable cursors.
- Record every failed or incomplete request as a censoring reason.

Market context can use timestamped Binance ETH/BTC data, Ethereum gas history
from `eth_feeHistory`, and DefiLlama DEX-volume and TVL data where repeatable.

## 3. Create the candidate frame and general model split

Build the candidate frame before inspecting primary labels:

- Stratify by launch period.
- Include multiple activity levels.
- Exclude tokens too new to have a complete 90-day follow-up.
- Keep all pools belonging to each selected token.
- Avoid sampling only from current high-volume pools.
- Preserve the sampling frame and selection criteria in a manifest.

Collect a buffer of candidates because some will be censored or excluded for
overlap. After complete labels are assigned, retain all eligible labeled rows
and apply `config/model_split.json`: 80% training, 10% validation, and 10%
test within label and launch-period strata, with overlap groups kept together.
For 1,000 active and 1,000 dead rows, this means 800/800 training,
100/100 validation, and 100/100 test. Retain the full labelled candidate
frame and selection weights; do not discard rows to force a 50/50 development
quota.

## 4. Construct labels

For each token:

1. Find `t0` across all selected pools.
2. Set the primary cutoff at 7 consecutive days after `t0`.
3. Set the follow-up end at 90 consecutive days after the cutoff.
4. Sum positive historical `Swap.amountUSD` values across all selected pools
   during follow-up.
5. Label the token `low_volume_dead` below USD 1,000, or
   `continued_activity` at or above USD 1,000.
6. Mark incomplete or unreliable evidence as `censored`.
7. Preserve evidence ranges and censoring reasons for every label.

Repeat the label construction with 14-day and 30-day cutoffs only as
predeclared history-window sensitivity analyses. Do not mix examples from
different cutoffs in the primary model or split them as though they had the
same feature window.

## 5. Audit the data

Manually inspect a sample of raw and normalized records. Check:

- Missing pages and duplicate events.
- Correct event timestamps and ordering.
- Multiple pools per token.
- Liquidity-only activity.
- Historical USD amount completeness for every follow-up swap.
- Source and launch-period bias.
- Difference between the collected candidate prevalence and each model split.
- Retrieval completeness.
- Shared deployers, funding wallets, bytecode, and counterparty overlap.

## 6. Freeze the general split

Create a versioned `split_manifest` before modelling using
`config/model_split.json`:

- Assign 80% to training, 10% to validation, and 10% to test within each
  label/launch-period stratum.
- Keep related tokens and overlap groups together.
- Keep all snapshots of a token in one partition.
- Record any count adjustment caused by group-preserving assignment.
- Keep the test partition locked until model selection is complete.
- A chronological split may be generated later as a secondary stress test.

The split seed, strata, grouping rule, and review budget must be fixed before
test labels are used.

## 7. Apply the go/no-go gate

Continue to modelling only if:

- Training, validation, and test each have enough supported examples for the
  planned metrics.
- The observed per-class allocations and any group-preserving adjustments are
  recorded.
- Censoring among candidates intended for the eligible development cohort is
  below 20 percent.
- Event histories and labels are reproducible.
- Source terms, licensing, rate limits, and retrieval costs are documented.

If the gate fails, report the limitation and either acquire a better archive
source or reduce the scope to one protocol. Do not start the GNN based on an
underpowered or biased cohort.

## Expected outputs

- `token_entities`
- `raw_events`
- `events`
- `outcomes`
- `split_manifest`
- `sampling_manifest`
- Source and retrieval manifest
- Updated feasibility report

The GNN and locked test set remain blocked until the pilot passes this gate.
