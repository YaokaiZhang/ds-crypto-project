# Data Engineering Workflow

This document defines the analytical data-engineering stage of the Ethereum
token project. It turns auditable source collections into reproducible tables
for exploratory analysis and modelling.

## Scope

The workflow is batch-oriented and research-scale. It is designed to be
reproducible on the remote server without introducing a managed cloud data
warehouse.

- Python handles collection, validation, and normalization.
- Compressed JSONL bundles are the immutable raw-response layer.
- Parquet is the normalized columnar storage layer.
- DuckDB is the local analytical query engine.
- SQL is used for joins, aggregations, feature construction, quality checks,
  and model-table assembly.

DuckDB reads Parquet directly and provides warehouse-style SQL workflows in a
single reproducible process. It is an implementation choice for this project,
not a claim that the final system is a production cloud warehouse.

## Data layers

```text
raw gzip JSONL + request manifests
  -> normalized Parquet tables
  -> DuckDB SQL transformations
  -> point-in-time feature and model tables
```

Keep these products separate:

- `tokens`: canonical token identity and `t0` evidence;
- `pools`: selected-pool membership and pool-scope coverage;
- `events`: normalized swap, mint, and burn records;
- `outcomes`: primary and sensitivity labels plus volume evidence;
- `censoring`: incomplete or unreliable retrieval reasons;
- `candidates` and `sampling`: label-blind selection metadata and weights;
- `splits`: general 80/10/10 token-level partitions and overlap groups;
- `features`: cutoff-bounded token and market features;
- `feature_audit`: raw-event and boundary-exclusion counts used for leakage
  checks, kept out of model-facing features;
- `request_log`: normalized request lineage for each source collection;
- `graphs`: graph-construction manifests and point-in-time graph inputs.

Raw bundles and request manifests remain the lineage source. Normalized and
analytical tables must retain source request identifiers and event identifiers
needed to trace a row back to raw data.

## SQL and DuckDB contract

When transformations are implemented, keep reusable SQL under `sql/` or the
documented equivalent and record the SQL/configuration version in each run.
Transformations must be deterministic from retained Parquet inputs and must:

- normalize and join on canonical token and pool identities;
- deduplicate using the documented transaction/log event key;
- enforce UTC timestamp and 7-day cutoff boundaries;
- keep follow-up events out of feature tables;
- preserve censored rows in quality tables while excluding them from supervised
  label tables;
- carry candidate selection probabilities and sampling weights;
- make label sums and threshold decisions traceable to event rows.

The model-facing `features` table contains only values available through the
recorded cutoff. Boundary counters such as post-cutoff, pre-`t0`, and missing
timestamp counts live in `feature_audit` and feed the DuckDB
`feature_cutoff_quality` table instead of being exposed as predictors.

DuckDB databases may be materialized for a run or created from Parquet on
demand. They are derived artifacts, not replacements for raw bundles,
manifests, or versioned Parquet outputs.

## Build sequence

1. Verify raw bundle checksums and request-manifest references.
2. Normalize addresses, timestamps, event types, amounts, source identifiers,
   token identities, and pool records.
3. Write versioned Parquet tables and validate required fields and uniqueness.
4. Load or query the Parquet tables with DuckDB.
5. Run SQL transformations for outcomes, censoring summaries, candidate and
   sampling joins, general stratified splits, and point-in-time features.
6. Export model-ready tables and a manifest containing input paths, row counts,
   code/configuration revisions, and validation results.

The current implementation is `scripts/build_data_product.py`; it writes the
normalized Parquet layer and runs `sql/model_tables.sql`. Its `--source`
arguments select completed collection runs, while `--candidate` arguments
preserve the full label-blind candidate frame, including candidate-only rows.

## Acceptance checks

Before modelling, the pipeline must reproduce:

- one canonical row per token contract;
- unique documented event keys within the selected scope;
- valid pool membership and complete-scope status;
- correct `t0`, 7-day cutoff, and 90-day follow-up boundaries;
- primary volume totals and labels from positive historical `amountUSD` values;
- explicit censoring reasons rather than inferred negative labels;
- selection probabilities, cohort roles, and sampling weights;
- 80/10/10 split assignments stratified by label and launch period, with
  overlap exclusions or group-preserving adjustments;
- no post-cutoff event, outcome, or market data in feature tables;
- zero duplicate event keys and explicit boundary counts in
  `feature_cutoff_quality`.

The analytical handoff is complete only when these checks can be rerun from
the retained raw, manifest, Parquet, and SQL/DuckDB artifacts.
