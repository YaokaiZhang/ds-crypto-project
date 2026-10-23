# Chainrisk visual direction brief

Date: 2026-10-12. Status: shape proposal for confirmation, not an implemented
design system or a replacement content specification.

## 1. Authority, audience and outcome

The [website architecture](WEBSITE_ARCHITECTURE.md),
[ETH Scam inventory](ETH_SCAM_WORKBENCH_DESIGN.md), and
[Token Scam inventory](TOKEN_SCAM_LAYOUT_SPEC.md) remain authoritative for
content, interactions, data semantics and component responsibilities.
This brief resolves visual choices those documents leave open.

The user confirmed the following requirements:

- Communication with the user is Chinese; website copy is English. Repository
  documentation remains English under the project contract.
- Everyday token holders are the primary audience.
- Global navigation is Forecast / ETH / ERC-20. The Chainrisk brand returns Home.
  Forecast opens a placeholder reading `To be implemented`.
- The homepage dashboard is the shared backend ETH RPC transaction-summary feed.
  Full scam workbenches remain on their own pages.
- The visual direction combines the supplied dashboard layout, blurred glass
  components, black space-like grounds and white/icy-blue moving light forms.
- More than ten background variants play as a continuous, naturally transitioning,
  randomized sequence. They are not merely a set of static page assignments.

Home combines an introductory Persuade region with an Operate feed region;
ETH, ERC-20 and persistent analysis detail are Operate surfaces. A first-time
visitor should understand the available tools and distinguish observed facts
from an unavailable model result without knowing graph-model terminology.

Only the navigation amendment is already confirmed as a contract revision.
The composition, token values and motion parameters below are design proposals;
confirm this brief before implementation. No new direction contract is created
by this shape task.

## 2. Reference analysis

These are visual observations, not sampled color measurements or identified
font families. Exact font identities cannot be established from screenshots.

| Reference | Typography and hierarchy | Color and material | Spacing and composition | Application |
|---|---|---|---|---|
| [layout.png](../reference/layout.png) | Neutral sans; medium navigation; light large numbers; tracked uppercase labels; monospaced technical values | Near-black ground, charcoal panels, off-white text, faint borders and restrained status accents | Wide horizontal brand/navigation strip; asymmetric large/small panels; generous padding; full-width ledger anchoring the bottom | Workbench grid rhythm, rounded shell and ledger treatment; do not copy metric inventory or numerical claims |
| [layout_element_blur.png](../reference/layout_element_blur.png) | Light display type; compact, legible content; small tracked section labels | Smoky translucent surfaces, blurred underlying light, delicate edge highlights; selective white foreground | Layered planes, pill navigation, large-radius containers; foreground clearly separated from atmospheric depth | Glass material for navigation and panels; workbench panels stay aligned and non-overlapping |
| [background_ref1.png](../reference/background_ref1.png) | Sparse, clear foreground; technical accents subordinate to readable labels | Almost-black ground; soft icy-blue halo with a white core; controlled bloom | Huge partial ring enters from outside the frame; luminous mass balanced against a quiet content area | Edge-cropped arcs and orbit forms; bright cores avoid text and chart plotting areas |
| [background_ref2.png](../reference/background_ref2.png) | Oversized, light, tightly arranged display headline; small navigation and supporting text | Black/charcoal with white particulate geometry, minimal chroma | A wave sweeps across the viewport; asymmetry and negative space create scale | Homepage background composition and headline scale; replace reference marketing content with actual Chainrisk purpose and feed |

Synthesis: one dark spatial environment behind a calm, structured glass interface.
The references supply different layers of the same design: dashboard topology,
glass material, and moving light. Do not import their unrelated logos, login,
pricing, export actions, fake metrics or operating-system terminology.

## 3. Page composition

### Shared header and navigation

Chainrisk wordmark at the left; Forecast / ETH / ERC-20 in a translucent pill
navigation group. Use a softly filled active segment and a visible keyboard
focus ring. Brand links to `/`; ETH keeps `/eth-scam`; ERC-20 keeps `/token-scam`.
Add `/forecast` only for the placeholder. The user removed the saved-analysis
feature on 2026-10-13; no persistent-result browser route or reopening link remains.
Nav labels do not rename task IDs or the Phishing/Ponzi/Honeypot/Rug Pull tasks.

Use the existing wordmark without inventing a final emblem. On narrow screens,
keep all three links visible in a second header row rather than hiding the
primary destinations. Header glass must remain legible over any background frame.

### Home: introduction and transaction dashboard together

Use the wave reference's spacious, asymmetric composition, with a concise
headline such as `Explore Ethereum activity.` and supporting text that explains
the two screening destinations without promising live model availability.
Primary links can read `Explore ETH` and `Explore ERC-20`.

