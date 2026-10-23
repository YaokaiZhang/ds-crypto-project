# Optional isolated inference service

Reserved for a later Python HTTP predictor if model resources or scaling require
isolation. Under the [2026-10-12 website design](../../apps/docs/WEBSITE_ARCHITECTURE.md),
initial inference runs in the analysis worker using installed chainrisk functions
and process-local approved model bundles. FastAPI exposes jobs/results without
loading weights. No isolated predictor service or approved real Task B models exist yet. The
API/worker skeleton is documented in [template development](../../apps/docs/TEMPLATE_DEVELOPMENT.md).
