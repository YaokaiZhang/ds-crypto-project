# ETH real-data adapter with temporary scoring

User-authorized implementation, 2026-10-24. This phase implements Phishing and
Ponzi collection/application behavior; model deployment is a later phase.

## Launch

From the repository root, with the existing Python 3.11 serving/research
environment and installed frontend dependencies:

```bash
.venv/bin/python scripts/start-eth-live.py
# Restart only processes recorded by this launcher:
.venv/bin/python scripts/start-eth-live.py --restart
# Preserve the running Vite/page while restarting API and worker:
.venv/bin/python scripts/start-eth-live.py --restart-backend
```

- Workbench: http://127.0.0.1:5173/eth-scam
- API/OpenAPI: http://127.0.0.1:8000/docs
- API, independent worker and Vite logs/PIDs: .runtime/eth-live-*.log and
  .runtime/eth-live-services.json.

The launcher sets ANALYSIS_MODE=eth_live_mock for API and worker. It does not
stop unrelated services, invoke training or load model weights. The same
commands can be run individually:

```bash
ANALYSIS_MODE=eth_live_mock .venv/bin/python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000
ANALYSIS_MODE=eth_live_mock .venv/bin/python -m apps.backend.app.workers.analysis
npm --prefix apps/frontend run dev -- --host 127.0.0.1 --port 5173
```

The independent homepage feed retains FEED_ENABLED and its own worker. This
mode enables ETH only; Token/Forecast real analysis remains unavailable. To
exercise the old three-family fixtures, use ANALYSIS_MODE=demo separately.

## Actual data and inputs

Default context freezes the current head minus 12 blocks; a supplied historical
cutoff resolves to its actual block. Balance, bytecode and headers use that
block. Chain/mainnet identity and final block hash are verified. Verification
and deployment metadata are optional explorer enrichment; absent fields remain
null. Confirmed type/balance and the fixed 30-day observation bounds appear
before historical collection. Missing history-derived facts stay unknown.

RootWindow streams the complete preceding 30 days of txlist/txlistinternal,
without applying graph node/edge or retained-row budgets to this ledger.
Normal/internal sources are paged over descending block ranges; withhold a
full page's last block before narrowing the next range to avoid the provider's
10,000-result ceiling. A single-block provider overflow remains an explicit
error. Completed observed blocks are accumulated into roughly 1,000-row or
one-second batches. Each batch atomically upserts ledger rows and publishes
root facts, daily flows and a new ledger revision. Existing rows stay visible
during frontend refresh. Source completion stays explicit in API coverage;
no graph incompleteness notice is rendered.

Incremental flow accounting re-normalizes touched transaction hashes with
their captured normal rows when internal traces arrive. Suppress duplicate
root transfers, exclude failed amounts and gas, preserve exact integer wei,
and keep raw trace identities/provenance. The UI's 7D/30D controls select the
visible daily series from that same fixed 30-day scope. Root counterparties
and ledger size may exceed the graph's display limit. The public ledger does
not include neighbor-only transactions.

ERC-20 enrichment uses Etherscan tokentx over the same frozen root window.
Join by transaction hash, group by contract/decimals/root-relative direction,
and never guess missing units or use token reputation as execution status.
Zero native value without an identified asset shows Unknown. Original native
value and token contract identities remain in Inspect. An unavailable token
endpoint preserves native data and records its enrichment failure; quota
exhaustion still pauses accepted jobs. Token data does not enter ETH native
flows or frozen model inputs.

Only after root history and token enrichment settle does the worker publish
the bounded display graph: at most 48 nodes for root plus direct neighbors,
then at most 16 second-hop nodes (64 total), and 4,096 aggregated directed
relations. A soft share of four new nodes per parent spreads branches; larger
indivisible observed groups may use more of the remaining global share.
Both hops may search the original 30-day bound; never query third-hop histories.
Their neighbor observations are display artifacts, not extra root ledger rows.
The graph retains its original controls/task selector and has no incompleteness
badge or graph-scope switch. Graph rendering identity depends on sample/task,
nodes and edges, excluding progress/model metadata, so repeated polling does
not reset zoom/selection or replay the entrance animation. The selected graph
start remains backend provenance; the displayed observation window is 30 days.

A completed root-window checkpoint prevents republishing a settled ledger on
worker/model retries. Successful provider responses and frozen cutoffs survive
restarts/quota waits. API acceptance and daily budget behavior remain unchanged.
For unfinished windows, cached reconstruction catches up with the persisted
counts before publishing again, preserving monotonic counts and revisions.

Models use separate frozen recipes: two hops, 32/16 fanouts, at most 512 nodes
and 4,096 original edges, with 100 rows/action/address for ETH. Do not fill or
pad sparse graphs. Reuse shared normalizer/builders and preserve each bundle's
feature/scaler/recipe identity. No trainer or weights are loaded.
deploy/registry/eth_models.json selects byte-identical manifest/scaler copies
under eth_inputs/. Current MeanSAGE consumed inputs are node_features,
edge_index and root_index, serialized using the frozen scaler and reverse
message-edge conversion. Missing/invalid model history has null scores.

## Temporary predictor

The worker writes a checksum-named input JSON under
.runtime/eth-artifacts/<analysis-id>/model_inputs/, then attempts an HTTP POST
to http://127.0.0.1:18081/predict (0.8-second timeout). This loopback target is
fixed; no real remote predictor is configured. The explicit temporary adapter
generates a random score once and stores it atomically. Reads/reconnects/recovery
reuse that result. Unexpected responses at that temporary port are ignored in
this mode rather than being mistaken for a trained model result.

