# Project Contract

This is the short governing contract for the whole project. Detailed rules,
schemas, procedures, and run results live in the referenced documents.

## System scope revision: 2026-10-05

The project now combines Task A (token low-volume outcome prediction) and
Task B (classic scam-pattern screening) in a shared data, graph, evaluation,
and eventual serving platform. This is a scope and architecture contract
change; it does not relabel historical experiments or change Task A's
numerical outcome/window/split rules.

The adopted system design is
[SYSTEM_REQUIREMENTS_AND_ARCHITECTURE.md](docs/SYSTEM_REQUIREMENTS_AND_ARCHITECTURE.md).
Task B follows [SCAM_TASK_CONTRACT.md](docs/SCAM_TASK_CONTRACT.md).
Reference-method limitations are documented in
[TRXLLM_REFERENCE_REVIEW.md](docs/TRXLLM_REFERENCE_REVIEW.md).
Task B data and offline training code is implemented as described in
[the implementation guide](docs/TASK_B_IMPLEMENTATION.md). No real Task B
dataset, trained weights, performance results, or online services are released.

The engineering boundary is further specified in
[PLATFORM_ENGINEERING_AND_DATA_GUIDE.md](docs/PLATFORM_ENGINEERING_AND_DATA_GUIDE.md):
a common frontend/platform API routes to independently callable token and
scam backends. They share a versioned graph container and GraphSAGE framework,
not necessarily topology, feature semantics, scalers, or weights. Separate
deployment processes are optional; separate task interfaces, model packages,
data analyses and performance artifacts are required. Preserve historical
reports and keep online assessments distinct from offline benchmarks.

### System-wide rules

Forecast model serving revision requested on 2026-10-25: the Gradio inference
server loads the trained Task A Forecast bundle
(`continued_activity-b6140c2fdd0cc2e6`, Models Release asset
`chainrisk-continued_activity-v0.2.0.zip`). It is the pruned temporal-split
`edge_gcn` three-seed probability ensemble retrained without
`log1p_positive_volume_usd` (node and edge), because live packets carry no
historical USD; labels, splits, architecture and seeds are unchanged, and its
validation/test metrics match the USD model (test AUC 0.942 vs 0.938).
`scripts/export_forecast_bundle.py` verified it reproduces the recorded research
scores. Its validation-selected ensemble threshold (0.537) is the Forecast
policy. Swap-free first-week graphs are scored as in training; backend
eligibility rules are unchanged. This is a model-service change only: backend
real-mode transport and the fixed mock fixture are unchanged. The earlier USD
bundle (`v0.1.0`) stays in the Release for rollback. See [deployment](deploy/README.md).

Model-service ownership revision requested on 2026-10-25: the Gradio inference
server owns trained binary thresholds, Scam risk bands and Forecast decisions,
and returns score plus a categorical/display label and provenance. The backend
validates request/response identity and persists/presents supplied labels without
re-thresholding. It has no runtime dependency on `deploy/`; input-only manifests,
scalers and indexes now ship in `apps/backend/config/`. In `eth_live_mock`, eligible
real inputs receive a fixed service-shaped response: 0.999 / High Risk for Scam,
0.999 / Continued activity for Forecast. This replaces random simulation and
backend-owned decision policies. Missing/incomplete/unsupported inputs stay
unscored; simulation remains explicit and real-model capabilities remain false.
Use a new mock cache identity so recovering old random outcomes cannot reuse them;
completed historical records are not rewritten. Deployment policies stay under
`deploy/registry/`, and real remote transport/Forecast bundle integration remain
separate work. See [the model-service contract](apps/docs/MODEL_SERVICE_CONTRACT.md).
This is an online serving/ownership contract change, not a change to training
weights, input recipes, labels or historical evaluation.

Online-service revision confirmed on 2026-10-24: ETH address facts, Flow
Activity and the Transaction Ledger use the complete fixed preceding 30-day
root-address window. They update incrementally as source batches arrive;
7D/30D controls select the visible activity range. Display graph selection is
independent: at most 64 total nodes, with root plus first hop at most 48 and
second hop at most 16, and 4,096 aggregated directed relations. Neighbor data
is used only for that graph, not added to root-address ledger/flow statistics.
Both hops may search the same 30-day maximum. Publish the graph after root
history and token-amount enrichment settle; progress, score and model metadata
updates must not replay or reset an unchanged graph. No incompleteness badge
is added to the graph. This latest user-confirmed revision supersedes the
previous shared truncated-window requirement. Frozen per-task model sampling
and backend input artifacts remain separate; no model-graph UI switch.
Etherscan has one process-shared 3-start/second and
99,000-attempt UTC-calendar-day budget; RPC/feed are outside this budget.
Reject new work at exhaustion, durably pause accepted work and resume after
00:00 UTC without changing cutoff. Empty/incomplete data, applicability and
provider/model failures remain explicit, unscored states. Actual collection
counters supplement the backend-driven stage/SSE UI. Per-model display bands
are separate from trained binary thresholds. See
[live backend contract and implementation status](apps/docs/LIVE_BACKEND_IMPLEMENTATION.md).
This revises online orchestration/display policy, not training recipes, weights,
labels or historical evaluation. ETH now has a single-host durable SQLite job
queue, real provider collection and fenced analysis workers. At the user's
explicit request, opt-in eth_live_mock mode sends real, recipe/scaler-compatible
inputs to the unavailable local predictor target and generates persisted random
scores. These are tagged simulated in API/artifacts; the frontend keeps its
original text. This exception never admits random scores for missing/invalid
data and never advertises real model availability. Trained serving remains
pending; the subsequently requested Forecast live adapter is described below.

