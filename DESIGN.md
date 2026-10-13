---
name: Chainrisk
description: Implemented dark glass workspace for Ethereum evidence
colors:
  "accent": "#cee6fb"
  "primary-button": "#dceafa"
  "primary-button-text": "#111d2c"
  "surface-page": "#05070b"
  "surface-panel": "rgb(17 23 32 / 72%)"
  "surface-feed": "rgb(15 22 32 / 67%)"
  "surface-nav": "rgb(19 26 35 / 65%)"
  "surface-button": "rgb(30 41 54 / 58%)"
  "surface-field": "rgb(4 10 18 / 44%)"
  "surface-hover": "#2b3b4f"
  "surface-disabled": "#28333f"
  "text-primary": "#edf3fa"
  "text-secondary": "#a5b3c5"
  "text-disabled": "#b6c1cf"
  "border-default": "rgb(176 204 235 / 18%)"
  "border-field": "#485a6e"
  "band-outer": "#68baf5"
  "band-middle": "#bae6ff"
  "band-core": "#eefaff"
  "band-bloom": "#86caff"
  workspace-ink: "#edf2f7"
  workspace-muted: "#b1becb"
  workspace-action: "#d2e7fa"
  workspace-action-ink: "#152333"
  workspace-low: "#bddfcf"
  workspace-medium: "#e9d1a5"
  workspace-high: "#efbdb5"
  workspace-solid: "#1a222b"
typography:
  "display":
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "clamp(56px, 6.1vw, 88px)"
    fontWeight: 500
    lineHeight: 1.04
    letterSpacing: "-.04em"
  "headline":
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "clamp(32px, 3.5vw, 48px)"
    fontWeight: 500
    lineHeight: 1.12
    letterSpacing: "-.035em"
  "title":
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "-.02em"
  "body":
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  "label":
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "13px"
  "metadata":
    fontFamily: "Helvetica Neue, Helvetica, Arial, sans-serif"
    fontSize: "12px"
  "address":
    fontFamily: "ui-monospace, monospace"
    fontSize: "12px"
  workspace-title:
    fontFamily: "Inter Workspace, Helvetica Neue, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 450
    letterSpacing: "-.025em"
  workspace-graph-title:
    fontFamily: "Inter Workspace, Helvetica Neue, Arial, sans-serif"
    fontSize: "23px"
    fontWeight: 400
  workspace-value:
    fontFamily: "Inter Workspace, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "-.015em"
  workspace-score:
    fontFamily: "Inter Workspace, Helvetica Neue, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 350
    lineHeight: 1.2
    letterSpacing: "-.03em"
rounded:
  "control": "12px"
  "panel": "24px"
  "panel-mobile": "20px"
  "pill": "99px"
  workspace-entry: "22px"
  workspace-action: "14px"
  workspace-risk: "10px"
spacing:
  "1": ".5rem"
  "2": "1rem"
  "3": "1.5rem"
  "4": "2rem"
  "5": "3rem"
  "panel-inset": "28px"
  "panel-inset-medium": "24px"
  "panel-inset-mobile": "22px 20px"
  workspace-gap: "22px"
  workspace-inset: "24px"
  workspace-mobile-inset: "22px"
components:
  "button-primary":
    backgroundColor: "{colors.primary-button}"
    textColor: "{colors.primary-button-text}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  "button-secondary":
    backgroundColor: "{colors.surface-button}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  "button-hover":
    backgroundColor: "{colors.surface-hover}"
  "button-disabled":
    backgroundColor: "{colors.surface-disabled}"
    textColor: "{colors.text-disabled}"
  "input":
    backgroundColor: "{colors.surface-field}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.control}"
    padding: "14px 16px"
  "navigation":
    backgroundColor: "{colors.surface-nav}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.pill}"
    padding: "5px"
  "status-badge":
    rounded: "{rounded.pill}"
    padding: "5px 9px"
  "panel":
    backgroundColor: "{colors.surface-panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel-inset}"
  "feed-panel":
    backgroundColor: "{colors.surface-feed}"
    rounded: "{rounded.panel}"
  "icon-button":
    textColor: "{colors.text-primary}"
    rounded: "50%"
    size: "40px"
  workspace-pane:
    textColor: "{colors.workspace-ink}"
    rounded: "{rounded.panel}"
    padding: "{spacing.workspace-inset}"
  workspace-submit:
    backgroundColor: "{colors.workspace-action}"
    textColor: "{colors.workspace-action-ink}"
    rounded: "{rounded.workspace-action}"
    size: "50px"
  workspace-risk-low:
    textColor: "{colors.workspace-low}"
    rounded: "{rounded.workspace-risk}"
    padding: "10px 11px"
  workspace-risk-medium:
    textColor: "{colors.workspace-medium}"
    rounded: "{rounded.workspace-risk}"
    padding: "10px 11px"
  workspace-risk-high:
    textColor: "{colors.workspace-high}"
    rounded: "{rounded.workspace-risk}"
    padding: "10px 11px"
