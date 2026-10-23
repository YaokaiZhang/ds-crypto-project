# ETH Scam layout content specification

> Presentation revision, 2026-10-13: [Workbench glass refinement](WORKBENCH_GLASS_REFINEMENT.md)
> supersedes the earlier ETH/ERC-20 query/panel composition, graph plot labels,
> workbench typography and panel material below. It preserves field inventories,
> task/model meanings, graph provenance and inspection semantics. Home, shared
> navigation and accepted background styling retain their own authority.

Date: 2026-10-12. Status: selected first-release display scope, recorded at the
user's request. This revision supersedes this document's earlier broad panel
catalog and layout alternatives. It determines content, not visual styling.
Application code and services are not implemented by this documentation change.
Token Forecast is deferred.

This is a UI scope refinement, not a change to Task B labels, entity definitions,
graph/model input recipes, training or research acceptance. The separate [website architecture revision](WEBSITE_ARCHITECTURE.md) now defines
Vue/Vite plus FastAPI; this content specification does not redefine its service
boundaries. The
[platform design review](FRONTEND_AND_SERVING_DESIGN_REVIEW.md) remains background;
this document governs the selected ETH Scam display inventory.

## 1. Direct answers

Transaction Graph visualizes the exact GraphSample used for the current task's
inference, or an explicitly disclosed display subset. Training and prediction
use compatible schemas, features and graph recipes. The view is not a graph
borrowed from the training set: it is constructed from the queried entity's
cutoff-bounded data. Node coordinates are frontend layout choices and are not
model inputs. Readable edge metadata can be shown even when a particular model
(e.g. MeanSAGE) does not consume it; the bundle's consumed_inputs is authoritative.
Display original directed chain relations, not synthetic reverse message edges.

One multi-column Basic Information panel is sufficient for account state and
window summaries. Keep five content modules: Risk Screening, Basic Information,
Transaction Graph, Funds Flow & Activity, and Transaction Ledger. Query/identity
and a compact provenance/status footer complete the inventory. No additional
standalone metric-card row is required.

Funds-flow lines, daily transaction counts, transaction tables and activity
heatmaps are feasible from indexed timestamped address histories. They require
normalization and aggregation, not additional ML. The existing default Task B
collector already fetches txlist and txlistinternal. Frontend-ready analytics
and balance/type enrichment still need application adapters. Paging, source
coverage and double-counting are the main data concerns; chart preparation
itself is straightforward after histories are valid. Select one combined daily
funds/activity chart and one transaction table; defer the heatmap and other
supplementary panels.

## 2. Complete selected layout inventory

The following table is the complete first-release page-element list. Detailed
field tables below define exactly what belongs inside each element.

| ID | Layout element | Internal fields / controls | Description |
|---|---|---|---|
| L1 | Query and identity bar | Ethereum address; account type; assessment cutoff| Enter one address and identify the object assessed. Chain is fixed to Ethereum; cutoff defaults to a frozen latest snapshot, with historical entry optional. |
| L2 | Risk Screening panel | Independent Phishing and Ponzi rows/cards: task, applicability/status, score/risk band | Primary analysis outcome. Preserve task-specific scores and meanings; no combined platform safety score. |
| L3 | Basic Information panel | ETH balance and state timestamp/block; observation window; external tx count; successful/failed/unknown external counts; successful internal-transfer count; ETH inflow, outflow and net transfer; unique native counterparties; first/last observed activity in window | One box arranged in multiple columns. State values and historical-window statistics carry different time/scope labels. |
| L4 | Transaction Graph panel | Task selector when applicable; target/root; nodes and roles; original directed relations; observed edge counts/amounts; node/edge selection details; fit/zoom; model/display counts; graph window/version; sampling/cropping label | Render the current task's actual model graph, not an independently generated illustration. If both tasks differ in graph recipe, switch between them. |
| L5 | Funds Flow & Activity panel | UTC date axis; daily successful native ETH incoming/outgoing series; daily unique external transaction count as aligned bars; hover date/amount/count; optional 7D/30D display filter within available history | One combined time-series panel replaces separate heatmap and transaction-count plots. Two aligned subplots share time; ETH and counts have separate labeled axes. |
| L6 | Transaction Ledger panel | External Transactions / Internal Transfers tabs; time; hash; from/to; target-relative direction; ETH value; success/failure/unknown status; method selector/name when available; block; pagination; transaction detail | Chronological transaction sequence in a table. External row unit is a transaction; internal row unit is an indexed transfer event. |

Top-level navigation and responsive styling are outside this content decision.
Transaction-hash entry is a later optional resolver mode; first-release input is
an address. ERC20 transfer tabs are also outside the selected ETH-native scope.

