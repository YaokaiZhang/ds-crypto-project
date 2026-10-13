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

- `src/pages/`: Home, ETH Scam, Token Scam and Forecast placeholder. No saved-analysis page.
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

Analyze controls follow `/capabilities`. An explicitly enabled backend demo adapter
supplies two complete analysis scopes with staged delays and no fixtures in frontend
code. See [analysis integration](../docs/ANALYSIS_ADAPTER_INTEGRATION.md) for startup
and removal. Template mode keeps analysis controls disabled.
The graph renderer implements the existing GraphRenderer interface. It validates
explicit display records, preserves task/sample identity, and supports hover,
selection, fit/zoom/pan, keyboard inspection and reduced motion. Real provider/model
integration remains unimplemented; the removable adapter exercises the same DTOs.
`AppIcon` is the sole icon-library adapter;
replace `design/icons.ts` or theme files to change appearance independently.
API DTOs are starter contracts, not yet generated: wire OpenAPI generation before
expanding production endpoints, and keep changes consistent with Python schemas.

## Graph component preview and checks

With the development server running, open `/graph-preview.html`. This separate
development entry contains clearly labeled synthetic fixtures for ETH/ERC-20 and
empty/loading/invalid states. It is not linked from application routes and is
not included in the normal production build. It never supplies fallback analysis
results. See [the graph design and display-record boundary](../docs/TRANSACTION_GRAPH_DESIGN.md).

Run graph contract/layout checks with `node --test checks/graph-display.test.mjs`.
The checks use the already installed TypeScript dependency; no additional test
package is required. `npm run build` also type-checks the development preview.

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
- Run all checks with `node --test checks/*.test.mjs`: graph integrity, exact wei
  formatting, explicit UTC conversion and complete non-repeating scene cycles.

See [website visual implementation](../docs/WEBSITE_VISUAL_IMPLEMENTATION.md)
for the scoped direction and verification evidence.

## Provenance and design

The previous demo originated in `TrxLLM/TrxLLM-Vue`; its implementation and
performance claims are not retained as project results. See
[website architecture](../docs/WEBSITE_ARCHITECTURE.md) and
[template development](../docs/TEMPLATE_DEVELOPMENT.md).
