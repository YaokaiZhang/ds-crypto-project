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

## Cohort sampling and class-balance requirement

The detailed sampling contract is in
[`docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`](docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md).

Build a label-blind candidate frame before inspecting primary outcomes. The
frame must cover multiple launch periods and activity or pool-count strata,
and must retain every candidate's selection metadata even when the candidate
is later censored or not selected for modelling.

After complete primary labels are available, target a development cohort of
50 `low_volume_dead` tokens and 50 `continued_activity` tokens. This 1:1
quota is a case-control sampling design for model development, not a claim
that the two outcomes are equally common in the market. Collect a buffer of
additional candidates because incomplete follow-up, unreliable USD amounts,
overlap exclusions, and chronological support can prevent a candidate from
contributing to the quota. Never change a label or duplicate a token to meet
the quota.

Keep a separate chronological holdout with its observed class prevalence. Do
not force the final test set to 50/50. Preserve the candidate frame,
selection probabilities, quota stratum, and any case-control weights so that
metrics and calibration can distinguish the balanced development sample from
the deployment population.

## Scope and claims

Start with Ethereum tokens traded on a fixed, documented set of selected decentralized-exchange protocols and liquidity pools. The prediction unit is the token contract. The primary task uses the same fixed 7-day observation window for every token and does not require reaching ten swaps. Use only pre-cutoff information as model input. Evaluate 14-day and 30-day observation windows as sensitivity analyses when support permits. Include a separate market-context input when reliable historical variables are available. Tokens without a launch/activity timestamp or complete label evidence are censored.

The project may claim an association between early on-chain activity and the later 90-day low-volume outcome under the documented cohort and split protocol. It must not claim guaranteed survival, fraud, price direction, or investment suitability.

## Deliverables and acceptance criteria

1. Source, schema, label, license, access, and limitation audit.
2. Reproducible token cohort with immutable raw snapshots, processed event tables, censoring records, and a versioned manifest.
3. Deterministic chronological split with duplicate, campaign, and neighborhood-overlap checks, plus an auditable class-balance and sampling manifest.
4. Activity heuristic, market-context and feature baselines, scratch static point-in-time GNN, and a graph-plus-token-plus-market fusion model. Temporal GNN processing is an optional exploration direction, not a required deliverable. Self-supervised GNN pretraining is optional if data and compute support it.
5. Locked test results with prevalence, support, average precision, precision, recall, F1, false-positive rate, and precision at a stated review budget.
6. Sensitivity analyses for history length, activity thresholds, and time periods where support permits.
7. At least six data-based figures, report, presentation, reproducibility instructions, and limitations covering censoring, market dependence, uncertain labels, and false alarms.

## Boundaries

No live trading, token recommendations, automatic blocking, public accusations, or claims that low trading volume proves fraud. Unknown and censored tokens are not confirmed healthy. Model scores are screening evidence only.
