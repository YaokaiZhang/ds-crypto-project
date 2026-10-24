# Website design documentation

Website architecture and selected page-content specifications live here.
These documents describe target application behavior and the current frontend presentation / backend templates, not deployed analysis services.

- [Template development](TEMPLATE_DEVELOPMENT.md): current skeleton, extension points and implementation boundaries.
- [Analysis adapter integration](ANALYSIS_ADAPTER_INTEGRATION.md): removable
  synthetic backend, staged jobs, UI integration, configuration and checks.
- [Ethereum homepage feed](FEED_INTEGRATION.md): real RPC source, separate collector,
  summary fields, replayable SSE, recovery and configuration.
- [ERC-20 live adapter](TOKEN_LIVE_ADAPTER.md): complete progressive 30-day token/pool
  observations, bounded display graph, frozen model inputs and simulated scores.
- [Forecast live adapter](FORECAST_LIVE_ADAPTER.md): real first-week observations,
  wallet/pool/token input, delayed graph and replaceable 0.5 mock decision policy.
- [Website architecture](WEBSITE_ARCHITECTURE.md): Vue/Vite, FastAPI, workers,
  API contracts, deployment, and replaceable themes/icons.
- [Visual direction brief](VISUAL_DIRECTION_BRIEF.md): reference analysis,
  proposed glass/space styling, page mapping, 12-scene motion sequence and
  specification conflicts; visual authority for the subsequent implementation.
- [Website visual implementation](WEBSITE_VISUAL_IMPLEMENTATION.md): whole-site
  presentation, current integration limits and verification evidence.
- [Space background refinement](SPACE_BACKGROUND_REFINEMENT.md): monochrome NASA
  photographs, wide icy-blue bands and the user-approved default motion behavior.
- [Workbench glass refinement](WORKBENCH_GLASS_REFINEMENT.md): current ETH/ERC-20
  entry-to-workspace flow, strong frosted glass, sticky context/risk rail,
  glyph-only scene-sized graph and ten-row cursor ledger.
- [Transaction graph implementation](TRANSACTION_GRAPH_DESIGN.md): the scoped
  interactive graph, strict display-record adapter, motion and preview boundaries.
- [ETH Scam layout](ETH_SCAM_WORKBENCH_DESIGN.md): selected elements, fields,
  graph/score consistency, and EOA/contract applicability.
- [Token Scam layout](TOKEN_SCAM_LAYOUT_SPEC.md): shared layout with independent
  Honeypot/Rug Pull tasks and token/pool-specific fields.
- [Earlier frontend and serving review](FRONTEND_AND_SERVING_DESIGN_REVIEW.md):
  background analysis; the architecture and page specifications above govern
  the current design.

- [Live backend contract and implementation status](LIVE_BACKEND_IMPLEMENTATION.md):
  confirmed ETH/ERC-20 scopes, quota, errors, risk bands and actual progress.

Research, data/model contracts, and the mixed Task B codebase/serving plan
remain in the project-level `docs/` directory.
