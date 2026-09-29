# Plan: Early prediction of low-volume Ethereum token-project outcomes

This plan implements [GOAL.md](GOAL.md). It is a five-week data-analysis project. The model predicts the operationally defined low-volume outcome; it does not infer fraud or provide investment advice.

## 1. Freeze the task and establish feasibility - week 1

- Select a fixed, documented set of Ethereum DEX protocols and liquidity sources with usable access, licenses, timestamps, and event fields. "Selected DEXs" means the protocol and factory/pool contract addresses frozen before labelling, chosen for coverage and data quality rather than because they produce convenient outcomes. Use the same event-normalization rule across protocols.
- Define `t0` as the earliest selected-pool creation timestamp, with first selected-DEX activity as the documented fallback.
- Define the primary task with a fixed 7-day observation window for every token; do not condition the primary cohort on reaching ten swaps. Preserve 14-day and 30-day windows as sensitivity analyses.
- Freeze the 90-day follow-up, swap-only USD volume rule, USD 1,000 threshold, positive-USD completeness rule, minimum fields, and treatment of multiple pools before modelling.
- Exclude incomplete follow-up as censored rather than calling it successful.
- Audit retrieval date, license, schema, coverage, time range, missingness, cost, and collection bias.

Create separate tables for token entities, raw events, outcomes, censoring reasons, splits, and sampling metadata. Preserve raw events and source identifiers. Build a label-blind candidate frame across launch periods and activity or pool-count strata, freeze the chronological test boundary before inspecting outcomes, and collect more candidates than the final quota requires. After complete labels are assigned, target a development cohort of 50 `low_volume_dead` and 50 `continued_activity` tokens only from the predeclared development pool. Prefer coverage across launch periods and pool strata, but record any quota shortfall instead of changing the label rule or duplicating tokens. Keep a separate chronological test holdout with its observed class prevalence; the test set is not quota-balanced. Preserve candidate and selection probabilities, quota strata, cohort role, split boundary, and case-control weights. Target less than 20% censoring among candidates intended for the eligible development cohort. These are go/no-go checks, not claims of market prevalence or statistical sufficiency.

**Go/no-go gate:** continue only if histories, historical USD amounts, and the low-volume endpoint are reproducible; the development cohort can reach 50 examples of each primary class; the chronological holdout has enough support for the planned metrics; and censoring, source terms, and selection metadata are documented. Keep the former tenth-swap/no-activity rule as a sensitivity analysis, not as the primary cohort filter. Reduce to one source and one history window if necessary.

## 2. Build the data product and EDA - week 2

- Preserve immutable raw snapshots and processed event tables, preferably Parquet.
- Normalize addresses and timestamps while retaining transaction and event identifiers.
- Deduplicate using transaction and log identifiers.
- Aggregate qualifying activity across pools while retaining pool-level details.
- Build pre-cutoff features: event counts, buy/sell balance, counterparties, liquidity changes, volume summaries, concentration, time gaps, and deployer/funding relationships where available. For the primary task, all features must be computed from `t0` through the 7-day cutoff.
- Build a separate pre-cutoff market-context vector: ETH/BTC returns and volatility, broad DEX-volume change, gas conditions, stablecoin or DeFi liquidity change, and a launch-period indicator where reliable sources exist. Use fixed lookback windows and record the timestamp and source for each value.
- Construct bounded token-centered directed graphs and document node types, edges, sampling, and edge attributes.
- Fit transformations on training data only; exclude post-cutoff activity, outcome fields, and label-revealing identifiers. Every market feature must be available at or before the token cutoff.

Deliver EDA on launch volume, class balance, natural prevalence, quota selection, censoring, missingness, follow-up coverage, activity distributions, liquidity trajectories, market periods, and representative neighborhoods. Check whether source, launch period, observation duration, or quota selection trivially identifies failure.

## 3. Freeze evaluation and leakage controls - week 2-3

