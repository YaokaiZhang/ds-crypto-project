# Plan: Early prediction of Ethereum token-project failure

This plan implements [GOAL.md](GOAL.md). It is a five-week data-analysis project. The model predicts the operationally defined outcome of 90-day inactivity; it does not infer fraud or provide investment advice.

## 1. Freeze the task and establish feasibility - week 1

- Select Ethereum DEX and liquidity sources with documented access, licenses, timestamps, and event fields.
- Define `t0` as the first qualifying liquidity or swap event.
- Define the primary window as the first 10 qualifying swaps, with 5, 25, and 50 as optional sensitivity windows.
- Freeze the 90-day follow-up, qualifying-activity rules, minimum fields, and treatment of multiple pools before modelling.
- Exclude incomplete follow-up as censored rather than calling it successful.
- Audit retrieval date, license, schema, coverage, time range, missingness, cost, and collection bias.

Create separate tables for token entities, raw events, outcomes, censoring reasons, and splits. Preserve raw events and source identifiers. Pilot 50-100 candidate tokens across launch periods and activity levels. Check that both outcome classes and chronological train/validation/test support exist.

**Go/no-go gate:** continue only if histories and the failure endpoint are reproducible with adequate class support. Reduce to one source and one history window if necessary.

## 2. Build the data product and EDA - week 2

- Preserve immutable raw snapshots and processed event tables, preferably Parquet.
- Normalize addresses and timestamps while retaining transaction and event identifiers.
- Deduplicate using transaction and log identifiers.
- Aggregate qualifying activity across pools while retaining pool-level details.
- Build pre-cutoff features: event counts, buy/sell balance, counterparties, liquidity changes, volume summaries, concentration, time gaps, and deployer/funding relationships where available.
- Construct bounded token-centered directed graphs and document node types, edges, sampling, and edge attributes.
- Fit transformations on training data only; exclude post-cutoff activity, outcome fields, and label-revealing identifiers.

Deliver EDA on launch volume, class balance, censoring, missingness, follow-up coverage, activity distributions, liquidity trajectories, and representative neighborhoods. Check whether source, launch period, or observation duration trivially identifies failure.

## 3. Freeze evaluation and leakage controls - week 2-3

- Use chronological partitions and keep all snapshots of a token together.
- Group duplicate contracts, known related launches, and strongly overlapping target neighborhoods where evidence supports it.
- Produce a deterministic `split_manifest` containing token, cutoff, follow-up end, label, censoring status, overlap group, partition, and exclusion reason.
- Audit shared deployers, funding wallets, pools, bytecode, and counterparty overlap. Report retained overlap and group or exclude severe near-duplicates.
- Keep post-cutoff edges and outcomes out of supervised training. State whether unlabeled pretraining is restricted to training-period history.
- Fit normalization, feature selection, and thresholds on training/validation data only. Lock the test set.

Report average precision, precision, recall, macro-F1, false-positive rate, support, test prevalence, and precision at a fixed review budget. Use three seeds when feasible. Resample independent token or overlap groups for uncertainty, not individual events.

## 4. Baselines and models - week 3-4

1. Implement a simple activity or liquidity heuristic.
2. Train logistic regression and gradient boosting on historical token features.
3. Train a small GraphSAGE model from scratch using the same cutoff and targets.
4. If data and compute support it, pretrain the encoder on training-period graph structure and fine-tune with failure labels.
5. Use class weighting or calibrated sampling only in training and select thresholds on validation data.
6. Run history-window, activity-threshold, and launch-period sensitivity analyses only where support is adequate.

Save configurations, manifests, checkpoints, metrics, seeds, software versions, runtime, memory, and negative results. Inspect false alarms from legitimate but inactive projects and market-wide activity effects.

## 5. Interpret and deliver - week 5

Required figures: data/label pipeline; cohort, censoring, and failure counts; chronological split; early activity and liquidity distributions; representative neighborhoods; performance versus history with eligibility counts; precision-recall curves and confusion matrices; and model comparison.

Explain that the outcome is inactivity, not proof of fraud. Discuss market regimes, uncertain negatives, censoring, source bias, graph overlap, class imbalance, and the danger of presenting a score as a buy/sell recommendation. For traders, describe a screening aid for new or obscure tokens; for analysts, describe ranked cases with historical evidence.

Deliver the report, slides, reproducibility instructions, data dictionary, model documentation, and a clear list of what the model cannot establish.

## Immediate next milestone

Produce the source-feasibility matrix, event schema, failure-label specification, and audited pilot cohort. Do not implement the GNN until 90-day follow-up, class support, and the chronological split are feasible.