## 3. Exact internal field dictionaries

### 3.1 Query and identity (L1)

| Field / control | Description / source |
|---|---|
| Input address | Validated Ethereum address; preserve readable checksum form if available. |
| Analyze | Starts an analysis job; displays real phases and errors rather than fixed-timer transitions. |
| Target address | The actual root being assessed; copy and external explorer link. |
| Network | Ethereum mainnet, chain ID 1; no unsupported chain selector. |
| Account type | EOA / Contract / Delegated / Unresolved, resolved at assessment cutoff. Use code/state plus role/type resolution; unverified source does not imply EOA. |
| Assessment as-of | Frozen cutoff timestamp and block identity used by model and window statistics. |

### 3.2 Risk Screening (L2, repeated independently per task)

| Field | Description |
|---|---|
| Task | Phishing or Ponzi. |
| Applicability / execution status | Eligible, Not applicable, Unsupported model scope, Entity unresolved, Collecting, Model unavailable, Insufficient data, Failed or Completed. These are proposed service/UI states, not all existing runtime codes. |
| Model score | Numeric task output when available; null otherwise. It is not a calibrated scam probability by default. |
| Risk band | Low / Medium / High under a separately validated, versioned two-cutoff display policy; unavailable until that policy exists. |
| Model decision | Existing task-specific threshold result (screen_positive / screen_negative); keep it distinct from the three display bands. |
| Observation window | Actual start and cutoff used by this task's bundle recipe. |
| Model version | Bundle identity for reproducibility; compact display or expandable details. |
| Reason / score meaning | Explain unavailable results; model details include P/U benchmark meaning and calibration status where applicable. |

The current runtime implements scores and one binary threshold, not three risk
bands or account applicability routing. Adding a display band policy does not
redefine the underlying binary task. Low Risk is not a guarantee of benignness.
Scores remain null when unavailable; never fill zero or mark green.

### 3.3 Basic Information (L3, one multi-column box)

| Field | Description / computation | Source |
|---|---|---|
| ETH balance | Current native balance, decoded from Wei using exact decimal arithmetic. Historical balance is displayed only when historical state is available. | account.balance; optional historical RPC / balancehistory |
| Balance state time/block | State provenance where known, otherwise retrieval time and latest-state scope; never invent an exact block. For historical assessment, present-day balance stays labeled Current and outside model inputs. | State response / application snapshot |
| Observation window | Start, cutoff and UTC timezone for all following window statistics. | Analysis metadata |
| External transaction count | Number of unique root-associated external tx hashes, including calls and failures. | txlist |
| Successful / failed / unknown external count | Status breakdown; missing execution status is unknown. | txlist status / receipt |
| Successful internal-transfer events | Qualifying indexed internal events; not independent signed transaction count and not full execution-trace coverage. | txlistinternal |
| ETH inflow | Sum of successful canonical native transfers into root during the window, excluding self-transfers and reverted value effects. | Normalized external/internal transfers |
| ETH outflow | Same scope for transfers out of root; gas is excluded. | Normalized external/internal transfers |
| Native net transfer | Inflow minus outflow; explicitly excludes gas and is not balance change or profit. | Derived |
| Unique native counterparties | Distinct non-root endpoints on successful native transfers in the window; an address count, not a people count. | Derived from complete collected root history |
| First observed activity in window | Earliest root-associated external tx or indexed internal fact in the collected window, including failed external activity where recorded. | txlist / txlistinternal |
| Last observed activity in window | Latest such activity no later than cutoff. | txlist / txlistinternal |

Do not label window-first activity Wallet creation or lifetime age. If no
activity exists, first/last are null. No nonce, USD portfolio value, token
holdings, lifetime counts or lifetime age are required in this release.
Incomplete collection uses Observed count/amount with a coverage warning rather
than presenting totals as complete. Metrics use root history before graph
neighbor sampling; graph-only statistics are separately labeled sampled scope.

### 3.4 Transaction Graph (L4)

| Field / control | Description |
|---|---|
| Active task / graph reference | Bind analysis ID, task ID and sample ID; switch Phishing/Ponzi only when applicable, with the active graph clearly named. |
| Root node | The queried and individually assessed address. |
| Nodes | Stable address references, local IDs and supported role/features; frontend derives coordinates. |
| Original edges | Source/target, original direction and relation type from GraphSample. No extra chain edges from reverse message passing. |
| Edge details | Event count, asset/units, readable amount when recoverable, observed times and contributing event/transaction references from lineage. Log-scaled tensor attributes are not directly presented as raw ETH. |
| Node details | Address/role, sampled in/out activity, whether individually assessed and related events; missing metadata stays unknown. |
| Provenance | Actual graph view/feature version, observation dates, sampling settings and displayed/model node/edge counts. |
| Controls | Fit, zoom/pan and node/edge selection. Filtering/cropping affects display only. |

