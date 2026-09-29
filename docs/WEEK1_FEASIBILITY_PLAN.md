# Week 1 Feasibility Follow-up Plan

The next phase is a data-audit pipeline with a hard stop before modelling.
The objective is to establish a reproducible token-level cohort, labels, and
chronological split before implementing a GNN.

The primary label in this document has been superseded by
`config/label_specification.json` version `week1-labels-0.4` and
`docs/WEEK1_GRAPH_VOLUME_LABELS.md`. The Blockscout/RPC collector below remains
useful for raw event and coverage experiments, but it does not provide the
historical `Swap.amountUSD` field required for the primary volume label.
The required cohort quota is specified in
`docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`.

## 1. Freeze the data contract

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

## 3. Create the candidate frame and balanced development cohort

Build the candidate frame before inspecting primary labels:

- Stratify by launch period.
- Include multiple activity levels.
- Exclude tokens too new to have a complete 90-day follow-up.
- Keep all pools belonging to each selected token.
- Avoid sampling only from current high-volume pools.
- Preserve the sampling frame and selection criteria in a manifest.

Collect a buffer of candidates rather than stopping at 100, because some
will be censored, excluded for overlap, or needed to preserve chronological
support. After complete labels are assigned, select the development cohort:

- 50 `low_volume_dead` tokens;
- 50 `continued_activity` tokens;
- coverage across launch periods and activity or pool-count strata where
  feasible;
- no duplicated token contracts and no label changes to meet the quota.

Keep a separate chronological test holdout with its observed class
prevalence. Do not force the test holdout to 50/50. Retain the full labelled
candidate frame and selection weights for prevalence-aware evaluation.

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
- Difference between the balanced development cohort and natural test
  prevalence.
- Retrieval completeness.
- Shared deployers, funding wallets, bytecode, and counterparty overlap.

## 6. Freeze chronological splits

Create a versioned `split_manifest` before modelling:

- Older launches: training.
- Middle period: validation.
- Newest sufficiently mature launches: test.
- Apply the 50/50 quota to the declared development cohort only; preserve the
  observed prevalence in the chronological test holdout.
- Keep related tokens and overlap groups together.
- Require at least two launch periods in test.
- Keep all snapshots of a token in one partition.

The split boundaries and review budget must be fixed before test labels are
used.

## 7. Apply the go/no-go gate

Continue to modelling only if:

- The development cohort reaches 50 examples of each primary outcome, or the
  shortfall and cause are explicitly reported.
- Validation and test have enough supported examples for the planned metrics;
  exact 50/50 balance is not required in chronological partitions.
- Test spans at least two launch periods.
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
