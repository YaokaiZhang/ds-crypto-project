# Analysis adapter integration

Date: 2026-10-13. This implements the user-requested local testing workflow, not
real Ethereum collection, trained model inference or an admitted risk-band policy.

## Run

From the repository root, using the existing serving environment:

```bash
mkdir -p .runtime
ANALYSIS_MODE=demo DEMO_DATABASE_PATH="$PWD/.runtime/analysis.sqlite3" FEED_DATABASE_PATH="$PWD/.runtime/feed.sqlite3" .venv/bin/python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000
```

Run `npm run dev` from `apps/frontend/`. Vite proxies `/api` to port 8000.
Open `/forecast`, `/eth-scam` or `/token-scam`: capabilities supplies the corresponding
configured address, and Analyze submits a real HTTP job. Default `ANALYSIS_MODE`
is `template`, which keeps all integrations unavailable. No RPC credentials,
provider requests, training code, torch imports or model loads are involved.

Three fixed scenarios are stored as complete readable JSON snapshots under
`app/demo/fixtures/`: `eth_scam.json` (Settlement Vault, an ETH smart contract,
570 ledger rows) and `token_scam.json` (Arcway Token, a declared v2 ARC/WETH pool,
871 ledger rows), and `forecast.json` (first-seven-day Arcway activity,
180 ledger rows). These are frozen observations, not randomly generated at request
time. `datasets.py` only loads/copies the snapshots and binds response identities.

The 2026-10-13 user-requested demo input revision accepts every syntactically
valid Ethereum address. The page's family selects the fixed scenario; only the
root/token address aliases and analysis/sample IDs adapt to the request. Scores,
transaction hashes, amounts, timestamps, activity curves and statistics do not
change. Participant collisions are remapped consistently to preserve unique graph
nodes. Malformed addresses, cross-family tasks, non-Ethereum chains and unsupported
pool scopes remain rejected. Caller-supplied cutoff values do not shift demo data:
both the accepted job and result declare the fixed snapshot's actual cutoff.
This behavior is exclusive to demo mode, not real entity resolution or scoring.

The authored snapshots include a quiet observation day, uneven daily activity,
small payments, larger settlements and shared routing participants. Native
contract payouts are internal traces paired with controller-signed external calls;
the contract never appears as an external transaction signer. Opening/closing
contract balances reconcile with successful transfers and exclude gas paid by
external callers. Failed calls remain in the ledger and outside successful totals.

