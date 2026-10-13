# Token Scam layout content specification

> Presentation revision, 2026-10-13: [Workbench glass refinement](WORKBENCH_GLASS_REFINEMENT.md)
> supersedes the earlier ETH/ERC-20 query/panel composition, graph plot labels,
> workbench typography and panel material below. It preserves field inventories,
> task/model meanings, graph provenance and inspection semantics. Home, shared
> navigation and accepted background styling retain their own authority.

Date: 2026-10-12. Status: companion display specification to
[ETH Scam](ETH_SCAM_WORKBENCH_DESIGN.md), following the user's request to reuse
the same layout with Honeypot/Rug Pull. This documents content, not application
implementation. It refines UI scope without changing task/model contracts.

## 1. Decision and task scope

Reuse the ETH Scam shell and five content modules: Risk Screening, Basic
Information, Transaction Graph, time-series Activity, and Transaction Ledger.
Use Honeypot and Rug Pull as the two primary risk tasks on this page. Ponzi and
Phishing remain primary ETH Scam tasks; separate associated-address analyses
can be linked later without adding more primary cards here.

Layout reuse does not mean replacing task names while retaining wallet data.
The target is an ERC20 token plus verified selected pool context. The accepted
limited first-release scope from “实现 Scam 检测基础流程” is API-defined sell-
restriction screening for Honeypot, and retrospective screening of documented
Ethereum Uniswap v2 malicious liquidity withdrawal for Rug Pull. No self-built
historical sell simulation, universal rug coverage or pre-incident prediction
is required for this initial scope.

Both tasks remain `data_only` in the current registry/configurations. Data and
initial graphs exist; token-specific coverage, label adapters/admission, training,
approved weights and services must be completed before real scores are enabled.
The UI can display collected facts and explicit unavailable states before then.

## 2. Complete corresponding element list

| ID | Element | Fields / controls | Description |
|---|---|---|---|
| T1 | Query and identity | Token contract address; Ethereum; token identity/type; verified selected pool(s); assessment cutoff; Analyze; copy/explorer | Same query structure, with explicit token and pool scope. Pool mappings can be supplied manually in the accepted first release; selecting a display pool does not silently change an existing model sample. |
| T2 | Risk Screening | Honeypot and Rug Pull independently: applicability/status, score, band where admitted, model decision, actual window/version and unavailable reason | Same risk component; separate task weights and thresholds. Model scores remain distinct from current external API evidence. |
| T3 | Basic Information | Token address/name/symbol/decimals; total supply when available with state time; selected pair addresses and paired assets; observation window; token Transfer count; participating address count; selected-pool Swap/Mint/Burn counts; first/last observed activity | One multi-column box. Replace native wallet balance and root ETH inflow/outflow with token/pool activity; optional supply is not a model prerequisite. |
| T4 | Transaction Graph | Active task/sample; token root; supported wallet/pool/LP/deployer roles; actual transfers/DEX events and structural relations; node/edge details; display/model counts and graph provenance | Same renderer, different graph adapter and legend. Render the actual task GraphSample, using token graph recipe rather than address_flow. |
| T5 | Token & Pool Activity | Daily target-token Transfer-event count; selected-pool Swap/Mint/Burn counts in an aligned time-series panel; date hover; pool display filter; available-range display filter | Reuse the chart container. First release uses event counts, which do not need USD valuation or reconstructed LP holdings. Native ETH wallet inflow/outflow are not token trading volume. |
| T6 | Token/Pool Event Ledger | Token Transfers / Pool Events tabs; time; hash; emitter/pool; from/to or event participants when known; event type; asset amounts/units when decoded; status; block; pagination/details | Reuse the table/detail component with token-event columns. A row is a log/event, not necessarily a unique transaction. Mint/Burn/Sync/Swap and LP Transfer preserve different meanings. |

Keep provenance, coverage, sampling, source/evidence and task availability in
compact inline/expandable details rather than adding a new main panel. Preserve
the latest ETH Scam field reductions; this specification does not restore
additional dashboard boxes that the user omitted there.

## 3. Measurement and graph semantics

- A token is a ledger asset: most ERC20 Transfer endpoints are holders/pools,
  not the token contract itself. Use the emitting token and event asset to
  collect token activity, not only address transactions whose from/to is the
  token contract. Its contract's ETH balance is not token liquidity or value.
- Token Transfer count means deduplicated target-token events in the window.
  Participating-address count is observed transfer participants, excluding the
  zero address; it is not total holder count or unique people. Pool event
  counts refer only to explicitly verified selected pools, not all DEX pools.
- Structural participation/pool/deployer links are distinguishable from money
  transfers. Do not draw membership as a payment or infer malicious ownership.
  The existing token graph uses token-root participation links and supported
  token/pool context; it is not the ETH wallet graph with a renamed root.
- Graph positions remain frontend choices. Reuse the task selector if approved
  Honeypot/Rug Pull graph recipes differ; do not require shared tensors/weights.
- Values use each token's own decimals and units. Missing metadata/decoding
  remains unknown; do not sum quantities of different assets or show zeros as
  fabricated amounts. Counts can still be displayed when units are unknown.
- First/last activity is within the admitted observed scope/window. Daily
  counts distinguish missing coverage from known zero. Normalization and
  timestamp grouping prepare these charts; the current model output does not
  itself contain ready-made frontend analytics.
- Reserve trajectories, buy/sell amounts and liquidity valuation are optional
  later chart modes after verifying pair mapping, decoded amounts, decimals,
  historical reserve state and the appropriate valuation definitions. They
  are not required for the selected event-count chart.

## 4. Applicability and result meaning

An ERC20 contract is a token-task candidate, not automatically a supported
sample. An EOA or unresolved/non-token contract returns an explicit entity
reason. Missing or unsupported pool/DEX coverage affects each task according
to its admitted graph recipe; it is not a low-risk result. This release's Rug
Pull branch requires verified Ethereum Uniswap v2 context and incident evidence.
Honeypot's actual model/pair scope must be declared by its admitted bundle.

Honeypot API evidence must retain its source, detection time, chain/pair and
unknown status. It is label/evidence input for the accepted training route,
not an automatic substitute for our model score or proof of historical state.
Historical inputs respect their own cutoff. A missing sell alone is not
Honeypot; Burn or reserve reduction alone is not malicious Rug Pull.

Retain independent scores, nulls, quality and model/band policy versions. Three
Low/Medium/High bands require the same separate validated display policy as
ETH Scam. Initial Rug Pull describes past/current evidence-backed screening;
future incident-warning claims require a separate evaluation contract.

## 5. Repository evidence

- [Task registry](../../packages/chainrisk/tasks.py)
- [Token and address graph strategies](../../packages/chainrisk/graph.py)
- [Task B delivered scope](../../docs/TASK_B_IMPLEMENTATION.md)
- [Scam task definitions](../../docs/SCAM_TASK_CONTRACT.md)
- [Honeypot configuration](../../research/task_b/configs/honeypot.json)
- [Rug Pull configuration](../../research/task_b/configs/rug_pull.json)
