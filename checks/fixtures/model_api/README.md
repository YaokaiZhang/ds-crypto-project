# Recorded model API regression packets

These files are used by the shared service verifier and inference regression
suite. They are not uploaded to the Modal runtime or required by the backend.
Keep graph features and recorded expected scores unchanged when moving them.

| Files | Origin | What the expected result means |
|---|---|---|
| `forecast-*.json` | Upstream commit `1e783b5`, dataset `wallet_graph_events_20261003_2000`; upstream describes them as two Task A test-holdout tokens | Recorded no-USD v0.2.0 research ensemble scores and outcomes |
| `scam-*.json` | Previously captured real Ethereum mainnet backend input artifacts, one per released Scam task | Golden CPU predictions from the pinned Release; no ground-truth class, accuracy or holdout claim |

Each Scam packet preserves the complete canonical graph, its task/target/cutoff,
model identity and scaler checksum. Only redundant pre-scaled `inputs` are
omitted; the server always scales the canonical graph itself. Provenance records
the source analysis ID, original input-file SHA256 and canonical packet SHA256.
The four bundles and their score-to-label policies remain unchanged.

The Forecast files retain their upstream graph, expected score and outcome. Their
request metadata has been bound to the published model and scaler, replacing a
retired temporary marker. The upstream files do not include a checksum mapping
back to the original split manifest, so their holdout provenance is documented
as upstream-supplied rather than independently re-established here.

Expected scores test implementation stability, not future model quality. Never
regenerate expected values automatically because a test fails; investigate any
weight, scaler, policy, graph or numerical change first.
