# Applications

This directory contains user-facing applications. Each application manages its own dependencies and startup commands.

- [docs](docs/README.md): website architecture and page-content specifications.
- [frontend](frontend/README.md): reconstructed Vue/Vite empty application template.
- [backend](backend/README.md): FastAPI API, removable analysis adapter and real homepage feed.
- [requirement.txt](requirement.txt): direct API/demo/feed Python dependencies for pip or conda.

The current application root is `apps/frontend/`. The 2026-10-12 [website architecture](docs/WEBSITE_ARCHITECTURE.md) retains Vue/Vite and plans a separate `apps/backend/` FastAPI application with analysis/feed workers. Deployment configuration stays under `deploy/`; research training remains separate. The frontend and backend templates now include a removable analysis demo and a real RPC homepage feed. Production analysis collection and model inference remain future work. See [template development](docs/TEMPLATE_DEVELOPMENT.md).
