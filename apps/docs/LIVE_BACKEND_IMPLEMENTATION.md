# Live backend contract and implementation status

Serving revision (2026-10-25): the model server owns score-to-label policies;
the backend validates and forwards returned labels. Input-only configuration now
ships in `apps/backend/config/`; backend runtime does not include or import
`deploy/`. Eligible live-mock inputs return 0.999 / High Risk for Scam or
0.999 / Continued activity for Forecast, with explicit simulated provenance.
This supersedes earlier random-score and backend-policy descriptions below.
See [MODEL_SERVICE_CONTRACT.md](MODEL_SERVICE_CONTRACT.md).

User-confirmed online-service revision: 2026-10-24. This document supersedes
earlier display/model identity and online quota plans where they differ. It
does not change training inputs, fitted parameters or historical evaluation.

## Current implementation boundary

Implemented and tested foundations:

- Backend-local literal-only credential loading, with environment precedence.
- Process-shared Etherscan pacing, UTC daily accounting and safe HTTP errors.
- Cutoff-block RPC address classification and Scam task applicability.
- Model-version-bound risk policy, progress DTOs and frontend displays.

ETH is now implemented in opt-in `eth_live_mock` mode: durable single-host SQLite
queue/leases/events, progressive complete 30-day root collection, bounded 64-node display graph, separate bounded model
sampling, real address metadata/balance, ledger/graphs/activity, resumable raw
request caches and quota pause/recovery. A separate worker processes at most two
jobs globally on this host. See [ETH live adapter](ETH_LIVE_ADAPTER.md) for launch
commands and real-address verification.

The model boundary is temporarily simulated at the user's explicit request:
send compatible input to a fixed loopback test target, then validate and persist
the fixed service-shaped 0.999 response and supplied label. API/artifacts mark simulated provenance and
capabilities keep model_available=false. The user requested the original front
end text and one recent display graph; no simulation badges or graph-scope switch.
ERC-20 now shares the live queue/worker/quota boundary and follows the same
complete 30-day progressive display, bounded delayed graph and simulated
predictor principles. Historical token/pool verification and separate frozen
directed edge-aware model inputs are documented in
[ERC-20 live adapter](TOKEN_LIVE_ADAPTER.md). Unsupported assets/pools and empty
or incompatible model inputs remain Unavailable with a null score and reason.
Forecast now shares these live foundations with its own creation-based
first-seven-day window, wallet/pool/token input and fixed Continued activity
mock response. The model server owns its eventual decision policy. See [Forecast live adapter](FORECAST_LIVE_ADAPTER.md).
Its packet explicitly awaits the Forecast bundle/scaler; historical USD stays
missing when unavailable. Real trained model serving and multi-host
PostgreSQL deployment remain pending. Template mode still returns 501; static
demo and the independent feed retain their existing switches.

## Server credentials

Root credentials have been copied to apps/backend/local_secrets.py (0600,
Git ignored). Settings reads string literals without executing the file.
Process environment takes precedence; an explicitly empty value disables
fallback. Credential values are omitted from Settings repr and public errors.
Never log full HTTP URLs containing provider credentials.

apps/backend/.env.example documents configuration; it is not automatically
loaded. Root/backend credentials are independent copies and should both be
updated when rotating the same account credentials.

## Shared Etherscan budget

- At most 3 HTTP starts/second, spaced across users, tasks, workers and retries.
- At most 99,000 attempts per UTC calendar day, reset at 00:00 UTC. Failures
  and retries count; cache hits and browser polling do not.
- RPC and homepage feed do not consume this budget and receive no application
  rate/daily cap from this revision. Timeouts and bounded concurrency remain.
- check_admission reads quota without spending a slot. Exhaustion returns
  quota_exhausted, HTTP 429, Retry-After and a UTC retry_at. Store a real job
  before any HTTP 202 acceptance.
- A worker must persist progress.state=waiting_quota and retry_at, preserve
  completed pages/events and cutoff, release its lease, and resume remaining
  work at reset. GET/SSE and stored artifacts remain readable. The implemented
  worker releases the lease on pause and reclaims work when retry_at is due;
  transport raises a typed pause instead of sleeping a worker until midnight.
- Ledger state survives restarts. All processes for an account use the same
  ETHERSCAN_QUOTA_FILE; default: root .runtime/etherscan/quota.sqlite3. Checking
  and reserving a request uses BEGIN IMMEDIATE, never a lock across HTTP I/O.
- The backend shares the trainer's buckets/pacing schema. Local training keeps
  its own 2.5/sec and 95,000/rolling-24h policy. Both see the same usage/pacing
  on this machine; research reservations are now atomic across processes too.
  Legacy slow-request completion accounting can conservatively debit the next
  day. Separate machines need a shared quota service; file/key copies do not
  coordinate account consumption.

## Address eligibility and failures

