# Week 1 Graph Free Pipeline Pilot

## Decision

`go_no_go: false` for modelling. The pipeline is technically reproducible,
but the cohort does not yet support a defensible train, validation, and test
study.

## Run

- Source: The Graph gateway using only `THE_GRAPH_API_KEY`.
- Protocol scope: official Uniswap v2 and v3 subgraphs.
- Cohort: 100 tokens from the frozen deterministic Week 1 candidate sample.
- Output: `data/week1_graph_free_volume_results_20260925`.
- Raw source archives: `data/week1_graph_free_volume_full_20260925` plus the
  targeted retry `data/week1_graph_free_volume_bbc_retry_20260925`.
- Combined raw request rows: 1,465.
- Normalized activity events: 933,385.
- Pool records: 179.

## Engineering Checks

| Check | Result |
| --- | ---: |
| Project tests | 19 passed |
| Lockfile and dependency checks | passed |
| HTTP 200 responses | 1,465 / 1,465 |
| Raw response files | 1,465 / 1,465 |
| Duplicate raw paths | 0 |
| Missing raw files | 0 |
| API-key leak in output | not found |
| Normalized events with missing required fields | 0 |
| Duplicate `(token, event_id)` records | 0 |
| Label consistency violations | 0 |

The transport, raw archive, normalization, and label-writing path therefore
works for the tested cohort.

## Scientific Gate

The primary volume-label counts are:

- 80 `low_volume_dead`;
- 18 `continued_activity`;
- 2 primary `censored`.

The current 100-token run used the earlier 30-day observation window and is
not a result for the new 7-day primary task or the final modelling cohort. The
project now
targets a balanced development sample of 50 `low_volume_dead` and 50
`continued_activity` tokens. Because only 18 tokens currently meet the
continued-activity threshold, the next collection must obtain at least 32
additional active cases plus a buffer for censoring, overlap exclusions, and
chronological support. The balanced quota is a case-control sampling design,
not an estimate of market prevalence; the chronological test holdout must
retain its observed prevalence.

The legacy sensitivity counts are:

- 74 `continued_activity`;
- 2 `failure`;
- 22 `excluded_early_death`;
- 2 `censored`.

All 100 entities have complete pool scope and activity retrieval after the
targeted retry. The merged archive has 0 duplicate event keys and 0 swaps
missing `amount_usd`. Two tokens contain nonpositive USD values in their
follow-up swaps and are censored under the conservative volume-completeness
rule. The primary labels are therefore reproducible for this cohort, but the
class support is still not a modelling pass: only 18 tokens meet the
active-volume class, and no chronological split has been frozen for the new
definition.

The primary USD amount is the historical `Swap.amountUSD` supplied by the
selected subgraph. This is preferable to applying a current price to old
transactions, but it remains source-derived and requires a reliability audit;
the project should not treat it as a perfect market-volume oracle.

The Graph source terms and usage limits have not yet been audited for the
project. This run also does not produce the pre-cutoff feature table or the
Graph-specific split manifest required by the modelling plan.

## Next Gate

Do not train GraphSAGE or publish model results from this output. The next data
step is to audit the source terms and USD methodology, preserve the full
candidate and sampling manifests, freeze a chronological split for the new
label, and expand the development cohort to the 50-per-class target. The final
chronological test holdout should retain observed prevalence rather than being
quota-balanced. Feature extraction and the split manifest should be built only
after that gate passes.