API/artifacts include simulated result_origin/model_version/explanation and
record input hash, delivery state and policy version. Capabilities advertise
model_available=false. Binary decisions and display bands use the selected
task's actual manifest threshold and user-confirmed band policy, with simulated
provenance. Original frontend text and three-decimal score rendering are
preserved at the user's request. These values are not model performance or
real risk evidence. Removing this adapter later leaves the real-data pipeline
and HTTP result schema intact.

## Durability and errors

SQLite/WAL is the explicitly local prototype store. Jobs have atomic claims,
unique fencing tokens, expiring leases and heartbeats; at most two are leased
globally on this host. API acceptance requires an actual stored job. Idempotent
retries read existing work even after quota exhaustion; changed requests with
the same key return 409. Ledger cursors and SSE replay IDs are analysis-scoped.

Etherscan starts share the existing account ledger: 3/sec, 99,000 attempts per
UTC day, retries included. RPC is not limited by that application budget.
Exhaustion rejects new work with 429/Retry-After; accepted work stores
waiting_quota/retry_at, releases its lease and resumes from cached pages at
midnight. Bounded transport/job retries expose retrying state. Crashes reclaim
expired jobs; stale workers cannot overwrite results. Optional metadata failure
does not erase collected facts. Global integrity failures cannot publish a
successful score. Per-task model preparation failure preserves useful data.

## Verification

```bash
.venv/bin/python -m unittest discover -s apps/backend/checks -v
node --test apps/frontend/checks/*.test.mjs
npm --prefix apps/frontend run build
```

Integration checks cover 1,001-row same-block paging, 64-node retention, early
paging termination, merged normal/internal recency and separate frozen model
caps, EOA versus contract applicability, exact native totals, empty
activity, genuine input serialization, failed HTTP delivery/random result,
quota pause/resume without refetching, restart-stable scores, cursor/SSE scope,
stale lease fencing and global concurrency. Provider doubles are explicitly
offline fixtures; they are not mixed with real request caches.

Previous full-30-day-policy mainnet/UI verification completed for:

| Address | Type | 30-day external/internal rows | Result |
|---|---|---:|---|
| 0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae | contract | 2 / 0 | Both POSTs attempted; target unavailable, simulated scores persisted |
| 0x11a6c3751c7c511d96ef6bb98252caa80f405a26 | EOA | 2 / 0 | Phishing POST attempted; Ponzi not_applicable and displayed Unavailable |

The contract model samples had 329/583 and 328/582 nodes/edges; the EOA sample
had 34/55. Frontend graphs remained the real 30-day 3-node views. Exact cuts,
sample/input hashes and delivery paths are recorded in the local
reports/serving/eth-live-smoke.json, with UI proof in eth-wallet-live.png.

The earlier single-hop 64-node revision was verified on mainnet for
0x6248f79e17a46d85bc6779e0dc7944b3741b9c28. Native display collection used two
requests and published the graph in 2.16 seconds after acceptance. The result
contains 64 nodes/64 directed relations, 84 external rows and one internal row,
with window 2026-10-24T04:20:11Z through 2026-10-24T05:49:35Z. The independent
Phishing model input contains 129 nodes/190 edges. Etherscan enrichment also
produced actual USDT/USDC quantities. The cutoff, ledger counts and displayed
window were reconciled in reports/serving/eth-display-limit-live.json, with UI
proof in eth-64-node-display.png. Old completed snapshots retain their original
data; oversized graphs are rejected before layout and require a new analysis.

Model-budget verification also streamed all four prepared graph files, checked
their checksums against prepared manifests, and compared partitioned graph
recipes with the frozen training/bundle recipes. All four have max_nodes=512
and max_edges=4096; these are upper budgets, not required or padded dimensions.
Actual node medians/maxima were Phishing 199/512, Ponzi 27.5/446, Honeypot
36/171 and Rug Pull 38/172. No recipe mismatch was found. The two ETH deployment
manifest copies are byte-identical to their trained bundles. Details are in
reports/serving/model-input-budget-audit.json. No weights, data or training
configuration were changed by this audit or by the 64-node display revision.

The subsequent user-confirmed two-hop policy is eth-two-hop-display-3. Tests
cover 47 direct neighbors plus 16 leaves, branch connectivity, no third-hop
queries, neighbor ledger directions, root-only native totals, overlapping token
query deduplication and final window extension to older retained second-hop
records. This supersedes the earlier single-hop display policy.

The latest progressive-root-window revision supersedes the earlier shared
truncated-window verification examples above. New checks cover page-by-
page native totals, ledger revisions, deferred graph publication, exact root
trace reconciliation and stable render identity across model updates.

The current full-window revision was verified with a real mainnet query for
0x4838B106FCe9647Bdf1E7877BF73cE8B0BAD5f97, analysis
137a9101-0762-4544-8b74-f836a97ef6f8. Its fixed observation window is
2026-09-24T13:58:47Z through 2026-10-24T13:58:47Z. It retained 10,988 external
transactions and 869,051 internal records (880,039 ledger rows), while the
display graph has 64 nodes and 141 directed relations. SQL reconciliation
confirmed ledger/fact/chart counts, root-only ledger scope and window bounds.
Progress snapshots showed growing ledger/flow totals with no graph; the graph
was first published after complete root collection and token enrichment.
Browser checks confirmed 7D/30D activity switching and preserved 125% graph
zoom across those switches. The graph was then fitted for the saved screenshot.
Evidence: reports/serving/eth-full30-live.json, eth-full30-progress.json,
eth-full30-graph.json and eth-full30-page.png. Automated checks passed:
64 backend tests, 27 frontend tests and the production frontend build.
