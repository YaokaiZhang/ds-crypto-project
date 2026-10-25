# ERC-20 live adapter

Serving revision (2026-10-25): the model server owns score-to-label policies;
the backend validates and forwards returned labels. Input-only configuration now
ships in `apps/backend/config/`; backend runtime does not include or import
`deploy/`. Eligible live-mock inputs return 0.999 / High Risk for Scam or
0.999 / Continued activity for Forecast, with explicit simulated provenance.
This supersedes earlier random-score and backend-policy descriptions below.
See [MODEL_SERVICE_CONTRACT.md](MODEL_SERVICE_CONTRACT.md).

Implemented on 2026-10-24 under the user-authorized ETH serving principles.
`eth_live_mock` supports `eth_scam` and `token_scam`; the subsequent Forecast
live extension has its own [first-week adapter](FORECAST_LIVE_ADAPTER.md). Start API/worker/frontend using
`scripts/start-eth-live.py`; use `--restart-backend` to apply backend changes
while preserving the running frontend. Open `/token-scam` and enter an ERC-20
contract address, not a transaction hash. No frontend simulation banner, graph
scope toggle or incompleteness badge is added.

## Identity and selected pools

Freeze the canonical observation block (head minus 12, or the requested UTC
cutoff), block hash and preceding 30-day bounds before collection. Validate
Ethereum mainnet and bytecode. At the frozen block, require correctly encoded
ERC-20 decimals (0–255), totalSupply and balanceOf; name/symbol and explorer
verification/creation metadata are optional. Calls use EIP-1898 blockHash with
requireCanonical. Successful RPC and Etherscan captures are immutable and
checksum-checked; credentials never enter artifacts or API responses.

Default discovery queries official Uniswap v2 Factory PairCreated logs for
both indexed token positions through the cutoff. Rank quote assets WETH,
USDC, USDT, DAI, then other assets; tie-break by earliest creation and pool
address. Select one pool by default, independently of labels or scores. An API
caller may supply up to 16 selected pools; every pool must pass the same
verification. Require historical token0/token1 sorted identity, inclusion of
the queried token, official factory, and factory.getPair membership. Pool facts
and decimals produce the shared `packages.token.token_scope` identity.

