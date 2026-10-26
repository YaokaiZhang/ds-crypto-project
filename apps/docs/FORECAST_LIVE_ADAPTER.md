# Forecast live adapter

Current serving update (2026-10-26): real inference uses `ANALYSIS_MODE=eth_live`.
The fixed mock and synthetic demo implementation/configuration have been removed
after real cloud verification. Earlier implementation/run notes below are
historical where they mention those modes. See the
[model-service contract](MODEL_SERVICE_CONTRACT.md) and
[backend setup](../backend/README.md).

Serving revision (2026-10-25): the model server owns score-to-label policies;
the backend validates and forwards returned labels. Input-only configuration now
ships in `apps/backend/config/`; backend runtime does not include or import
`deploy/`. Eligible live-mock inputs return 0.999 / High Risk for Scam or
0.999 / Continued activity for Forecast, with explicit simulated provenance.
This supersedes earlier random-score and backend-policy descriptions below.
See [MODEL_SERVICE_CONTRACT.md](MODEL_SERVICE_CONTRACT.md).

Implemented on 2026-10-24 at the user's request. The existing `eth_live_mock`
mode now accepts ETH, ERC-20 Scam and Forecast jobs through the same durable
queue, lease fencing, SSE/progress, caches and account-wide Etherscan budget.
The Forecast page remains `/forecast`; enter a token contract address. Start
with `.venv/bin/python scripts/start-eth-live.py`, or use `--restart-backend`
to apply backend changes while preserving Vite and open pages.

## Observation and pool scope

Forecast replays the first seven days from `t0`, rather than recent activity.
For the initial live source adapter, use the same verified canonical Ethereum
Uniswap v2 discovery as ERC-20: both indexed token positions, default quote
priority WETH/USDC/USDT/DAI/other and earliest creation, one pool by default;
API callers may explicitly choose up to 16 pools. This is a supported subset
of the research wallet graph's v2/v3 schema. It does not claim arbitrary DEX
or v3 source support. A missing supported pool returns Unavailable and a reason.

Freeze the discovery block, selected pool identity and actual Factory
PairCreated creation evidence. Define `t0` as the earliest selected-pool
creation. Freeze the nominal end at `t0 + 7 days` and resolve its canonical
block/hash. Reverify historical ERC-20 decimals, supply, quote precision and
pool getters/factory membership at that first-week block. Do not put today's
mutable token state into historical model features. Pools created after the
first-week cutoff are excluded from the observation scope. Public cutoff is
the exact temporal boundary; basic state_time records the actual preceding
block timestamp. Pool creation evidence is required in this verified v2 source
path; unavailable/missing source coverage is never reinterpreted as a fallback
creation time or no activity.

An immature pool can show the part of its first week available at the frozen
discovery cutoff, but receives no score until the complete seven-day window
exists. It does not extend its cutoff automatically or mix in later events.
Old tokens replay their historical first week; this is not a forecast from
today's recent activity. Never retrieve the following 90-day outcome as an
inference feature, and never relabel old tokens from known future outcomes.

## Progressive display and graph

Reuse the complete-window token/pool log scanner, exact-unit normalization,
transactional ledger upserts and revision-based refresh. Include both temporal
boundaries according to Task A's first-week contract. Publish confirmed token
facts early, then update Transfer/pool-event ledger and daily event counts as
pages settle. All observed Transfer, Swap, Mint, Burn, Sync and LP Transfer
records in scope remain inspectable, independent of display node limits.
Quota waits and worker retries preserve cutoff/data; unfinished reconstruction
catches up before publishing so displayed totals never move backward.

The existing Forecast activity control remains 7D only. A seven-day duration
starting partway through a UTC day can touch eight UTC dates; preserve those
boundary buckets rather than dropping the first partial day. The date buckets
are counts, not historical USD approximations.

Publish the graph only after the full observation ledger settles. The display
structure is wallet -- swap_activity --> pool -- contains_token --> target.
Pool membership is structural. Wallet identity uses the actual decoded
Swap.sender; recipient and transaction caller are never substituted for it.
Selected pools are first-hop nodes, wallets are second-hop nodes: retain at
most 48 nodes including root/first hop and 16 second-hop participants, within
64 total and 4096 relations. A single selected pool therefore displays at most
18 nodes; do not add unrelated Transfer participants to fill it. Display limits
do not cap ledger collection or model graphs. Repeated progress/provenance
updates reuse the existing frontend render identity, preserving zoom/animation.
No graph-scope switch or incompleteness badge is added.

## Input and prediction contract