ERC-20 live implementation requested on 2026-10-24 extends the same durable
queue/quota/progress and simulated predictor boundary to token_scam. Token
facts, Transfer ledger, selected-pool event ledger and daily activity collect
the complete fixed preceding 30 days progressively. The independently bounded
64-node display graph (root/first hop at most 48, second hop at most 16) is
published after those logs settle. Resolve ERC-20 state and canonical Ethereum
Uniswap v2 pool membership at the frozen cutoff. Discover either indexed token
position and support non-WETH quote assets; arbitrary DEX/v3 pools remain
outside both current trained recipes. Missing supported pools or incompatible
input yields Unavailable, a null score and the existing small reason text;
valid token facts/activity remain useful. Preserve each token model's frozen
recent collection, graph, scaler and directed edge-aware input contract,
including separate 4100/2771-day model recipe windows, independently of the
30-day display. No training/weights/labels are changed. See
[ERC-20 live adapter](apps/docs/TOKEN_LIVE_ADAPTER.md).

Forecast live revision requested on 2026-10-24 shares the durable worker,
progressive observations/ledger, delayed bounded display graph and provider
quota/cache behavior. Preserve Task A's creation-based first-seven-day window
and wallet--Swap.sender activity-->pool--membership-->token graph, excluding
all post-cutoff events/outcomes. Initial live pool discovery supports the same
verified canonical Ethereum Uniswap v2 subset as ERC-20, including non-WETH
quotes; the research graph's v3 source adapter is not integrated. Reverify
mutable state at the first-week cutoff. Collect the full observation ledger
independent of display limits, publish the graph after collection settles,
and return Unavailable/reasons for unsupported, empty or immature inputs.
At the user's explicit request, send real label-free wallet graph input to the
unavailable local mock target, then persist one random continued_activity score.
Keep an independent replaceable 0.5 temporary decision policy: below is
low_volume_dead; at/above is continued_activity. No Scam risk bands apply.
Historical USD remains missing when unavailable; no current-price substitution.
The unscaled temporary packet explicitly awaits a Forecast deployment bundle
and training-fitted scaler; it never claims trained inference. This changes
online serving only, not Task A labels, graph recipes, fitted parameters or
historical splits/results. See [Forecast live adapter](apps/docs/FORECAST_LIVE_ADAPTER.md).

Online display refinement requested on 2026-10-24 publishes confirmed basic
state and the fixed 30-day observation bounds before activity collection
finishes; history-derived facts then update as observations arrive. ETH external ledger amounts additionally join cutoff-bound Etherscan
ERC-20 transfers by transaction hash and identify assets by token contract and
direction; a zero native value without identified amounts displays Unknown.
Original native value remains available in record details. This extends the
display-data contract only; token observations do not alter ETH graphs, native
flow totals or frozen model inputs. See [the ETH adapter guide](apps/docs/ETH_LIVE_ADAPTER.md).

Unified pipeline revision requested on 2026-10-23 supersedes the earlier
task-specific public stages and data-only all promises below. All four Scam
tasks expose sources, collect (including graph construction), prepare, train,
all and status. all executes through training and requires an explicit --run;
standalone data stages never fit. The file, installed command and module
launchers share research.scam.pipeline; low-level commands are private.
Independent diagnostic audit scripts are removed while required source,
coverage, label, integrity and training-admission checks remain in the pipeline.
Dry runs never write, query providers or fit; fresh snapshots report a plan,
while existing prepared inputs receive actual admission validation. Existing
model outputs cannot be overwritten. This is an execution-interface contract
change, not a frozen data/model/policy migration. See [the unified guide](docs/SCAM_PIPELINE.md).

Workspace maintenance on 2026-10-23 removes superseded Rug Pull snapshots,
unused Honeypot graph plans/pilots and redundant Phishing script wrappers.
The byte-identical Ponzi source copies are consolidated in
data/scam/ponzi/xblock-unica-recent-v1/sources, with the original inspection
records retained beside them. This is storage/entrypoint maintenance, not a
label, cohort, graph, split or training-policy change. Retained prepared inputs,
model runs and referenced shared observations remain unchanged.

Rug Pull training-entry completion on 2026-10-23 is an execution-interface
correction, not a dataset/model/training-policy revision: run_pipeline --task
rug_pull --stage train now shares the checked token training dispatcher with
Honeypot. Require --run, validate frozen prepared inputs before calling the existing
trainer, preserve parameter overrides/dry runs and pin outputs in run_manifest.json.
all/evidence never starts fitting. See the Rug Pull training guide below.

Rug Pull offline-preparation extension requested on 2026-10-23: remove the
temporary external-account process configuration and quota ledger after collection,
then build graphs and prepare the existing TokenScout cohort for the unchanged
trainer. Admit source-defined rugpull/truthworthy supervision only under the
explicit tokenscout-rug-pull-source-adopted-1 retrospective policy, preserving
unknown incident/validity/availability times and source provenance. The default
rug_incidents adapter still requires incident/controller evidence. Freeze audited
sample failures without replacement, enforce the existing token/pool-grouped
90/10 train/validation split and validate the actual training command without
fitting. Training remains a separate explicit user command. See
[the Rug Pull training guide](docs/RUG_PULL_TRAINING_PIPELINE.md).

