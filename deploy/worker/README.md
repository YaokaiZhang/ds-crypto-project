# Analysis and homepage-feed worker deployment

Reserved for deployment/startup configuration for independent analysis and
homepage-feed processes. Template source now lives in `apps/backend/app/workers/`.
Analysis performs historical collection, normalization, task graphs and bounded
frozen inference. The feed collector watches Ethereum RPC and publishes a shared
sampled recent-transaction stream, independently of analysis requests.
See [WEBSITE_ARCHITECTURE.md](../../apps/docs/WEBSITE_ARCHITECTURE.md). The analysis
entrypoint runs the real ETH pipeline in explicit eth_live_mock mode with a
durable local queue, fenced leases, resumable caches and temporary random scores.
Template mode still fails fast. See [ETH live adapter](../../apps/docs/ETH_LIVE_ADAPTER.md). The
separate homepage-feed worker is implemented as documented in
[feed integration](../../apps/docs/FEED_INTEGRATION.md). Confirmed quota pauses,
actual progress and remaining live-analysis work are tracked in the
[live backend contract](../../apps/docs/LIVE_BACKEND_IMPLEMENTATION.md).