Each v2 operation shares its hash/block/time/index with an ARC Transfer and Sync
log. Swap raw fields and reserves satisfy the 0.3% fee-adjusted v2 invariant;
Mint/Burn quantities update the paired reserves, Sync precedes the corresponding
operation log, and holder balances remain nonnegative while conserving supply.
Token addresses and indexed amount/reserve fields are ordered consistently when
an input alias changes token0/token1. WETH uses the mainnet deployment address.
These checks follow the [v2 pair implementation](https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2Pair.sol)
and [SDK WETH address registry](https://github.com/Uniswap/sdk-core/blob/main/src/entities/weth9.ts).

| Task | Score | Band |
|---|---:|---|
| Phishing | 0.546 | Medium |
| Ponzi | 0.173 | Low |
| Honeypot | 0.918 | High |
| Rug Pull | 0.627 | Medium |

These are fixture outcomes. API responses declare `result_origin: synthetic`;
capabilities reports `model_available: false` and separate assessment availability.
At the user's request the local frontend has no demo badge. Scores are displayed
as model scores with uncalibrated meaning, never as fraud probabilities.

## Response and lifecycle

`POST /api/v1/analyses` validates the scope, saves a job and returns 202. The
complete bundle is read from `GET /api/v1/analyses/{id}`. It includes family,
snapshot/cutoff/block identity, basic information, independent task results,
task-keyed graphs and contexts, activity points and the ledger's first page.

Phases and default backend waits are resolving (0.6s), collecting (2.6s),
normalizing (0.8s), building_graph (1.3s), predicting (2.4s), then completed.
Total intentional delay is 7.7 seconds plus transport/processing. Set
`DEMO_DELAY_SCALE` between 0 and 10 to scale all waits; zero is useful for checks.
Facts/curves/ledger become available in building_graph, graphs in predicting,
scores only in completed. Timing is owned by the backend, not frontend timers.

`/events` emits named `progress` SSE messages with monotonically increasing IDs,
stage/status/timestamp/message and the analysis ID. `Last-Event-ID` replays later
events; heartbeats keep active streams alive. Streams close on terminal states.
The frontend uses event notifications to reread the bundle, with 1.2s polling
recovery. HTTP requests and subscriptions are disposed on unmount.

Graph and activity read endpoints remain available. Ledger requests use
`category` (external/internal or token_transfer/pool_event), limit and a scoped
cursor. Default response bundles include 30 rows and a next cursor. Bad-category,
cross-analysis/category cursor, missing-job and not-ready states are explicit.
Idempotency keys reuse the same body/job and reject changed requests with 409.

## Data semantics and graph topology

Both datasets contain 30 UTC buckets, exact decimal-string raw amounts, nullable
fields, normal transaction/log/trace identifiers and declared state timestamps.
Successful native movement excludes gas and failed attempted transfers. Token
transfers refer to holder/pool endpoints rather than treating the asset contract
as every transfer's sender. Pool quantities retain individual assets and decimals.
Summary fields and charts reconcile to the root/token ledger records.

Neighborhood graph records additionally include second-hop participants, uneven
hub activity, secondary flows and shared routing contracts. Unrelated native
neighbor records are excluded from the root ledger. Target-token transfers in
the graph remain included in the token ledger and its totals. Structural token/pool
links remain visibly distinct from transfers. Graph metadata and scores bind to
the same task/sample identity. None of these fixture graphs claim to be an
admitted research-model input or complete real-chain collection.

The renderer uses seeded irregular initialization and a bounded force relaxation,
then freezes the layout. It uses actual supplied edges to form clusters without
adding display-only relationships. Node separation, original direction, parallel
edges, loops, fit bounds, keyboard inspection and reduced motion are preserved.

## Ownership and removal

All frozen JSON data, synthetic outcomes and artificial delays live under
`apps/backend/app/demo/`. `Settings.analysis_mode` and the composition root are
the only activation switch. The adapter is single-process, with four concurrent
jobs; its SQLite file defaults to the OS temp directory and can be overridden
using `DEMO_DATABASE_PATH`. Internal persistence supports restart recovery and
SSE replay; it is not a user-facing saved-analysis feature. It has no list/history
API, production worker lease system, authentication or multi-process guarantees.

The user removed saved analysis entirely from the frontend: there is no
`/analyses/:id` browser route, details page, reopen link or history preference.
Leaving a workbench discards its current UI result. The internal analysis ID
continues to identify progress and artifact reads.

To replace synthetic processing, select/inject the real analysis service in
`container.py`, implement provider/graph/predictor/analytics/repository adapters,
and keep these HTTP DTOs. The frontend contains no fixture imports or family
score constants. Template mode is the immediate disabled fallback. The demo
package and its checks can be removed when the real service is ready. Real Forecast model/provider integration remains unavailable; Home Feed has its
independent integration below.

## Verification

```bash
.venv/bin/python -m unittest discover -s apps/backend/checks -v
npm --prefix apps/frontend run build
```

From `apps/frontend/`, run `node --test checks/*.test.mjs`.
Backend checks cover staged availability, risk bands, sample binding, exact flow
and graph reconciliation, pagination, replay, idempotency, scope, persistence and
template-mode separation. Browser checks cover both workbenches, graph task
switching, ledger categories/pages/details and the 390px responsive layout.
Additional checks cover arbitrary demo addresses, immutable fixture reuse,
address collisions and fixed cutoff behavior. Edit a snapshot and restart the
backend to change its observations; there is no runtime transaction generator.

## Independent homepage feed

The later real-chain [homepage feed](FEED_INTEGRATION.md) is enabled separately
with `FEED_ENABLED=true`. Demo mode alone still does not enable it. A combined
local run can use fixed Scam analysis fixtures and real homepage transactions;
removing the analysis demo module does not remove the feed worker or RPC adapter.

## Forecast extension

Forecast uses the same POST, SQLite job, staged GET, replayable SSE, graph,
activity and scoped ledger endpoints. The thin Forecast page wraps the shared
AnalysisWorkbench. There are no frontend fixtures, fixed scores or page timers.
`ANALYSIS_MODE=demo` remains the canonical fixture-adapter switch; it does not
create a separate frontend demo mode.

`forecast.json` freezes the first seven days of the authored Arcway observations:
2026-09-13T00:00:00Z through 2026-09-20T00:00:00Z. It contains 180 ledger rows,
seven daily buckets and a wallet--swap activity-->pool--contains-->token graph.
Edges aggregate only in-window Swap.sender records; recipients are not silently
substituted for senders. Graph, facts, activity and ledger share this cutoff.
No later events or realized future labels are included. Historical USD amounts
are unavailable in this fixture; token/WETH amounts remain inspectable, without
current-price conversion or an admitted research-model input claim.

The family is `forecast`, with exactly one task, `continued_activity`. Its score
0.27 targets continued activity (following-90-day selected-pool swap volume at
least USD 1,000); the synthetic 0.5 decision policy displays `low_volume_dead`.
This is a frozen illustrative outcome, not a calibrated probability or a scam
classification. Completed task metadata declares observation/horizon, threshold,
score target, outcome and decision policy. Forecast risk bands are rejected.
Model availability stays false in both adapter and template capabilities.

Facts and the first ledger page arrive at building_graph, the task/sample-bound
graph at predicting, and the outcome only at completed. Accepted jobs declare
the family-specific frozen cutoff immediately, even if callers supply another
cutoff. Valid Ethereum addresses bind aliases only, as on the existing pages;
only the configured selected pool is accepted in fixture mode. Token-style
ledger categories remain token_transfer and pool_event, with scoped pagination.

Configure paths explicitly outside system temporary directories when running:

```bash
ANALYSIS_MODE=demo DEMO_DATABASE_PATH="$PWD/.runtime/analysis.sqlite3" \
  .venv/bin/python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000
```

Forecast does not change or load research checkpoints, feature transforms,
training splits or external providers. Removing the fixture adapter leaves the
same unavailable template boundary as ETH and ERC-20.

## Expanded Forecast fixture and service startup

Forecast uses its frozen scenario for every valid Ethereum address, with only
address aliases changed. Its seven-day graph now includes 30 synthetic swap
senders, one pool and the target token (32 nodes, 31 relations). Ledger sender
identities agree with graph observations; activity counts and amounts remain fixed.
It uses the same interactive graph renderer as ETH and ERC-20.

On Roihu, run `scripts/start-demo-feed.sh` from the repository root to start the
fixture API and independent live Ethereum collector. Both use explicit repository
`.runtime` database, PID and log paths. Override `CHAINRISK_PYTHON` for another
Python installation. Existing running processes managed by those PID files are
left running; after configuration or fixture changes, stop them before restarting.

```bash
cd /scratch/project_2020551/ds-crypto-project
kill $(cat .runtime/api.pid) $(cat .runtime/feed.pid)
scripts/start-demo-feed.sh
```

Forecast presentation refinement: the score uses the shared workbench numeric
output, meter and outcome badge. Observation, horizon, volume boundary and
explanation occupy a separate Forecast details card. This is presentation only;
continued-activity score semantics and the prohibition on scam risk bands stay
unchanged. The entry form has no example-token button.