The current GraphSample carries node_refs, root_index, edge_index, node_features,
edge_attributes, relation_ids/names, quality and lineage. A display adapter maps
these into readable nodes/edges and joins retained source events where necessary.
The existing default is trailing 30 days, two hops, fanouts 32/16, at most 512
nodes and 4096 aggregate edges; the approved model's frozen recipe governs an
actual request. Matching adjacency alone is insufficient: features, scalers,
relations and task-specific bundles must also match training.

If Phishing/Ponzi consume equivalent topology under compatible recipes, one
visual layout can be reused; retain each task's graph identity and feature/model
provenance. If recipes or cutoffs differ, use the task selector and display the
corresponding graph. The UI does not imply one shared tensor or model weights.

### 3.5 Funds Flow & Activity (L5)

| Field / control | Description |
|---|---|
| UTC date/time axis | Initially daily bins over the admitted collection window. |
| Incoming ETH | Daily successful canonical native inflow to root. |
| Outgoing ETH | Daily successful canonical native outflow from root, excluding gas. |
| External transaction count | Daily unique external root-associated tx hashes, with the same definition as Basic Information. |
| Hover details | UTC date, incoming ETH, outgoing ETH and external tx count. |
| Display range | Optional trailing 7D / full 30D inside the same frozen snapshot; only offer ranges actually collected. |
| Missing-data indication | Distinguish known zero days from uncovered days; never draw a missing interval as zero or interpolate across it as fact. |

Use two aligned plot areas within one panel: native ETH flow above and transaction
count bars below. Changing display range does not change the model graph or score.
Changing the assessment cutoff creates a new analysis. No heatmap or additional
transaction-time chart is included: their main activity information is represented
by these count bars and the ledger.

### 3.6 Transaction Ledger (L6)

| Field / control | Description |
|---|---|
| Source tabs | External Transactions / Internal Transfers; preserve different row units. |
| Time (UTC) | Event timestamp; chronological sort. |
| Transaction hash | External explorer link; internal entries share their enclosing hash. |
| From / To | Full addresses in details; abbreviated in table; contract creation handles missing To explicitly. |
| Direction | IN / OUT / SELF / CALL as applicable relative to root; no manufactured counterparty for creation. |
| ETH value | For successful monetary effects; failed rows show attempted value only if explicitly labeled Attempted. Zero-value calls retain zero. |
| Status | Success / Failed / Unknown, distinguishing source execution fields. |
| Method | functionName/selector when available on external calls; unknown ABI stays selector/unknown; not required for internal rows. |
| Block | Block number and relevant transaction inclusion provenance. |
| Pagination | Backend pagination/sorting; no requirement to load all records into the browser. |
| Transaction detail | Internal event identity/trace ID, raw attempted value/status, calldata/receipt and root-paid external gas fee if available. |

Successful fund sums exclude reverted effects. Deduplicate external txs and
indexed internal events with their own identifiers, and reconcile overlapping
representations rather than counting one value twice. Calls are not transfers.
Gas is counted once per external transaction and attributed to its actual payer;
a contract recipient does not inherit the caller's gas expense.

### 3.7 Data / Assessment status (L7)

| Field | Description |
|---|---|
| Sources | Normal/internal indexed histories; optional balance/code/contract metadata. |
| Coverage | Requested/collected interval, completed paging, request gaps and field missingness; no unsupported coverage percentage. |
| Cutoff/block | Immutable assessment snapshot identity; distinct from current-state enrichment. |
| Retrieval time | When data was fetched; not the event time. |
| Sampling/cropping | Intentional graph sampling versus failed collection, and model/display counts. |
| Model details | Per-task versions, score/threshold/band policy and calibration/benchmark meaning. |
| Analysis ID / task errors | Reopen result and explain partial/failed tasks. |

## 4. EOA versus Contract applicability

| Resolved target | Ponzi | Phishing | Layout behavior |
|---|---|---|---|
| Ordinary EOA | Not applicable: contract task | Address task; eligible subject to model scope/data | Use all common elements. |
| Supported contract | Contract task; eligible subject to model scope/data | Address task can apply to a malicious phishing-role contract; do not disable solely because bytecode exists | Same elements; add a small contract metadata subsection inside Basic Information. |
| Contract outside an admitted Phishing model's entity scope | Independent Ponzi applicability | Unsupported model scope, null score; not automatically Low Risk | Keep both risk cards and explicit reasons. |
| Delegated/smart-wallet/unknown type | Resolve role/type and admitted task scope first | Resolve admitted task scope first | Keep common elements; unresolved/unsupported reasons replace scores as appropriate. |