Reuse `scripts.build_wallet_graph.aggregate_wallet_edges` and
`wallet_graph_for_target` for the label-free model artifact. All first-week
Swap/Mint/Burn observations contribute the existing 18-node-feature /
11-edge-feature schema, including participant/missingness flags. The native
MeanSAGE interface consumes node_features, edge_index and root_index; edge
metadata is retained separately. Model graphs preserve all admitted observed
swap senders; Task A's wallet builder has no inherited Scam 512-node cap.
No training partition, outcome label or follow-up evidence enters inference.

Etherscan event logs do not supply historical amountUSD or transaction origin.
Keep both missing, with explicit missingness/quality flags. Do not convert
current prices into historical USD or use the recipient as a missing sender.
The shared wallet builder explicitly supports missing historical USD through
its quality features. The real adapter selects the published no-USD Forecast v0.2.0 bundle,
`continued_activity-b6140c2fdd0cc2e6`. It sends the canonical unscaled graph with
that identity and scaler checksum. The server selects 14 node / 8 edge features
by name, applies its frozen scaler and runs the three-member edge-aware GCN
ensemble. The builder carries the exact release model and scaler identities.
No historical USD substitution is needed or performed.

For a complete first-week graph with at least one valid Swap, `eth_live`
persists the exact input packet, sends it to the authenticated HTTPS model server,
and validates the returned score, label, provenance and sample/model/scaler
identity. Failures remain unscored, with bounded worker retries for transient
errors. Production fixture scoring has been removed. Invalid token/pool/participant/history or no
swaps remains Unavailable with a null score and reason.

The model service alone loads `deploy/registry/forecast_policy.json`. It binds
Forecast v0.2.0 to the released validation-selected threshold
0.5369952122370402: below is `low_volume_dead` / Low volume; at or above is
`continued_activity` / Continued activity. The first-seven-day observation,
following 90-day horizon and USD 1000 selected-pool Swap outcome definition are
unchanged. Scores remain uncalibrated; Forecast never emits Scam risk bands.
The backend consumes the supplied label without thresholding and needs no
`deploy/` directory. See [the service contract](MODEL_SERVICE_CONTRACT.md).

## Verification

Backend controlled-provider checks cover exact creation-based windows,
historical metadata revalidation, inclusive boundaries, exclusion of later
records/labels, true sender versus recipient, full ledger versus limited graph,
uncapped model sender graph, quota-backed recovery, persisted random scores,
unsupported/no-activity/immature cases and 0.5 boundary semantics. Existing
ETH/ERC-20 and static Forecast checks remain applicable.

Real acceptance jobs for GNO, RAI and LQTY are recorded under
reports/serving/forecast-live-smoke.json. Refresh with
`.venv/bin/python checks/live/verify_analysis.py --family forecast`; `--submit` creates the named
acceptance jobs through the local API when absent. Tests use controlled provider
fixtures only; mainnet jobs use real credentials/caches and no synthetic rows.

Mainnet acceptance completed on 2026-10-24:

| Token | Contract | First-week window (UTC) | Transfer / pool-event rows | Model nodes / directed edges |
|---|---|---|---:|---:|
| GNO | 0x6810e776880c02933d47db1b9fc05908e5386b96 | 2020-05-20 01:39:48 to 2020-05-27 01:39:48 | 825 / 41 | 9 / 16 |
| RAI | 0x03ab458634910aad20ef5f1c8ee96f1d6ac54919 | 2021-02-13 13:48:18 to 2021-02-20 13:48:18 | 6305 / 11438 | 22 / 42 |
| LQTY | 0x6dea81c8171d0ba574754ef6f8b412f2ed88c54d | 2021-04-05 10:32:39 to 2021-04-12 10:32:39 | 15459 / 9143 | 43 / 84 |

SQL/input reconciliation verified exact seven-day creation bounds, historical
state block, ledger/fact/chart counts, all true swap senders, no later events
or labels, explicit missing USD and pending preprocessing, display budgets,
mock provenance and threshold semantics. Inputs contain 15, 3438 and 4433
first-week Swaps respectively. Display graphs have 9/8, 18/17 and 18/17
nodes/original relations respectively. These are historical first-week replays,
not current-date forecasts. Automated checks passed: 80 backend tests,
27 frontend tests and the production frontend build.

Browser acceptance is recorded in reports/serving/forecast-live-ui.json, with
forecast-live-page.png and forecast-unavailable-page.png. GNO showed 825 Transfer
records, 41 pool-event rows, eight UTC boundary date buckets for the exact
seven-day duration, 9 display nodes/8 relations and the original Forecast
score/details text. A real ordinary wallet query returned null score,
Unavailable and the small unsupported-ERC-20 reason in the Forecast card.