The real `Latest Transactions` glass dashboard begins within the first desktop
viewport: a compact introduction above it, with wave motion mainly around the
outside. At a 1440 x 900 reference viewport, aim to show the dashboard heading,
source status, column headers and several rows without scrolling. This is a
composition target, not a requirement to shrink text on shorter screens.
The feed is part of the homepage itself, not a screenshot of a hypothetical app.

Feed fields remain hash, from, to, block/time, native ETH value and Gas Limit;
receipt-derived fields appear only when available. Preserve the initial 20–30
row snapshot, at most one new sampled row per second, pause/reading behavior,
freshness, reconnect and source-gap semantics in the architecture.
No market KPI cards, risk verdicts, fabricated throughput or unsupported totals.
In today's scaffold, use the explicit unavailable state rather than invented rows.

### ETH and ERC-20: shared glass workbench

Desktop proposal uses a 12-column grid with the reference's asymmetric rhythm:

1. Full-width query and identity, including cutoff and relevant pool scope.
2. Risk Screening (4 columns) and Basic Information (8 columns).
3. Transaction Graph (8 columns) and Activity (4 columns).
4. Full-width Transaction Ledger, followed by compact provenance/status details.

Risk Screening contains two independent task rows within one module; do not add
the reference's extra summary-card row. Basic Information stays one multi-column
panel. The graph has the largest working area. The narrower Activity panel must
still fit two aligned ETH subplots; stack it below the graph at widths where
axes and labels no longer fit, rather than compressing them into illegibility.

At medium widths, stack Risk then Basic Information, Graph then Activity, then
Ledger. On mobile, use the same single-column reading and focus order, preserve
full-address detail/copy access, and contain horizontal ledger overflow inside
its panel. Never remove required fields just to fit a reference composition.

ETH retains native account fields, Phishing/Ponzi, directed task graph,
native flow/count plots and External Transactions/Internal Transfers.
ERC-20 retains token/pool fields, Honeypot/Rug Pull, token graph roles,
Transfer/Swap/Mint/Burn counts and Token Transfers/Pool Events.
Graph drawing, ledger semantics and scope remain defined by their specifications.

Forecast receives only the shared shell and `To be implemented` message.
No forecast dashboard, sample prediction or new forecasting interaction.

## 4. Proposed semantic tokens

Values are implementation starting points, not extracted measurements. Verify
contrast on the actual composited surface during implementation. The dark
direction is primary; the existing light-theme capability is not silently removed.
Any later light-theme refinement must preserve the same semantic contracts.

| Token or group | Proposed value / intent |
|---|---|
| `--surface-page` | `#05070B`, near-black with a restrained cool bias |
| `--surface-panel` | `rgba(15, 20, 28, 0.80)`, stable dark tint under glass |
| `--surface-panel-solid` | `#10151D`, no-backdrop-filter/reduced-transparency fallback |
| `--surface-data` | `rgba(7, 11, 17, 0.94)`, quieter chart/table interior |
| `--text-primary` / `--text-secondary` | `#F2F5F8` / `#ABB6C5`; keep body copy distinctly readable |
| `--border-default` / `--border-emphasis` | White at 12% / 22%; decorative panel edges, not sufficient by themselves for input affordances |
| `--border-control` | `#718197`; visible field boundaries, checked against the composited surface |
| `--accent` / `--accent-foreground` | `#DDEEFF` / `#07111B`; pale cool primary actions |
| `--focus-ring` | `#B8DFFF`; clear 2px outline with offset |
| `--risk-low` / `--risk-medium` / `--risk-high` | `#8AD5B4` / `#E6C477` / `#F19BA7`; small status accents with text, never decorative background palette |
| `--status-unknown` | `#AFB8C5`; explicitly distinct from low risk |
| `--glass-blur` | 18–24px desktop, 10–14px mobile; fixed blur radius, never animated |
| `--radius-panel` / `--radius-control` | 24px / 12px; pill treatment only for nav and compact controls |
| Spacing scale | 4, 8, 12, 16, 24, 32, 48, 64px; extend existing spacing names without changing their current meanings |
| Panel padding / grid gap | 24–32px / 24px desktop; 16–20px / 16px mobile |
| Content width / outer gutters | Approx. 1440px max; 32–48px desktop and 16–20px mobile gutters |
| `--font-body` | Existing system sans stack; clean neutral appearance, no new external font dependency |
| `--font-mono` | Existing UI monospace stack for addresses, hashes and technical identifiers |
| Type scale | Body 15–16px; helper 13–14px; panel heading 16–18px; page heading 28–36px; homepage display 56–88px desktop / 36–48px mobile |
| Type behavior | Body line-height 1.5; display 1.0–1.1; tabular numeric figures; tracking reserved for short labels |
| UI motion | 160–240ms feedback; content visible immediately, no staggered reveal delay before use |

