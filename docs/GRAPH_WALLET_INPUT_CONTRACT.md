# Wallet-Enriched Graph Input Contract

## Status

This document defines wallet-graph-input-0.1, the next graph-input contract.
It is a contract change for the model-input and data-engineering layers. It
does not change the prediction unit, primary label, observation window,
follow-up window, split policy, or evaluation rules.

The existing GraphSAGE artifacts use a token-centered graph with pool and
counterparty nodes. Those results remain valid under the older graph-input
version. A wallet-enriched result must use a new versioned artifact and must
be reported as a new experiment.

## Prediction unit and graph shape

The prediction unit remains one token contract, and the model still produces
one score per target token. The first wallet-enriched graph uses this typed
relation:

    wallet --swap activity--> pool --contains--> target token

For message passing, the implementation may store both directions of each
relation, but it must retain the relation type and original addresses. The
initial implementation is one separate target-token graph per token. It does
not build one global graph or pass hidden state between train, validation, and
test token graphs.

### Nodes

- One center node for the target token.
- One pool node for each selected pool of the target token that exists by the
  target cutoff.
- One wallet or participant node for each distinct address observed in a
  selected pool's pre-cutoff swap records.

"Wallet" means a blockchain address observed in a swap event. It does not mean
a verified human. Routers, contracts, aggregators, and other service
addresses may appear and must not be described as individual users.

### Edges and features

- target token to pool: selected-pool membership and the existing pool
  features;
- wallet to pool: aggregated swap activity for that wallet and pool during
  the target's observation window.

The first wallet-to-pool edge feature set is:

- swap count;
- positive historical USD volume when available;
- active-day count or fraction;
- first and last swap offset from t0 or the cutoff;
- participant-role counts when sender and recipient roles are both retained.

Wallet node features may summarize its pre-cutoff swap count, volume, active
days, and number of connected selected pools. Token-level and pool-level
features remain available. Individual transaction rows remain auditable source
events; they are not transaction nodes in the first implementation.

## Participant fields

The normalized event contract must preserve the swap participant fields needed
to construct these edges:

- swap_sender: the primary participant address used for the first wallet graph;
- swap_recipient: the output-recipient address when the source provides it;
- transaction_from: the transaction caller when the source provides it.

The collector must document which source field supplies each value and must
lowercase and validate every address. A missing swap_sender is not silently
replaced with a different field or with a fabricated address. The row is
retained for audit, and the wallet-graph build records the missing-participant
status and excludes or flags the affected graph according to the run policy.

The current normalized event artifacts do not contain these participant
fields. They therefore do not satisfy this contract and cannot be used to
claim that the wallet-enriched graph has been evaluated.

### Current Graph source mapping

New collections from the selected Uniswap subgraphs use these source fields:

| Protocol | `swap_sender` | `swap_recipient` | `transaction_from` |
| --- | --- | --- | --- |
| Uniswap v2 | `Swap.sender` | `Swap.to` | `Swap.from` |
| Uniswap v3 | `Swap.sender` | `Swap.recipient` | `Swap.origin` |

These are swap-level fields. `transaction_from` records the source's
transaction-origin field; it is not inferred from `swap_sender`. The selected
Graph query's nested `Transaction` object remains limited to transaction id,
block number, and timestamp. Every address is lowercased and validated as a
20-byte EVM address. Missing or invalid participant values remain null, while
the raw response and normalized event lineage are retained.

## Point-in-time rule

For a target token, graph inputs use only events in the interval from t0
through the fixed 7-day cutoff, inclusive according to the project's boundary
rule. This includes wallet identity, wallet-pool edges, counts, volumes,
active days, and all derived node features.

The graph build must exclude:

- swaps, pools, wallet activity, and market information after the cutoff;
- the 90-day follow-up events and the outcome label;
- censoring fields and any post-cutoff completeness information;
- future activity of a wallet that is also seen in another token graph.

Missing early amount_usd must remain missing or be represented by an explicit
feature-quality flag. It must not be silently converted to zero.

## Builder run policy

The first implementation writes `wallet_graph_edges.jsonl` with one row per
target token, selected pool, and normalized `swap_sender`. Each row retains
the target `t0` and cutoff, aggregate counts and positive historical USD
volume, active-day dates, first and last offsets, participant-role counts,
missing-amount counts, and the supporting normalized event identifiers.

The builder writes one local graph per target token to `graphs.jsonl`. It
records every target in `graph_quality.jsonl`, including targets that cannot
be model inputs. A target graph is model-ready only when selected-pool scope
is complete, at least one selected pool remains, every in-window swap has a
valid `swap_sender`, every in-window swap has a valid timestamp and event
identifier, and no post-cutoff event is included. Missing recipient or caller
fields do not exclude a graph; they remain explicit coverage counts. Missing
historical USD amounts do not become zero and remain edge-quality flags.

If the normalized events table lacks the participant columns, the builder
fails closed with a versioned blocked manifest and writes no model-ready
graphs. This is the expected result for historical pre-extension data.

## Training, testing, and inference

1. Split target tokens using the existing token-level split manifest before
   fitting the model.
2. Build one cutoff-bounded wallet graph for each training, validation, and
   test token. The same address may occur in multiple graph files, but the
   initial experiment does not connect those files or share a learned wallet
   state across them.
3. Train GraphSAGE on training-token graphs and their future 90-day labels.
   Fit feature normalization and class weighting on training data only.
4. Use validation-token graphs to select the checkpoint, threshold, and any
   calibration. Do not use test labels for these choices.
5. Freeze the model and threshold, score test-token graphs once, and compare
   the scores with their later labels.
6. For inference, wait for the same 7-day observation window for a new token,
   build the same wallet-pool-token graph, apply training-fitted transforms,
   and output one continued_activity score. No future label is needed at
   inference time.

## Acceptance checks

Every wallet-graph run must record:

- graph-input contract version and source schema version;
- participant-field coverage and missing-participant counts;
- one-to-one mapping from graph output to target token and split partition;
- event identifiers supporting every wallet-pool aggregate;
- zero post-cutoff events in graph inputs;
- no train/validation/test token duplication or overlap-group crossing;
- normalization, threshold, seed, and model configuration;
- whether participant addresses include routers or other contracts.

The old pool-counterparty GraphSAGE result and the new wallet-enriched result
must be compared on the same eligible tokens, split, cutoff, labels, and
validation-only tuning procedure. A change in graph input must not be
presented as a change in label definition or as evidence from the old run.