---

# Design System: Chainrisk

## Overview

**Creative North Star: "Evidence in dark glass"**

Monochrome NASA starfields, broad icy-blue light bands and translucent charcoal surfaces form one calm workspace. Dense evidence stays in readable panels while the homepage has a more open, large-scale introduction. White and icy blue carry emphasis; the background supplies atmosphere without encoding activity or risk.

This record captures the implemented dark frontend and the already pinned visual direction. The north-star phrase is a descriptive shorthand, not a new brand selection. The retained light-theme variable block is not a complete light implementation: shared components and canvas geometry include dark-specific colors.

Ground truth: [shared tokens](apps/frontend/src/design/tokens.css),
[dark theme](apps/frontend/src/design/themes/default.css),
[shared styles](apps/frontend/src/styles/base.css),
[shell](apps/frontend/src/components/layout/AppShell.vue),
[backdrop](apps/frontend/src/components/layout/SpaceBackdrop.vue) and
[scene drawing](apps/frontend/src/design/spaceMotion.ts),
[image sequence](apps/frontend/src/design/spaceImages.ts) and
[NASA source credits](apps/frontend/src/assets/space/SOURCES.md). The
[implementation record](apps/docs/WEBSITE_VISUAL_IMPLEMENTATION.md) and
[background refinement](apps/docs/SPACE_BACKGROUND_REFINEMENT.md) own this
surface's direction and validation. The
[Transaction Graph design](apps/frontend/src/components/analysis/DESIGN.md)
and its [sidecar](.impeccable/surfaces/transaction-graph.design.json) remain scoped
references for graph semantics and standalone styling. The approved
[workbench refinement](apps/docs/WORKBENCH_GLASS_REFINEMENT.md) and
[workbench styles](apps/frontend/src/styles/workbench.css) define the ETH/ERC-20
surface override: strong frost, locally hosted Inter and compact evidence. This
scoped change preserves the accepted Home, shell and background system.

**Key Characteristics:**
- Monochrome starfields, translucent charcoal panels and broad icy-blue light bands.
- A spacious introduction followed by compact, readable evidence.
- Slow photographic crossfades and continuous band motion, with a static reduced-motion alternative.
- Explicit unavailable states, exact values and traceable context.

## Colors

### Primary

Icy light (`accent`) provides focus and links; frost (`primary-button`) marks the
principal action. The band tokens build substantial icy-blue light
geometry with a white-blue core, softer outer strokes and blue bloom. These are decorative,
not data categories. Scoped workbench risk boxes use green, gold and red only for
supplied Low, Medium and High task bands; their text preserves the meaning.

### Neutral

Space black (`surface-page`) anchors translucent charcoal panel, feed, navigation,
button and field surfaces. Cool white (`text-primary`) and slate blue
(`text-secondary`) establish reading priority. Fine cool borders separate layers;
fields use a stronger border. Disabled controls retain legible text on an opaque
muted surface. Primitive values above are normative; the sidecar's synthesized
color ramps are preview metadata, not additional application tokens.

**The Evidence Rule.** Atmospheric light and neutral status styling never imply transaction activity, model readiness or a risk verdict.

## Typography

The shared stack is Helvetica Neue, Helvetica, Arial and sans-serif, explicitly
following the user's pinned neutral-system direction. Monospace addresses and
tabular figures preserve exact evidence. Do not infer a new font identity from
this documentation pass. The approved workbench override uses the locally bundled
Inter variable font under the CSS family `Inter Workspace`, with Helvetica Neue,
Arial and sans-serif fallbacks. It enables contextual alternates, tabular numerals
and optical sizing only within `.workbench`. Workspace titles are lighter than
shared titles; risk values use the workspace-score role. Workspace context titles
are 21px at weight 450, address entry is 18px (16px on narrow screens), and field
labels/readouts are 11px. Exact addresses still use the inherited monospace class.

