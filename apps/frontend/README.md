# Chainrisk frontend

Vue 3, TypeScript, Vite and Vue Router application skeleton. The legacy reference
views, fixed results, graph fixtures, static sample transactions and image assets
were removed on 2026-10-12. The 2026-10-13 frontend implements the glass/space
visual direction, responsive workbench panels and explicit unavailable states.
The real homepage stream is supplied by the separately enabled backend feed worker.

## Start and build

From this directory:

```bash
npm ci
npm run dev
npm run build
```

The existing locked dependencies are retained; a framework upgrade is separate
work. `package-lock.json` is the only frontend dependency lock. Vite proxies
`/api` to `http://127.0.0.1:8000` during development. Production needs a same-origin
reverse proxy and SPA fallback. `.env.example` documents the public API base URL;
provider credentials never belong in VITE variables.

## Extension points

- `src/pages/`: Home, ETH Scam, Token Scam and Forecast. No saved-analysis page.
- `src/components/analysis/`: workbench panels, including the interactive
  Transaction Graph renderer; no example scores/data in application routes.
- `src/components/ui/`: replaceable input/button/panel/table/icon primitives.
- `src/api/`: transport and starter typed DTOs matching backend schemas.
- `src/composables/`: analysis request cancellation, feed connection lifecycle,
  and theme updates. Home receives incremental SSE transactions with snapshot recovery; current analysis
  jobs receive SSE progress with polling recovery and are discarded by the UI on navigation.
- `src/presenters/`: page labels/formatting and graph-renderer interface.
- `src/design/`: semantic tokens, default theme, icon provider and chart theme.
- `src/stores/`: UI preferences; results are scoped to analysis IDs.

Analyze controls follow the real backend's `/capabilities`; all five model tasks
are served by Modal through the backend. Production routes have no demo/mock
adapter or local-data fallback. Default unconfigured template mode keeps analysis
controls disabled. See [backend setup](../backend/README.md).
The graph renderer implements the existing GraphRenderer interface. It validates
explicit display records, preserves task/sample identity, and supports hover,
selection, fit/zoom/pan, keyboard inspection and reduced motion. Real provider/model
integration uses backend API responses and returned score/label metadata.
`AppIcon` is the sole icon-library adapter;
replace `design/icons.ts` or theme files to change appearance independently.
API DTOs are starter contracts, not yet generated: wire OpenAPI generation before
expanding production endpoints, and keep changes consistent with Python schemas.

## Regression checks

All frontend checks are in root `checks/frontend/`; the synthetic graph preview
page and its development entry were removed. From the repository root run
`python checks/run.py --suite frontend`, or use `npm test` from this directory.
The checks reuse the existing TypeScript dependency. `npm run build` type-checks
and builds the actual application. See [repository checks](../../checks/README.md).

## Website behavior

- The brand returns Home; Forecast / ETH / ERC-20 keep the approved routes.
- Home renders validated real-chain snapshots and SSE transactions, with pause/resume,
  refresh, UTC freshness, receipt details, errors and stale-data messaging.
  Missing services never fall back to synthetic data. See
  [feed integration](../docs/FEED_INTEGRATION.md) for startup and source semantics.
- ETH and ERC-20 retain distinct task meanings and fields. Enabled analysis
  adapters drive query submission, progressive panels, task graph switching,
  chart date/range inspection, record details and cursor pagination.
- Five locally bundled NASA photographs alternate sparse starfields and Hubble
  deep fields, with CSS grayscale, 72-second holds and 24-second crossfades.
  Two images are loaded at a time; transitions wait for decoding. Credits and
  official downloads are in `src/assets/space/SOURCES.md`.
- Twelve luminous icy-blue canvas bands run in shuffled bags: 40-second scenes
  with ten-second crossfades, slow drift and breathing brightness. The background
  plays by default with no header toggle; reduced motion keeps a static image
  and arc. Hidden tabs suspend drawing. Workbench routes dim the same timeline;
  cached masks protect actual foreground glyphs. Canvas resolution is capped
  at 1.5 device pixels per CSS pixel, drawing at about 30 fps desktop / 20 fps mobile.
- Run all checks with `npm test`: graph integrity, exact wei
  formatting, explicit UTC conversion and complete non-repeating scene cycles.

See [website visual implementation](../docs/WEBSITE_VISUAL_IMPLEMENTATION.md)
for the scoped direction and verification evidence.

## Provenance and design

The previous demo originated in `TrxLLM/TrxLLM-Vue`; its implementation and
performance claims are not retained as project results. See
[website architecture](../docs/WEBSITE_ARCHITECTURE.md) and
[template development](../docs/TEMPLATE_DEVELOPMENT.md).
