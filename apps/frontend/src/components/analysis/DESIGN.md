---
name: Chainrisk Transaction Graph
description: Scoped transaction graph and approved ETH/ERC-20 workbench overrides
colors:
  graph-surface: "#10151d"
  graph-glass: "rgb(14 20 29 / 88%)"
  graph-text: "#edf4fc"
  graph-accent: "#c2e0fb"
  graph-muted: "#a8b6c8"
  graph-border: "#2b394a"
  graph-line: "#748ba4"
  graph-control-border: "#718197"
  graph-hover: "#233245"
  graph-field: "#111d2a"
  graph-details: "#142131"
  workspace-ink: "#edf2f7"
  workspace-muted: "#b1becb"
  workspace-low: "#bddfcf"
  workspace-medium: "#e9d1a5"
  workspace-high: "#efbdb5"
typography:
  title:
    fontFamily: "system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 500
    letterSpacing: "-.02em"
  body:
    fontFamily: "system-ui, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, sans-serif"
    fontSize: "12px"
  address:
    fontFamily: "ui-monospace, monospace"
    fontSize: "13px"
  workspace-title:
    fontFamily: "Inter Workspace, Helvetica Neue, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 450
    letterSpacing: "-.025em"
  workspace-score:
    fontFamily: "Inter Workspace, Helvetica Neue, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 350
    lineHeight: 1.2
    letterSpacing: "-.03em"
rounded:
  control: "8px"
  detail: "12px"
  panel: "24px"
  pill: "999px"
  workspace-risk: "10px"
spacing:
  compact: "8px"
  mobile-inset: "16px"
  detail-inset: "20px"
  panel-inset: "28px"
components:
  graph-control:
    backgroundColor: "transparent"
    textColor: "{colors.graph-muted}"
    rounded: "{rounded.control}"
    padding: "8px"
  graph-control-hover:
    backgroundColor: "{colors.graph-hover}"
    textColor: "{colors.graph-text}"
  graph-select:
    backgroundColor: "{colors.graph-field}"
    textColor: "{colors.graph-text}"
    rounded: "{rounded.control}"
    padding: "10px"
  graph-details:
    backgroundColor: "{colors.graph-details}"
    rounded: "{rounded.detail}"
    padding: "20px"
  graph-task:
    rounded: "{rounded.pill}"
    padding: "8px 12px"
  graph-panel:
    backgroundColor: "{colors.graph-glass}"
    textColor: "{colors.graph-text}"
    rounded: "{rounded.panel}"
---

# Design System: Chainrisk Transaction Graph

## Overview

**Creative North Star: "Dark glass, readable relations"**

This record covers the implemented Transaction Graph component and the approved
ETH/ERC-20 workbench overrides recorded on 2026-10-13. Its dark
glass frame, pale-blue geometry and stable topology inherit the pinned visual
brief. It neither approves nor implements a whole-site redesign. The surrounding
scaffold retains its own styles. The phrase above describes that existing
direction; it is not a new brand decision.

Ground truth: [styles](../../styles/transaction-graph.css),
[panel](TransactionGraphPanel.vue), [canvas](TransactionGraphCanvas.vue).
The [component contract](../../../../docs/TRANSACTION_GRAPH_DESIGN.md) owns its strategy;
the broader [visual brief](../../../../docs/VISUAL_DIRECTION_BRIEF.md) remains a proposal.

**Key Characteristics:**
- Dark glass and restrained icy-blue contrast.
- Role shapes and original directed relationships.
- Stable geometry after a bounded entrance.

## Colors

### Primary

Icy blue (`graph-accent`) marks focus and restrained emphasis. Original edges use
the quieter `graph-line`. Neither color encodes a risk verdict.

### Neutral

Dark glass, cool white text, muted descriptions and fine borders separate the
plot, controls and persistent evidence. Custom properties scope these assignments
to the graph panel.

**The Evidence Rule.** Role and selection styling never imply that a neighbor was assessed.

## Typography

Standalone graph system sans supports compact operational text; the inherited monospace stack
distinguishes addresses. Title, body and label tokens describe the main hierarchy.
Details headings use 16px at weight 500. Mobile titles reduce to 18px and
explanatory copy to 13px. No site-wide display typography is established here. Within `.workbench`, locally
hosted Inter replaces the inherited body face, with tabular numerals/contextual
alternates. Graph View uses 23px at weight 400; other panel titles use the scoped
workspace-title role. This override leaves Home and global type unchanged.

## Layout

Header and wrapping toolbar precede the SVG, legend, inspection selects, selected
details and expandable provenance. Desktop uses the panel inset and plot height
`clamp(380px, 45vw, 560px)`. At 640px and below, mobile insets apply, selects stack,
controls spread across a full row, and the plot is 380px tall.

The current plot renders role glyphs without node text labels at all sizes,
including hover/selection. Details remain available through tooltips, focus,
inspection lists and selected records. Fit includes curve and loop bounds.
In workbenches the graph aligns at the start of its column and its SVG uses the
scene width/height as the aspect ratio with automatic height. This avoids the
previous vertical stretch against Basic Information/activity. The standalone
plot-height rules above remain outside that override. The surrounding three-column
workspace, sticky context rail and ten-row ledger are documented in
[the workbench revision](../../../../docs/WORKBENCH_GLASS_REFINEMENT.md).

## Elevation & Depth

Tonal layers, a dark radial plot gradient and fine borders carry depth without
box shadows. Panel backdrop blur is 20px; tooltip blur is 12px with a more opaque
ground. The workbench frame overrides this with a borderless translucent
145-degree highlight gradient, 46px blur, `.8` saturation, an inset top highlight
and a soft ambient shadow; see root DESIGN.md and its sidecar for the exact
material. Workbench tooltips use `rgb(27 36 46 / 94%)`. Reduced transparency removes
filters and uses the corresponding solid surface.

## Shapes

Broad panel corners, medium detail/tooltip corners, compact controls and a pill
task badge follow the frontmatter scale. A root orbit and distinct role shapes
identify nodes. Structural edges retain their dashes after entrance resolves.

## Components

### Controls and inspection fields

Transparent muted buttons brighten on hover. Focus uses a pale-blue 2px outline
with a 4px offset; SVG focus strengthens the node shape instead. Controls have
a 36px minimum size and a 40px minimum height on mobile. Native selects provide
an alternative inspection path. Disabled controls dim.

### Panel, task badge and details

The standalone bordered glass panel contains the inspection flow; workbench
panes use the scoped borderless frost. The badge names the actual
sample task. Selected details persist below the graph; hover/focus reveals a
nearby tooltip. Addresses wrap. Empty, loading and error states explain missing
evidence. This component has no navigation primitive.

### Directed graph

Nodes resolve by graph distance over 720ms; edges draw over 780ms, using
`cubic-bezier(.16, 1, .3, 1)`. Geometry then settles. State transitions take 180ms.
Reduced motion and the motion toggle disable animation and transitions. Replay
affects presentation only. Pan, Fit and zoom preserve inspection; arrows traverse
items, Enter selects, and Escape dismisses inspection.

**The Settled Geometry Rule.** Entrance finishes; inspection never depends on perpetual drift.

## Do's and Don'ts

### Do:
- Do preserve original direction and structural dashes.
- Do keep missing evidence explicit and addresses readable.
- Do suppress animation and transitions for reduced motion.

### Don't:
- Don't assign risk meaning to neighboring node colors.
- Don't apply these scoped tokens to unrelated pages without a separate decision.
- Don't present entrance animation as live transaction activity.
