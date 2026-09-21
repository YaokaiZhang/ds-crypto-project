# Goal: Early prediction of Ethereum token-project failure

## Purpose

Build models that predict whether a newly launched Ethereum token project will fail, using only early transaction and liquidity information. The intended users are analysts and traders screening new or obscure tokens. This is a risk-screening study, not investment advice, price prediction, or fraud detection.

## Main research question

Can early transaction and liquidity history predict whether a newly launched Ethereum token project will fail within the next 90 days, and does graph information improve prediction over token-level historical features?

## Operational definition of failure

We define failure as entering a 90-day inactivity period:

- `t0` is the first qualifying decentralized-exchange liquidity or swap event for the token.
- The primary observation cutoff is after the first 10 qualifying swap events, if the token reaches that window.
- A token is labelled `failure` if it has no qualifying decentralized-exchange swap or liquidity event during the following 90 consecutive days.
- A token is labelled `continued_activity` if it has qualifying activity during that follow-up period.
- A token is `censored` or `uncertain` when complete follow-up or reliable activity evidence is unavailable; these cases are not silently treated as successes.

Qualifying activity and thresholds must be frozen from the data audit before modelling. Ordinary wallet transfers, airdrops, price changes, and isolated automated transactions do not count by themselves. Failure describes observable inactivity, not malicious intent.

## Scope and claims

Start with Ethereum tokens traded on identifiable decentralized exchanges and liquidity pools. The prediction unit is the token contract. Compare the first-10-swap history with 5, 25, and 50 swaps where support permits. Keep post-cutoff information out of features. Tokens without enough history for a window are reported as ineligible.

The project may claim an association between early on-chain activity and later 90-day inactivity under the documented cohort and split protocol. It must not claim guaranteed survival, fraud, price direction, or investment suitability.

## Deliverables and acceptance criteria

1. Source, schema, label, license, access, and limitation audit.
2. Reproducible token cohort with immutable raw snapshots, processed event tables, censoring records, and a versioned manifest.
3. Deterministic chronological split with duplicate, campaign, and neighborhood-overlap checks.
4. Activity heuristic, feature baseline, scratch GNN, and pretrained GNN only if data and compute support it.
5. Locked test results with prevalence, support, average precision, precision, recall, F1, false-positive rate, and precision at a stated review budget.
6. Sensitivity analyses for history length, activity thresholds, and time periods where support permits.
7. At least six data-based figures, report, presentation, reproducibility instructions, and limitations covering censoring, market dependence, uncertain labels, and false alarms.

## Boundaries

No live trading, token recommendations, automatic blocking, public accusations, or claims that inactivity proves fraud. Unknown and censored tokens are not confirmed healthy. Model scores are screening evidence only.
