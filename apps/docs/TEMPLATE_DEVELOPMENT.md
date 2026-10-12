# Application template development

Date: 2026-10-12. Status: runnable frontend/FastAPI scaffolds with explicit
unimplemented integrations. This is the selected basis for subsequent website
development. No chain scraping, persistent jobs, graph renderer, real inference,
SSE stream or homepage scanner is delivered by this scaffold.

## Source layout

```text
apps/frontend/src/
  pages/ components/ui/ components/layout/ components/analysis/ components/feed/
  api/ composables/ presenters/ design/themes/ stores/ styles/ router/
apps/backend/
  app/api/ app/application/ app/ports/ app/adapters/ app/workers/
  app/main.py app/container.py app/domain.py app/settings.py app/errors.py
  checks/test_template.py
apps/docs/                      application designs and this guide
```

## Implement next

| Boundary | Classes / methods | Next work |
|---|---|---|
| Durable jobs | PostgresAnalysisRepository.create/get/claim/save/artifact | Idempotent job insertion, leases, atomic results and artifact references. |
| Entity/history | EtherscanProvider.resolve_entity/collect_history | Cutoff type/role/pool checks, existing collection/normalization integration and coverage. |
| Graph | ChainriskGraphBuilder.build | Use the frozen recipe and chainrisk GraphSample contract. |
| Model | ModelRegistry.load/bundle_for; ChainriskPredictor.predict | Approved per-task bundles loaded in workers, schema/quality gates and null statuses. |
| Presentation | GraphViewPresenter.present; RootAnalyticsBuilder.aggregate | Exact graph provenance plus readable event joins, scoped root/token statistics. |
| Analysis | AnalysisService.create; AnalysisPipeline.resolve_context/execute | Persist, freeze context, orchestrate stages and preserve partial task results. |
| Feed | EthereumRpcProvider; PostgresFeedRepository; FeedCollector; FeedWorker | Shared cursor/reorg-aware scanning, bounded fresh sample and actual SSE events. |
| Frontend | Empty panel slots, presenters, useAnalysis/useFeed | Bind real DTOs, implement graph/chart renderers and enable queries after capability checks. |
| Style/icons | Theme tokens, AppIcon registry, resolveChartTheme | Replace provider/theme centrally; retain semantic state and component contracts. |

HTTP and data-source details stay outside task semantics. Templates use Protocol
ports and composition rather than subclasses for every helper. Unsupported methods
raise FeatureNotImplemented; API maps this to HTTP 501. Requests are validated
before those methods run. The public API currently reports mode=template, readiness
false and models unavailable. It must not accept jobs as if durable storage exists.

Frontend DTOs are manually aligned starter definitions, not generated OpenAPI
types yet. Connect generation when extending the schema. Do not wire a page to
sample scores or static chains while backend methods remain unavailable. Real
status and per-task sample/model provenance are required for scores and bands.

## Dependency and research boundary

Frontend uses its existing package-lock. API/worker share the existing root uv
lock through optional `serving` dependencies. Install that group explicitly;
ordinary research-only setup does not need it. Existing Task A/Task B models,
labels and research entrypoints are unchanged. Honeypot/Rug Pull still have
`data_only` runtime stage and cannot publish actual model scores yet.

Use the [frontend README](../frontend/README.md) and
[backend README](../backend/README.md) for startup/check commands. The
[website architecture](WEBSITE_ARCHITECTURE.md) remains the target deployment;
this guide records which of its boundaries now exist only as templates.
