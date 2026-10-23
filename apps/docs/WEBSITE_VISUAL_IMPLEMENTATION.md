# Website visual implementation

> Presentation revision, 2026-10-13: [Workbench glass refinement](WORKBENCH_GLASS_REFINEMENT.md)
> supersedes the earlier ETH/ERC-20 query/panel composition, graph plot labels,
> workbench typography and panel material below. It preserves field inventories,
> task/model meanings, graph provenance and inspection semantics. Home, shared
> navigation and accepted background styling retain their own authority.

Date: 2026-10-13. Scope: implement the user's pinned visual brief across Home,
ETH, ERC-20, Forecast placeholder and common navigation. The user requested
continuing the remaining webpages after the Transaction Graph implementation.
The [visual brief](VISUAL_DIRECTION_BRIEF.md) supplies appearance; the page-content
and website architecture specifications still govern fields, flows and data.

## Direction contract

**THESIS:** Ethereum activity and its evidence live in one calm, readable glass
workspace. The homepage contains the actual transaction-summary dashboard, not
a mock product image. Analysis pages preserve the five specified modules.

**OWN-WORLD:** Black space-like ground, slow white/icy-blue light geometries,
translucent charcoal panels and pill navigation. Neutral system typography follows
the pinned brief; exact addresses and values use monospace/tabular figures.

**STORY:** Enter through Chainrisk, inspect the transaction feed, navigate to ETH
or ERC-20, and understand independent task availability. Missing data remains
explicit. Forecast says only `To be implemented`.

**FIRST VIEWPORT:** Brand left, three-item navigation centered, motion control
right. Homepage uses a large two-line headline balanced by concise explanation
and two analysis links, with the glass feed dashboard beginning immediately below.
Workbench headers lead into full-width query, risk/basic information, graph/activity,
and a full-width ledger. Mobile follows the same semantic order in one column.

**FORM:** Direct implementation of the user-pinned composition and material,
code-first. No new aesthetic concept or selection round. Signature motion is a
12-scene, shuffled continuous background with breathing light and crossfades;
the workbench dims it without resetting the timeline.

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Boundaries

This continues an already confirmed navigation amendment; it does not introduce
another workflow/model contract change. All webpage copy is English. No backend
service is implemented here. Homepage may request the existing read-only feed
snapshot endpoint; errors show unavailable state. No fake transactions, scores,
chart values, elapsed analysis progress or availability claims are introduced.
The graph's synthetic development preview remains separate from application routes.

## Implemented surface

The shared shell uses a black ground, pale blue-white text, translucent dark
panels, 24px blur and compact pill navigation. Home contains the actual snapshot
feed component, with retry, UTC freshness, stale-state disclosure and exact
decimal ETH values. Analysis routes retain their five specified modules with
family-specific fields. Risk details and ledger category switches are available;
query submission and record pagination remain unavailable with explanations.

The canvas implements twelve compositions, a shuffled bag with no immediate
repeats, 24-second scenes and five-second smooth crossfades. Brightness breathes
slowly. Navigation preserves the timeline and dims it behind workbenches.
Pause persists in optional local storage, reduced motion renders a static wave,
hidden documents stop scheduling frames, and unmount cleans up all listeners.
No external image assets or new dependencies were added.

## Validation

- Production build and TypeScript check pass; eleven graph/website checks pass.
- Scene tests verify all twelve variants per cycle and non-repeating boundaries;
  amount tests retain single-wei and large-number precision without floats.
- Integrated browser captures cover Home, ETH and ERC-20 at 1440px and 390px,
  plus the actual 615px app window. Page-level horizontal overflow was absent.
  Wide table headers remain scrollable; empty-state guidance remains outside
  the scrolling region and fully readable on mobile.
- Browser interactions verified navigation, Forecast placeholder, task
  disclosures, ledger category/column switching and background pause.
- Automated design detector returned no findings. Real stream behavior, complete
  populated analysis workflows and physical-device performance are not verified.

The frontend still reports missing services honestly. These checks do not imply
chain collection, admitted models, real scores or operational service readiness.

## Later homepage integration: 2026-10-13

The earlier snapshot-only boundary above is superseded by the separately enabled
real-chain feed. Home now receives incremental SSE transactions with pause/resume,
HTTP recovery, source freshness, receipt details and a bounded scrollable table.
No homepage synthetic fallback was added. See [feed integration](FEED_INTEGRATION.md).

## Later background refinement: 2026-10-13

The user requested a bolder space background and removed the header's decorative
motion control. The original background paragraph above is superseded by
[space background refinement](SPACE_BACKGROUND_REFINEMENT.md): five attributed
NASA photographs rendered in monochrome; 72-second holds and 24-second image
crossfades; twelve wide icy-blue band geometries on 40-second scenes with
ten-second crossfades. No new runtime dependency was added. Operating-system
reduced motion and hidden-tab suspension remain; Feed pause is independent.

The refinement passes production/TypeScript build and all nineteen current
frontend checks. Updated browser evidence covers Home and ETH at 1440px / 390px,
plus the actual 1280px window. Image loading, grayscale presentation, natural
photo advancement, route continuity and removal of header controls were checked.
The source metadata scan reports five attributed rasters and zero missing.
Physical-device animation performance and the complete eight-minute photo cycle
have not been benchmarked.