Blur applies to what is behind a panel, never to its text or data. Use a narrow
edge highlight and restrained shadow, avoiding multiple nested glass layers.
Dense data regions can become nearly opaque without losing the shared material.

## 5. Motion system: 12 distinct presets

2026-10-13 approved refinement: the user requested a monochrome NASA photo
slideshow, brighter/wider icy-blue bands and removal of the header motion switch.
The current implementation uses five photographs, 72-second holds and 24-second
photo fades. Geometry scenes use 40 seconds with ten-second fades. This revision
supersedes the original timing proposal below; the twelve varied geometries stay.
See [the refinement](SPACE_BACKGROUND_REFINEMENT.md) for scope and sources.

Background light is decorative, never a blockchain signal or model activity.
These are twelve different geometries and paths, not twelve colors of one wave.
All use white cores and restrained icy-blue falloff; no saturated rainbow lighting,
flash/strobe, lightning strikes, or foreground particle showers.

| ID | Form and placement | Movement and light character |
|---|---|---|
| 01 Left orbital arc | Huge partial ellipse entering the left edge | Slow clockwise drift; broad blue halo, soft white inner edge |
| 02 Lower horizon | Shallow curved ribbon beneath the dashboard | Lateral flow; a small highlight travels along the rim |
| 03 Diagonal filament | Thin curve from lower-left toward upper-right | Gradual sweep, subtle thickness changes, quiet trailing glow |
| 04 Polar crescent | Tall crescent clipped by the right boundary | Gentle vertical drift with asymmetric breathing |
| 05 Double orbit | Two offset incomplete rings at opposing corners | Slow counter-motion; one brightens while the other softens |
| 06 Open spiral | Broad open spiral outside the central text zone | Slight expansion and rotation, dissipating toward the edge |
| 07 Luminous sine | Continuous wide icy-blue wave across the lower background | Slow phase drift, soft bloom and breathing brightness |
| 08 Braided ribbons | Two parallel sinusoidal light strands | Gradual phase exchange; localized highlights move along strands |
| 09 Long S-wave | One large continuous S-shaped band | Slow curvature evolution; moves through outer negative space |
| 10 Vertical veil | Sparse, nearly vertical curved filaments at one side | Upward drift; low-amplitude light breathing |
| 11 Offset ripple | Off-center expanding elliptical arcs | Slow outward travel; outer arcs dissolve before reaching text |
| 12 Distant sweep | A thin near-horizontal light plane at the upper/lower edge | Sideways passage with broad faint halo; quiet finale before next form |

### Timing and continuity proposal

- One scene lasts roughly 20–28 seconds: 3–4 seconds entering, 13–18 seconds
  flowing and breathing, and 4–6 seconds exiting. The next enters during the
  outgoing tail, so no abrupt cut or black reset is visible.
- Breathing uses a continuous 6–10 second period with modest amplitude, not
  repeated on/off blinking. It never encodes progress, score or data freshness.
- Pick scenes using a shuffled bag of all 12. Do not repeat a preset until the
  bag is exhausted; reject an immediate repeat at bag boundaries. Avoid more
  than two successive scenes from the same ring/ribbon/particle family.
- Match the outgoing and incoming light center, direction and brightness where
  practical. Crossfade unlike geometries; only morph compatible path families.
  Normalize combined brightness during overlap so two scenes do not double bloom.
- Small bounded random variation in path, phase, duration and halo makes cycles
  feel natural. Fixed exclusion zones and brightness caps outrank randomness.
- Maintain one shell-owned timeline through route changes. Ease the composition
  and intensity toward the new page profile instead of restarting the animation.
- Landing profile: more visible geometry in margins and around the feed.
  Workbench profile: about 35–50% of landing intensity as an initial tuning range,
  with strong suppression behind risk text, axes, ledger and graph nodes.

### Accessibility and rendering boundaries

The 2026-10-13 user refinement removes the header background-motion control and
its persisted pause preference; decorative motion plays by default. Feed pause
remains independent. Honor `prefers-reduced-motion` with one static subdued
image and band, and no automatic swaps. When supported, reduced-transparency preference
uses opaque panel surfaces. Motion is not necessary to understand any content.

Use one isolated decorative rendering layer with pointer events disabled and
hidden from assistive technology. A procedural canvas renderer is a candidate
for the curves/particle wave; exact renderer choice follows a performance spike.
Keep at most outgoing/incoming scenes alive during overlap; reuse cached glow
layers, cap pixel ratio/particle density, and suspend rendering in hidden tabs.
Animate path phase, transforms and opacity rather than CSS backdrop-filter.
On mobile or constrained devices, simplify geometry and reduce rendering rate;
use a static scene if necessary. Glass and motion must never delay input or graph
interaction. Validate on actual desktop/mobile targets before claiming smoothness.

## 6. Component responsibility mapping

