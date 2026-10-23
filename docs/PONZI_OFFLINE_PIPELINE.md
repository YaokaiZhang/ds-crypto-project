# Ponzi Offline Pipeline

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

Adopted on 2026-10-20. This is a cohort, source-label admission, input and
execution contract revision requested by the user. The task remains
source-defined retrospective Ponzi contract screening. It does not claim
incident forecasting, independently proven benign negatives, or online serving.

## Cohort and source times

The immutable original source bundle is
`data/scam/ponzi/xblock-unica-recent-v1/sources/`; its checks are documented in
[the source audit](PONZI_SOURCE_AUDIT.md). New runnable snapshots copy and verify
those source bytes under their own `sources/` directory.

The adopted cohort contains all distinct, nonconflicting XBlock/Unica positives
and exactly 1,000 seeded-hash-selected XBlock negatives. Selection happens
before observing transactions, graph quality or model performance. The default
seed is `20261008`; repeat runs select exactly the same roots.

| Population | Count |
|---|---:|
| XBlock positives | 200 |
| Unica unique positive addresses | 182 |
| Positive overlap between sources | 133 |
| Deduplicated positive union before conflict removal | 249 |
| Positive/negative source conflicts removed from both classes | 2 |
| Selected positive roots | 247 |
| Remaining eligible XBlock negative pool | 3,588 |
| Selected negative roots | 1,000 |
| Total roots before collection quality exclusions | 1,247 |

The two excluded conflicts are `0x5158cf97c3e001b402ccb0f9063736ee8d6dad5a`
and `0xd361e374be9e3907fceac60c6ea5cbdce89fc9ae`. XBlock's three `error`
records remain audited and cannot become negative examples. Repeated Unica
addresses do not generate repeated roots. Failed/unusable roots are not replaced.

The user explicitly selected these source-date observation anchors:

| Primary source | Cutoff (UTC) | Unix timestamp | Basis |
|---|---|---:|---|
| XBlock | 2018-11-22 23:59:59 | 1542931199 | Bundled README release date |
| Unica | 2017-05-07 23:59:59 | 1494201599 | Transaction extraction date in the cited study |

UTC end-of-day is an explicit experiment convention for date-only evidence.
These are chosen reconstruction bounds, not newly established per-contract
incident dates or exact original download timestamps. Shared positives use the
XBlock anchor and retain both source evidence records. Thus 200 positive and
1,000 negative roots use the XBlock cutoff; 47 Unica-only positives use Unica's.
Each root and all its queried neighbors use that root's cutoff and block bound.

The source-defined positive/negative labels are admitted for this named
retrospective experiment under the user's adopted source policy. Per-contract
`valid_from`, `valid_to` and `label_available_at` remain explicitly unknown.
The pipeline requires `training_as_of=null`; it cannot claim labels were known
at the historical cutoff. Labels, source identities and cutoff-source names do
not become graph features.

## Bounded collection and recovery

`ponzi_recent.json` uses the same `scam-recent-egonet-2.0` graph view as current
Phishing: ordinary ETH transactions and internal calls, descending from the
cutoff, one page of at most 100 records per action and queried address, at most
32 distinct first-hop neighbors and 16 per second-hop boundary. The root and
selected first-hop nodes have histories fetched; second-hop boundary nodes are
selected from those histories, without a third-hop expansion. Node/edge budgets
are 512/4,096.

Queries may look back to chain genesis; this is not a trailing 30-day window.
One common frozen `window_days` large enough to cover genesis for both source
anchors preserves a consistent graph recipe across all roots. The earlier
source's interval can start before genesis; there are no pre-genesis events.
Reaching a row or neighbor cap is successful bounded sampling, not complete
lifetime coverage. Fewer available observations retain their actual counts.
No older pages are fetched to fill quotas, and no transactions are invented.

The common collector supports multiple source cutoffs and stores their block
lookups separately. It retains the original single-cutoff path for Phishing.
All workers share the 2.5-request-starts/second ceiling and persistent 95,000
attempts per rolling 24 hours. Use one live collector process for this account.
The existing `local_secrets.py` supplies the API key; do not put keys in settings.

Per-root graph publication, compact shared `events.jsonl.gz` observations,
checksum verification, failure scratch retention, progress display and retry
budgets reuse Phishing's implementation. Raw scratch is removed only after
successful atomic publication. Shared observation reuse requires matching
address, cutoff/block, query recipe and provider origin. Task-specific labels,
cohorts and model weights remain independent.

Optional `--drop-failed` follows the existing audited exclusion policy. Under
`--stage all`, recoverable roots are retried before exclusions are frozen.
Authentication, quota, integrity failures and unattempted roots cannot be
dropped. Insufficient-history outcomes remain explicit quality exclusions.

## Run order

Run from the repository root using the existing Python 3.11 environment:

```bash
cd /Users/austin/Documents/Courses/DS-Project/ds-crypto-project
```

1. Verify the already-downloaded canonical source snapshot locally:

   ```bash
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage sources
   ```

2. Preview and then freeze the cohort. No Etherscan requests occur here:

   ```bash
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage sources --dry-run --progress off
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage sources --progress on
   ```

   The default canonical source path is automatic. `--stage sources` can copy
   and verify sources separately. `--source-snapshot /absolute/sources/path`
   selects another verified source bundle. New snapshot overrides are
   `--negative-count N`, `--xblock-cutoff ISO_OR_UNIX` and
   `--unica-cutoff ISO_OR_UNIX`. Changing frozen inputs requires a new snapshot.

