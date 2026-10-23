# Honeypot source audit and contemporary supplement

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

Evidence revision: 2026-10-20. Graph stages added on 2026-10-21; see
[HONEYPOT_GRAPH_PIPELINE.md](HONEYPOT_GRAPH_PIPELINE.md) for source-specific
cutoffs, descending collection, graph commands and RPC requirements. Evidence
preparation does not automatically admit labels or fit models.

Run from the repository root:

```bash
uv run --frozen python scripts/scam/run_pipeline.py --task honeypot --snapshot trapdoor-api-v1 --stage sources --candidate-count 1000 --allow-network --progress on
```

The equivalent CLI is chainrisk-scam prepare-honeypot --task honeypot --snapshot
NAME --stage STAGE. Evidence stages: sources, audit, discover (addresses alias),
label, prepare, evidence, status. Here prepare writes evidence readiness, not
graph training inputs. all additionally runs the graph workflow; graphs runs
plan/verify/collect/build-graphs from existing evidence. Training remains explicit
and is not enabled through this evidence runner. Existing
Phishing/Ponzi stage behavior stays unchanged. Dry-run writes/calls nothing.
Stages use the existing snapshot lock, durable status and attempt logs.

## Source preservation and quality

Download trapdoor_list.csv and non_malicious_list.csv from
[bsdp2023/trapdoor_data](https://github.com/bsdp2023/trapdoor_data), pinning both
to one repository commit; retain exact bytes, SHA256s and retrieval time. Local
inputs are supported by settings.source_files with positive and negative paths.
Changed frozen sources require a new snapshot.

Audit columns, valid addresses, token/pool equality, duplicate rows, unique
tokens, multiple pools, mechanism counts and cross-source conflicts. Retain
invalid rows/reasons and file/line provenance. Conflicting labels are excluded;
every valid historical token, including conflicts, is excluded from discovery.

The CSVs supply no per-sample detection time, incident block or validity
interval. cutoff, valid_from, valid_to and label_available_at stay null and
training_eligible=false. Commit/download dates are not incident dates. Before
historical graph collection, obtain reviewed temporal evidence or separately
approve a retrospective observation-anchor protocol. Pool identities, source
mechanisms, negative definitions and usage terms also require review. Structural
audit is not independent truth validation.

## Discovery

Defaults: 1,000 unique tokens, seed 20261020, 180-day range ending at a frozen
discovery timestamp. Resolve boundary blocks with Etherscan. Read complete,
paged/range-covered PairCreated logs from Ethereum Uniswap v2 factory
0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f with WETH in token0 or token1.
Decode token/pair identities, deduplicate by token and exclude WETH and every
historical token. Hash-rank the full eligible range by seed/token and select
before API labels or graph availability are inspected.

This samples recent WETH-paired launches, not all ERC20 or market activity. It
does not select the largest-liquidity pools, use suspicious behavior or stratify
by month. Pair creation does not prove funded liquidity. Incomplete coverage or
too few candidates cannot silently reduce the cohort; use a new wider-range
snapshot if needed. Reruns retain the original time range, seed and targets.

## API capture and acceptable losses

Query IsHoneypot with chainID=1, token and selected pair. Preserve raw response,
checksum, capture time and per-sample outcome before moving on. Defaults are four
HTTP workers sharing one request-start/second ceiling and a thread-safe finite
attempt budget, with finite retries. Completion order does not change output
order. Fixture mode defaults to one worker. HONEYPOT_API_KEY is optional, read from the
environment; Etherscan uses the existing private ETHERSCAN_API_KEY source.
Credentials do not belong in settings/CSVs. Provider usage terms must support
the intended research/service use.

The existing honeypot_is adapter validates token/chain/pair/v2 scope. Candidate
false requires simulationSuccess=true; explicit true can use other-source API
evidence with failed simulation. Missing/non-boolean verdicts and failed negative
simulations stay unlabeled; scope mismatches remain invalid. Keep raw API
snapshots pending admission review. training_eligible remains false.

After finite retries, sample-local failures are recorded as excluded_query_failure
and skipped. Reuse completed captures, unknowns and recorded exclusions without
re-querying; no replacement roots or class quotas. Authentication, request budget,
rate/quota exhaustion and checksum/integrity failures stop the stage. Interrupted
captures resume from immutable raw caches and per-sample results.

## Outputs and later graph collection

Under data/scam/honeypot/NAME/:

- sources/: original CSVs and commit/checksum manifest.
- historical/: labels.csv/jsonl, tokens.jsonl, rejected.jsonl, quality_audit.json/md.
- discovery/: recipe, block range, coverage, all eligible candidates, selected
  targets.jsonl, candidates.csv and checksum manifest.
- contemporary/: raw_requests/, results/, progress.json, honeypot_snapshots.jsonl,
  labels.csv/jsonl, detection_targets.jsonl, pending_supervision.jsonl and manifest.
- readiness.json/md: cohort counts, API-reported detection reasons and unresolved
  temporal/review/pool gates. These reasons are provider outputs, not independently
  validated mechanisms.
- status.json, runs/, logs/: runner status and execution records.

Historical/current cohorts remain separate. A current unknown cannot erase a
historical positive; a historical positive cannot label today's graph. Once
cutoffs and labels are reviewed, use existing verify-token-targets, collect and
prepare commands in [TOKEN_SCAM_TRAINING_PIPELINE.md](TOKEN_SCAM_TRAINING_PIPELINE.md).
No API verdict, risk, tax or source-label field enters graph features. Do not
silently merge historical positives and contemporary negatives.

Example non-secret settings (pass --settings FILE on each stage):

```json
{
  "discovery": {"lookback_days": 180, "seed": 20261020},
  "collection": {"rate_limit_rps": 2.5, "max_requests": 5000, "max_history_rows": 300000},
  "honeypot": {"workers": 4, "rate_limit_rps": 1, "timeout_seconds": 15, "retries": 1, "max_requests": 3000}
}
```

Explicit sampling/count changes are rejected on frozen snapshots. Omitting
candidate-count on resume retains its frozen value. Retry/rate controls are
runtime settings. Use --stage status to inspect progress.

Tests cover sources/conflicts, complete paging, label-blind dedup/sampling,
no-write dry-run, interrupted replay, scope mismatch, unknown vs negative,
sample failure exclusion, fatal authentication and checksum gates.
Concurrent execution also checks canonical output ordering, no re-query on
replay and the shared request-start/attempt budget.


2026-10-21 combined Honeypot revision: use the `all-recent-v1` graph run for both
Trapdoor (2023-01-31T23:59:59Z retrospective anchor) and frozen contemporary API
labels. Local RPC configuration, four-sample concurrency, shared lossless gzip
replay, `prepare-training`, and explicit `run_pipeline --stage train` are described
in [HONEYPOT_GRAPH_PIPELINE.md](HONEYPOT_GRAPH_PIPELINE.md).
