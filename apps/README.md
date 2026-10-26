# Applications

This directory contains user-facing applications. Each application manages its own dependencies and startup commands.

- [docs](docs/README.md): website architecture and page-content specifications.
- [frontend](frontend/README.md): reconstructed Vue/Vite empty application template.
- [backend](backend/README.md): FastAPI API, removable analysis adapter and real homepage feed.

The current application root is `apps/frontend/`. The 2026-10-12 [website architecture](docs/WEBSITE_ARCHITECTURE.md) retains Vue/Vite and plans a separate `apps/backend/` FastAPI application with analysis/feed workers. Deployment configuration stays under `deploy/`; research training remains separate. The backend now provides real chain collection and authenticated remote inference for all five models, plus an independent RPC homepage feed. Mock/demo scoring has been removed. See [backend setup](backend/README.md) and [Modal deployment](../deploy/MODAL.md). See [template development](docs/TEMPLATE_DEVELOPMENT.md).