Display typography belongs to the homepage headline; headline typography serves
page titles. Panel titles use the title role. Body, labels and smaller metadata
carry compact supporting information. Homepage introductory copy is 22px with
1.35 line height; panel descriptions are 13px with 1.6 line height. Table and
address text is 12px; metadata can reduce to 11px. Smaller values are observed
contextual treatments, not an instruction to shrink general body copy.

At 760px and below, the homepage display becomes `clamp(48px, 10vw, 68px)` and its
introductory copy becomes 20px. The generic title scale stays intact. Main weights
are restrained: headings and buttons use 500, while the wordmark uses 600.

**The Readable Evidence Rule.** Keep exact addresses and quantities in monospace or tabular figures, with explicit units and unavailable-state text.

## Layout

The shared desktop container is `min(1400px, calc(100% - 96px))`. Header uses a
three-column brand/navigation/tools grid; content starts with 40px top padding.
The homepage introduction uses a 1.35:1 split and 60px gap. Its actual transaction
feed follows directly in a full-width glass panel.

ETH and ERC-20 initially show a centered address field. Submission replaces it
with the workbench. Desktop columns are `minmax(220px, .7fr) minmax(380px, 1.45fr)
minmax(300px, 1fr)`, separated by the workspace gap. Analysis context and independent
risk results share the sticky left rail (24px top; maximum height
`calc(100dvh - 48px)` with internal overflow). Graph View sits in the center;
Basic Information and activity occupy the right. The ten-row ledger spans center
and right below. Basic Information uses two columns, with each label above its value.

At 1180px and below the workbench becomes a 220px rail plus a flexible evidence
column: graph, two-column information/activity, then ledger. At 820px and below
sticky positioning releases and the page becomes a vertical flow; context/risk
and information/activity each retain two columns. At 560px and below those pairs
stack, workspace insets use 22px and the entry field fills the available width.
The SVG derives its aspect ratio from scene width/height with automatic height;
Graph View aligns at the start and never stretches to match the right rail.

Shared responsive behavior remains independent: at 1100px container gutters become
28px; at 760px they become 20px, navigation moves to a centered header row and the
homepage introduction becomes one column. Tables keep a dedicated horizontal
scroll container and empty-state explanations remain outside it.

## Elevation & Depth

Shared surfaces use tonal layering, fine translucent borders and 24px backdrop
blur instead of box shadows. Navigation is a shallow glass capsule. The feed uses
a distinct slightly darker translucent fill. Standalone graph surfaces retain their scoped 20px panel blur and inner layers.
Within the approved workbenches, borderless panes use a 145-degree translucent
highlight gradient (`rgb(220 233 247 / 12%)` to `rgb(139 159 179 / 6%)`), 46px blur
and saturation `.8`. The inset highlight and soft ambient shadow are recorded in
the sidecar. The entry uses the same gradient and blur without the saturation
adjustment. Reduced transparency uses `workspace-solid` and removes these filters. Reduced transparency makes shared panels and
navigation opaque and removes their blur.

Five locally bundled NASA original JPEGs supply the photographic layer; source
credits and original download links live in
[NASA image sources](apps/frontend/src/assets/space/SOURCES.md). Their pixels
remain intact, with browser presentation using `grayscale(1) brightness(.9)
contrast(1.12)` and fixed cover cropping. Photographs hold for 72 seconds and
crossfade for 24 seconds without pan or zoom. Two image slots keep the current
and upcoming observations available; the next image must decode before fading.
Failed assets are skipped, the last available image stays visible, and the dark
ground remains the fallback if all images fail.

The fixed canvas starts with Orbital arc and cycles through twelve compositions:
Orbital arc, Lower horizon, Diagonal filament, Polar crescent, Double orbit,
Open spiral, Luminous sine, Braided ribbons, Long wave, Vertical veil, Offset
ripple and Distant sweep. A shuffled bag avoids immediate repeats. Each
composition lasts 40 seconds, including a ten-second smoothstep crossfade.
Slow drift and soft breathing modulate continuous bands. Three soft strokes
share a width-dependent base of 13–24px, scaled to 1.65, .95 and .45 for the
outer, middle and core passes; their bloom is decorative canvas depth, not a
panel shadow.

A gradient veil darkens the photographic layer. A cached spatial canvas mask
attenuates bands around actual text-node client rectangles in page headings and
the header, with 22px blur. The landing headline/copy overlays the continuous
background without local cutouts. The mask is remeasured on
resize, scroll, route quiet-state changes and main-content resize. Glass panels
continue to protect dense evidence. Home uses .96 canvas and .72 starfield
opacity; other routes use .58 and .55, with 900ms opacity transitions that leave
the timeline continuous.

