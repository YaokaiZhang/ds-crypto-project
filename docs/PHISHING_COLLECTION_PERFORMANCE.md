# Phishing collection performance investigation

Date: 2026-10-15. Snapshot: `forta-2022-v2`.

## Observed evidence

The user reported one completed root in 8.73 seconds and a 27:51:57 ETA.
The root progress bar includes neighbor histories and pagination. The first
root consumed one cutoff lookup and eight external/internal history queries;
its timing therefore did not represent the cost of one API request.

A read-only process inspection around 97 seconds into collection reported
3.9% CPU and 82,704 KiB RSS (about 81 MiB). This single snapshot indicates no
CPU/memory saturation at that moment; it is not a long-run resource profile.

A subsequent cache inspection of one busy neighbor found 65 successful requests,
63,052 downloaded rows and 23,052 unique transaction/trace identities. Thus
40,000 rows in that inspected subset repeated previously returned identities.
The queries show page 1 through 10 over the full interval, then page 1 through
10 again over bisected ranges. This is the main demonstrated avoidable request
cost. Cache growth showed ongoing work even while the root count stayed at one.
Request completion gaps ranged roughly from one second for small pages to two
seconds for full pages in the inspected excerpt; these gaps include HTTP time,
old post-response pacing and local processing, not isolated server latency.

## Changes

1. Keep the provably complete prefix of an ascending account-history page window;
   restart at the last block, never at the original lower bound. Reread that last
   block to avoid losing transactions when it spans pages. Preserve fallback
   splitting and explicit incomplete status when the single-block API limit is hit.
2. Enforce 2.5 requests/second by request-start spacing instead of adding 0.4 seconds
   after each response. Serial execution and the 95,000 rolling-24h cap remain.
3. Remove the unused in-memory response archive and deduplicate repeated source-row
   references across graph roots before aggregate normalization.
4. Expose HTTP/cache/pacing/page telemetry, and label progress in root graphs.

## Reproducible offline comparison

Synthetic provider: 2,000 ascending transactions, three transactions per block,
requested block interval 0..1,000,000, page size 50 and two pages per window.
Both strategies used the same mock provider, data and admission checks. The old
strategy was the existing binary fallback with the new cursor optimization
removed; no real API requests were made for this comparison.

| Strategy | Requests | Downloaded rows | Final rows | Coverage |
| --- | ---: | ---: | ---: | --- |
| Previous binary paging | 122 | 5,300 | 2,000 | Complete |
| Prefix-preserving cursor | 41 | 2,020 | 2,000 | Complete |

Requests fell by 66.4% in this scenario, with identical ordered transaction
identities and complete coverage. This is not a measured wall-clock speedup for
the real 11,490-root cohort; real histories, cache overlap and server latency vary.

Regression checks cover partial boundary blocks, a cursor walk exceeding 1,000
steps, single-block saturation, row budgets, repeated histories, cached resume,
request-start pacing and persistent daily quota. No roots, neighbor fanouts or
historical windows were reduced as a performance shortcut.

## Applying to the currently running job

The already-running interpreter retains its imported code. Stop it normally with
Ctrl-C, then rerun the same command and snapshot to load the fixes. Successful
raw requests are atomically cached and remain reusable. Page boundaries that
change can create new request identities; not every older subrange cache will
match the new cursor queries. No live process was terminated by this investigation.
