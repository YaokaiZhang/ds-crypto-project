# Week 1 Source Probe

## Result

No already-authorized archive endpoint or project credential was present on
`roihu-gpu`. The public endpoints can prove historical capability, but they
do not provide a reliable quota for the full 100-token, 90-day audit.

## Endpoint Checks

- PublicNode answered current-block requests but required a personal archive
  token for historical logs.
- OnFinality and Ankr required an API key.
- Flashbots reported pruned history.
- 1RPC was not usable for this query shape.
- Tenderly public RPC returned a known historical Uniswap factory event and
  completed exact pool-scope queries for all selected tokens.
- MEV Blocker returned historical pool logs in small probes, but also returned
  transient service errors on some multi-pool queries.

## Exact Scope Probe

The Tenderly-only scope stage completed for the same deterministic 100-token
cohort:

- exact pool scope: 100 / 100 entities complete;
- discovered pools: 180;
- pool counts per selected token: 86 with 1, 5 with 6, 3 with 2, 2 with 4,
  and one each with 3, 5, 8, and 34;
- factory events: 820;
- sampling candidates: 822.

The selected cohort is still a window-based sample. Exact scope was resolved
after selection, so its pool counts must not be retroactively interpreted as a
selection stratum.

## Activity Probe

The batched activity run archived 2,051 RPC responses before it was stopped:

- HTTP 200: 2,009;
- HTTP 429: 42;
- unique raw response files: 2,051;
- duplicate raw paths: 0.

The run was interrupted during timestamp retrieval and did not produce a
complete normalized activity table or valid labels. Its `200,000`-block
horizon was a transport probe, not a 90-day follow-up window. No primary
volume-label result should be inferred from it.

## Decision

The project code now supports batched multi-pool RPC retrieval, response-cap
range bisection, transient-error retries, raw response preservation, and
separate RPC URLs for scope and activity. The go/no-go gate remains closed.

To produce the planned labels, use an authenticated archive/RPC endpoint with
documented quota or a locally available archive/indexer, then rerun with a
timestamp-aware horizon covering the full 90-day follow-up. Build a
label-blind candidate buffer large enough to obtain 50 `low_volume_dead` and
50 `continued_activity` development cases after censoring and exclusions. Keep
the chronological test holdout at observed prevalence. The public probe is
retained at `data/week1_batched_pilot/` for transport and scope evidence.

## Authorized RPC configuration

The collector resolves the archive RPC at runtime. Process environment values
take precedence over the project `.env` file. Set
`ETHEREUM_ARCHIVE_RPC_URL` to a complete URL when possible. Otherwise set
`ENDPOINT` and `API_KEY`; `ENDPOINT` may already contain the key, contain an
`API_KEY` placeholder, or be a base URL to which the key is appended once.

The authenticated URL is used only for the live request. Raw archives,
request manifests, source manifests, and reports store a redacted URL. Keep
`.env` out of version control and do not place keyed URLs in configuration or
output artifacts.

The authorized provider probe succeeded for a historical single block and a
10-block `eth_getLogs` range. Its free-tier response rejected larger ranges
with JSON-RPC error `-32600`; this is a provider transport/quota limitation,
not evidence of complete historical coverage or valid 90-day labels.
