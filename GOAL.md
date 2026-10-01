# Goal: Early prediction of low-volume Ethereum token-project outcomes

## Purpose

Build models that predict whether a newly launched Ethereum token project will meet the primary `low_volume_dead` outcome, using only early transaction and liquidity information. The intended users are analysts and traders screening new or obscure tokens. This is a risk-screening study, not investment advice, price prediction, or fraud detection.

## Main research question

Can early transaction and liquidity history predict whether a newly launched Ethereum token project will meet the `low_volume_dead` outcome during the following 90 days, beyond common crypto-market conditions, and does graph information improve prediction over token-level historical features?

## Operational definition of the primary outcome

The primary label follows the proposed dead-coin volume heuristic:

- `t0` is the earliest selected-pool creation timestamp, falling back to the first selected-DEX activity timestamp when pool creation time is unavailable.
- The primary observation cutoff is a fixed 7 consecutive days after `t0`, for every token.
- A token is labelled `low_volume_dead` when the total historical `Swap.amountUSD` across selected pools is strictly less than USD 1,000 during the complete 90-day period after the cutoff.
- A token is labelled `continued_activity` when that 90-day swap volume is at least USD 1,000.
- Only swaps count toward trading volume. Mints and burns remain available as liquidity features and are not added to the volume total.
- A token is `censored` when follow-up is incomplete, retrieval is incomplete, the pool scope is incomplete, or any follow-up swap lacks a usable positive historical USD amount.

The former tenth-swap/no-qualifying-activity rule remains a sensitivity analysis under a separate label definition. It is no longer the primary task and it does not exclude tokens that have fewer than ten swaps. Ordinary wallet transfers, airdrops, and price changes do not count as swaps. The outcome describes observable low trading volume, not malicious intent.

## Cohort sampling and split requirement

The detailed sampling contract is in
[`docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`](docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md).

Build a label-blind candidate frame before inspecting primary outcomes. The
frame must cover multiple launch periods and activity or pool-count strata,
and must retain every candidate's selection metadata even when the candidate
is later censored or not selected for modelling.

After complete primary labels are available, use the complete eligible
labeled population rather than selecting a fixed 50/50 development quota.
Apply the general token-level split in
[`config/model_split.json`](config/model_split.json): 80% training, 10%
validation, and 10% test, stratified within each label and launch-period
stratum. Keep each overlap group in one partition. The term development set
means training plus validation; the test set remains locked until model
selection is complete.

For example, with 1,000 `continued_activity` and 1,000 `low_volume_dead`
tokens, the intended allocation is 800 active plus 800 dead for training,
100 active plus 100 dead for validation, and 100 active plus 100 dead for
test. Group-boundary constraints can make individual counts differ slightly;
the assignment rule and resulting counts must be recorded.

Retain the candidate frame, selection probabilities, launch/activity strata,
and any enrichment or case-control weights. Such weights may be used in
training or reporting when selection was unequal, but they do not replace the
general split or justify discarding otherwise eligible labeled rows. A
chronological split may be reported as a secondary stress test when support
is adequate, not as the primary evaluation split.

## Scope and claims

Start with Ethereum tokens traded on a fixed, documented set of selected decentralized-exchange protocols and liquidity pools. The prediction unit is the token contract. The primary task uses the same fixed 7-day observation window for every token and does not require reaching ten swaps. Use only pre-cutoff information as model input. Evaluate 14-day and 30-day observation windows as sensitivity analyses when support permits. Include a separate market-context input when reliable historical variables are available. Tokens without a launch/activity timestamp or complete label evidence are censored.

The project may claim an association between early on-chain activity and the later 90-day low-volume outcome under the documented cohort and split protocol. It must not claim guaranteed survival, fraud, price direction, or investment suitability.

## Deliverables and acceptance criteria

1. Source, schema, label, license, access, and limitation audit.
2. Reproducible token cohort with immutable raw snapshots, normalized Parquet
   tables, DuckDB/SQL transformations, censoring records, and a versioned
   manifest. The implementation contract is in
   [`docs/DATA_ENGINEERING_WORKFLOW.md`](docs/DATA_ENGINEERING_WORKFLOW.md).
3. Deterministic general token-level 80/10/10 split with duplicate, campaign,
   and neighborhood-overlap checks, plus an auditable class-balance and
   sampling manifest.
4. Activity heuristic, market-context and feature baselines, scratch static point-in-time GNN, and a graph-plus-token-plus-market fusion model. Temporal GNN processing is an optional exploration direction, not a required deliverable. Self-supervised GNN pretraining is optional if data and compute support it.
5. Locked test results with prevalence, support, average precision, precision, recall, F1, false-positive rate, and precision at a stated review budget.
6. Sensitivity analyses for history length, activity thresholds, and time periods where support permits.
7. At least six data-based figures, report, presentation, reproducibility instructions, and limitations covering censoring, market dependence, uncertain labels, and false alarms.

## Boundaries

No live trading, token recommendations, automatic blocking, public accusations, or claims that low trading volume proves fraud. Unknown and censored tokens are not confirmed healthy. Model scores are screening evidence only.
