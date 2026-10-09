# TrxLLM review: reusable methods, factual corrections and GraphSAGE adaptation

Review date: 2026-10-05; reference paths updated: 2026-10-09. Reference:
[competition report v7](../../Ref/信安大赛文档6.8版v7.pdf), 73 PDF pages.
Page references below use **PDF page numbers**; printed page numbers are usually
four lower. Text extraction and rendered checks covered data definitions, graph
structure, model equations, distributions and result tables. The accompanying
Vue reference is now under `apps/frontend/`; it establishes only the supplied
local implementation scope.

Task B now implements target-centered graphs, separate direction/relation
handling, amount/time messages and root classification; see the
[implementation guide](TASK_B_IMPLEMENTATION.md). It reuses attribute-graph and
sampling ideas, not proprietary experiments, GIN + Transformer or maximum
transaction-score aggregation.

The target-centered workflow—bounded history, local attributed interactions,
then task-specific classification—is useful. Several blockchain definitions
require correction, and proprietary performance figures or UI screenshots do
not establish reproducibility for our GraphSAGE. A complete system does not
require copying the large-model architecture.

## 1. What the report proposes

| Component | Description | Pages | Relevance |
|---|---|---|---|
| Transaction graph | Hash/address input; historical transactions and neighborhood expansion; accounts as nodes, transfers/calls as edges | 14–22 | Reuse problem decomposition and target-centered local graphs |
| Attributes | EOA/contract fields, amount/gas/block data and traces; textualization with BPE/vectorization | 21–25 | Use field coverage as a checklist; encode numeric, categorical and temporal semantics first |
| Graph analysis | GIN-style aggregation explicitly consumes edge embeddings, followed by a decoder Transformer | 26–30 | Motivates edge-aware research; differs from MeanSAGE |
| Pretraining | Masked node/edge attribute recovery followed by downstream fine-tuning | 30–34 | Optional separately budgeted extension |
| Downstream tasks | Malicious transactions, address risk and contract function-name recovery | 33–34, 49–50 | First two partially overlap our scope; function recovery is not necessary for activity prediction |
| Application | Queries, graph display, risk labels and live pages | 56–64 | Useful information organization; does not replace service acceptance |

The default temporally nearby range is approximately 30,000 blocks, with
multi-hop expansion. Our tasks require a fixed observation window strictly
bounded by cutoff. Nearby events after a target transaction cannot support
early detection; equal block counts do not guarantee equal elapsed days.

The equation `ReLU(x_j + e_ji)` consumes edge representations. The original
Task A training script consumes node matrices and connectivity only; storing
attributes does not make a model use amount, direction or traces.

## 2. Limits of the data and reported experiments

The report describes 213,857 pretraining transactions from a MetaTrust
collaboration, 83,170 downstream malicious transactions and 5,000 risk addresses.
The supplied report/frontend does not include complete proprietary samples,
split manifests, training code, weights or configurations. Public alternatives
can support independent experiments, but not claims of reproducing these results.

### 2.1 Internal ambiguities

| Item | Observation | Consequence |
|---|---|---|
| Counts | p39 lists 26,820, 13,208, 10,017, 9,735, 8,726, 7,199 and 7,456: **83,161**, nine short of 83,170 | Reconcile against the original manifest before treating counts as verified |
| Classes | p39 says six but lists seven including safe; attack/laundering names differ between p38 and p39 | Do not infer one mutually exclusive label dictionary |
| Split | p38 mentions train/validation/test; p49–50 primarily describe random 80/20 | Validation selection, time/attack-family separation and duplicate audits are unclear |
| Transaction metrics | p49 reports precision 0.9244, recall 0.9017, macro-F1 0.9123 and micro-F1 0.9122 | Not an expected 92% accuracy for our task, data or thresholds |
| Address metrics | p50 headers list accuracy, recall, micro-F1 and balanced accuracy; prose is inconsistent | Do not interchange precision/accuracy or macro/micro across tables |
| Risk features | Nodes include third-party GoPlus risk information | Shared-source or post-incident features may create shortcuts; ablation evidence is insufficient |
| Address aggregation | p39 samples 20 transactions when more exist and takes the maximum risk category | Sampling omission, sample-size effects and victim-role confusion; not a calibrated address probability |

These are consistency and reproducibility limitations, not allegations of
fabrication. Stronger assessment requires dictionaries, splits, independent
feature ablations and runnable artifacts. Visualizations and random holdout
results alone do not establish later-period or unseen-attack generalization.

## 3. Blockchain descriptions to correct

Addresses as entities and timestamped attributed interactions as edges are
appropriate high-level concepts. Protocol documentation should define the facts.

