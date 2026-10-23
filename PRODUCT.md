# Chainrisk product context

<!-- impeccable:product-schema 1 -->

## Platform

web

## Scope and Authority

This record initializes Impeccable for the Vue frontend in [apps/frontend](apps/frontend/).
It does not redefine the research platform or revise the [project contract](CONTRACT.md).
The user confirmed the audience and build workflow during initialization on
2026-10-12. Product capabilities and boundaries below come from the adopted
[website specifications](apps/docs/README.md); they describe intended behavior
unless explicitly identified as implemented.

The [website architecture](apps/docs/WEBSITE_ARCHITECTURE.md),
[ETH Scam specification](apps/docs/ETH_SCAM_WORKBENCH_DESIGN.md), and
[Token Scam specification](apps/docs/TOKEN_SCAM_LAYOUT_SPEC.md) govern their
respective implementation decisions. The earlier frontend review is background.
Use [template development](apps/docs/TEMPLATE_DEVELOPMENT.md) to distinguish
existing scaffolds from integrations still to be built.

## Users

Everyday token holders are the primary audience, as confirmed by the user.
They need understandable Ethereum address/token screening results and explanations
that do not assume specialist knowledge of graph models or blockchain analytics.
Exact use frequency and device distribution remain undecided.

## Product Purpose

Help users inspect an Ethereum address or token, understand the available
task-specific screening evidence, and see the limitations of an assessment.
Success means understanding what was assessed, what each result means, and
whether missing data or unsupported models prevent a conclusion.

## Positioning

The intended mechanism combines independent scam-screening tasks with the
transaction graph actually used for each assessment, scoped activity, and
traceable transaction/event evidence. This is a design commitment, not a claim
of competitive superiority or validated model performance.

## Operating Context

- Navigation, confirmed on 2026-10-12: Forecast / ETH / ERC-20. The Chainrisk
  brand returns Home. ETH and ERC-20 retain `/eth-scam` and `/token-scam`;
  `/forecast` uses the shared analysis workbench and canonical frozen fixture
  workflow (2026-10-13); real Forecast models and APIs remain unavailable.

- Home presents a sampled recent Ethereum transaction feed. It carries freshness
  and coverage information, not scam verdicts.
- ETH Scam accepts an Ethereum address and presents independent Phishing and
  Ponzi outcomes, with account-type and model-scope applicability.
- Token Scam accepts an ERC20 token with verified selected pool context and
  presents independent Honeypot and Rug Pull outcomes.
- Both workbenches use the specified Risk Screening, Basic Information,
  Transaction Graph, Activity, and Transaction Ledger modules, plus query/identity
  and compact provenance/status details. Shared structure preserves distinct
  wallet and token field meanings.
- An analysis freezes its cutoff and task/sample identities. Persistent
  `/analyses/:id` results should reopen without restarting collection.
- Graph/task selection and display filters change presentation; changing an
  assessment cutoff creates a new analysis. Copy/explorer actions support
  inspection of underlying addresses and transactions.

## Capabilities and Constraints

- Existing stack: Vue 3, TypeScript, Vite, Vue Router and a semantic Lucide icon
  adapter. Preserve theme tokens, reusable UI primitives, and chart/graph adapters
  as replacement boundaries. The frontend uses same-origin `/api/v1` with a
  FastAPI backend and separate analysis/feed worker responsibilities.
- The current application is a scaffold. Durable jobs, chain collection, graph
  rendering, real inference and the live feed are not delivered integrations.
  No deployed Task B weights or verified performance results exist.
- Honeypot and Rug Pull are currently `data_only`. Initial Honeypot scope is
  API-defined sell-restriction screening; Rug Pull scope is retrospective
  Ethereum Uniswap v2 malicious liquidity-withdrawal screening. Neither supports
  universal safety claims or unvalidated future-incident predictions.
- Preserve independent task scores and meanings. No combined safety score,
  unknown-as-benign mapping, or low-activity-as-fraud mapping. Forecast exposes a synthetic continued-activity outcome; Task A remains
  a separate research task.
- Unavailable scores remain null with reasons. A score is not automatically a
  calibrated probability. Low/Medium/High bands require an admitted, versioned
  display policy; Low Risk never guarantees safety.
- Bind graph and score to the same actual task sample, cutoff and model recipe.
  Disclose display subsets and distinguish sampling from collection gaps.
- Keep current-state enrichment separate from historical model inputs. Preserve
  UTC dates, units, source coverage and task/model provenance. Missing intervals
  are not zero activity; token quantities are not native ETH or USD values.
- Show real job states, partial results and errors. Do not substitute invented
  scores, fixed-timer progress, or static transactions for unavailable services.
- Provider credentials belong on the server, never in public frontend settings.

## Brand Commitments

The user requires English website copy and Chinese communication during design
work. Project documentation remains English. The confirmed visual constraints
are a black space-like ground, blurred glass navigation/panels, white and pale-blue
light arcs/stripes/waves, and more than ten naturally transitioning background
variants in a randomized continuous sequence. The homepage includes the actual
transaction feed dashboard; full workbenches remain on their analysis pages.
The [visual direction brief](apps/docs/VISUAL_DIRECTION_BRIEF.md) proposes the
specific composition and token direction. The 2026-10-13 user-requested
[background refinement](apps/docs/SPACE_BACKGROUND_REFINEMENT.md) adds five
NASA sparse-starfield/deep-field photographs, displayed in black and white with
barely noticeable slow crossfades. Twelve geometries become broad, brighter
icy-blue bands with breathing brightness. Background animation plays by default
without a header switch, and still honors the system reduced-motion preference.

The scaffold uses the name Chainrisk. A final logo and broader brand voice have
not been confirmed. Use plain-language explanations appropriate for everyday
token holders while preserving the specifications' exact task meanings.

The user supplied [visual references](apps/reference/) for the intended aesthetic:
[layout](apps/reference/layout.png),
[layered panel reference](apps/reference/layout_element_blur.png),
[background reference 1](apps/reference/background_ref1.png), and
[background reference 2](apps/reference/background_ref2.png).
Consult these alongside the existing specifications during visual implementation.
Their third-party names, copy, numbers and unrelated features are not Chainrisk
content or product requirements. Init does not establish new visual tokens or
replace these references with a new design direction.

## Evidence on Hand

The repository contains the selected page/architecture specifications, a Vue
application scaffold, backend templates, research contracts and four visual
reference images. These establish intended workflows and engineering boundaries,
not a released analysis service. Do not fabricate testimonials, adoption figures,
screening accuracy, live results or deployment claims.

## Product Principles

1. Explain the assessment and its limitations in language token holders understand.
2. Keep independent tasks and their evidence distinct, even inside shared panels.
3. Make uncertainty and unavailable results as understandable as completed results.
4. Keep every assessment traceable to its actual snapshot, graph and model scope.
5. Preserve accurate content and semantics when changing themes, icons or layouts.

## Accessibility & Inclusion

The architecture requires status information in text as well as icons/color;
unknown states must remain distinguishable from successful or low-risk states.
A formal accessibility conformance target, localization scope and additional
audience-specific access needs remain open decisions.
