# Phishing offline pipeline

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

Revision: 2026-10-20 (90/10 train/validation; lossless shared-gzip storage retained). The adopted default is a **bounded, descending, retrospective
address graph**, with equal Forta positives and Poison Hunter background roots.
This is an input, cohort, execution, shared-storage and retention contract revision. Background
labels remain **unlabeled**, and results remain a P/U benchmark. No real model
fitting or performance evaluation has been performed.

## Model-stage split and reporting revision (2026-10-20)

New preparation uses a deterministic, class-stratified and entity/group-preserving
90/10 train/validation split, without a test set. For the current 950 usable
positives and 1,108 usable backgrounds, the intended counts are train 855/997
and validation 95/111, subject to grouping adjustments. Do not discard background
rows to force 1:1. Background remains unlabeled, not verified benign.

`training_summary.json` stores `metrics.validation` (Accuracy, Balanced Accuracy,
F1, support, raw confusion counts and a matrix normalized by actual-label rows)
and `final_report.accuracy`. The evaluation metadata explicitly marks validation
as reused for checkpoint/threshold selection and no independent test estimate.
The standalone evaluator defaults to validation. Matched tabular baselines use
the same partitions and report the same interpretation. No real fit is started
by this revision. Frozen source/cohort/collection identities and existing graph
bytes remain unchanged; preparation freezes the new `scam-split-2` manifest.
Legacy prepared 80/10/10 artifacts/runs are preserved and need new versioned
splits before use with the new trainers (see the Task B README). The failure
exclusion policy below can resolve recorded failed roots before preparation.

## Dropping failed roots before preparation (2026-10-20)

The user chooses to omit failed collection roots from training. For a bounded-
recent snapshot with recorded failures, prepare offline with:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --snapshot forta-recent-v1 --stage prepare --drop-failed --progress on
```

This records each missing root's address, sample/input identity and failure
reason in `collection/failure_exclusions.json`, saves the byte-identical original
collection manifest as `collection/pre_exclusion_manifest.json`, and pins the
cohort and failure-record checksums. No replacement root, empty graph or negative
label is invented. Failure records and raw scratch remain available for audit.
Unattempted/missing roots and authentication/quota/checksum problems stop with
an error; the flag cannot bypass graph corruption or label/split admission.

After this explicit decision, `recent-collection-3` records `complete=true` when
published plus excluded roots account for the whole frozen cohort. It separately
records `download_complete=false`, the failure-exclusion count and reasons.
This is an audited dataset selection, not a claim that failed downloads succeeded.
`prepared/dataset_manifest.json` pins both the resolved collection and exclusion
ledger. Its graph/supervision files retain successful insufficient-history
outcomes for audit; training admission excludes those unusable graphs as before.

Repeat the same command after interruption. Once the ledger exists, ordinary
prepare/collect resumes honor it without the flag and do not retry excluded roots.
The frozen selection cannot change after dataset publication. Collecting an
omitted root later requires a new dataset version.

For future unattended collection followed by preparation, use:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --snapshot NEW --stage all --run NEW_RUN --allow-network --drop-failed --max-attempts 20 --progress on
```

The runner first retries unfinished recoverable roots within the attempt budget.
When it stops retrying, preparation freezes recorded sample failures and continues
if the remaining data pass admission. This option applies to the recent profile;
legacy full-history inputs need a separately defined selection policy. Preparation alone does not train; `--stage all --run NAME` continues through fitting.

Local execution on 2026-10-20 completed this preparation for `forta-recent-v1`.
Of 2,308 frozen roots, 2,306 published outcomes remain and two recorded failures
are explicitly excluded. Normal graph admission excludes 248 insufficient-
history outcomes, leaving 2,058 trainable graphs: train 855 positive + 997
background, validation 95 positive + 111 background. Prepared artifact/input
checksums and the MeanSAGE training dry-run passed. No model fitting was started.

## Adopted sampling policy

The cutoff is the frozen Forta source timestamp: **2022-10-06 18:27:48 UTC**
(1665080868) in the current snapshot. Start at that cutoff and look **backwards**;
never use later events. The cutoff is a source-file boundary, not an incident date.
The Poison Hunter list was published later, so this is a retrospective experiment,
not a simulation of which labels were known in 2022.

For each root:

1. Query `txlist` and `txlistinternal` with the frozen `endblock`, `sort=desc`,
   `page=1`, `offset=100`. Both actions succeed or the sample remains unfinished.
