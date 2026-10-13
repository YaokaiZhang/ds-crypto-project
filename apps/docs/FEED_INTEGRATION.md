# Ethereum homepage feed

Implemented on 2026-10-13. The homepage uses real Ethereum mainnet data, independently
of `ANALYSIS_MODE`. Analysis demo fixtures never supply homepage transactions.
This implements the previously adopted shared, single-owned feed contract. The
local persistence choice is SQLite/WAL with an OS ownership lock; multi-host
production persistence remains a PostgreSQL adapter boundary.

## RPC source and configuration

The default HTTP endpoint is `https://ethereum-rpc.publicnode.com`, listed by
[PublicNode](https://ethereum.publicnode.com/). No browser connects to it directly.
Override the server-only `ETHEREUM_RPC_URL` to use another mainnet JSON-RPC provider,
for example the authenticated endpoint in the
[Alchemy quickstart](https://www.alchemy.com/docs/reference/ethereum-api-quickstart).
The collector checks `eth_chainId` before collection and requires chain ID 1.
Only read methods are called; endpoint credentials are not included in API DTOs,
capabilities, error messages or worker HTTP logs.

Run these in two terminals from the repository root:

```bash
# API: retain the existing local analysis fixtures and enable the real feed.
FEED_ENABLED=true ANALYSIS_MODE=demo .venv/bin/python -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000

# Collector: one owner per feed database, independent of API browser connections.
FEED_ENABLED=true .venv/bin/python -m apps.backend.app.workers.feed
```

`FEED_ENABLED` defaults to `false`, preserving the unavailable template endpoints.
Both processes must share `FEED_DATABASE_PATH`; when omitted it defaults to
`chainrisk-feed.sqlite3` in Python's OS temporary directory. Use an absolute path
on persistent local storage for a long-lived installation. `.env.example` is
reference text; the application reads process environment and does not load it.
The API opens the feed store but starts no collector. Restarting the API does not
restart collection. Closing the collector releases its advisory ownership lock.
SQLite files must be on a local filesystem, not a shared network filesystem.

## Summary semantics

| UI field | RPC source | Meaning |
| --- | --- | --- |
| Transaction Hash | transaction `hash` | Full hash in Inspect, explorer link in table. |
| From / To | transaction `from` / `to` | Sender and direct recipient; null To means contract creation. |
| Amount · ETH | transaction `value` | Exact native ETH value; failed transactions show attempted value. |
| Block / Block Time · UTC | block `number` / `timestamp` | Inclusion time, not first broadcast time. |
| Gas Limit | transaction `gas` | Supplied gas upper limit, not actual gas consumed. |
| Gas Used | receipt `gasUsed` | Actual execution gas; unavailable when enrichment fails. |
| Execution | receipt `status` | Success, failed or receipt unavailable. |
| Effective Gas Price | receipt `effectiveGasPrice` | Wei per unit of execution gas, shown in Inspect. |
| Execution Fee · ETH | Gas Used × Effective Gas Price | Exact execution fee; excludes any separate blob fee. |

The API also returns block hash and transaction index. All monetary quantities and
gas quantities are decimal integer strings; the frontend formats Wei using string
arithmetic. No floating-point conversion is used for displayed values, including USD estimates. These are
included transactions, not finalized transactions, ERC-20 transfers or internal
traces. No scam inference is triggered by a feed row. Field semantics follow the
[Ethereum JSON-RPC specification](https://ethereum.org/developers/docs/apis/json-rpc/).

## Collection and delivery

- Check the latest header every four seconds; fetch full transactions only for
  new blocks. The first run starts at the latest block, without historical backfill.
- Check parent/hash continuity. Keep 32 recent block hashes for short reorganization
  recovery. Delete orphan rows and issue an authoritative snapshot reset.
- Catch up through at most four blocks. Larger gaps or reorganizations beyond the
  retained window reset to the latest head, with `last_gap_at` exposed to clients.
  A lagging RPC head is treated as degraded rather than undoing the local view.
- Filter transaction `value > 0` before sampling; select up to 24 distributed
  transaction positions in the latest block. Replace
  queued candidates when a new block arrives and drop candidates older than 45s.
  Publish at most two new rows per second (at least 0.5s between publications); slow RPC,
  empty blocks or absent data can produce a slower rate. No stale playback queue.
- Prefetch receipts for selected candidates with at most four concurrent requests,
  each with a two-second receipt budget. Cancel unused work when the head changes. Missing
  receipts leave fields null. A mismatched receipt block prevents publication.
- Keep 100 published rows and 300 journal events. The homepage displays 30 rows.
  Sample identity uses the transaction hash; duplicate publication is ignored.
- HTTP/RPC failures use bounded exponential backoff plus jitter. Header freshness
  older than 20s or head time older than 90s marks the snapshot stale.

`GET /api/v1/feed/recent?limit=30` returns a snapshot with source state, head,
collection time, publication time, sequence, gap time and transaction rows.
`GET /api/v1/feed/events` uses SSE:

| Event | Payload | Event ID |
| --- | --- | --- |
| `snapshot` | Authoritative FeedSnapshot on initial connection/reset | Snapshot sequence |
| `transaction` | `{ transaction, meta }`, incremental new row | Durable sequence |
| `status` | Current metadata, every five seconds | None; does not advance replay cursor |

Reconnect uses `Last-Event-ID`. Events still retained are replayed; expired,
invalid or future IDs receive a fresh snapshot. API replies disable stream proxy
buffering. Production proxies must also allow long-lived SSE responses.

The frontend validates every message, deduplicates hashes, rejects old incremental
sequences and bounds the list at 30. Pause freezes the displayed rows and closes
the stream; Resume fetches the current snapshot. Hidden tabs close the stream and
reconnect on visibility. A ten-second HTTP recovery loop handles broken streams;
requests have a ten-second deadline. Disabled endpoints never supply invented rows.

## Files and checks

- `app/adapters/feed_rpc.py`: small read-only RPC client.
- `app/adapters/feed_store.py`: bounded SQLite store, replay journal and owner lock.
- `app/application/live_feed.py`: normalized rows, collector and streaming reader.
- `app/workers/feed.py`: independent collector lifecycle and retry policy.
- Frontend `presenters/feed.ts`, `composables/useFeed.ts` and `FeedPanel.vue`:
  validation/reduction, connection lifecycle and display.

```bash
.venv/bin/python -m unittest discover -s apps/backend/checks -v
# From apps/frontend:
npm run build
node --test checks/*.test.mjs
```

Checks cover exact fee/value arithmetic, missing receipts, creation transactions,
rate limits, bounded queues, reorganization rollback, gaps, persistence, ownership,
replay/reset, wrong-chain errors, API scope and frontend message validation.
Multi-host deployments must replace the local ownership/store adapter with a
shared transactional repository and lease; starting collectors in every API
process would violate the adopted contract.

## Positive-ETH and USD revision: 2026-10-13

The adopted revision increases publication to two rows/second and restricts samples
and cached rows to strictly positive native ETH value. This does not filter by
receipt success; failed positive-value transactions still show **Attempted**.
The worker applies a one-time cache/journal transition, preserving positive rows
and issuing a fresh snapshot so old zero-value events cannot reappear on replay.

Amounts display `0.05 ETH (≈ $124.65)`, using a shared, current ETH/USD reference
quote from Coinbase's public `GET /v2/prices/ETH-USD/spot`. It requires no API key;
see [Coinbase Prices documentation](https://docs.cdp.coinbase.com/coinbase-app/track-apis/prices).
An independent worker task refreshes the quote every 60s; RPC scanning continues
if price retrieval fails. A quote expires after 300s and is then omitted, leaving
the exact ETH amount visible. Feed metadata includes `usd_quote` with decimal price,
source and fetch time; five-second status events update that metadata without
advancing the transaction replay cursor. USD arithmetic uses BigInt, rounds to
cents and shows estimates below one cent as `<$0.01`. This is current reference
valuation, not transaction-time price, settlement value or an execution quote.

PublicNode supplies the chain data. Etherscan transaction/address hyperlinks are
ordinary public explorer pages for inspection; they are not the RPC data source
and do not require an Etherscan API key. `ETHERSCAN_API_KEY` is unrelated to this
feed path. The current public price source is also separate from Etherscan.
