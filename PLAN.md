# Plan: Early prediction of low-volume Ethereum token-project outcomes

This plan implements [GOAL.md](GOAL.md). It is a five-week data-analysis project. The model predicts the operationally defined low-volume outcome; it does not infer fraud or provide investment advice.

## 1. Freeze the task and establish feasibility - week 1

- Select a fixed, documented set of Ethereum DEX protocols and liquidity sources with usable access, licenses, timestamps, and event fields. "Selected DEXs" means the protocol and factory/pool contract addresses frozen before labelling, chosen for coverage and data quality rather than because they produce convenient outcomes. Use the same event-normalization rule across protocols.
- Define `t0` as the earliest selected-pool creation timestamp, with first selected-DEX activity as the documented fallback.
- Define the primary task with a fixed 7-day observation window for every token; do not condition the primary cohort on reaching ten swaps. Preserve 14-day and 30-day windows as sensitivity analyses.
- Freeze the 90-day follow-up, swap-only USD volume rule, USD 1,000 threshold, positive-USD completeness rule, minimum fields, and treatment of multiple pools before modelling.
- Exclude incomplete follow-up as censored rather than calling it successful.
- Audit retrieval date, license, schema, coverage, time range, missingness, cost, and collection bias.

Create separate tables for token entities, raw events, outcomes, censoring reasons, splits, and sampling metadata. Preserve raw events and source identifiers. Build a label-blind candidate frame across launch periods and activity or pool-count strata, and freeze the general split rule before model selection. After complete labels are assigned, use all eligible labeled rows and assign them with the `config/model_split.json` policy: 80% training, 10% validation, and 10% test within label and launch-period strata, keeping overlap groups together. Do not discard rows to manufacture a 50/50 development sample. Preserve candidate and selection probabilities, strata, cohort role, split version, random seed, and any enrichment or case-control weights. These are go/no-go checks, not claims of market prevalence or statistical sufficiency.

**Go/no-go gate:** continue only if histories, historical USD amounts, and the low-volume endpoint are reproducible; each general split has enough support for the planned metrics; overlap groups and split assignments are auditable; and censoring, source terms, and selection metadata are documented. Keep the former tenth-swap/no-activity rule as a sensitivity analysis, not as the primary cohort filter. Reduce to one source and one history window if necessary.

## 2. Build the data product and EDA - week 2

For the wallet-enriched graph revision, preserve source-mapped swap
participant fields and build cutoff-bounded wallet-pool aggregates. Use one
separate graph per target token with the structure wallet --swap activity-->
pool --contains--> token. Retain raw event identifiers for audit and do not
create transaction nodes in the first implementation.

Follow the implementation contract in
[`docs/DATA_ENGINEERING_WORKFLOW.md`](docs/DATA_ENGINEERING_WORKFLOW.md): keep
immutable raw bundles, write normalized Parquet tables, and use DuckDB with
versioned SQL transformations for analytical and model-ready tables.

- Preserve immutable raw snapshots and processed event tables in the documented
  Parquet layer.
- Normalize addresses and timestamps while retaining transaction and event identifiers.
- Deduplicate using transaction and log identifiers.
- Aggregate qualifying activity across pools while retaining pool-level details.
- Build pre-cutoff features: event counts, buy/sell balance, counterparties, liquidity changes, volume summaries, concentration, time gaps, and deployer/funding relationships where available. For the primary task, all features must be computed from `t0` through the 7-day cutoff.
- Build a separate pre-cutoff market-context vector: ETH/BTC returns and volatility, broad DEX-volume change, gas conditions, stablecoin or DeFi liquidity change, and a launch-period indicator where reliable sources exist. Use fixed lookback windows and record the timestamp and source for each value.
- Construct bounded token-centered directed graphs and document node types, edges, sampling, and edge attributes.
- Fit transformations on training data only; exclude post-cutoff activity, outcome fields, and label-revealing identifiers. Every market feature must be available at or before the token cutoff.

Deliver EDA on launch volume, class balance, dataset prevalence, candidate enrichment and selection, censoring, missingness, follow-up coverage, activity distributions, liquidity trajectories, market periods, and representative neighborhoods. Check whether source, launch period, observation duration, or selection process trivially identifies failure.