2. Normalize the at most 200 returned records and select up to **32 distinct
   counterparties**, ordered by most recent observed interaction. Address order
   breaks timestamp ties. Fewer than 32 is allowed; repeated transfers to one
   counterparty do not become multiple nodes. A creation uses its created contract
   as the counterparty when the API's `to` field is empty.
3. Query the same two latest-100 actions for each selected first-hop address,
   using the **same cutoff**. Select up to **16** observed counterparties per
   first-hop node. Do not request histories for second-hop boundary nodes.
4. Retain original direction and relation, aggregate repeated events, and bound
   the graph at **512 nodes / 4,096 aggregate edges**. Features describe the
   bounded observed subgraph; degrees and amounts are not whole-history totals.

A full 100-row page means the event sample reached its budget. It is not a
failed query and does not trigger older-page traversal. Record this as sampling
truncation. Provider errors, malformed rows, wrong addresses, non-descending
blocks and post-cutoff records remain failures. An empty root can produce an
`insufficient_history` exclusion; it never becomes an inferred benign example.
No replacement roots are selected based on graph availability or model results.

`startblock=0` remains the API's permissive lower bound. The stored `window_days`
is 2,626 to permit older activity for inactive historical addresses. **Neither
setting causes traversal from genesis:** descending order plus the one-page
budget controls retrieval. There is no 2,626-day completeness claim. The new
view is `scam-recent-egonet-2.0`, sampling mode `recent_bounded_v1`; lifetime/hash
samples and checkpoints have incompatible recipes despite equal feature widths.

## Cohort

`data/scam/phishing/forta-recent-v1/` is prepared with:

- 1,154 eligible unique Poison Hunter background addresses;
- 1,154 deterministic hash-selected Forta positive addresses;
- 2,308 total roots and no RPC-discovered background supplement.

Only explicitly named phishing-tag roles become Forta training positives.
Other accepted public positives remain exclusion evidence for background roots.
Canonical background status stays `unlabeled`; CSV `training_target=0` is only
its P/U comparison target. `--per-class N` optionally caps both source cohorts.
Without that flag, use all eligible reference backgrounds and equal positives.
Data-quality exclusions can make final training support unequal; the report
must retain the actual support, and insufficient split support stops preparation.

The source-listed background **master pool** lives under
`data/shared/address_pools/ethereum/poison_hunter-<source-sha-prefix>/`.
It retains all valid source candidates, including candidates excluded by a
particular task's positive evidence. Each task snapshot freezes a
`background_ref.json` with the shared path and manifest checksum. Its cohort
TXT/CSV files are task-specific selections/exports, not independent master pools.
These are unlabeled candidates; sharing the pool does not certify benign labels
for any of the four tasks. Different source bytes create a new immutable pool.

## Concurrency and call budget

Live responses reported a **3 calls/second** provider limit despite the earlier
upgrade confirmation. The user therefore selected a project ceiling of
**2.5 request starts/second**, shared by all HTTP workers in the process, with a
persistent **95,000-attempt rolling-24-hour limit**. Retries consume that same
budget. At the daily limit, the process waits and resumes without interaction.

Defaults are **4 active root samples** and a shared pool of **10 HTTP workers**.
This allows I/O overlap even for roots with very few neighbors. Root workers use
a separate pool so waiting for their HTTP futures cannot exhaust the HTTP pool.
The quota lock covers only reservation/accounting, never the duration of an HTTP
response. There is no coordination across independent processes or machines.
Request start spacing is at least approximately 400 ms; latency already consumes this
interval. Each response has a 4 MiB byte guard. A 16 MiB raw-response budget per sample
prevents successful publication of unexpectedly large inputs; queued requests for
that sample are cancelled on overflow. Responses already in flight can temporarily
overshoot the scratch-disk budget, and the failed scratch remains available for
inspection. This guard is a terminal failure, never a silently truncated success. SIGINT/SIGTERM cancels queued roots
and wakes quota waiters; already-running HTTP requests finish or time out.