- Use chronological partitions and keep all snapshots of a token together.
- Group duplicate contracts, known related launches, and strongly overlapping target neighborhoods where evidence supports it.
- Produce a deterministic `split_manifest` containing token, cutoff, follow-up end, label, censoring status, overlap group, partition, and exclusion reason.
- Produce a sampling manifest containing the candidate-frame rule, candidate selection probability, primary label, quota stratum, cohort role, development-selection reason, and case-control or inverse-probability weight.
- Audit shared deployers, funding wallets, pools, bytecode, and counterparty overlap. Report retained overlap and group or exclude severe near-duplicates.
- Keep post-cutoff edges and outcomes out of supervised training. State whether unlabeled pretraining is restricted to training-period history.
- Fit normalization, feature selection, and thresholds on training/validation data only. Lock the test set. Scale market variables from training data only.

Report average precision, precision, recall, macro-F1, false-positive rate, support, observed test prevalence, and sampling-weighted metrics where the development cohort was case-control sampled. Define a fixed review budget before looking at test labels: `Precision@K` is the fraction of supported `low_volume_dead` cases among the top K model scores in the prevalence-preserving chronological test cohort. Select K from the intended analyst capacity using validation data and freeze it before test evaluation. Use three seeds when feasible. Resample independent token or overlap groups for uncertainty, not individual events.

## 4. Baselines and models - week 3-4

1. Implement a simple activity or liquidity heuristic.
2. Train a market-context-only baseline.
3. Train logistic regression and gradient boosting on historical token features, with and without market context.
4. Train a small static point-in-time GraphSAGE model from scratch on the same eligible tokens, 7-day cutoff, labels, split manifest, and tuning budget. The graph is intentionally richer than the feature baseline; using the same cohort makes any performance difference attributable to the additional graph information rather than different sample selection.
5. Fuse graph, token-feature, and market-context representations in a small late-fusion classifier.
6. If data and compute support it, optionally pretrain the graph encoder on training-period graph structure and fine-tune with failure labels. Pretraining is an extension, not a required deliverable.
7. Use the 50/50 quota only for the development/training sample. Use class weighting, case-control weights, or calibrated sampling only in training; select thresholds and calibration on a declared validation design, then evaluate on the prevalence-preserving chronological test set.
8. Run 14-day and 30-day history-window, activity-threshold, and launch-period sensitivity analyses only where support is adequate.

9. Treat a temporal GNN that consumes timestamped events up to the prediction cutoff as an optional exploration direction. Do not use it for the primary result unless a separate temporal data contract, leakage audit, and matched evaluation are completed.

### Multimodal comparison

For each token at cutoff `t_cutoff`, construct:

- `h_graph`: the token embedding from the pre-cutoff static GraphSAGE encoder;
- `x_token`: historical token-level features from the same cutoff;
- `m_market`: market-context variables whose timestamps are no later than `t_cutoff`.

The primary fusion model concatenates these representations and applies a small multilayer classifier:

`p_low_volume_dead = sigmoid(MLP(concat(h_graph, x_token, m_market)))`

Train the following ablations on exactly the same eligible tokens and split: market context only; token features plus market context; graph plus token features; and graph plus token features plus market context. The required graph question is whether the last model improves over token features plus market context, while the market ablation tests whether common conditions explain apparent graph performance.

Save configurations, manifests, checkpoints, metrics, seeds, software versions, runtime, memory, and negative results. Inspect false alarms from legitimate but inactive projects and market-wide activity effects.

## 5. Interpret and deliver - week 5

Required figures: data/label pipeline; cohort, censoring, and primary-outcome counts; chronological split; early activity and liquidity distributions; representative neighborhoods; market-period outcome rates; performance versus history with eligibility counts; precision-recall curves and confusion matrices; and model comparison including the multimodal ablations.

Explain that the outcome is low trading volume, not proof of fraud. Discuss market regimes, uncertain negatives, censoring, source bias, graph overlap, the difference between balanced development sampling and market prevalence, and the danger of presenting a score as a buy/sell recommendation. For traders, describe a screening aid for new or obscure tokens; for analysts, describe ranked cases with historical evidence.

Deliver the report, slides, reproducibility instructions, data dictionary, model documentation, and a clear list of what the model cannot establish.

## Immediate next milestone

Produce the source-feasibility matrix, selected-DEX and event schema, low-volume label specification, market-context schema, and audited pilot cohort. Do not implement the static GNN until 90-day follow-up, class support, and the chronological split are feasible. Record temporal GNN work as optional exploration.
