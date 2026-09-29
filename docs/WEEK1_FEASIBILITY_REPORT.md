# Week 1 Feasibility Report

## Decision

`go_no_go: false`. The pilot does not support modelling or GNN implementation.
The next step is to repair source coverage and complete the terms and limits
review, then rerun the current frozen volume-label and cohort-sampling
contract using the 7-day primary cutoff. The zero eligible labels in this report reflect incomplete pool
scope and activity retrieval; they are not evidence that either primary class
is absent.

## Run

- Source: Blockscout Ethereum mainnet REST and JSON-RPC endpoints.
- Protocol scope: Uniswap V2 and V3 factory creation events, plus pool Swap,
  Mint, and Burn events.
- Environment: project-local `.venv`, Python 3.12.14, created and run with
  `uv`.
- Cohort: 100 tokens selected deterministically before label inspection.
- Retrieval command used `--factory-source rest`, `--max-factory-pages 20`,
  `--activity-tokens 100`, one activity page per pool, and a 200,000-block
  activity horizon.
- Exact all-pool scope was skipped after the public RPC quota returned HTTP
  429 responses. Window-observed pools were retained only to preserve the
  retrieval evidence; they do not produce eligible labels.

## Retrieval Results

| Measure | Result |
| --- | ---: |
| Factory windows complete | 14 / 14 |
| Factory events | 820 |
| Sampling candidates | 822 |
| Selected token entities | 100 |
| Activity events | 1,745 |
| Activity pools complete | 43 / 100 |
| Entities with complete pool scope | 0 / 100 |
| Outcomes | 100 censored |
| Primary volume labels | 0 `low_volume_dead` / 0 `continued_activity` |
| HTTP 200 / HTTP 429 requests | 127 / 56 |
| Raw manifest rows / unique raw files | 183 / 183 |
| Missing raw files / checksum failures | 0 / 0 |

Normalized activity contained 1,622 swaps, 61 mints, and 62 burns. Event
deduplication and raw-body checksum validation completed without detected
duplicates or checksum failures.

The sampling frame contained observed-window pool strata `1: 815` and
`2-4: 7`. All 100 selected entities were in observed stratum `1`. This is a
count of pools seen in the sampled windows, not a complete all-pool count, and
must not be interpreted as evidence that the selected tokens have only one
pool.

## Spot Checks

- A successful raw response checksum matched its stored canonical JSON body.
- All 1,745 normalized events had block timestamps and were ordered by token,
  block, and log index.
- The frame includes a token with three observed pools across Uniswap V2 and
  V3, demonstrating that the frame can represent multiple pools even though
  the selected pilot cohort happened to be in observed stratum `1`.
- Swap, Mint, and Burn records were all present in the normalized activity.
- Deployer, funding-wallet, bytecode, and broader counterparty-overlap
  features were not collected in this frozen Week 1 contract and remain
  follow-up work after source coverage is repaired.

## Gate Checks

- Development quota of 50 examples of each primary outcome: failed; no
  eligible labels exist.
- Validation and test support: not available; all outcomes are censored.
- Test spans two launch periods: failed; no test labels exist.
- Censoring among candidates intended for the development cohort below 20
  percent: failed; all candidates were censored.
- Histories and labels reproducible: failed because exact pool scope and
  complete activity histories were not available.
- Source terms, licensing, rate limits, and costs documented: failed pending
  institutional review.

## Artifacts

- Configuration: `config/week1_config.json`
- Source matrix: `config/source_feasibility_matrix.json`
- Event schema: `config/event_schema.json`
- Label specification: `config/label_specification.json`
- Token entities: `data/week1_pilot/token_entities.jsonl`
- Raw events: `data/week1_pilot/raw_events.jsonl`
- Normalized events: `data/week1_pilot/events.jsonl`
- Outcomes: `data/week1_pilot/outcomes.jsonl`
- Split manifest: `data/week1_pilot/split_manifest.jsonl`
- Retrieval manifest: `data/week1_pilot/source_retrieval_manifest.json`
- Machine-readable audit: `data/week1_pilot/audit_report.json`

The machine-readable report preserves request URLs, parameters, timestamps,
statuses, retry attempts, raw response paths, and canonical JSON checksums.
The updated archive assigns a unique raw response file to every request
manifest row.

## Required Follow-up

Acquire a source/API allowance that can enumerate all selected pools and
retrieve complete histories, or reduce the scope to one protocol after review.
Record the source terms, rate limits, expected cost, and repeatability before
the next run. Build a label-blind candidate buffer, then collect enough
complete labels for a 50 `low_volume_dead` / 50 `continued_activity`
development cohort. Keep the chronological test holdout at observed
prevalence and retain selection weights. Keep the chronological split and
test labels locked until the gate passes.
