# Project Contract

## Delivered scope

Chainrisk combines Ethereum token activity forecasting with four independent
scam-screening tasks. Shared graph/model code does not imply shared task labels,
weights, feature meanings, scalers or score calibration.

| Task | Target and interpretation | Delivered model |
|---|---|---|
| Forecast (`continued_activity`) | Token's first-week activity predicts its following 90-day selected-pool swap-volume outcome | Three-seed no-USD edge-aware GCN ensemble, v0.2.0 |
| Phishing | Address screening: Forta positives versus frozen, unverified Poison Hunter background | MeanSAGE, `mean-sage-v1` |
| Ponzi | Source-defined retrospective XBlock/Unica contract screening | MeanSAGE, `mean-sage-v1` |
| Honeypot | Retrospective Trapdoor and captured Honeypot.is selected-pair labels | DirectedEdgeSAGE, `sage-v1` |
| Rug Pull | TokenScout `rugpull` versus source-spelled `truthworthy`, restricted to official Ethereum Uniswap v2 pools | DirectedEdgeSAGE, `sage-v1` |

All four Scam pipelines have collected/prepared datasets and completed model
runs. Source-defined labels do not establish universal benignness, independent
mechanism verification or advance incident prediction. Unknown incident,
label-validity and label-availability times remain unknown; reconstruction
anchors are not incident dates. Phishing is a positive-versus-unlabeled
benchmark, not verified scam-versus-honest classification.

The website provides Home, Forecast, ETH and ERC-20 workbenches. Task results
remain independent. There is no combined safety probability, inactivity-as-fraud
mapping, automatic trading or blocking, universal DEX coverage, or saved-analysis
reopening page. Unavailable scores remain null with explicit reasons.

## Data and model invariants

- Freeze task/entity, source cohort, cutoff/block, graph recipe, labels, split
  and model identities. Keep labels and follow-up outcomes out of inference
  inputs. Historical state must be verified at the relevant cutoff; today's
  state or price is not a historical substitute.
- Task A uses the earliest selected-pool creation as `t0`, with the documented
  first-activity fallback. Observe the first 7 days; label the following complete
  90 days of selected-pool historical Swap USD volume: below USD 1,000 is
  `low_volume_dead`, at least USD 1,000 is `continued_activity`. Mints/burns do
  not add trading volume. Incomplete/unreliable follow-up, USD, pool scope or
  retrieval is censored, never a successful or failed label.
- New Task A sampling uses all eligible labeled rows from a label-blind candidate
  frame, retaining selection metadata and overlap groups. Do not manufacture a
  balanced population. The historical 2,000-token balanced experiments retain
  their own cohort, graph versions and original splits.
- Task A research graphs are wallet → pool → token graphs over first-week swap
  participants. Scam address and token graphs have separate frozen recipes;
  current Scam model caps are 512 nodes and 4,096 edges, not fill-to targets.
  Do not mix legacy/full-history and bounded-recent graph versions.
- Real token/Forecast pool discovery currently supports canonical Ethereum
  Uniswap v2, matching either token side and allowing non-WETH quote assets.
  This does not extend the live adapter to all DEXs or to the research v3 adapter.
- Preserve provenance, exact units, UTC timestamps and event identities. Keep
  native ETH, token quantities and USD distinct; missing observations are not
  zero activity. Credentials and provider URLs with secrets never enter public
  recipes, logs, model packets or frontend settings.
- Frozen source bytes, admitted graphs, splits and trained outputs are immutable.
  Record sample-quality exclusions without replacing roots or inventing empty
  graphs/negative labels. Transport, authentication, quota and integrity failures
  must not be silently converted into sample exclusions.
- Shared checksum-pinned `events.jsonl.gz` observations are replay dependencies,
  not disposable caches. A task snapshot alone may not be a portable archive.
  Preserve failed scratch/evidence and use explicit journaled maintenance for
  storage migration; do not rewrite published training provenance.

## Training and evaluation

