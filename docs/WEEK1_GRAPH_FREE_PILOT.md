# Free Graph Pilot

## Result

The keyed free-only GraphQL pilot completed for five tokens selected from the
existing deterministic Week 1 sample. It used only `THE_GRAPH_API_KEY`; the
project's paid `ENDPOINT`, `API_KEY`, and `ETHEREUM_ARCHIVE_RPC_URL` variables
were explicitly removed from the pilot process.

| Measure | Result |
| --- | ---: |
| Tokens | 5 |
| Launch periods represented | 2021, 2022, 2023, 2024, 2025 |
| Pools discovered | 13 |
| Normalized Swap/Mint/Burn events | 42,883 |
| Graph requests recorded | 72 |
| Pool queries complete | 5 / 5 |
| Activity queries complete | 5 / 5 |
| Legacy continued-activity outcomes | 4 |
| Legacy excluded early deaths | 1 |
| Censored outcomes | 0 |

The `Excluded early deaths` row is from the former first-10-swaps sensitivity
definition, not the current primary label. Under the current primary volume
definition, the same five-token check produced 3 `low_volume_dead`, 2
`continued_activity`, and 0 `censored` outcomes.

This historical five-token run predates the 7-day primary cutoff and therefore
does not provide evidence for the current 7-day label contract.

The run did not expose the API key in the report or raw archive. The report
is `data/week1_graph_free_pilot_20260923_v3/graph_free_pilot_report.json`.
Raw responses, request metadata, normalized events, pool coverage, activity
coverage, and outcomes are in the same output directory.

## Interpretation

This proves that the free Graph route can retrieve a small complete pilot for
Uniswap v2/v3 without a paid RPC provider or a local archive node. It does not
yet make the dataset ready for modelling. The sample is too small for class
support, source terms have not been audited, and the selection/label contract
still needs a larger reproducibility audit. It does not address the required
50/50 development quota. Keep `labels_ready: false` and do not train a model
from this five-token run.

The v2 deployment required `pairs` collection queries filtered by `token0` and
`token1`; the older `token.allPairs` field was unavailable. Activity requests
are grouped by pool to avoid gateway disconnects on large multi-pool queries.
