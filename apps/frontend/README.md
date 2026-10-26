# Chainrisk frontend

Vue 3, TypeScript and Vite application with Home, Forecast, ETH and ERC-20 pages.
Configure and start the [backend](../backend/README.md) to enable real analysis
and the homepage feed.

## Install and run

From this directory:

```bash
npm ci
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000`. `VITE_API_BASE_URL` defaults to
`/api/v1`; `.env.example` shows the public API setting. Provider credentials and
inference keys must not be placed in `VITE_*` variables.

## Build and serve

```bash
npm run build
```

Serve `dist/` as static files with SPA fallback to `index.html`. Reverse-proxy
`/api` to the backend on the same origin, allowing long-running requests and
unbuffered SSE responses. Analysis availability follows backend capabilities;
missing services remain unavailable.

## Checks and asset credits

```bash
npm test
```

Checks are maintained under root `checks/frontend/`; `npm run build` also
performs TypeScript checking. See [repository checks](../../checks/README.md).
Keep the [NASA image credits](src/assets/space/SOURCES.md) and
[Inter font license](src/assets/fonts/INTER-LICENSE.txt) with their assets.