- New general Task A and all four Scam workflows use deterministic, stratified,
  entity/group-preserving 90/10 train/validation. `config/model_split.json`
  governs Task A. Keep related token/selected-pool groups together where defined.
  Historical 80/10/10 and chronological holdout results remain separate versions.
- Fit scalers and class weights on training only. For Scam, validation AP alone
  selects checkpoints and early stopping (`patience=25`, `min_delta=0.0001` in
  retained runs); validation macro-F1 selects the binary threshold. Restore the
  saved checkpoint. Do not introduce validation-loss or additional stopping rules
  when describing those runs.
- Report validation Accuracy, class support, Balanced Accuracy, AP, precision,
  recall, F1, FPR and confusion counts/matrices. Validation also selects models
  and thresholds; it is not an independent test estimate. Neither source balance
  nor high AP establishes market prevalence, calibrated risk or online accuracy.
- Keep source/era confounding and cross-graph overlap visible. Current entity/pool
  grouping does not establish campaign/controller-disjoint evaluation. Retain
  simple-model comparisons and negative results alongside graph results.
- Four Scam tasks share `scripts/scam/run_pipeline.py`, `chainrisk-scam` and
  `python -m research.scam`: `sources → collect → prepare → train`, plus `all`
  and `status`. `all` includes training; `all`/`train` require a new `--run` name.
  Existing nonempty model runs cannot be overwritten. Dry runs do not write,
  query providers or fit; a fresh plan is not validation of absent inputs.

## Application and serving

- Vue/TypeScript/Vite calls a modular FastAPI backend. Analysis workers use a
  single-host durable SQLite queue with fenced leases, immutable inputs,
  progressive results and replayable SSE/polling recovery. Multi-host shared
  queue/store deployment is outside the implemented configuration.
- `ANALYSIS_MODE=eth_live` performs real collection and authenticated HTTPS
  inference; unconfigured `template` remains explicitly unavailable. Production
  `demo`, `eth_live_mock`, fixed/random scores and local loopback prediction have
  been removed. No fixture fallback is permitted; unfinished legacy simulated
  jobs cannot become real assessments. Completed history retains its origin.
- Backend-local input contracts live in `apps/backend/config/`. Send canonical
  unscaled graphs with task/sample/target/cutoff/model/scaler identities. The
  model service alone applies the frozen scaler, runs models and supplies
  decisions/display labels; the backend validates, persists and forwards them.
- Release bundle identities are pinned in `deploy/release.json`. Forecast uses
  `continued_activity-b6140c2fdd0cc2e6`, selecting 14 node and 8 edge columns by
  name, without historical USD inputs. Its server-owned threshold is
  `0.5369952122370402`. Scam display bands live in `deploy/registry/` and are
  distinct from trained binary thresholds. All scores remain uncalibrated.
- Modal hosts the model API with CPU, scale-to-zero and one container by default.
  The frontend/backend host is separate; backend runtime needs its input config
  and required shared helpers, not weights, `deploy/` or Modal management tokens.
  Windows/Caddy deployment and portable runtime fixes were delivered; one-off
  Windows packaging/service-install tooling was subsequently removed from the
  repository at the user's request. It is not a maintained deployment option.
- The live backend shares an Etherscan account ledger across processes: at most
  3 request starts/second and 99,000 attempts per UTC calendar day, retries
  included. Exhaustion rejects new work and durably pauses accepted jobs until
  UTC reset without changing the cutoff. Research collectors retain their own
  frozen recipes and runtime safety limits. RPC/feed are outside this ledger.
- ETH/ERC-20 facts, activity and ledgers collect the complete fixed preceding
  30-day root window; neighbor histories do not inflate root totals. Forecast
  observes its creation-based first week instead. Display graphs are separate
  from model sampling: at most 64 nodes (root/first hop ≤48, second hop ≤16) and
  4,096 relations. Publish after collection/enrichment settles; metadata/progress
  updates must not reset an unchanged graph. No model-graph view switch or
  incompleteness badge is added. Ledger cursor pages contain ten rows.