| Existing boundary | Visual application | Must remain unchanged |
|---|---|---|
| AppShell | Shared glass header, navigation, shell-owned decorative motion layer | Route content ownership; background never owns requests or results |
| HomePage / FeedPanel | Concise wave-backed introduction and actual feed dashboard | Shared server feed, source freshness, sample semantics, independent feed pause |
| AnalysisWorkbench | Responsive asymmetric panel placement | Five modules, query workflow and family-specific inputs |
| AppPanel | Consistent glass surface, edge highlight, readable dense-region treatment | Slots and panel responsibilities |
| AppInput / AppButton / AppIcon | Pale primary action, clear field boundary/focus, semantic icons | Events, validation/disabled behavior, icon adapter |
| StatusBadge / RiskScreeningPanel | Quiet text-led task states and bounded semantic color | Independent scores, explicit null reasons, admitted band policies |
| BasicInformationPanel | Multi-column label/value layout and tabular numbers | Exact wallet/token fields, source/time scopes and units |
| TransactionGraphPanel / graph presenter | Dark quiet plot field, readable nodes/edges and selection details | Actual task sample, original direction, provenance, model/display counts |
| ActivityPanel / chart theme adapter | Restrained lines/bars and contrast-safe axes | Required series, separate units, unknown intervals and display-only filters |
| AppTable / TransactionLedgerPanel | Full-width ledger, subtle row dividers and contained horizontal scrolling | Pagination, event/transaction row identity, tabs and details |
| preferences / useTheme | UI-only motion preference and theme integration when implemented | Analysis identity and stored result values |

## 7. States, ranges and content stress cases

Design query-empty, capability-unavailable, queued, collecting, partial, failed,
completed, not-applicable and unsupported-model states without changing their
service meaning. Preserve usable facts when one task cannot return a score.
Current template state must explicitly explain disabled analysis availability.

Use `Model unavailable`, `Insufficient data`, `Not applicable`, `Coverage incomplete`
and `Feed unavailable` where those states actually apply. Never use a decorative
green indicator or a zero score for missing results. Do not invent percentage
progress from the background animation or from a fixed timer.

Check 42-character addresses, 66-character hashes, long token names, unknown
symbols/decimals, zero versus missing values, large counts, long unavailable
reasons and empty ledger pages. Preserve exact values in details and show units.
For graph density, use model/display counts and the admitted recipe; the current
documented default up to 512 nodes/4096 aggregate edges is a stress case, not
permission to fabricate an example graph or silently crop it.

## 8. Conflicts and resolutions

| Tension | Resolution / status |
|---|---|
| Requested Forecast/ETH/ERC-20 vs current Home/ETH Scam/Token Scam links | Confirmed navigation-only contract amendment: brand returns Home, old analysis URLs remain, Forecast is a placeholder. Domain/task names remain unchanged. |
| Forecast visible while its integration is deferred | Placeholder only; no Task A model integration, prediction UI or readiness claim. |
| Reference layout has an extra metric-card row | Borrow grid proportions and full-width ledger, not its metric inventory. Preserve the five specified modules. |
| Blurred reference overlaps panels and obscures background | Borrow material only; keep analysis panels aligned and readable. Never blur data or obscure required controls. |
| Oversized landing headline can hide the required dashboard | Shorten the introduction so the feed begins in the first desktop viewport; do not create a separate fake dashboard preview. |
| Animated luminous backgrounds compete with graphs/data | Separate decorative and semantic layers; reduce workbench intensity, protect plot/text zones and honor reduced motion. The user removed the header background toggle on 2026-10-13. |
| Monochrome references vs meaningful task states | Keep semantic status accents and text. White/blue atmosphere never replaces risk/unknown distinctions. |
| Current scaffold defaults to light styling | Proposed dark primary presentation is a visual change. Retain theme adapter and light capability; do not alter API/model behavior. |
| Polished landing might imply working live services | Keep explicit template/unavailable states until real feed/model integrations exist; no fake rows, scores or performance claims. |
| Reference fonts and exact visual measurements are unknown | Treat proposed tokens as deliberate design choices; verify rendered contrast and spacing rather than claiming exact extraction. |

## 9. Acceptance and remaining decisions

Confirm the proposed page composition, token direction and motion choreography
as one brief before building. The supplied visual world is already pinned; no
unrelated aesthetic alternatives are required.

Implementation acceptance should check: all required modules and field semantics;
readable desktop/mobile layout; keyboard navigation; focus and status contrast;
real unavailable/partial states; a complete 12-scene cycle without abrupt cuts
or repeats; route continuity; independent feed pause; reduced motion;
and unchanged graph/score identity through theme or background changes.

Exact scene geometry, font rendering, measured contrast, animation cost and final
breakpoints require implementation validation. A final brand emblem and formal
accessibility conformance target remain undecided. No visual prototype, Vue/CSS
change or performance validation is claimed by this document.
