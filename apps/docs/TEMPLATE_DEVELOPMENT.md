# Application template development

Current serving update (2026-10-26): real inference uses `ANALYSIS_MODE=eth_live`.
The fixed mock and synthetic demo implementation/configuration have been removed
after real cloud verification. Earlier implementation/run notes below are
historical where they mention those modes. See the
[model-service contract](MODEL_SERVICE_CONTRACT.md) and
[backend setup](../backend/README.md).

Date: 2026-10-12. Status: runnable frontend/FastAPI scaffolds with explicit
unimplemented integrations. This is the selected basis for subsequent website
development. No chain scraping, persistent jobs, graph renderer, real inference,
SSE stream or homepage scanner is delivered by this scaffold.

Frontend refinement on 2026-10-13: the Transaction Graph component now has a
validated SVG display adapter, deterministic layout, node/edge hover and selected
details, progressive entrance, keyboard inspection, fit/zoom/pan and reduced motion.
The [graph implementation guide](TRANSACTION_GRAPH_DESIGN.md) defines its explicit
display-record boundary and separate synthetic development preview. Backend graph
presentation, real graph fetching, collection and inference remain unimplemented;
analysis pages show an unavailable state until a real task sample is supplied.

Whole-site refinement on 2026-10-13: Home, ETH, ERC-20, Forecast
and not-found routes now share the dark glass shell and twelve-scene canvas
background. Workbenches have family-specific information, independent task
unavailability, activity placeholders and ledger category switching. Home calls
the real read-only snapshot endpoint, validates its envelope and shows a failure
state when unavailable. The user subsequently removed the saved-analysis page.
This implements frontend presentation, not analysis creation, durable storage,
real charts, model scoring or SSE streaming. See
[website visual implementation](WEBSITE_VISUAL_IMPLEMENTATION.md).

Subsequent integration on 2026-10-13 adds a removable backend synthetic adapter,
real HTTP job creation, replayable SSE phases, progressive graph/score delivery,
activity rendering and typed ledger pagination. Production collection and model
serving remain unimplemented. See [analysis adapter integration](ANALYSIS_ADAPTER_INTEGRATION.md).

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
| Frontend | Workbench panels, graph renderer, presenters, useAnalysis/useFeed | Bind real analysis DTOs, implement activity charts and enable queries after capability checks. Feed snapshot refresh is connected; SSE is not. |
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

## Homepage integration update: 2026-10-13

The feed template boundary is now replaced when `FEED_ENABLED=true`, independently
of analysis mode. A separate single-owned worker scans real Ethereum blocks and
provides persisted samples and replayable SSE to homepage readers. The default
disabled feed remains HTTP 501. See [feed integration](FEED_INTEGRATION.md).