3. Collect, normalize and publish each root's graph, with unattended retries:

   ```bash
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage collect --allow-network --progress on
   ```

   Repeat the same command to resume. Successful samples are verified and
   skipped; incomplete scratch is reused. The stage does not resample roots.

4. Assemble admitted graphs/labels and freeze the 90/10 train/validation split:

   ```bash
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage prepare --progress on
   ```

   If recorded sample failures must be explicitly excluded, add `--drop-failed`
   to this command. The exclusion ledger persists on subsequent resumes.

5. Check model admission, then explicitly start independent MeanSAGE fitting:

   ```bash
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage train --run mean-sage-v1 --dry-run --progress off
   .venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage train --run mean-sage-v1 --progress on
   ```

   `train` verifies frozen source/cohort/collection/prepared inputs first.
   Existing run outputs cannot be overwritten. Optimizer-state training resume
   is not implemented.

The unattended complete sequence combines the data stages and training:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage all --run NEW_RUN --allow-network --progress on
```

`all` includes fitting and requires `--run NAME`. It can include `--drop-failed` if explicitly
desired. Status is available with the same task/snapshot and `--stage status`.
`--dry-run` makes no output writes or network requests.

## Validation monitoring and model selection

Validation AP alone controls early stopping and checkpoint selection. An AP
increase greater than `min_delta` saves the model and resets the no-improvement
counter. Training stops after `patience` consecutive epochs without such an
improvement, or at the epoch limit, then restores the saved model. Defaults are
`patience=25`, `min_delta=0.0001` and at most 200 epochs.

Each epoch reports training loss and validation AP/Accuracy/Balanced Accuracy.
Validation scoring uses eval/inference mode; it does not compute validation
loss. There are no additional stopping counters, candidate comparison rules or
monitor-selection flags. Validation macro-F1 still selects the classification
threshold after the AP-selected model is restored. Validation is reused for
model and threshold selection and is not an independent test estimate.

`training_summary.json` records the history, selected epoch, selected validation
AP, threshold and final metrics. `--patience`, `--min-delta` and `--epochs` are
model-stage overrides recorded in the run manifest, without changing
`prepared/training_config.json` or source/graph inputs. Existing output folders
cannot be overwritten; choose a new run name for another fit.

For a new run using the existing prepared inputs:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage train --run mean-sage-ap-v2 --patience 25 --min-delta 0.0001 --dry-run --progress off
```

Remove `--dry-run` and set `--progress on` to fit. This starts a fresh deterministic
run; optimizer-state resume from `mean-sage-v1` is not supported.

The 2026-10-20 comparison confirmed that `mean-sage-v1` and the experimental
`mean-sage-v2` had identical model tensors, predictions, scaler, threshold and
all reported train/validation metrics. Both trained for 62 epochs and selected
epoch 37 (validation AP 0.8722183192319912, Accuracy 0.9186991869918699).
The redundant experimental `mean-sage-v2` was deleted at the user's request;
`mean-sage-v1` remains the retained result. The temporary multi-metric experiment
has been removed from the code and the AP-only behavior restored.

## Recorded dataset preparation

Local verification on 2026-10-20 froze
`data/scam/ponzi/xblock-unica-recent-v1/cohort/` with the exact 247/1,000
address counts and confirmed `collect --dry-run` performs no HTTP or file
changes. The full 174-check suite passed, including synthetic mixed-cutoff
collection, interrupted-root resume, audited failure exclusions and training
admission.

Later on 2026-10-20, real collection published 1,228 usable graphs (240
positive, 988 negative). The user explicitly requested exclusion of the 19
recorded `missing_or_invalid_tx_hash` normalization failures (seven positive,
12 negative). Running `--stage prepare --drop-failed` froze the audited
exclusion ledger, retained the original collection index, failure records and
scratch, and successfully published `prepared/`. The fixed split is train
216 positive + 889 negative (1,105 total), validation 24 positive + 99 negative
(123 total). All prepared artifact/input checksums and the explicit MeanSAGE
training dry-run passed. Collection resolution is complete with exclusions;
`download_complete=false` still records the 19 unsuccessful downloads. Formal
Ponzi model fitting has not started.

```text
data/scam/ponzi/<snapshot>/
  sources/                         # original bytes and checksums
  cohort/
    manifest.json, training_config.json
    targets.jsonl, evidence.jsonl
    scam_addresses.txt, negative_addresses.txt, address_labels.csv
  collection/
    cutoffs/<timestamp>.json        # source-specific block lookups
    samples/<sample-key>/           # graph, enriched target, audit, manifest
    .work/, failures/, progress.json, manifest.json
    failure_exclusions.json        # optional explicit failure exclusions
  prepared/
    graphs.jsonl, targets.jsonl, supervision.jsonl, splits.jsonl
    dataset_manifest.json, training_config.json
  status.json, runs/, logs/

artifacts/scam/ponzi/<snapshot>/<run>/
  bundle/, training_summary.json, predictions.jsonl, run_manifest.json
```

Actual eligible class counts can decrease after collection quality admission.
Keep the full retained population with class-stratified, entity/group-preserving
90/10 train/validation; there is no test partition or forced 1:1 rebalance.
Fit scalers and weighted-BCE class weights on train only. Validation is reused
for checkpoint/threshold selection and must be reported as such. Report
Accuracy together with Balanced Accuracy, class support, F1 and confusion
matrices. No Ponzi fitting or live Etherscan collection is implied by the
synthetic integration checks or the frozen address cohort.