Training-monitor precision correction on 2026-10-23: show loss and validation /
saved-best AP to six decimal places so near-one values are not displayed as 1
by tqdm's default significant-digit formatter. This is a presentation correction;
the AP-only checkpoint/min_delta/patience rules, frozen datasets, splits and
existing weights/metrics are unchanged. The Honeypot graph diagnostic report
separates mixed-source and source-specific validation, and treats high pooled
AP as a retrospective result rather than evidence of prospective generalization.

Rug Pull collection extension requested on 2026-10-22 supersedes the earlier
label-only prohibition for explicit plan/collect/build-graphs/graphs stages.
Freeze the existing metadata-verified TokenScout cohort without reselection or
new cutoff resolution; reuse its verified targets through the existing bounded
token collector and graph recipe. all/evidence still ends at the label-quality
summary. Fitting and training preparation remain separate and unstarted.
ETHERSCAN_API_KEY remains a process environment override; ETHERSCAN_QUOTA_FILE
may select an independent persistent ledger for a different account. Neither
credentials nor account quota paths belong in dataset recipes. Unset overrides
retain existing collector defaults. See [the collection guide](docs/RUG_PULL_COLLECTION_PIPELINE.md).

Rug Pull label-preparation revision requested on 2026-10-22: use the frozen
TokenScout token_labels_processed.csv and token-dict.json as a source-defined
retrospective cohort. Map rugpull to 1 and truthworthy (source spelling) to 0;
exclude other classes, invalid/missing/ambiguous address mappings and conflicting
token labels, deduplicating repeated same-label addresses. Audit all source rows,
then default to 1,000 deterministic source positives and all source negatives
before pool queries, with no replacement after pool/metadata failures. Restrict
this preparation to canonical Ethereum Uniswap v2 pools, verified at
the source-coverage end anchor 2023-02-28T23:59:59Z, separately from unknown label
validity/availability and incident times. These source labels are not independently
confirmed malicious-withdrawal incidents and must not fabricate incident/controller
evidence. run_pipeline --task rug_pull all/evidence performs only sources -> audit
-> discover -> verify -> prepare (label-quality summary). It rejects transaction
collection, graphs and training; these remain unstarted under this request.
The existing data-processing and training recipes are unchanged. See
[the Rug Pull preparation guide](docs/RUG_PULL_LABEL_PREPARATION.md).
The user's same-day follow-up removes the initial WETH-only discovery restriction:
new snapshots index all official v2 PairCreated metadata through the anchor and
match both token sides, regardless of quote asset. Preserve all discovered pool
memberships; select one pool per token using WETH/USDC/USDT/DAI priority, then
earliest creation, independently of labels. The initial WETH-only snapshot is
retained. Factory creation logs are pool-identity metadata, not trading histories.
The report distinguishes no official-v2 match from no pool on any DEX.
The user's subsequent selection instruction supersedes the initial pre-query
1,000-positive pilot: first match the full cleaned source to supported pools,
then choose exactly 1,500 metadata-valid positives and all metadata-valid source
negatives. Freeze the hash-ranked eligible order; if a positive has invalid token
metadata, retain the exclusion and advance to the next eligible positive until
the quota is met. No transaction collection or graph creation is authorized here.
Canonical Factory PairCreated evidence plus cutoff-bound factory.getPair can
supply the immutable pool token/factory identity; historical RPC decimals supply
token units. This equivalent metadata snapshot passes the same token_scope
contract without synthesizing RPC getter responses. Freeze the verification
method in the pool recipe and preserve the complete source evidence.

Honeypot recovery/progress correction requested on 2026-10-21: DNS resolution,
network-unreachable/reset/disconnect and timed-out transport failures stop the
current batch and enter the runner's bounded automatic retry policy. They and
cancellation of other in-flight roots must never become data-quality exclusions.
Before graph/dataset publication only, resume may archive and reopen legacy
transport/cancellation exclusions with original bytes/checksums and a recovery
ledger; genuine sample-quality exclusions and already-published experiments
remain frozen. Keep successful graphs/observations and raw scratch for replay;
reset stale active-root status after an aborted batch. Use the same two-fixed-row
NestedSampleProgress as Phishing/Ponzi, retaining four-sample concurrency and
all per-root states in durable JSON. The inner query denominator grows as log
ranges/pages are discovered; it is not an estimate of all remaining history.
TTY sessions render the two bars; redirected logs retain periodic text summaries
without ANSI animations. This corrects execution/recovery/presentation, not
frozen cohorts, labels, cutoffs, graph recipes or training splits.


Honeypot combined-run revision requested on 2026-10-21: adopt the source-defined
Trapdoor labels and frozen contemporary API candidates for one retrospective
supervised experiment, after cutoff-bound pool verification and graph quality
checks. Use 2023-01-31 23:59:59 UTC (1675209599) for both Trapdoor classes, the
chosen month-end reconstruction bound for the paper's May 2020–January 2023
coverage, not an incident or label-known-at date. Keep historical validity and
availability null. Contemporary roots keep their individual frozen checked_at.
The existing snapshot's new all-recent-v1 plan includes both cohorts (3,494
selected token/pool roots; 3,431 distinct tokens); the old contemporary-only plan
is preserved. The settings may select both cohorts and the historical anchor;
existing plans take priority on resume. Preserve source/time provenance in
prepared supervision and disclose mixed-source/time confounding and lack of
independent mechanism validation. Raw evidence is never silently rewritten as
reviewed ground truth. All pools of a token stay in one 90/10 train/validation
partition; no separate test set or early-warning claim. The explicit train stage
uses the generated frozen config and normal AP-only early stopping. all ends at
prepare-training; model fitting remains an explicit train invocation.
New graph stages use four concurrent samples by default, one shared Etherscan
2.5-start/second persistent quota budget and one paced/cached RPC client.
Publish lossless normalized token observations in the shared gzip store with
selected-pool/block/recipe-specific identities; pin the reference before cleaning
only successful private raw scratch and redundant local event files. Retain
failed scratch, RPC verification evidence and source/API captures. Existing shared
raw caches are never cleanup targets. ETHEREUM_RPC_URL uses the same ignored
literal-only local_secrets.py loader as Etherscan (environment overrides it);
never store URLs/keys in public recipes, logs or model artifacts. See
[HONEYPOT_GRAPH_PIPELINE.md](docs/HONEYPOT_GRAPH_PIPELINE.md).