Backgrounds play by default with no header pause control or persisted background
pause state. Hidden pages stop scheduling animation frames; reduced motion shows
a static photograph and Orbital arc without opacity transitions. The homepage
Feed pause remains an independent data control. Ordinary control transitions
last 180ms and stop under reduced motion.

**The Quiet Workspace Rule.** Dim the continuous backdrop behind workbenches without resetting its timeline; preserve a static alternative for reduced motion.

## Shapes

Broad panel corners contrast with smaller rounded controls and capsule navigation
and status badges. Shared panel radius reduces on mobile. Borders are one pixel;
focus is a two-pixel pale-blue outline with a
five-pixel offset. Decorative arcs and waves belong behind the content, while
information itself remains aligned to rectangular grids and table rows. Workbench
panes retain the 24px panel radius on mobile, while the entry, submit control and
risk classifications use their scoped rounded tokens. These overrides do not
change global control shapes.

## Components

### Buttons

Primary buttons have a light fill and dark text, brightening to white on hover.
Secondary buttons have a translucent dark fill, brighter hover fill and stronger
hover border. Both use compact padding and a 42px minimum height. The workbench entry's submit control is a 50px square (44px at 560px and below),
using the scoped action fill and a 14px radius. Disabled buttons use the explicit muted
surface and text treatments.

### Inputs and status badges

Labeled fields have a dark translucent inset fill, stronger border, 14px by 16px
padding and pale-blue caret. Label and field stay together. Workbench entry remains editable; submission requires a valid address and an
enabled analysis service. Validation/service messages appear only when needed.
The editable field disappears after submit; New analysis returns to entry and
restores input focus. Submitted address, real backend stage, network, cutoff and
selected pool remain in context. The seven-segment stage indicator reflects
actual backend states, without a timer-derived percentage. Status
badges are compact outlined capsules with text. Although their API accepts risk
tones, the current shared badge CSS renders neutral styling; do not infer shipped
colored risk variants from the API. Workbench risk classifications are a distinct
component: right-aligned rectangular boxes with supplied Low/Medium/High labels,
subtle colored fills/borders, exact task scores and narrow meters. Null stays
unavailable; task reasons/calibration remain accessible without expanded prose.

### Panels and evidence tables

Panel headers pair a medium title with optional actions. Descriptions and
footnotes use quieter text. Tables use restrained shaded header rows, thin
dividers, exact-value columns and a dedicated horizontal scroll container.
Unavailable-state headings remain brighter than their explanations. The feed
requests a real read-only snapshot and may show unavailable or stale-state text;
this visual implementation does not deliver the backend stream. No synthetic rows are used to fill the feed presentation. Workbench information
renders every supplied `information.fields` item; each current family retains its
12-field inventory. The ledger requests ten rows through the cursor API on every
page, including the initial analysis payload. A presentation slice of a larger
page must not substitute for server pagination.

### Navigation and ledger categories

The Chainrisk wordmark returns Home. The shared capsule contains Forecast, ETH
and ERC-20. Links brighten on hover; the current route receives a translucent
light fill. Forecast's page content is only `To be implemented`. Ledger categories
use text buttons with a pale underline on the selected category. All interactive
controls inherit visible keyboard focus; reduced motion removes transitions.

### Transaction Graph

Keep the existing scoped design for topology, node roles, selection, directed
edges, inspection and bounded entrance. Within workbenches the plot is glyph-only, including selected/hovered nodes;
node/edge labels and summaries remain in hover/focus tooltips and persistent
inspection. Role shapes and original directed edges retain their semantics. The
canvas follows its scene aspect ratio. Inspect graph and Graph provenance open
by default; the desktop graph panel stretches to match the adjacent information
and activity column without stretching the canvas. Its
synthetic development preview remains separate from application routes.

## Do's and Don'ts

### Do:
- Do reuse the dark palette, glass panels and pale-blue focus treatment.
- Do preserve clear field labels, keyboard focus, text statuses and horizontally scrollable tables.
- Do keep the homepage feed inside the page and independent task evidence inside the workbenches.
- Do respect reduced motion and reduced transparency preferences; keep Feed pause independent of decorative background motion.

### Don't:
- Don't use atmospheric motion or decorative color as evidence of a live service or a risk result.
- Don't fabricate transactions, chart values, scores or completed analysis states to fill a panel.
- Don't treat the retained light variables as evidence that every surface supports light mode.
- Don't replace the graph's scoped interaction and geometry rules with the global panel defaults.
