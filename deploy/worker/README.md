# Analysis and homepage-feed worker deployment

Reserved for deployment/startup configuration for independent analysis and
homepage-feed processes. Template source now lives in `apps/backend/app/workers/`.
Analysis performs historical collection, normalization, task graphs and bounded
frozen inference. The feed collector watches Ethereum RPC and publishes a shared
sampled recent-transaction stream, independently of analysis requests.
See [WEBSITE_ARCHITECTURE.md](../../apps/docs/WEBSITE_ARCHITECTURE.md). Worker entrypoints fail fast until their processing methods are implemented;
no collection, durable queue execution or live feed is running.
