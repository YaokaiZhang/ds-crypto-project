# Project Contract

This is the short governing contract for the whole project. Detailed rules,
schemas, procedures, and run results live in the referenced documents.

## Read first

- docs/GRAPH_WALLET_INPUT_CONTRACT.md: wallet-enriched graph input and
  participant-field rules.

- `GOAL.md`: purpose, scope, claims, and deliverables.
- `PLAN.md`: project stages, model sequence, leakage controls, and gates.
- `config/label_specification.json`: primary and sensitivity label rules.
- `config/event_schema.json`: normalized event fields and identifiers.
- `config/market_context_schema.json`: point-in-time market features.
- `config/model_split.json`: primary general split and evaluation rules.
- `docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`: candidate sampling and quotas.
- `docs/DATA_ENGINEERING_WORKFLOW.md`: Parquet, SQL, DuckDB, and data checks.
- `docs/WEEK1_GRAPH_VOLUME_LABELS.md`: label rationale and source evidence.

## Non-negotiable rules

- The wallet-enriched graph is a versioned model-input revision. Its first
  graph is wallet --swap activity--> pool --contains--> target token, with one
  separate target-token graph per token. It requires cutoff-bounded swap
  participant fields; the existing pool-counterparty graph artifacts do not
  satisfy this input contract.

- Study Ethereum token contracts in a fixed, documented set of selected DEX
  pools; use one canonical row per token.
- Define `t0` from the earliest selected-pool creation, with the documented
  activity fallback. Use the first 7 days for features and the following
  complete 90 days for the primary outcome.
- `low_volume_dead` means selected-pool swap volume below USD 1,000;
  `continued_activity` means at least USD 1,000. Swaps alone count toward
  volume. Use historical positive `amountUSD`; do not backfill current prices.
- Mark incomplete or unreliable follow-up, pool scope, retrieval, timestamps,
  or USD evidence as `censored`. Never turn censored rows into a class or use
  them to fill a quota.
- Build candidates label-blind and retain selection probabilities and strata.
  After complete labels exist, use the complete eligible labeled population;
  do not require a fixed 50/50 development quota. Apply the general token-
  level split in `config/model_split.json`: 80% training, 10% validation, and
  10% test within each label and launch-period stratum, keeping overlap groups
  together. A prior 500/500 cohort is a historical pilot artifact, not the
  current sampling contract.
- The split is class-proportional, not a single global row split: with 1,000
  active and 1,000 dead rows, assign 800/800 to training, 100/100 to
  validation, and 100/100 to test, subject to overlap-group adjustments.
- Use only data available by the 7-day cutoff as model input. Follow-up events,
  outcomes, censoring fields, and post-cutoff market data are not features.
- Keep raw bundles, manifests, normalized Parquet tables, SQL/DuckDB outputs,
  outcomes, censoring, splits, features, graphs, and model artifacts auditable
  and traceable to source rows.

## Project flow

The data product and modelling stages must treat the wallet-enriched graph as
a new input version. It keeps the token-level labels and split, but requires
participant-field collection, wallet-pool aggregation, and a separate
leakage audit before it can produce results.

1. **Feasibility:** freeze sources, schemas, windows, labels, sampling, and
   evaluation; verify access, coverage, historical USD, and retrieval quality.
2. **Collection:** discover and screen candidates without labels, collect full
   histories, assign outcomes, and build sampling and split manifests.
3. **Data product:** follow `docs/DATA_ENGINEERING_WORKFLOW.md` to produce
   validated Parquet and DuckDB/SQL model tables.
4. **Modelling:** compare heuristics, market and token baselines, static
   GraphSAGE, and graph/token/market fusion on the same split.
5. **Delivery:** report metrics, figures, reproducibility details, limitations,
   and negative results.

Temporal GNNs and graph pretraining are optional explorations. They require a
separate data contract and leakage audit before being treated as results.

## Evaluation and release gate

Use the general token-level train, validation, and test partitions defined in
`config/model_split.json`. Audit duplicate or related launches and overlapping
graph neighborhoods. Fit transformations, thresholds, and calibration on
training/validation data only; keep the test partition locked until the final
evaluation. Report class support, dataset prevalence, average precision,
precision, recall, macro-F1, false-positive rate, `Precision@K`, and
sampling-weighted metrics where relevant. A chronological partition may be
reported as a secondary stress test when it has adequate class support.

Do not claim final GNN performance until completeness, censoring, source
limitations, class support, split support, and leakage checks pass. Every
released result must record source and retrieval date, code/configuration
versions, counts, uniqueness and time checks, split metadata, model inputs,
seeds, metrics, and resource use. Never expose `.env` secrets.