At defaults, each root makes **2 × (1 + first-hop count) <= 66 history queries**,
plus retries when necessary. Contradictory ordinary-transaction execution flags
trigger supplementary `eth_getTransactionReceipt` verification, at most **eight
new lookups per root per attempt**. Cached validated receipts do not consume this
new-lookup budget. Exhaustion records a resumable checkpoint; the runner retries
unfinished roots within its attempt budget, using saved receipts to make progress.
An initial uncached pass therefore uses at most 66 history + 8 verification
lookups before retries; a completed root can reference more verification queries
accumulated over multiple attempts. Receipt calls use the same 2.5/sec quota,
daily accounting and per-sample raw-byte guards. The cutoff
lookup is shared by the whole snapshot.
Across 2,308 roots the no-retry worst case is 152,328 history queries, requiring
more than one local daily quota if every root fills its neighbor budget. Most
sparse roots use fewer calls; no real-run median is claimed before collection.
Completed-sample query medians, graph-byte medians and maximum query counts are
saved in the collection manifest. Failed samples are separately reported.

For a conflict such as `isError=0` and `txreceipt_status=0`, neither list field is
silently preferred. Require the receipt's transaction hash, block number/hash and
participants to match; a valid receipt status then determines ordinary-transaction
execution. Retain original flags, receipt query/hash/retrieval metadata and the
resolution in the normalized audit/event lineage. A root receipt cannot resolve
the success of an individual internal trace. Missing/mismatched receipt status
remains an explicit failure. These are verification calls, not extra history pages;
sample manifests distinguish `history_query_count` and `verification_query_count`.
Failed `create`/`create2` records can legitimately have an empty `to` and empty
created-contract address: execution failed before a contract existed. When the
sender and failed execution are known, retain the fact and its source/error/amount
metadata under `failed_creations_without_address` in the normalization audit.
Do not invent a destination, deployment or transfer edge. These audit-only facts
do not inflate graph activity. Other missing-participant records still fail.
Receipt field semantics follow the
[Ethereum execution API specification](https://ethereum.github.io/execution-apis/api/methods/eth_getTransactionReceipt/).

Real cached responses also demonstrate that an Etherscan `traceId` can be reused
for distinct internal-call records in the same transaction. It is therefore not
a unique canonical call identity. When this ambiguity occurs, the recent adapter
uses a digest of immutable observed record fields plus the occurrence within one
queried address's history. Equal occurrences across overlapping histories merge;
repeated equal records within one history remain distinct. The identity fields
are block/time, participants, created contract, value, call type, gas/gas used,
input, error flags and the original root-trace-zero marker. Preserve the original trace ID and mappings in event
lineage and `trace_identity_resolutions` in the audit. Preserve normal/root-internal
transfer suppression. This records the bounded provider observations, not a claim
of canonical EVM execution-path recovery. It adds no routine API calls and never
imports unseen transfers. Missing trace metadata and other malformed fields still
fail. The generic/legacy normalizer remains strict; completed valid samples need
no rebuild.

## Per-sample publication and raw-cache deletion

Each root is independently normalized, graphed and atomically published. Keep:

- `graph.json`: the training graph and its bounded-query coverage;
- a pinned `shared_observation` in the manifest: normalized replay events live
  once in the shared store as `events.jsonl.gz`;
- `target.json`: cutoff, source identity and frozen frontier selections;
- `normalization_audit.json`: normalization results;
- `manifest.json`: input/recipe identity, artifact SHA256s, query count, HTTP/cache
  counts, elapsed time, graph size, quality and retention policy.

The coverage retains public query parameters, response hashes and retrieval
times. Long call input bytes are removed **after normalization** has established
transfer/call semantics. Only after the whole sample directory has been
published are its scratch raw responses deleted. Successful exclusions are also
published and cleaned, rather than repeatedly fetching empty histories.

This preserves **graph reconstruction from compact events**. It does not preserve
raw-response re-parsing or original-response byte inspection. Response hashes
alone cannot reconstruct deleted bytes. This reduced audit scope is an explicit
user-requested storage tradeoff. No global raw-response archive is used by the
recent profile. Normalized events, bounded coverage and normalization audits are
published to `data/shared/observations/ethereum/<specification-sha>/` before graph
construction. These observations have no task labels or task/sample identifiers.
Any consumer using the same root address, cutoff timestamp/block, exact graph
query recipe, endpoint and actions can reuse them. Fixture observations are
isolated from network data. The Phishing recent pipeline uses this store
automatically; other task pipelines must explicitly adopt a compatible recipe
and this store before they gain reuse. Token/pool views require different inputs.

This is reuse of a whole root observation, not an arbitrary neighbor-page cache:
a busy neighbor can still be fetched for another root. Cutoff lookup is frozen
per task snapshot and can require one API request for a new snapshot. Completed
local root graphs are reused directly on resume. Task samples keep their audit
and target metadata, but no duplicate transaction file. `recent-sample-3` records
`event_storage=shared_observation`; its reference pins the shared manifest SHA256.
The shared manifest hashes the gzip bytes and records the original uncompressed
byte SHA256. Gzip is lossless: event fields, order and graph inputs are preserved.
`packages.observations.read_sample_events(sample_directory)` resolves old local
JSONL, local gzip or the new pinned shared reference. Injected test transports
that cannot use the shared store retain one local `events.jsonl.gz` instead.

## Storage

All paths below are relative to the repository root:

```text
data/shared/
  address_pools/ethereum/poison_hunter-<source-sha-prefix>/
    source.txt, addresses.txt, addresses.jsonl, manifest.json
  observations/ethereum/<specification-sha>/
    events.jsonl.gz, coverage.json, normalization_audit.json, manifest.json

data/scam/phishing/<snapshot>/
  background_ref.json            # shared master-pool path + checksum
  sources/                       # pinned public source bytes + manifest
  cohort/
    scam_addresses.txt, background_addresses.txt, address_labels.csv
    targets.jsonl, evidence.jsonl, manifest.json, training_config.json
  collection/
    cutoff.json                  # frozen timestamp-to-block lookup
    .work/<sample-key>/raw_requests/  # temporary; failures can resume here
    .work/<sample-key>/normalization_failure.json  # detailed audit when normalization fails
    samples/<sample-key>/
      graph.json, target.json, normalization_audit.json
      manifest.json              # pins shared replay inputs; atomic directory publication
    failures/<sample-key>.json   # failed attempts; collection manifest is current
    failures/recovered/<sample-key>.json  # archived after successful recovery
    failure_exclusions.json     # frozen dropped-root identities/reasons/checksums
    pre_exclusion_manifest.json # original collection index before explicit drops
    manifest.json               # ordered sample index, quality and cost statistics
    progress.json               # latest root/request progress
  prepared/
    graphs.jsonl, targets.jsonl, supervision.jsonl, splits.jsonl
    dataset_manifest.json, training_config.json
  status.json, runs/*.json, logs/*.log, logs/*.json
  storage_migrations/shared-gzip-v1/
    plan.json                    # original manifests and checksums; no event backup copies
    progress.json, complete.json # resumable maintenance and final savings report

artifacts/scam/phishing/<snapshot>/<run>/
  bundle/model.pt, bundle/scaler.json, bundle/manifest.json
  training_summary.json, predictions.jsonl, run_manifest.json

.runtime/etherscan/quota.sqlite3  # persistent local attempt count; not a credential
local_secrets.py                 # project-local credential, mode 0600, Git ignored
```

The key is loaded from the literal `ETHERSCAN_API_KEY` assignment in the project
file; no machine configuration or shell-profile modification is required. An
explicit environment variable takes precedence. Do not delete the quota database
when resuming: doing so discards recent local usage accounting.

Graphs are bounded numeric inputs plus compact audit metadata, not raw Etherscan
responses. Final `prepared/` duplicates graph records into the trainer's existing
JSONL interface. It is published only after complete collection and label/split
admission. Training scalers, weights and graph recipes remain task-specific.

Disk usage is larger than the sum of graph files. Source/cohort files cover all
2,308 selected roots from the address stage onward. Normalized replay transactions
are compressed once in the shared store. Graphs, coverage, target and audit metadata
still occupy space; `prepared/` adds another graph copy when explicitly assembled.
Back up referenced shared observations together with task snapshots, and preserve
their paths (or perform an explicit reference migration). Do not delete shared
objects just because another task owns their original producer. Unfinished roots retain their
scratch responses, including roots interrupted before a failure record was saved.
Only after successful publication are those responses deleted. A storage audit
must compare `.work/<key>/` against published sample keys before calling it stale;
never delete unfinished caches or shared observations merely because graphs exist
for other roots.

Local storage audit after the 2026-10-16 migration of `forta-recent-v1`:
`du -sh data` decreased from approximately **9.4 GiB to 1.7 GiB** (about
**7.7 GiB reclaimed**). The two normalized transaction copies previously totaled
8,754,572,114 logical bytes; the single shared gzip copy is now 494,266,179 bytes
(approximately 471 MiB). All 2,306 original graph/target/audit file hashes and
all decompressed event-byte hashes matched after migration. Graph JSON remains
968,819,048 bytes, of which 967,399,341 bytes belong to usable graphs. Failed
scratch remains 3,064,165 logical bytes. No training dataset or weights were
created. The journal retains approximately 7.9 MiB of manifests for recovery.

## Commands

Run from `/Users/austin/Documents/Courses/DS-Project/ds-crypto-project` using the
existing Python 3.11 environment. `--stage all --run NAME` includes training.

New collection automatically uses shared gzip and omits task-local transaction
copies. To compact an existing bounded-recent snapshot **before** preparation:

```bash
.venv/bin/python scripts/scam/compact_storage.py --snapshot forta-recent-v1 --dry-run
.venv/bin/python scripts/scam/compact_storage.py --snapshot forta-recent-v1
```

Stop the collector first. The maintenance command takes the snapshot writer lock,
verifies the complete published index and original artifact hashes, then journals
the original manifests before modifying anything. It reports progress and returns
nonzero on errors; no API requests, training or prompts are involved. Each gzip
must reproduce the original event byte SHA256 before references are published
and either raw normalized copy is deleted. Graph/target/audit bytes remain intact;
only storage manifests and their collection-index hashes change. Collection
completeness, exclusions and failures are preserved, including failed raw scratch.
`--dry-run` verifies and reports without publishing a migration or changing data.
Repeat the same command after interruption; completed migrations are idempotent.
If two legacy snapshots share an observation, migrate them sequentially. The
second can validate its old shared pin by reconstructing the original encoding
manifest and comparing its intact local event hash, then adopt the compressed
reference; an unrelated manifest mismatch is still rejected.
An unfinished journal blocks collection/preparation until maintenance finishes.
The small plan stores old manifests, not a second multi-gigabyte event archive.
Already prepared snapshots are refused before changes so frozen training input
provenance is not rewritten. No broad deletion of old snapshots, sources, quota,
unreferenced observations or unfinished caches is performed.

Interactive collection shows two fixed rows: total published roots above and
the oldest active root below. The lower row shows completed/planned logical
queries, hop/normalization/graph/publication/cleanup phase, HTTP attempts (`h`)
and cache hits (`c`). Its query total grows when the first-hop frontier becomes
known or receipt verification is needed; retries do not become completed queries.
Other roots still run concurrently and the upper row reports their active count.
Refreshes are limited to once per second and bounded to terminal width. The lower
row changes focus only when the focused root finishes; it is removed on exit.
All active roots' details remain in `collection/progress.json`.

Terminal animations bypass durable text logs. When output is redirected or the
terminal cannot reposition the cursor, `--progress on` writes plain summaries
at most once per 30 seconds plus start/end; `auto` stays quiet without a terminal,
and `off` suppresses progress. Errors and quota notices remain visible and logged.

The current `forta-recent-v1` address cohort is already frozen. Plan its collection:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --snapshot forta-recent-v1 --stage collect --dry-run
```

Collect, immediately build/clean each graph, then assemble training inputs:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --snapshot forta-recent-v1 --stage all --run NEW_RUN --allow-network --max-attempts 20 --progress on
```

For a new cohort, download the two public sources and prepare addresses:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --snapshot another-recent-v1 --stage sources --allow-network --progress on
```

Alternatively, add `--source-snapshot <existing-snapshot>/sources` to reuse pinned
source files. The recent profile does not use `--discover-background` or
`--background-snapshot`; those flags produce a clear error. The redundant
`scripts/scam/phishing/` wrappers were removed on 2026-10-23; use the unified
runner's `addresses`, `collect` and `prepare` stages instead.

`--stage collect` now includes per-root graph construction and raw cleanup.
`--stage prepare` assembles already-published graphs with supervision and splits;
it does not need deleted raw responses. `--stage status` reads durable status.
The unified runner automatically retries recoverable failures, up to its attempt
budget. Provider-level retries are also bounded. A sample-local data/byte-budget
failure is recorded and unrelated roots continue. Account authentication errors
cancel remaining work. Terminal failures are printed with addresses/reasons;
they are not repeatedly downloaded or silently admitted. Transient failures in
other roots still receive retry attempts. Without `--drop-failed`, an unresolved
terminal failure leaves collection incomplete and blocks training-data assembly.
With the explicit policy above, recorded sample failures can instead become
frozen exclusions after retries, while provider/integrity problems still stop.

Future explicit training, after successful preparation:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --snapshot forta-recent-v1 --stage train --run sage-recent-seed20261008 --dry-run
```

Remove `--dry-run` only when a formal fit is intended. Run output is never
silently overwritten. Optimizer-state training resume is not implemented.

## Recovery

- A completed sample is hash-validated and reused without HTTP, including samples
  published before a process interruption prevented the overall collection index
  from being written.
- Failed samples retain their own raw request cache. Retry only unfinished roots.
- A previously failed root is pending until a sample is atomically published.
  Successful recovery archives its active failure record under
  `collection/failures/recovered/`. Old per-run logs remain historical evidence.
- `insufficient_history` is a completed query outcome with no usable graph, not
  a retryable download failure. It remains an explicit training exclusion; do not
  fetch older pages or future events to fill it. `collection_incomplete` instead
  means some roots still lack either a published outcome or an explicit frozen
  collection-failure exclusion.
- An observation published before graph construction failed can be reused on
  retry, including in a different task snapshot with the same query recipe.
  Shared hits report zero new history HTTP attempts in the sample manifest.
- Shared pools/observations are checksum-validated. Changed source
  bytes or observation specifications produce new directories. Corruption stops
  the run rather than silently replacing evidence. Observation identities and
  contents are immutable; the explicit journaled storage migration above changes
  encoding and updates pinned manifests. New samples require their shared replay
  dependency to remain present and intact on resume. Legacy samples with complete
  local inputs still read independently until explicitly migrated. Address-stage
  validation also requires its referenced master pool.
- Interruption after graph publication but before raw cleanup is repaired on the
  next run: validate the published graph/events, then finish its scratch cleanup.
- Partially written `.sample-build-*` directories are not published samples.
  Sample publication is an atomic directory rename; completed graph files never
  refer to a deleted scratch raw path.
- Changed sources, labels, sampling budgets, worker settings or graph recipes
  require a new snapshot. Corrupt artifacts fail explicitly and are not silently
  refetched/replaced. The collection index keeps a stable identity across resumes.
- A lower global runtime rate ceiling is an exception: effective rate is the
  minimum of the frozen configured rate and the current project ceiling. Existing
  snapshots containing 4.8 therefore resume at 2.5 without changing input hashes
  or re-fetching completed samples. Stop once with Ctrl+C, wait for exit, then
  rerun the same command to load the new ceiling. Keep the quota database.
- Exit 0 means the requested stage completed/planned; 2 means invalid input or
  terminal failure; 3 means collection remains incomplete; 130 means interruption.
  No incomplete collection advances to training-data assembly.

## Compatibility and validation

Existing snapshots retain the configuration in their cohort manifest. An old
full-history snapshot is **not migrated by rerunning its old name**. Use a new
snapshot name for this profile. `--profile full-history` explicitly creates a
legacy snapshot; `--profile recent` can assert the new profile on a new run.
The earlier [performance diagnosis](PHISHING_COLLECTION_PERFORMANCE.md) records
the binary-paging issue in the legacy collector; that unbounded collection path
is no longer the default for new Phishing snapshots.

Offline checks cover descending bounds, repeated counterparties, future-row
rejection, sampled-page saturation, thread-shared start pacing, daily accounting,
per-sample cleanup, interrupted publication, checksum failures, cached graph resume,
shared pool/observation reuse across snapshots, task-neutral cache identities,
cutoff/recipe isolation, lossless gzip replay, interrupted storage migration at
shared/sample/index publication and duplicate cleanup, missing shared dependencies,
sequential migration of snapshots sharing the same legacy observation,
receipt-based execution conflict verification/rejection, local failure isolation,
nonunique internal trace IDs, repeated-call multiplicity, overlapping-record
deduplication and root-transfer suppression,
recovered failure archiving, label/split admission, and new-view model bundle
prediction. A real failed sample was replayed successfully from 61 cached queries,
including one matching receipt verification. As of 2026-10-16, 2,306/2,308 roots
are published: 2,058 usable (950 positive, 1,108 background), 248 excluded for
insufficient history, and two failures. Collection was incomplete at that point;
the storage change did not bypass the preparation gate. On 2026-10-20, the user
authorized the explicit failure-exclusion policy above and the dataset was
prepared successfully. Formal fitting is still pending.