Classify ETH addresses at the frozen cutoff block. EOA: Phishing applicable,
Ponzi not_applicable. Contract: both potentially applicable, subject to model
scope, sufficient history, matching schema and available bundle. Unresolved or
delegated accounts require explicit resolution. RPC failure is never treated
as empty code or an ordinary wallet.

Token analyses require verified Token and supported Ethereum Uniswap v2 pool
identities. Missing pool/model data still permits useful facts to be displayed.
Forecast keeps its own first-week eligibility and graph contract, with the
user-authorized temporary mock predictor documented above.

A syntactically valid address can have no code, balance or observed activity;
do not label it malformed or globally nonexistent. Empty history requires an
explicit successful no-records response and completed pagination/range coverage.
Timeouts, authentication errors, overflow and missing pages are not emptiness.

An empty 30-day display window does not by itself imply insufficient model
history; complete the model's separate sampling recipe. Distinguish no_activity,
insufficient_history, data_incomplete, not_applicable, model_unavailable and
model_error, with readable reasons and null scores. Never substitute zero, Low
or demo data for missing assessments. Preserve usable results of other tasks.

Immediate failures use the safe ServiceError catalog. After acceptance, failures
become durable per-task/job statuses; the original HTTP response cannot change.
Never expose raw upstream bodies, URLs, credentials or stack traces.

## Display data versus model samples

ETH root facts, ledger and Flow Activity cover the complete fixed 30-day
window through the frozen cutoff. Stream complete observed blocks, publish
roughly every 1,000 rows or one second of accumulated data, and upsert only
changed ledger rows in the same fenced transaction as their statistics. Keep
source completion explicit in API coverage. Incremental native-flow updates
reconcile normal rows with internal traces, so root traces are not double
counted. The public ledger remains root-address-only. Etherscan token amounts
are joined to those same external identities after native collection.

The display graph separately retains root plus first hop at most 48 nodes,
then at most 16 second-hop nodes (64 total, 4,096 directed relations). Both hops
may search the original 30-day bound; never query third-hop histories. Keep
that bounded graph and neighbor observations separate from root statistics.
Observation window remains the fixed 30 days; graph-selected earliest time is
backend selection provenance only. Publish the graph after the complete root
ledger and token enrichment settle. API progress and model provenance updates
must not change graph rendering identity or reset zoom, selection or animation.
No incompleteness annotation or model-graph switch is added to the UI.

Ledger revision increases only on data changes, so the frontend can refresh
any current cursor page without clearing already-visible rows. Partial source
collection survives quota waits through request caches; a completed root ledger
checkpoint skips rebuilding/republication on model retry or worker recovery.
During recovery of an unfinished window, rebuild counters from cached pages
without publishing until they catch up with the last persisted ledger counts;
already-visible counts and ledger revisions must never move backward.

Model graphs follow the exact bundle recipe, feature ordering and frozen scaler.
Reuse matching observations and query missing neighbors/older records separately.
Respect record/page/fanout/node/edge budgets; sparse graphs need not fill
512 nodes/4096 edges. Preserve each model sample's lineage and identity.

## Display risk policy

deploy/registry/risk_policies.json binds these user-selected bands to exact
model versions, separately from trained binary thresholds:

| Task | L | H |
|---|---:|---:|
| Phishing | 0.600 | 0.950 |
| Ponzi | 0.600 | 0.930 |
| Honeypot | 0.200 | 0.700 |
| Rug Pull | 0.400 | 0.850 |

Low [0,L); Medium [L,H); High [H,1]. Compare raw scores; display three decimal
places. Missing/mismatched policies cannot silently use another model's bands.
These uncalibrated scores are screening signals, not fraud probabilities.
Validation was reused for model/threshold/band selection; there is no independent
test guarantee, and Phishing's background class is not verified benign.

## Actual progress

Retain the existing seven-stage UI. SSE notifications trigger result reads,
with polling fallback and event replay. Stage transitions and counters come
from backend work; no frontend timers simulate progress.

Optional AnalysisResult.progress supplies state, unit, completed, nullable
total, total_final, records_collected, retry_at and optional task_id. Counters
describe current-stage logical work, not total runtime. Retried HTTP attempts
consume quota but must not double-count completed logical pages.

Initially the denominator is unknown. Discovering more pages, log subranges or
neighbors may increase total; total_final stays false until all work is known.
Display counts/discovery text, not an invented overall percentage. Only use a
ratio for a known final denominator, without implying overall job completion.

Explicit states include queued, retrying and waiting_quota. Pause preserves the
stage/counters and shows its UTC resume time. Browser disconnect does not cancel
a durable job; reconnect replays events and rereads stored state. Only final
result/artifact persistence permits completed. Partial and failed remain explicit
terminal outcomes. Integration checks cover durable quota pause, cache-backed
resume, replay, fenced stale workers and stable simulated results after recovery.
Actual mainnet wallet/contract runs are recorded in the live-adapter guide.