The task registry defines Phishing entity=address and Ponzi entity=contract.
Label admission requires task-appropriate malicious roles, not simply interaction
with a phishing address. There is no EOA-only Phishing gate in the current code,
but that does not prove a future trained bundle generalizes to all contract
addresses. A provider/account type should not be confused with a model's supported
population. Model scope should be explicitly recorded at serving admission.

No real deployed Task B weights currently exist: type eligibility does not imply
that a live score is already available. Missing models retain Model unavailable.

## 5. Contract-specific fields (inside L3, not a new panel)

| Additional field | Description / source |
|---|---|
| Contract name | Verified metadata from getsourcecode if available; otherwise Unknown. |
| Source verification status | Verified / Unverified / Unknown; verification is source publication, not a safety judgment. |
| Creator address | Source-backed deployer identity from getcontractcreation if available; no inherited scam label. |
| Creation transaction / time | Creation hash and confirmed timestamp when resolvable; distinct from first activity in the 30-day window. |
| Proxy / implementation | Report only supported metadata, with its time scope; current implementation is not assumed historical. |

All common fields and charts remain usable for contracts. Balance is contract-held
ETH; inflow/outflow include indexed internal transfers under the same rules.
External count is associated external transactions, not proof that the contract
signed them. Preserve units, status and coverage. Metadata failures do not remove
usable graph/model results. Method appears in the existing ledger column when known.

## 6. Deliberately excluded from the selected release

Heatmap; separate activity line chart; counterparty ranking panel; behavior/radar
scores; network price/Gas ticker; token holdings/transfers; approval exposure;
public label panel; risk history; watchlist/notes; USD portfolio/P&L; historical
balance chart; expandable whole-chain graph. These remain possible future work,
not requirements or hidden fallback content. Retained evidence/provenance lives
in L7, not a separate expanded dashboard.

## 7. Data availability and implementation boundary

Normal/internal histories, cutoff normalization, graph construction and offline
model prediction interfaces exist. Selected charts/tables need deterministic
root-history aggregation and a display API; graph drawing needs a GraphSample
adapter, not another model. Current balance/type/contract metadata need enrichment
adapters. Etherscan supports the underlying history, balance and contract endpoints,
but account entitlement, indexed coverage and source fields must be checked.
Historical balance is optional and must not be fabricated from current state.

Front-end styling and a new prototype are out of scope for this update. Three-band
risk classification, routing/applicability statuses, source enrichment, aggregation
and HTTP service fields are recorded requirements, not claims of implemented code.

## 8. Acceptance

- Exactly L1-L7; five content modules plus query/identity and compact status.
- Graph is bound to the actual task input sample, with any display cropping disclosed.
- Task applicability follows entity/role/model scope; contracts do not automatically disable Phishing.
- Basic metrics and chart/ledger aggregates share root-history definitions and observation window.
- Unknown/missing/failed/unavailable values remain explicit; zero only means observed zero.
- Current state and historical assessment remain temporally distinguished.
- Contract-specific information is a conditional subsection, preserving the common layout.
- Model performance and live-serving admission remain separate from layout completion.

## 9. References

Repository definitions:

- [Task registry](../../packages/chainrisk/tasks.py)
- [GraphSample and graph strategies](../../packages/chainrisk/graph.py)
- [Model bundle and prediction](../../packages/chainrisk/bundle.py)
- [Role-aware label admission](../../packages/chainrisk/labeling.py)
- [Default Phishing configuration](../../research/task_b/configs/phishing.json)
- [Scam task contract](../../docs/SCAM_TASK_CONTRACT.md)

Primary API references:

- [Normal transactions](https://docs.etherscan.io/api-reference/endpoint/txlist)
- [Internal transactions](https://docs.etherscan.io/api-reference/endpoint/txlistinternal)
- [Native balance](https://docs.etherscan.io/api-reference/endpoint/balance)
- [Account code](https://docs.etherscan.io/api-reference/endpoint/ethgetcode)
- [Contract source metadata](https://docs.etherscan.io/api-reference/endpoint/getsourcecode)
- [Contract creator and creation](https://docs.etherscan.io/api-reference/endpoint/getcontractcreation)
- [Receipts](https://docs.etherscan.io/api-reference/endpoint/ethgettransactionreceipt)
- [EIP-7702 account delegation](https://eips.ethereum.org/EIPS/eip-7702)
