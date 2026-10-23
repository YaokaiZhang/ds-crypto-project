# Transaction graph implementation

> Presentation revision, 2026-10-13: [Workbench glass refinement](WORKBENCH_GLASS_REFINEMENT.md)
> supersedes the earlier ETH/ERC-20 query/panel composition, graph plot labels,
> workbench typography and panel material below. It preserves field inventories,
> task/model meanings, graph provenance and inspection semantics. Home, shared
> navigation and accepted background styling retain their own authority.

## Scope

An Operate component for everyday token holders inspecting a task-specific graph.
Inherit the [visual brief](VISUAL_DIRECTION_BRIEF.md) and preserve the ETH/Token
content contracts. This implements the already specified hover, selection,
fit/zoom and graph presentation responsibilities; it does not change the product
workflow or model graph contract. English UI; Chinese design communication.

## Direction contract

**THESIS:** Make the assessed root and its actual relations readable before showing
complexity. Stable topology replaces an endlessly drifting decorative network.

**OWN-WORLD:** Dark glass frame, cool white/blue geometry, restrained role shapes,
readable system type, monospaced addresses. No risk colors assigned to neighbors.

**STORY:** Identify the task and sample, follow original directed relations, hover
for a short summary, select for persistent details. Missing metadata stays unknown.

**FIRST VIEWPORT:** Compact title/task toolbar above a large graph field. Root
centered in breadth-first rings, role legend below, hover summary near the pointer,
selected details below the plot. Fit, zoom and motion controls remain visible.

**FORM:** A scoped extension of the user-pinned visual brief; no concept roll or
new aesthetic selection. Signature motion: nodes resolve by graph distance, edges
draw toward their original targets, then settle into stable geometry.

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Data boundary

The backend GraphView envelope remains unchanged: sample_id, task_id, nodes, edges.
Its record arrays are not yet a typed serving contract. The frontend display
adapter therefore requires an explicit record shape and rejects malformed graphs
rather than guessing tensor fields. The backend presenter remains unimplemented.

Nodes: unique string `id`, readable string `ref`, one `is_root: true`, optional
`role` (wallet, contract, token, pool, deployer, lp, unknown), optional `label`,
optional `individually_assessed` boolean. Unknown roles stay unknown.

Edges: unique string `id`, valid `source` and `target` node IDs, string `relation`,
`direction: original`, `kind: observed | structural`; optional nonnegative integer
`event_count`, exact decimal-string `amount` with string `asset`, and optional
`first_seen` / `last_seen` timestamps. No conversion of log tensor features to
readable amounts; no synthetic reverse-message edges. Missing values remain null.

Graph context is a separate component prop: optional model node/edge counts,
window, graph version, sampling note and cutoff. Omitted provenance is shown as
not supplied, never inferred from display counts. Metadata must match the graph's
sample and task identity before it is displayed.

The renderer accepts one task/sample at a time. Task switching belongs to its
parent, which must supply the corresponding GraphView and matching context.
The standalone development preview is explicitly synthetic, separate from
application routes and excluded from the normal production entry.

## Layout and interactions

2026-10-13 refinement: the initial regular ring layout is replaced by seeded
irregular positions and a bounded force relaxation over the supplied adjacency.
The final layout freezes, remains reproducible, retains all records and original
directions, and exposes uneven hubs and branches without inventing relations.

Breadth-first distance controls entrance timing only. A stable force layout uses
observed relations and weaker structural links to organize the supplied nodes;
disconnected nodes remain visible. Fit frames every node and complete edge curve.
Above 28 nodes, persistent labels emphasize the root and pools; hover, selection,
keyboard focus and inspect lists reveal other identities without label collisions.
Parallel/reverse relations use separate curved paths; self-loops remain visible.
Role shapes and a root ring communicate identity without implying maliciousness.

Hover or keyboard focus shows a compact summary; clicking/Enter pins details.
Escape dismisses hover and pinned details. Pan the background, zoom with buttons
or Ctrl/Meta + wheel, and use Fit to restore the complete view. Plain wheel keeps
page scrolling. Node/edge lists provide keyboard access when a dense SVG is hard
to navigate. Display all supplied records; do not silently crop a model sample.

Progressive entrance is bounded and concerns rendering only. Replay never starts
collection or inference. Reduced motion suppresses entrance and hover motion.
Stable coordinates support precise inspection. Background motion and transaction
activity semantics remain independent.

## Implementation and verification

Implemented on 2026-10-13 in TransactionGraphPanel/TransactionGraphCanvas through
the existing GraphRenderer lifecycle. Node and edge validation is in the pure
graphDisplay adapter. Model GraphSample and backend schemas are unchanged.
The graph can be inspected in `/graph-preview.html` during Vite development;
fixtures are isolated from the main build and are visibly labeled synthetic.

Root/active labels use screen-space font sizing. Mobile hides non-selected
neighbor labels and the extra root caption; dense graphs suppress inactive
labels above 60 nodes while retaining all nodes/edges and the inspection lists.
Fit includes padded curve control geometry, including self-loops and parallel
relations. Fixed positions are presentation coordinates, never model features.

Seven contract/layout checks cover identity, exact amount strings, direction,
malformed input, unknown values, structural semantics, separate relations,
curve bounds and the documented 512-node/4096-edge count. This verifies layout
integrity, not rendering frame rate at that density. The real backend connection
and physical mobile performance remain outside this component delivery.
