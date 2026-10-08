# DeFi risk frontend demo

This application was moved from `TrxLLM/TrxLLM-Vue` on 2026-10-08. It retains Vue 3, Vite, and Vue Router and runs independently of the project's Python training environment. The original interface, images, example pages, and `info.md` are preserved.

This is an interactive demo from the reference project. Fixed addresses and result pages do not represent predictions from this project's models. The Real-Time Data page is not connected to live data collection. The Nuxt backend and Python inference service will be added later.

## Development

From the `ds-crypto-project` root directory, run:

```bash
cd apps/frontend
npm ci
npm run dev
```

Use the local URL printed in the terminal. Existing `node_modules` were retained during the move, so this computer can run `npm run dev` directly. Use `npm ci` to install the locked dependencies in a fresh checkout.

## Build

```bash
npm run build
npm run preview
```

`package-lock.json` is the dependency lockfile used for installation. The original `yarn.lock` is retained only as a source record. Dependencies, build outputs, and TypeScript build caches are excluded from Git.

## Future integration

- Nuxt migration will adapt the application entrypoint, routing, and API calls. The current changes cover relocation and build fixes only.
- The browser will obtain analysis results through the application API. Model weights and Python inference logic will run in a separate environment.
- Preserve source attribution. Performance claims from the reference project are not experimental results from this project.