| Report statement | Correction and project handling |
|---|---|
| p16: access/cache includes accounts and private keys | Access lists contain addresses and storage keys; private keys are not written into transactions. [EIP-2930](https://eips.ethereum.org/EIPS/eip-2930) |
| p17 table 2.2.2 swaps Balance/Nonce meanings | Balance is an account balance; nonce is an account-state counter. Do not reuse the incorrect dictionary. [Ethereum accounts](https://ethereum.org/developers/docs/accounts/) |
| p16: Code/API and timestamps are ordinary transaction fields | Calls contain calldata; creation transactions contain initcode. Source/ABI/function interpretations require extra sources; time is associated through the block. Separate native fields and annotations. [Ethereum transactions](https://ethereum.org/developers/docs/transactions/) |
| p16: Type means transfer/deployment; MaxFee means maximum gas quantity | Separate envelope type from business event, and gas limit/used, per-gas price and fee cap with units. [Ethereum transactions](https://ethereum.org/developers/docs/transactions/) |
| p17: deployed code and state are immutable | State changes through execution; proxies can change execution logic. Roles depend on block state and patterns. EIP-7702 allows EOA code delegation, so code presence is not a timeless binary identity. [EIP-7702](https://eips.ethereum.org/EIPS/eip-7702) |
| p18: honeypot uses the defensive-system definition | Define contract exploit lures and deceptive token sell restrictions separately. HoneyBadger studies contracts luring attackers with apparent vulnerabilities, which differs from modern sell-restriction tokens. [USENIX paper](https://www.usenix.org/conference/usenixsecurity19/presentation/ferreira) |
| p22: calltrace fully explains internal behavior | Geth callTracer primarily returns call frames with optional logs. Opcode/storage execution tracing is separate, and internal Solidity names are not automatically recovered. [Geth tracers](https://geth.ethereum.org/docs/developers/evm-tracing/built-in-tracers) |
| p22: hash/topics can be removed as meaningless | Hashes should not become memorized supervised features, but must retain provenance. Topics support event decoding. Feature filtering and evidence preservation are separate |
| p33–34, 50: hexadecimal function identifiers are invalid names | The first four ABI calldata bytes are a function selector, not inherently invalid data or unique source semantics. ABI/signature candidates and context are needed. [Solidity ABI](https://docs.soliditylang.org/en/latest/abi-spec.html) |

Uniswap v3 `Swap.sender` initiates the swap and receives its callback; it can be
a router rather than the ultimate trader. Treating it as wallet identity is an
operational definition requiring role limitations and sensitivity analysis, not
a network of identifiable people. [Uniswap v3 event interface](https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolEvents.sol)

### 3.1 Suggested project description

> The system constructs temporal attributed graphs from Ethereum address
> entities and on-chain interactions. Transactions, receipts and logs provide
> raw evidence, supplemented where needed by account/contract state at specified
> blocks and execution traces. Addresses can have participant, token, pool and
> deployer roles; roles do not identify natural persons. External transactions,
> calls, token transfers and DEX swaps are modeled separately and linked through
> transaction hashes, log indices or call paths. Local graphs use a fixed
> historical window per target, containing only information existing by cutoff
> and satisfying source-availability rules.

Follow this description with the actual source coverage. It must not imply
complete collection of all traces, assets and protocols.

## 4. Mapping TrxLLM to GraphSAGE

| TrxLLM design | Adaptation | Status |
|---|---|---|
| Transaction/address input center | Token activity uses a token root; scam graphs use the target address/contract | Reuse the idea with separate graphs |
| Account expansion | Budgeted pre-cutoff incoming/outgoing funds and call neighborhoods, with recorded sampling | Shared mechanics and task adapters |
| Textual node/edge fields | Numeric log/scale, category encoding, time offsets and missingness; decide text inputs separately | Preserve auditable semantics before tokenization |
| Edge-aware GIN + Transformer | Native MeanSAGE baseline and independently evaluated directed/relational SAGE | Different architecture, not a reproduction |
| Summed endpoint embeddings | Directed concatenation plus event attributes if a transaction task is added | Symmetric sums cannot distinguish reverse direction or repeated distinct transactions |
| Masked pretraining | Optional train-period events excluding held-out targets | Requires a separate data/leakage contract |
| Maximum transaction risk for addresses | Address-root head with external evidence kept separate | Do not equate local transaction scores with malicious-address probability |
| Multiple tasks | Shared data/graph/training code, independent heads and calibration | Shared weights are optional |

At minimum, compare tabular summaries, MeanSAGE and direction/relation/edge-aware
SAGE on the same cohort. Match feature budgets or add equivalent neighborhood
statistics so more information is not mistaken for an architectural gain.
BPE/Transformer experiments follow this comparison.

## 5. Why Honeypot classification needs more than a graph

Graphs can suggest buy/sell asymmetry or control relationships. Missing successful
sells cannot distinguish no attempted sells, missing approval, slippage, route
errors, pauses, blacklists or dynamic taxes. One successful seller does not prove
universal sellability.

Store three outputs separately:

1. Graph screening score from a versioned token graph, reflecting learned patterns.
2. Rule/state evidence with restrictions, permissions, failures, sources and blocks.
3. Simulation evidence under a fixed fork/block, caller, balances, allowance,
   route, amount, slippage and full buy/sell sequence; unknown failures stay uncertain.

Simulation uses an isolated environment without real signatures or asset
transactions. Results apply only to tested states and conditions. GoPlus can
provide external evidence, with unknown/missing values and query time recorded,
but is not sole independent truth. [GoPlus fields](https://docs.gopluslabs.io/reference/response-details)

## 6. Implementation and reproduction

The p64 latency comparison supports measuring collection, graph construction
and inference separately. Its seconds are not our SLA: models, services, cache
hits, hardware and neighborhoods differ.

`apps/frontend/src/views/TradeIdentification.vue` routes two known hashes to
specific result pages; `RealTimeData.vue` redirects after five seconds. These
supplied paths do not show real analysis requests. This observation does not
rule out a backend that was not provided.

The practical route is existing data engineering and small-graph GraphSAGE,
strict scam adapters, independent supervision, label-free inference and a future
evidence API. Large-model training, function-name recovery and cross-chain tasks
are outside the main path. Goals, source decisions, shared components, experiment
gates and deployment plans are in the
[system architecture](SYSTEM_REQUIREMENTS_AND_ARCHITECTURE.md).