- Home has an independent, single-owned real mainnet RPC feed with SQLite/WAL,
  replayable SSE and OS file locking on Unix/Windows. Publish at most two rows
  per second with positive native ETH values; approximate current USD quotes
  carry source/time/expiry and never become historical model inputs.
- Preserve the approved English glass/space interface, independent task labels,
  exact units, keyboard access and reduced-motion behavior. Progress comes from
  backend work, never frontend timers. Provider/model failures remain explicit.

## Delivery status (replaces the original plan)

These entries consolidate the original P0–P5 roadmap and Task A work packages.
Completed means delivered within the scope above, not every ambition in the
original research plan. Partial or unestablished research items are recorded
limitations, not automatically reopened development work.

| Original work item | Final status | Delivered evidence or remaining boundary |
|---|---|---|
| P0: task definitions and usable label sources | Completed | Two task families, five independent tasks, source/time/label policies and frozen cohorts |
| P0: recover all historical Task A specifications/artifacts | Partial | Historical reports retained; some original schemas, manifests and linked artifacts remain absent locally |
| P1: data products, provenance and task graph infrastructure | Completed | Task A Parquet/SQL/DuckDB builders; Scam JSONL graphs and shared gzip observations; task-specific manifests and quality gates |
| Task A: participant collection and wallet graph | Completed | First-week wallet/pool/token experiments and versioned input contract |
| Task A: EDA and graph/non-graph experiments | Completed | Dated cohort/error reports, matched logistic/graph comparisons, repeated seeds and chronological stress tests |
| Task A: market-context-only, boosted and graph/token/market fusion comparisons | Not established in retained results | Do not claim the full original multimodal/market ablation programme was delivered |
| Task A: 14/30-day and alternative-outcome sensitivity programme | Not established as a complete suite | Historical pilots are not a matched sensitivity study of the released model |
| P2/P3: four independent Scam data/training loops | Completed | Phishing/Ponzi `mean-sage-v1`; Honeypot/Rug Pull `sage-v1`, prepared inputs and model bundles |
| P2: matched Scam tabular comparisons | Partial | Exploratory Honeypot/Rug Pull diagnostics exist; no complete matched four-task benchmark is established |
| Evaluation, leakage and error controls | Delivered with limits | Train-only scaling, frozen grouped splits, validation selection and diagnostics; unknown campaign/controller overlap remains a limitation |
| P3: mechanism simulation and independently reviewed incident truth | Outside final implementation | Graph/source/API screening does not claim full sell simulation or reconstructed malicious-withdrawal ground truth |
| P4: asynchronous API, workers and evidence UI | Completed | Real chain collection, durable jobs, progressive activity/ledger/display graph, independent task outcomes and explicit errors |
| P4: shared live homepage feed | Completed | Independent RPC worker, persistent/replayable stream and source/freshness semantics |
| P4: bundles, remote model serving and reproduction | Completed | Five pinned Release bundles, Modal adapter, server-owned labels, Docker/local reproduction and recorded service verification |
| P4: regressions and recovery checks | Completed | Unified `checks/`, controlled offline fixtures and separate explicit provider/service acceptance tools |
| P4: later-cohort/prospective independent Scam validation | Not established | Retrospective validation and live service verification do not demonstrate future-cohort accuracy |
| P5: relation/edge-aware models | Completed within independent tasks | DirectedEdgeSAGE and edge-aware GCN; no claim of one shared trained encoder |
| P5: pretraining, joint weights and temporal-event GNNs | Outside final implementation | Optional research extensions; no delivered benefit or experiment is claimed |

## Operating references

- [Application setup](apps/backend/README.md) and [frontend](apps/frontend/README.md).
- [Scam data and training](research/scam/README.md).
- [Release/reproduction](deploy/README.md), [Modal](deploy/MODAL.md) and [checks](checks/README.md).

Use the frozen manifest and report for each historical experiment. New revisions
must receive new versioned outputs; documentation cleanup never changes datasets,
weights, labels, thresholds or historical measurements.