Honeypot graph-run revision requested on 2026-10-21 supersedes the earlier
evidence-only runner limit. run_pipeline supports plan/verify/collect/build-graphs
and graphs orchestration. Default contemporary graphs use each frozen API
checked_at; historical Trapdoor graphs require an explicit per-run retrospective
observation anchor, recorded separately from unknown source label-validity and
incident times. Both cohorts retain separate source/time provenance. Immutable
graph-run plans pin targets, labels and budgets; changing them requires a new
graph-run name. The new token-v2-recent-1.0 view uses verified cutoff-bound token/
pool identities, descending ordinary/internal records and newest-first log-range
scans (getLogs has no assumed descending sort). Default 100 rows/action/emitter
and at most three progressive rounds stop at node/edge budget, source exhaustion,
or record budget. Preserve 32/16 topology and 512-node/4096-edge maxima. Recipe
coverage is distinct from full history; never invent edges to fill a sparse graph.
Successful samples resume without querying again; finite-retry sample-local
failures may be recorded/excluded by default under the user's prior instruction.
Provider/authentication/quota/integrity and missing historical-RPC capability
stop execution. Graph creation does not admit labels, combine source cohorts into
a model dataset, or fit weights. Legacy complete-window token views remain valid
and cannot be silently mixed with the new view. all now proceeds through graphs;
evidence retains the previous evidence-only sequence. See the Honeypot guide.

Honeypot evidence/cohort revision requested on 2026-10-20: preserve the
Trapdoor positive/non-malicious CSV bytes at one repository revision and audit
addresses, pools, duplicates, conflicts and missing temporal evidence. Keep
source-defined historical labels separate from contemporary API detections.
Select 1,000 distinct Ethereum Uniswap v2 TOKEN/WETH targets by fixed-seed hash
sampling of complete PairCreated logs over a frozen default 180-day range,
excluding all valid Trapdoor tokens before sampling. The supplement is
unlabeled, not a guaranteed negative cohort. Capture explicit chain/token/pair
Honeypot.is results with raw evidence and candidate labels. Finite per-request
retries may exclude sample-local failures with recorded reasons; do not recheck
unknowns, replace roots or manufacture negatives. Authentication/quota/integrity
and incomplete discovery coverage stop the stage. Honeypot run_pipeline all
ends at evidence/readiness, not graph collection or training. Historical CSVs
have no per-sample label time: never invent one or use today's API capture to
backdate labels. Structural checks do not constitute independent ground-truth
validation or human admission review. Later graph/90:10 contracts remain in force.
See [HONEYPOT_OFFLINE_PIPELINE.md](docs/HONEYPOT_OFFLINE_PIPELINE.md).

