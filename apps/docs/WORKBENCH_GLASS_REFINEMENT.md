# Workbench glass refinement

Date: 2026-10-13. User-requested revision of ETH and ERC-20 page interaction and
presentation, using `apps/reference/layout_element_blur.png` as visual authority.
The established data fields, independent task semantics and model boundaries stay
authoritative; this revision replaces the former query-above-five-panels layout.

## Direction contract

**THESIS:** Enter one address, then read its evidence in a quiet, frosted workspace.

**OWN-WORLD:** Actual smoky glass over the existing NASA starfield and icy-blue
bands. Strong background blur, soft translucent highlights and no dark outlined
cards. A locally hosted Inter variable face provides the compact modern UI voice.

**STORY:** A centered address field is the sole initial page body. Submit once to
enter the workspace. Submitted identity and actual service stages remain visible
in the left rail; the editable address field disappears. New analysis resets the
view and cancels frontend tracking, without deleting the backend job.

**FIRST VIEWPORT:** Three columns. Left: two compact sticky panes, analysis context
above independent task scores. Center: the dominant Graph View. Right: Basic
Information and Flow Activity. Below: a ten-row Transaction Ledger spanning center
and right. Mobile releases sticky positioning and follows a single reading order.

**FORM:** Code-led refinement of the pinned glass reference. Preserve existing
backgrounds and application behavior. Cut explanatory headings, subtitles and
redundant helper paragraphs specifically named by the user. The graph plot holds
symbols only; labels and summaries remain in hover/focus and explicit inspection.

**FINISH:** Validate entry, submission, progressive states, sticky scrolling,
null-score meaning, glyph-only graph hover, ten-row cursor pagination and narrow
screen layout. Independent finish review and scoped design documentation follow.

## Information boundaries

Risk panes show task names, exact supplied scores, meters and admitted risk bands.
Null scores stay unavailable; no numeric zero or low-risk substitute. Supporting
task metadata remains in response data and accessible labels rather than expanded
prose. ERC-20 retains Honeypot/Rug Pull, never ETH task relabeling.

Basic Information retains every supplied `information.fields` entry in a compact
two-column layout, with each label above its value. Redundant hints and separate secondary metadata prose are
removed from the main presentation. Cutoff and selected pool identity remain in
the persistent analysis-context pane. Actual backend stage changes drive progress;
no timer-derived percentage is introduced.

Ledger pages request limit=10 from the existing cursor API, including page one.
Do not truncate the old 30-row initial payload and reuse its cursor: that would
skip records. Preserve task/sample provenance, graph edge direction and existing
transaction detail inspection.