## 3. Freeze evaluation and leakage controls - week 2-3

For the wallet graph, build separate target-token graph artifacts after the
token split. The same address may appear in multiple graph files, but the
first experiment must not pass learned wallet state or message-passing
information across token graphs.

- Use the general token-level 80/10/10 partitions in `config/model_split.json`
  and keep all snapshots of a token together.
- Group duplicate contracts, known related launches, and strongly overlapping target neighborhoods where evidence supports it.
- Produce a deterministic `split_manifest` containing token, cutoff, follow-up end, label, censoring status, overlap group, partition, and exclusion reason.
- Produce a sampling manifest containing the candidate-frame rule, candidate selection probability, primary label, selection stratum, cohort role, selection reason, and case-control or inverse-probability weight.
- Audit shared deployers, funding wallets, pools, bytecode, and counterparty overlap. Report retained overlap and group or exclude severe near-duplicates.
- Keep post-cutoff edges and outcomes out of supervised training. State whether unlabeled pretraining is restricted to training-period history.
- Fit normalization, feature selection, and thresholds on training/validation data only. Lock the test set. Scale market variables from training data only.

Report average precision, precision, recall, macro-F1, false-positive rate, support, test prevalence, and sampling-weighted metrics where selection was unequal. Define a fixed review budget before looking at test labels: `Precision@K` is the fraction of supported `low_volume_dead` cases among the top K model scores in the general test partition. Select K from the intended analyst capacity using validation data and freeze it before test evaluation. Use three seeds when feasible. Resample independent token or overlap groups for uncertainty, not individual events. A chronological partition may be reported as a secondary stress test.

## 4. Baselines and models - week 3-4

Run the wallet-enriched graph as a separately versioned input experiment after
the existing pool-counterparty GraphSAGE baseline. Use the same eligible
tokens, cutoff, labels, split, and tuning budget so any difference is
attributable to participant information rather than a different cohort.

### Wallet-graph implementation gate

Before training the wallet-enriched graph, verify that the source exposes a
stable swap participant field for the selected protocols. Store the participant
role, normalized address, source event identifier, and retrieval lineage. If a
participant is a router or contract, retain that fact as a limitation; do not
call it a human user. A graph build with missing participant coverage must be
reported as incomplete and must not be silently merged with the older graph
artifact.

1. Implement a simple activity or liquidity heuristic.
2. Train a market-context-only baseline.
3. Train logistic regression and gradient boosting on historical token features, with and without market context.
4. Train a small static point-in-time GraphSAGE model from scratch on the same eligible tokens, 7-day cutoff, labels, split manifest, and tuning budget. The graph is intentionally richer than the feature baseline; using the same cohort makes any performance difference attributable to the additional graph information rather than different sample selection.
5. Fuse graph, token-feature, and market-context representations in a small late-fusion classifier.
6. If data and compute support it, optionally pretrain the graph encoder on training-period graph structure and fine-tune with failure labels. Pretraining is an extension, not a required deliverable.
7. Use all eligible training rows from the general split. If the observed class
   ratio is imbalanced, use class weighting, training-only sampling, or
   selection weights and record the choice. Select thresholds and calibration
   on validation data, then evaluate once on the locked general test set.
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

Required figures: data/label pipeline; cohort, censoring, and primary-outcome counts; general 80/10/10 split; early activity and liquidity distributions; representative neighborhoods; market-period outcome rates; performance versus history with eligibility counts; precision-recall curves and confusion matrices; and model comparison including the multimodal ablations.

Explain that the outcome is low trading volume, not proof of fraud. Discuss market regimes, uncertain negatives, censoring, source bias, graph overlap, selection bias, and the danger of presenting a score as a buy/sell recommendation. For traders, describe a screening aid for new or obscure tokens; for analysts, describe ranked cases with historical evidence.

Deliver the report, slides, reproducibility instructions, data dictionary, model documentation, and a clear list of what the model cannot establish.

## Immediate next milestone

Produce the source-feasibility matrix, selected-DEX and event schema, low-volume label specification, market-context schema, general split configuration, and audited pilot cohort. Do not implement the static GNN until 90-day follow-up, class support, and the general split are feasible. Record temporal GNN work as optional exploration.