Task B AP-only early-stopping restoration requested on 2026-10-20:
validation AP alone controls checkpoint selection and early stopping. An AP
increase greater than `min_delta` saves the model and resets patience; stop after
`patience` consecutive epochs without such improvement, or at the epoch limit,
then restore that saved model. Compute and report training loss, but do not
compute validation loss or maintain additional stopping counters/candidates.
Validation scoring runs in eval/inference mode. Macro-F1 still selects the
classification threshold. Training overrides are recorded per model run without
rewriting frozen datasets, collection recipes or the retained original weights.
Validation-reuse disclosure and Accuracy-first final reports remain unchanged.
See [Ponzi training controls](docs/PONZI_OFFLINE_PIPELINE.md#validation-monitoring-and-model-selection).

Ponzi offline cohort/input/execution revision requested on 2026-10-20:
merge the frozen XBlock and Unica positive address lists, deduplicate by entity,
and exclude the two conflicting labels from both classes. The resulting cohort
has 247 positive roots (249 before conflict removal) and 1,000 deterministic
XBlock source-negative roots, selected before inspecting graph availability.
Use the user-confirmed UTC end-of-day reconstruction anchors 2018-11-22 for
XBlock and 2017-05-07 for Unica; shared positives prefer the XBlock anchor.
These source-date bounds do not establish per-contract incident times or
label-known-at dates. This is an explicitly retrospective, source-defined
supervised experiment. Preserve unknown validity/availability dates; do not
fabricate temporal evidence. Collect source-specific bounded descending graphs
with the Phishing 100-record/action and 32/16-neighbor recipe, shared quota,
atomic per-root publication, compact replay storage and audited optional failure
exclusions. No root replacement or automatic training occurs. The independent
Ponzi model follows the existing 90/10 validation protocol. See
[PONZI_OFFLINE_PIPELINE.md](docs/PONZI_OFFLINE_PIPELINE.md) for exact semantics,
commands, paths and the count correction.

Collection-failure selection revision requested on 2026-10-20: the bounded-recent
Phishing pipeline can freeze recorded sample failures as training exclusions
with `--drop-failed` at preparation. This supersedes the unconditional rule that
any failed root blocks preparation. Preserve the original collection manifest,
failure reasons/records and unfinished scratch; keep cohort/source bytes and
published graph inputs unchanged. Do not invent empty graphs, replacement roots
or negative labels. Missing/unattempted targets, authentication, quota and
integrity failures cannot be dropped. In the unattended all-stage runner,
retry recoverable roots first, then apply the explicit exclusion policy after
the attempt budget ends. A frozen checksum-pinned exclusion ledger persists
across resumes; excluded roots are not retried. `complete` then means every
cohort root is published or explicitly excluded; `download_complete` separately
records whether every root downloaded successfully. Quality exclusions still
pass through normal label/graph admission. Model selection retains 90/10 P/U
semantics. See the current Phishing pipeline guide for the command and audit paths.

Training/evaluation contract revision requested on 2026-10-20: new Task A and all
four Task B training workflows use class-stratified, group-preserving **90/10
train/validation**, with no independent test partition. This supersedes earlier
80/10/10 and locked-test requirements for new training. Keep the full eligible
population; a 1:1 validation quota is not required. Freeze assignments before
model selection, fit scalers/weights on train only, and select checkpoints and
thresholds on validation. Final reports identify validation Accuracy as the
primary reported metric and retain Balanced Accuracy, per-class support, F1,
raw confusion counts and confusion matrices normalized by actual label. Mark
validation as reused for selection, never an independent/unbiased test estimate.
Historical split files, reports and weights remain unchanged; new trainers
reject legacy test partitions instead of silently dropping or reassigning them.
Create a new versioned split/output from the retained eligible inputs. This
changes model preparation/evaluation only, not frozen collection inputs, labels,
graph recipes, historical results or completeness/admission gates.

Lossless storage revision requested on 2026-10-16 supersedes the local replay-copy
promise below. New bounded-recent samples keep graphs, targets, audits and a
checksum-pinned shared observation reference. Canonical normalized replay events
are stored once as `events.jsonl.gz` in the shared observation store; no fields or
observations are removed. Graph/cohort/query identities are unchanged. Existing
pre-preparation snapshots can be explicitly migrated with an offline journaled
tool: verify originals, compress exact bytes, validate physical and decompressed
SHA256s, publish per-item manifests, delete verified redundant event copies, then
finalize the collection index under the migration guard and snapshot lock.
Interrupted migration blocks pipeline execution until that same command resumes.
Keep failed scratch, source/cohort evidence and quota accounting. Shared replay
inputs are now required for complete replay and resume; copying only a task
snapshot is no longer a portable archive. Published training provenance is never
silently rewritten by maintenance. See the storage/migration procedure in
[PHISHING_OFFLINE_PIPELINE.md](docs/PHISHING_OFFLINE_PIPELINE.md).

Live-data recovery refinement on 2026-10-15: failed contract creations with a
known sender and no resulting contract address are retained as audit-only facts;
no destination or graph edge is invented. Ordinary missing participants remain
invalid. The receipt guard allows eight **new lookups per root per attempt**;
previously cached validated receipts do not consume that budget. Exhaustion is a
resumable checkpoint, automatically retried within the runner's attempt budget,
not a permanent rejection of a root needing a ninth receipt. History bounds and
the global rate/daily/byte limits remain unchanged. This refines normalization
and recovery semantics; it does not invalidate already completed valid samples.

Collection progress presentation revision requested on 2026-10-15: interactive
recent collection uses two fixed terminal rows (completed roots and the oldest
active root's query/phase progress). Preserve concurrent collection; retain all
active roots' progress in the durable JSON. Bound refreshes and terminal width,
forward terminal geometry through log wrappers, and exclude cursor animations
from text logs. Redirected `--progress on` emits periodic plain summaries. This
changes monitoring/presentation only, not cohort identities, collection bounds,
retention or resume rules.

Collection recovery correction on 2026-10-15: real cached ordinary-history rows
can contain contradictory `isError` and `txreceipt_status` fields. The bounded
collector resolves such conflicts only through a matching transaction receipt
(hash, block number/hash and participants), retaining both source flags and the
receipt evidence. Receipt verifications share the normal rate, retry and byte
budgets and the resumable new-lookup guard above. Unresolved conflicts remain failures; raw fields
are never silently rewritten. A local sample failure no longer cancels unrelated
roots; account-wide authentication errors still stop collection. Retry transient
failures even when another root has a deterministic data failure. Recovered
failure records are archived, and permanent failures block dataset publication.
This corrects execution/recovery behavior without changing the frozen sampling
or label contract. Existing complete samples remain valid.
The same real-cache audit found nonunique provider `traceId` values for distinct
internal-call records. The recent adapter assigns ambiguous transactions stable
observed-record identities (immutable field digest plus within-address occurrence),
deduplicates overlapping histories, retains repeated observed calls and original
trace IDs, and preserves root-transfer suppression. It does not infer canonical
EVM trace paths, import unseen calls or add routine verification queries for this
identity correction. Generic/legacy conflicting-event checks remain strict.


Etherscan rate correction requested on 2026-10-15: live provider responses report
`Max calls per sec rate limit reached (3/sec)`. The user selects a global
**2.5 request starts/second** ceiling across all in-process HTTP workers,
superseding the earlier 4.8 ceiling below. Concurrency remains enabled. Lowering
the runtime safety ceiling does not mutate frozen snapshot recipes or invalidate
completed samples: effective rate is the minimum of the frozen configured rate
and this ceiling. Restart the collector to load the new ceiling; preserve quota
accounting and resumable caches. This changes the execution contract only.

Shared-background storage revision requested on 2026-10-15: source-listed
unlabeled address master pools live in `data/shared/address_pools/ethereum/`;
task snapshots freeze a `background_ref.json` and retain their selected cohort
exports. Task-neutral compact observations live in
`data/shared/observations/ethereum/`, keyed by address, cutoff timestamp/block,
exact query recipe and provider origin. The recent Phishing pipeline publishes
and reuses this store; other task pipelines must explicitly adopt compatible
inputs before reuse. Task labels, graph admission, splits and weights remain
independent. This is a storage/recovery contract revision, not a universal benign
label or shared-model claim. See
[PHISHING_OFFLINE_PIPELINE.md](docs/PHISHING_OFFLINE_PIPELINE.md).


Phishing bounded-recent revision requested on 2026-10-15 supersedes the earlier
full-history default for **new** snapshots. Freeze Forta's cutoff and query
backwards: at most 100 ordinary and 100 internal records per queried address,
32 most recent distinct first-hop counterparties and 16 per second-hop boundary,
with no older-page expansion. Use all eligible Poison Hunter background roots
and an equal deterministic Forta subset (currently 1,154 + 1,154). The background
remains unlabeled. `scam-recent-egonet-2.0` explicitly describes bounded observed
statistics, not complete lifetime histories. Publish each graph and compact
normalized replay inputs atomically, then delete only its scratch raw responses;
failed samples retain resumable scratch data. Raw-response re-parsing is no
longer promised after cleanup. The user confirmed a 5-calls/second API plan and
selected a shared 4.8-starts/second ceiling, with 10 HTTP workers, up to four
active root samples and persistent 95,000-attempt rolling-24-hour accounting.
This is a cohort/input/execution/retention contract change. Old snapshots retain
their frozen recipes; model admission must reject mixed graph versions. See
[PHISHING_OFFLINE_PIPELINE.md](docs/PHISHING_OFFLINE_PIPELINE.md).

Offline workflow/storage revision requested on 2026-10-15: Phishing uses Forta
positives and explicitly unlabeled background cohorts, with an unattended staged
runner, bounded automatic retries, durable status/logs, atomic dataset publication
and frozen-parameter resume. Historical address pools and exact raw Etherscan
requests may be shared across tasks; labels, graphs, splits and weights retain
task-specific admission. This is an engineering contract change, not a benign
label or shared-weight revision. The real `forta-2022-v2` address-only snapshot
is preserved; real transaction collection and formal fitting remain pending.
Canonical code/data/model paths and limitations are defined in
[PHISHING_OFFLINE_PIPELINE.md](docs/PHISHING_OFFLINE_PIPELINE.md).

Etherscan setup revision on 2026-10-15: the user selects one serial collection
task, a 2.5 requests/second runtime cap and project-local `local_secrets.py`
credentials, excluded from Git. Persistent rolling-24-hour accounting caps local
attempts at 95,000, including retries, and waits automatically for quota. No
machine/shell configuration or cross-process coordination is introduced. A
three-request live endpoint probe passed. The user subsequently started real
collection; complete dataset preparation and fitting remain pending. Performance
refinement preserves complete ascending history prefixes, uses request-start
pacing, deduplicates repeated raw-source references and adds live request telemetry.
These are collector implementation changes; frozen task/sampling semantics remain
unchanged. See [performance diagnosis](docs/PHISHING_COLLECTION_PERFORMANCE.md).

Token offline pipeline revision requested on 2026-10-15: implement the complete
Honeypot and Rug Pull training lifecycle, while deferring real training execution
and backend analysis integration. Both tasks become trainable with independent
GraphSAGE weights. `token-v2-scoped-2.0` adds mechanism features and an explicitly
verified token/selected-pool emitter coverage policy; Ponzi/Phishing inputs remain
unchanged. Honeypot captures/imports reviewed API-defined pair-specific labels;
Rug Pull uses reviewed v2 incident/negative observations. Labels never become
model features, and neither task gains a future-event forecast claim. This is a
task-stage and token-input contract revision. See
[TOKEN_SCAM_TRAINING_PIPELINE.md](docs/TOKEN_SCAM_TRAINING_PIPELINE.md).

Forecast application revision requested on 2026-10-13: replace the placeholder
and discarded frontend-only implementation with the canonical analysis job/result
workflow. Forecast uses the backend frozen fixture adapter, shared workbench,
persisted jobs and replayable progress events. Its `forecast` family has one
`continued_activity` task: first-seven-day observations, followed by a 90-day
selected-pool swap-volume outcome at the USD 1,000 boundary. No real models or
external analysis APIs are integrated. Fixture scores are synthetic and
uncalibrated, and never carry scam risk bands. This extends the application
contract without changing Task A research rules. See
[analysis adapter integration](apps/docs/ANALYSIS_ADAPTER_INTEGRATION.md).

Workbench interaction revision requested on 2026-10-13: ETH and ERC-20 open with
one centered address field; submission transitions to a three-column frosted-glass
workspace. Analysis context and independent risk results form a sticky left rail,
Graph View occupies the center, Basic Information/activity the right, and a
ten-row paginated ledger spans the center and right below. Redundant explanatory
copy and graph plot labels are removed; node/edge summaries remain available on
hover/focus. This changes page interaction/presentation, not data fields or task
semantics. See [workbench glass refinement](apps/docs/WORKBENCH_GLASS_REFINEMENT.md).

Homepage feed integration revision requested on 2026-10-13: implement the adopted
single-owned real Ethereum mainnet RPC feed with a separate collector, bounded
sampling, receipt enrichment and replayable SSE. PublicNode is the default source,
overridable with a server-only RPC URL. The local application uses SQLite/WAL and
an OS ownership lock shared by API readers and one worker; multi-host deployment
requires a shared transactional store/lease. The feed is enabled independently of
analysis demo mode. The subsequent homepage refinement publishes at most two rows
per second, filters strictly positive native ETH values, and adds approximate USD
amounts from a separately cached public Coinbase ETH/USD quote with explicit
source/time and expiry. Etherscan links remain inspection links only. See
[feed integration](apps/docs/FEED_INTEGRATION.md).

Application integration revision requested on 2026-10-13: an explicitly enabled,
removable synthetic analysis adapter exercises the ETH smart-contract and ERC-20
workbenches with backend delays, replayable progress events and production-shaped
response envelopes. This extends the application contract, not model admission.
Default template mode remains unavailable; demo responses retain synthetic origin
in API metadata and capabilities never claim real weights. The user requested no
demo marker in the local testing UI. The saved-analysis page, browser route and
all reopen-history controls are removed by the same user request. Analysis IDs
remain internal job/artifact identities. See
[analysis adapter integration](apps/docs/ANALYSIS_ADAPTER_INTEGRATION.md).
The subsequent demo-only input revision accepts any syntactically valid Ethereum
address and selects one of two frozen JSON scenarios by page family. Transaction
data and outcomes stay fixed; only address aliases and job/sample identities are
bound to the request. This does not broaden real task/model scope.

Website navigation refinement confirmed on 2026-10-12: use Forecast / ETH /
ERC-20, with the Chainrisk brand returning Home. Preserve existing ETH/Token
analysis URLs and workflows; Forecast adds only a `To be implemented`
placeholder. Home keeps the shared ETH RPC transaction-summary dashboard.
This is a navigation-only contract revision; Task A integration remains deferred
and task/model/data contracts are unchanged. See
[website architecture](apps/docs/WEBSITE_ARCHITECTURE.md) for the route mapping.

Documentation convention revised on 2026-10-09: project Markdown documentation
is written in English, with language-neutral filenames. The former `zh-CN`
guides have been translated and renamed, and their references updated. This
changes documentation language and naming, not task scope or historical results.

Implementation boundaries are further specified in
[TASK_B_CODEBASE_AND_SERVING_PLAN.md](docs/TASK_B_CODEBASE_AND_SERVING_PLAN.md)
(2026-10-08 codebase refinement): additive Task B research modules and a shared
Python runtime package. The website architecture revision adopted on 2026-10-12
is [WEBSITE_ARCHITECTURE.md](apps/docs/WEBSITE_ARCHITECTURE.md): reconstruct the Vue/Vite
frontend, use a modular FastAPI application, a separate analysis worker with
process-local model loading, and a separate single-owned homepage RPC feed.
This supersedes the unimplemented Nuxt/Nitro plan; a separate inference HTTP
process is optional when resources justify it. Theme tokens, UI primitives and
a semantic icon adapter allow later style/icon replacement. Preserve Task A
entrypoints and artifacts until checkpoint/input compatibility is verified.
The website templates are now implemented as recorded in
[TEMPLATE_DEVELOPMENT.md](apps/docs/TEMPLATE_DEVELOPMENT.md); collection, durable
jobs, model serving remains unimplemented; the homepage feed is implemented separately as recorded above. The 2026-10-08 scope revision admits a fourth Task B
mechanism: Ethereum Uniswap v2 malicious liquidity withdrawal. The 2026-10-15 offline revision makes Honeypot and rug-pull trainable with
versioned selected-pool inputs. Historical execution simulation remains future
work; real data collection, formal fitting and backend analysis integration are
explicitly deferred.

Task B uses `packages/`, `research/scam/`, and `checks/`.
TaskSpec, source adapters, graph strategies, backbone and loss registries share
code without sharing task weights. The user-selected local environment is
the existing arm64 Python 3.11 `.venv`, managed by the root `pyproject.toml`
and `uv.lock`. Task A scripts and historical artifacts are preserved; its
previous remote environment is not silently migrated. This release is code
and synthetic engineering checks only: no real training data collection or
formal model training. Applications and deployment were excluded from that
offline release; the separate 2026-10-12 website scaffold supplies only empty
frontend and explicit unimplemented backend integration boundaries.

Repository layout adopted on 2026-10-08: user-facing projects live under
`apps/`; the reference Vue/Vite demo has moved to `apps/frontend/`.
`deploy/` contains documented placeholders for inference_service, worker
and registry. The old demo has been replaced by the Vue/Vite template, and `apps/backend/`
contains a runnable FastAPI shell plus class/method templates. Real model
serving remains unimplemented. The later homepage feed revision is recorded above. Deployment owns
operations; backend application logic will live in `apps/backend/`. These
design additions do not change Task A training entrypoints or experiment rules.

- Keep activity outcomes and scam labels separate. No inactivity-as-fraud
  mapping, unknown-as-benign mapping, or unvalidated universal risk score.
- Share event provenance and graph/experiment interfaces; version each task's
  entity, window, features, graph semantics, labels, split and model artifacts.
  Shared GraphSAGE code does not imply compatible checkpoints or shared weights.
- Exclude post-cutoff information from inputs. Distinguish event validity,
  external evidence availability, retrieval time, and label maturity.
- Preserve source disagreements and incomplete data. Independent evidence or
  mature outcomes are required for supervised labels; live collection alone
  is not supervised training data.
- Make unlabeled inference independent of training labels. Scores carry task,
  cutoff, quality, model version and calibration status; missing scores remain
  null with an explicit reason.
- Audit cross-task entity/campaign/time leakage before fitting shared weights
  or pretraining. Evaluate each task independently against matched baselines.
- Require data/model admission, later-cohort or prospective shadow evidence,
  operating measurements and rollback checks before broad live claims.
  Research and service readiness are separate acceptance decisions.

## Read first

- docs/GRAPH_WALLET_INPUT_CONTRACT.md: wallet-enriched graph input and
  participant-field rules.

- `GOAL.md`: purpose, scope, claims, and deliverables.
- `PLAN.md`: project stages, model sequence, leakage controls, and gates.
- `config/label_specification.json`: primary and sensitivity label rules.
- `config/event_schema.json`: normalized event fields and identifiers.
- `config/market_context_schema.json`: point-in-time market features.
- `config/model_split.json`: primary general split and evaluation rules.
- `docs/COHORT_SAMPLING_AND_CLASS_BALANCE.md`: candidate sampling and quotas.
- `docs/DATA_ENGINEERING_WORKFLOW.md`: Parquet, SQL, DuckDB, and data checks.
- `docs/WEEK1_GRAPH_VOLUME_LABELS.md`: label rationale and source evidence.

The label, event and market-context JSON specifications referenced above were
not present in this checkout at the scope review. Recover and version them
with experiment artifacts before claiming reproducibility; do not invent
their past contents. `config/model_split.json` remains the current Task A
split contract. The following sections govern Task A specifically.

## Task A non-negotiable rules

- The wallet-enriched graph is a versioned model-input revision. Its first
  graph is wallet --swap activity--> pool --contains--> target token, with one
  separate target-token graph per token. It requires cutoff-bounded swap
  participant fields; the existing pool-counterparty graph artifacts do not
  satisfy this input contract.

- Study Ethereum token contracts in a fixed, documented set of selected DEX
  pools; use one canonical row per token.
- Define `t0` from the earliest selected-pool creation, with the documented
  activity fallback. Use the first 7 days for features and the following
  complete 90 days for the primary outcome.
- `low_volume_dead` means selected-pool swap volume below USD 1,000;
  `continued_activity` means at least USD 1,000. Swaps alone count toward
  volume. Use historical positive `amountUSD`; do not backfill current prices.
- Mark incomplete or unreliable follow-up, pool scope, retrieval, timestamps,
  or USD evidence as `censored`. Never turn censored rows into a class or use
  them to fill a quota.
- Build candidates label-blind and retain selection probabilities and strata.
  After complete labels exist, use the complete eligible labeled population;
  do not require a fixed 50/50 development quota. Apply the general token-
  level split in `config/model_split.json`: 90% training and 10% validation
  within each label and launch-period stratum, keeping overlap groups
  together. A prior 500/500 cohort is a historical pilot artifact, not the
  current sampling contract.
- The split is class-proportional, not a single global row split: with 1,000
  active and 1,000 dead rows, assign 900/900 to training and 100/100 to
  validation, subject to overlap-group adjustments.
- Use only data available by the 7-day cutoff as model input. Follow-up events,
  outcomes, censoring fields, and post-cutoff market data are not features.
- Keep raw bundles, manifests, normalized Parquet tables, SQL/DuckDB outputs,
  outcomes, censoring, splits, features, graphs, and model artifacts auditable
  and traceable to source rows.

## Project flow

The data product and modelling stages must treat the wallet-enriched graph as
a new input version. It keeps the token-level labels and split, but requires
participant-field collection, wallet-pool aggregation, and a separate
leakage audit before it can produce results.

1. **Feasibility:** freeze sources, schemas, windows, labels, sampling, and
   evaluation; verify access, coverage, historical USD, and retrieval quality.
2. **Collection:** discover and screen candidates without labels, collect full
   histories, assign outcomes, and build sampling and split manifests.
3. **Data product:** follow `docs/DATA_ENGINEERING_WORKFLOW.md` to produce
   validated Parquet and DuckDB/SQL model tables.
4. **Modelling:** compare heuristics, market and token baselines, static
   GraphSAGE, and graph/token/market fusion on the same split.
5. **Delivery:** report metrics, figures, reproducibility details, limitations,
   and negative results.

Temporal GNNs and graph pretraining are optional explorations. They require a
separate data contract and leakage audit before being treated as results.

## Evaluation and release gate

Use the general token-level train and validation partitions defined in
`config/model_split.json`. Audit duplicate or related launches and overlapping
graph neighborhoods. Fit transformations, thresholds, and calibration on
training/validation data only. Report validation Accuracy as the primary final
number, explicitly noting that validation also selected the model and threshold.
There is no independent test estimate in this protocol. Report class support,
Balanced Accuracy, raw and row-normalized confusion matrices, dataset prevalence, average precision,
precision, recall, macro-F1, false-positive rate, `Precision@K`, and
sampling-weighted metrics where relevant. A chronological partition may be
reported as a secondary stress test when it has adequate class support.

Do not claim final GNN performance until completeness, censoring, source
limitations, class support, split support, and leakage checks pass. Every
released result must record source and retrieval date, code/configuration
versions, counts, uniqueness and time checks, split metadata, model inputs,
seeds, metrics, and resource use. Never expose `.env` secrets.
