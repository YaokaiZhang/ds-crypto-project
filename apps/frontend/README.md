# Chainrisk frontend template

Vue 3, TypeScript, Vite and Vue Router application skeleton. The legacy reference
views, fixed results, graph fixtures, static sample transactions and image assets
were removed on 2026-10-12. This directory is the starting point for new development.

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

- `src/pages/`: Home, ETH Scam, Token Scam and persisted analysis routes.
- `src/components/analysis/`: five empty workbench panels; no example scores/data.
- `src/components/ui/`: replaceable input/button/panel/table/icon primitives.
- `src/api/`: transport and starter typed DTOs matching backend schemas.
- `src/composables/`: analysis request cancellation, feed connection lifecycle,
  and theme updates. Pages do not call these on load in the empty template.
- `src/presenters/`: page labels/formatting and graph-renderer interface.
- `src/design/`: semantic tokens, default theme, icon provider and chart theme.
- `src/stores/`: UI preferences; results are scoped to analysis IDs.

Analyze inputs/buttons are disabled until real pipeline integration exists.
Implement a renderer against the existing GraphRenderer interface rather than
adding graph fixtures to a page. `AppIcon` is the sole icon-library adapter;
replace `design/icons.ts` or theme files to change appearance independently.
API DTOs are starter contracts, not yet generated: wire OpenAPI generation before
expanding production endpoints, and keep changes consistent with Python schemas.

## Provenance and design

The previous demo originated in `TrxLLM/TrxLLM-Vue`; its implementation and
performance claims are not retained as project results. See
[website architecture](../docs/WEBSITE_ARCHITECTURE.md) and
[template development](../docs/TEMPLATE_DEVELOPMENT.md).