The current Honeypot and Rug Pull trained inputs both require canonical
Ethereum Uniswap v2 scope. The Rug Pull relaxation allowed non-WETH quote
assets; it did not admit arbitrary factories or v3 event semantics. See
[factory membership](https://developers.uniswap.org/docs/sdks/v2/guides/getting-pair-address)
and [canonical factory implementation](https://github.com/Uniswap/v2-core/blob/master/contracts/UniswapV2Factory.sol).
No Honeypot.is verdicts, tax estimates or external risk labels become features.

A valid ERC-20 without a supported pool still receives its complete token
Transfer ledger/activity and token facts. Both assessments have null score,
not_applicable/unsupported_pool and a readable reason. Other invalid/missing or
insufficient input states also have null scores and reasons. The existing risk
cards display Unavailable plus that small explanatory text, like EOA Ponzi.
Never fall back to synthetic transactions, zero scores or a Low result.
Provider failures are not interpreted as no pool or empty history.

## Complete 30-day display data

`TokenWindow` collects all target-token logs and all selected-pool logs in the
fixed preceding 30 days. `getLogs` has no assumed descending sort: scan newest
block ranges, recursively split saturated ranges newest half first, completely
page a saturated single block, then sort by block/transaction/log identity.
Missing timestamps are hydrated from captured historical RPC headers. A
single-block overflow, missing identity, removed log, conflicting duplicate or
normalization failure is explicit data_incomplete, not an empty result.

Normalize with the shared event decoder, verified pool membership and token
unit mapping. The public ledger categories are token_transfer and pool_event.
The latter includes Swap, Mint, Burn, Sync and LP Transfer. Preserve raw integer
amounts, token decimals/contracts, event fields and log identities; never
coerce another asset to ETH or sum different contracts under one symbol.
Unknown quote precision stays absent from readable quantities, with original
ABI amounts available in Inspect. Transfer participants are observed addresses,
not a claimed global holder count. Facts expose cutoff-bound total supply,
identity, selected pools and observed event counts.

Publish updated facts, daily transfer/swap/mint/burn counts and ledger batches
roughly every 1,000 retained rows or one second. Preserve the fixed observation
window and existing 7D/30D display controls. Ledger upserts, statistics, revision
and source completion are stored transactionally under the worker lease. On
retry/quota recovery, replay cached observations and catch up to persisted
counts before publishing; totals never move backward. A completed checkpoint
skips reconstruction during later model retries. Token/pool observations do
not enter ETH account ledger/flow scope.

## Display graph versus model inputs

The display selection is independent of full ledger/activity collection:
root plus first hop at most 48 nodes, second hop at most 16, total at most 64,
and at most 4,096 directed relations. Pool membership and participation are
structural edges backed by verified state/events, never monetary transfers.
Actual Transfer and pool observations provide the remaining relations. Token
and LP edge amounts retain their own units. Selection is bounded while the
full 30-day log stream continues; it does not cap the public ledger.

Publish the display graph once, only after all 30-day token/pool logs settle.
Model provenance and progress updates do not change the frontend render key,
so the existing zoom/selection and animation remain stable.

Model input collection follows each byte-identical trained manifest and scaler
under apps/backend/config/token_inputs/. It separately queries all selected emitters
(token and pools): getLogs newest range first, and txlist/txlistinternal
descending. Use 100 records/action/emitter per round, at most three rounds;
stop on graph budget, complete source exhaustion or record budget. Both use
32/16 fanouts, max 512 nodes and 4,096 original directed relations. Honeypot
retains window_days=4100; Rug Pull retains window_days=2771. These historical
recipe windows are not shortened to the frontend's 30 days. Preserve the
35-node/17-edge feature order, reverse relations and all five consumed tensors:
node_features, edge_index, root_index, edge_attributes, relation_ids. Token
models are directed edge-aware SAGE, unlike ETH's MeanSAGE. Models have distinct
sample identities, scalers, versions, trained binary thresholds and risk bands.

For eligible usable graphs only, persist the exact scaled JSON input and try
POST http://127.0.0.1:18081/predict. At the user's explicit request the target
remains a test boundary and a fixed 0.999 / High Risk response is persisted.
API/artifacts mark it simulated; model_available stays false. These fixtures
are not evidence of an actual Honeypot/Rug Pull verdict. The model server owns
Honeypot L=.200/H=.700 and Rug Pull L=.400/H=.850; the backend accepts supplied
labels and does not load those policies. Invalid or empty model input remains
unscored.

## Shared execution and verification

ETH and ERC-20 share the durable SQLite queue, global worker concurrency,
lease fencing, replayable SSE, retry policy and account-wide Etherscan budget:
3 HTTP starts/second and 99,000 attempts per UTC day. Reject new work at daily
exhaustion; accepted work releases its lease and resumes at 00:00 UTC using
saved cutoff/pages. RPC has no application rate/daily cap.

Automated checks include full ledger versus bounded graph, single-block
pagination, progressive facts with deferred graph, exact token/quote units,
canonical pool membership, no-pool/invalid-token/empty-input unscored outcomes,
quota pause/recovery without count regression or duplicate rows, frozen model
recipes/tensors, persisted random scores and malformed logs.

Real mainnet acceptance jobs and input checks are recorded under
reports/serving/token-live-smoke.json. Refresh this report with
`.venv/bin/python scripts/verify-token-live.py`; `--submit` submits the named
acceptance tokens if not already recorded. This script only calls the local
API and inspects local results, never handles provider credentials.

Mainnet acceptance completed on 2026-10-24:

| Token | Contract address | 30-day Transfer / pool-event rows | Display nodes / relations |
|---|---|---:|---:|
| GNO | 0x6810e776880c02933d47db1b9fc05908e5386b96 | 6210 / 276 | 64 / 220 |
| RAI | 0x03ab458634910aad20ef5f1c8ee96f1d6ac54919 | 2091 / 1247 | 64 / 342 |
| LQTY | 0x6dea81c8171d0ba574754ef6f8b412f2ed88c54d | 7226 / 326 | 64 / 157 |

All three completed both simulated assessments after actual model-input POST
attempts. SQL reconciliation confirmed fixed 30-day bounds, complete source
coverage, ledger/fact/chart counts, emitter scopes and graph budgets. Both model
input recipes matched their trained bundle/scaler copies; the first acceptance
inputs had GNO 99/287, RAI 64/264 and LQTY 98/217 nodes/edges for each task.
These are frozen-cutoff examples; new queries naturally have updated counts.

A final browser GNO query (63a808f8-feed-4152-bd9c-8d1836d485f2) confirmed
6210/276 records, real GNO/WETH quantities, 7D/30D activity switching and
preserved 125% graph zoom. For negative acceptance, ERC-721 contract
0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d produced invalid_token, null scores
and Unavailable plus a small reason in both cards. No predictor POST occurred.
Evidence is in token-live-ui.json, token-live-page.png and
 token-unavailable-reasons.png under reports/serving/. Automated checks passed:
74 backend tests, 27 frontend tests and the frontend production build.
