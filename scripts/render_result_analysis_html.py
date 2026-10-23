#!/usr/bin/env python3
"""Build the standalone HTML version of the Ethereum token result report."""

from __future__ import annotations

import argparse
import base64
import html as html_mod
import json
import re
from pathlib import Path
from typing import Any

import mistune


REPORT_NAME = "wallet_graph_project_result_analysis_20261005_v1.md"
DEFAULT_OUTPUT = "reports/wallet_graph_project_result_analysis_20261005_v1.html"
FIGURE_DIR = "data/result_analysis_wallet_graph_20261005_v1/figures"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def slug(text: str) -> str:
    plain = re.sub(r"<[^>]+>", "", text)
    plain = html_mod.unescape(plain).lower()
    plain = re.sub(r"^\d+[.)-]?\s+", "", plain)
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def image_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def inline_report_images(markup: str, report_path: Path) -> str:
    image_pattern = re.compile(
        r'<p>\s*<img src="([^"]+)" alt="([^"]*)"\s*/?>\s*</p>',
        re.DOTALL,
    )

    def replace(match: re.Match[str]) -> str:
        source = (report_path.parent / html_mod.unescape(match.group(1))).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"report image is missing: {source}")
        alt = html_mod.escape(match.group(2), quote=True)
        return (
            '<figure class="report-figure">'
            f'<img src="{image_data_uri(source)}" alt="{alt}">'
            "</figure>"
        )

    return image_pattern.sub(replace, markup)


def method_map() -> str:
    return """
<div class="method-map" role="img" aria-label="Method flow from a label-blind candidate frame through point-in-time features and wallet graphs to validation and locked-test case review">
  <div class="method-row">
    <div class="method-node"><span class="method-kicker">Frame</span><strong>Candidate tokens</strong><span>Fixed pools and sources</span></div>
    <span class="method-arrow" aria-hidden="true"></span>
    <div class="method-node"><span class="method-kicker">Observe</span><strong>t0 + first 7 days</strong><span>Point-in-time cutoff</span></div>
    <span class="method-arrow" aria-hidden="true"></span>
    <div class="method-node"><span class="method-kicker">Follow up</span><strong>Complete 90 days</strong><span>Outcome definition</span></div>
  </div>
  <div class="method-row method-row-branches">
    <div class="method-node method-node-muted"><span class="method-kicker">Input A</span><strong>Tabular logistic</strong><span>Nine aggregate features</span></div>
    <div class="method-node method-node-muted"><span class="method-kicker">Input B</span><strong>Topology GraphSAGE</strong><span>Local wallet-pool structure</span></div>
    <div class="method-node method-node-accent"><span class="method-kicker">Input C</span><strong>Edge-aware GCN</strong><span>Structure plus edge features</span></div>
  </div>
  <div class="method-row">
    <div class="method-node method-node-wide"><span class="method-kicker">Evaluate</span><strong>General split + temporal stress test</strong><span>Validation-only threshold and K=20 review budget</span></div>
    <span class="method-arrow" aria-hidden="true"></span>
    <div class="method-node method-node-wide"><span class="method-kicker">Use</span><strong>Locked test + analyst review</strong><span>Rank, inspect, monitor, record misses</span></div>
  </div>
</div>
"""


def replace_mermaid(markup: str) -> str:
    pattern = re.compile(
        r'<pre><code class="language-mermaid">.*?</code></pre>',
        re.DOTALL,
    )
    return pattern.sub(method_map(), markup, count=1)


def add_heading_ids(markup: str) -> str:
    seen: dict[str, int] = {}
    pattern = re.compile(r"<h([1-3])>(.*?)</h\1>", re.DOTALL)

    def replace(match: re.Match[str]) -> str:
        base = slug(match.group(2)) or "section"
        count = seen.get(base, 0)
        seen[base] = count + 1
        identifier = base if count == 0 else f"{base}-{count + 1}"
        return f'<h{match.group(1)} id="{identifier}">{match.group(2)}</h{match.group(1)}>'

    return pattern.sub(replace, markup)


def case_explorer_markup(cases: list[dict[str, Any]]) -> tuple[str, str]:
    case_json = json.dumps(cases, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    markup = """
<section class="case-explorer" id="case-explorer" aria-labelledby="case-explorer-title">
  <div class="explorer-header">
    <div>
      <h3 id="case-explorer-title">Live case review</h3>
      <p>Select a historical holdout case to inspect the prediction-time evidence, the selected threshold, and the later evaluation outcome.</p>
    </div>
    <div class="explorer-control">
      <label for="report-case-select">Select a case</label>
      <select id="report-case-select" aria-label="Select a historical token case"></select>
      <span id="report-case-count" aria-live="polite"></span>
    </div>
  </div>
  <div class="explorer-grid" aria-live="polite">
    <div class="explorer-main">
      <div class="case-heading">
        <div>
          <h4 id="report-case-title"></h4>
          <p id="report-case-copy"></p>
        </div>
        <span class="case-badge" id="report-case-badge"></span>
      </div>
      <div class="score-line"><span>Estimated low-volume-dead score</span><strong id="report-score-value"></strong></div>
      <div class="score-track" aria-hidden="true"><div class="score-fill" id="report-score-fill"></div><div class="score-threshold" id="report-score-threshold"></div></div>
      <p class="score-note" id="report-score-note"></p>
      <h5>Available at the seven-day cutoff</h5>
      <div class="context-grid" id="report-context-grid"></div>
    </div>
    <aside class="explorer-outcome">
      <span class="outcome-label">Observed later for evaluation</span>
      <h4 id="report-outcome-value"></h4>
      <p id="report-outcome-note"></p>
      <div class="boundary">
        <span class="outcome-label">Reading the case</span>
        <p>Transaction and graph context describe the evidence available for this token. Feature attribution requires a separate analysis.</p>
      </div>
    </aside>
  </div>
  <div class="explorer-footer">
    <p><strong>Prediction-time view.</strong> Early swaps, activity days, pools, protocols, and wallet-pool structure are the available evidence. No follow-up events or outcome fields enter this view.</p>
    <p id="report-review-action"></p>
  </div>
</section>
"""
    script = f"""
<script>
  const reportCases = {case_json};
  const reportSelect = document.getElementById("report-case-select");
  const reportTitle = document.getElementById("report-case-title");
  const reportCopy = document.getElementById("report-case-copy");
  const reportBadge = document.getElementById("report-case-badge");
  const reportScoreValue = document.getElementById("report-score-value");
  const reportScoreFill = document.getElementById("report-score-fill");
  const reportScoreThreshold = document.getElementById("report-score-threshold");
  const reportScoreNote = document.getElementById("report-score-note");
  const reportContextGrid = document.getElementById("report-context-grid");
  const reportOutcomeValue = document.getElementById("report-outcome-value");
  const reportOutcomeNote = document.getElementById("report-outcome-note");
  const reportReviewAction = document.getElementById("report-review-action");
  const reportCaseCount = document.getElementById("report-case-count");
  const reportNumber = new Intl.NumberFormat("en-US", {{ maximumFractionDigits: 2 }});
  const reportMoney = new Intl.NumberFormat("en-US", {{ style: "currency", currency: "USD", maximumFractionDigits: 2 }});

  function reportContextItem(label, value) {{
    const item = document.createElement("div");
    item.className = "context-item";
    const name = document.createElement("span");
    name.textContent = label;
    const content = document.createElement("strong");
    content.textContent = value;
    item.append(name, content);
    return item;
  }}

  function renderReportCase(index) {{
    const item = reportCases[index];
    const context = item.transaction_context;
    const graph = item.graph_context;
    const score = Number(item.score_low_volume_dead);
    const threshold = Number(item.decision_threshold_low_volume_dead);
    const flagged = item.model_decision === "flag_failure";
    reportSelect.value = String(index);
    reportTitle.textContent = `${{item.case_id}} / ${{item.token_symbol || item.token_fingerprint}}`;
    reportCopy.textContent = item.interpretation;
    reportBadge.textContent = `${{item.case_type}} / ${{flagged ? "flagged" : "not flagged"}}`;
    reportBadge.className = `case-badge ${{flagged ? "case-badge-alert" : "case-badge-quiet"}}`;
    reportScoreValue.textContent = score.toFixed(3);
    reportScoreFill.style.width = `${{Math.max(0, Math.min(100, score * 100))}}%`;
    reportScoreThreshold.style.left = `${{Math.max(0, Math.min(100, threshold * 100))}}%`;
    reportScoreNote.textContent = `Decision threshold ${{threshold.toFixed(3)}} / validation-selected 10% false-positive-rate budget`;
    reportContextGrid.replaceChildren(
      reportContextItem("Observation volume", reportMoney.format(context.pre_cutoff_volume_usd)),
      reportContextItem("Swaps", reportNumber.format(context.swap_count)),
      reportContextItem("Active days", reportNumber.format(context.active_day_count)),
      reportContextItem("Pools / protocols", `${{context.pool_count}} / ${{context.protocol_count}}`),
      reportContextItem("Graph nodes", reportNumber.format(graph.node_count)),
      reportContextItem("Wallet-pool edges", reportNumber.format(graph.wallet_pool_edge_count)),
    );
    const isDead = item.observed_label === "low_volume_dead";
    reportOutcomeValue.textContent = isDead ? "Low-volume dead" : "Continued activity";
    reportOutcomeNote.textContent = isDead
      ? "The later 90-day follow-up fell below the project's USD 1,000 swap-volume threshold."
      : "The later 90-day follow-up reached at least the project's USD 1,000 swap-volume threshold.";
    reportReviewAction.innerHTML = flagged
      ? "<strong>Review action.</strong> Open this token for analyst review, then inspect the transaction and graph context before recording a research decision."
      : "<strong>Review action.</strong> Keep this token lower in the review queue and compare its context with other low-scored cases.";
    reportCaseCount.textContent = `Case ${{Number(index) + 1}} of ${{reportCases.length}}`;
  }}

  reportCases.forEach((item, index) => {{
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${{item.case_id}} / ${{item.token_symbol || item.case_type}}`;
    reportSelect.appendChild(option);
  }});
  reportSelect.addEventListener("change", (event) => renderReportCase(Number(event.target.value)));
  renderReportCase(0);
</script>
"""
    return markup, script


def page_css() -> str:
    return """
  :root {
    color-scheme: light;
    --ink: #24323a;
    --muted: #66757c;
    --paper: #f7f5ef;
    --surface: #fffefa;
    --line: #d8dfdc;
    --teal: #287d8e;
    --coral: #d6614b;
    --gold: #d9a441;
    --green: #5d9a78;
    --purple: #8064a2;
    --max-page: 1320px;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: "Avenir Next", "Helvetica Neue", Arial, sans-serif;
    line-height: 1.55;
  }
  ::selection { background: rgba(40, 125, 142, .22); color: var(--ink); }
  a { color: var(--teal); text-underline-offset: 3px; }
  a:hover { color: #1b5b68; }
  :focus-visible { outline: 3px solid rgba(40, 125, 142, .35); outline-offset: 3px; }
  .skip-link { position: absolute; left: 16px; top: -48px; padding: 8px 12px; background: var(--ink); color: var(--surface); z-index: 10; }
  .skip-link:focus { top: 16px; }
  .site-header {
    max-width: var(--max-page);
    margin: 0 auto;
    padding: 22px 32px 18px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    border-bottom: 1px solid var(--line);
  }
  .brand { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .header-meta { color: var(--green); font-size: 12px; font-weight: 700; }
  .page-layout {
    max-width: var(--max-page);
    margin: 0 auto;
    padding: 42px 32px 80px;
    display: grid;
    grid-template-columns: 190px minmax(0, 820px);
    gap: 72px;
    align-items: start;
    min-width: 0;
  }
  .contents { position: sticky; top: 24px; align-self: start; min-width: 0; }
  .contents-title { margin: 0 0 14px; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .contents ol { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--line); }
  .contents li { border-bottom: 1px solid var(--line); }
  .contents a { display: block; padding: 9px 0; color: var(--muted); font-size: 13px; text-decoration: none; }
  .contents a:hover { color: var(--teal); }
  .report-meta { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-bottom: 32px; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
  .report-main, article { min-width: 0; }
  article h1 { max-width: 12ch; margin: 0 0 18px; font-size: 56px; line-height: 1.02; letter-spacing: -.035em; }
  article h1 + p { max-width: 70ch; margin-top: 0; color: var(--muted); font-size: 13px; }
  article h2 { margin: 68px 0 20px; padding-top: 24px; border-top: 1px solid var(--line); font-size: 30px; line-height: 1.12; letter-spacing: -.025em; }
  article h3 { margin: 42px 0 12px; font-size: 21px; line-height: 1.2; letter-spacing: -.015em; }
  article p, article li { max-width: 74ch; }
  article p { margin: 0 0 18px; }
  article ul, article ol { padding-left: 24px; margin: 0 0 22px; }
  article li { margin: 6px 0; }
  article code { padding: 2px 5px; background: rgba(40, 125, 142, .08); color: #1c5f6c; font-size: .91em; }
  article pre { max-width: 100%; overflow: auto; padding: 18px; background: #edf1ef; border: 1px solid var(--line); color: var(--ink); }
  article pre code { padding: 0; background: transparent; color: inherit; }
  article strong { font-weight: 700; }
  article table { width: 100%; margin: 26px 0 30px; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  article thead { border-top: 2px solid var(--ink); border-bottom: 1px solid var(--ink); }
  article th { padding: 10px 12px; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .04em; text-align: left; text-transform: uppercase; white-space: nowrap; }
  article td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
  article tbody tr:last-child td { border-bottom: 2px solid var(--ink); }
  article th:not(:first-child), article td:not(:first-child) { text-align: right; }
  .report-figure { margin: 34px 0 38px; padding: 16px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .report-figure img { display: block; width: 100%; height: auto; }
  .method-map { margin: 32px 0 40px; padding: 24px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .method-row { display: grid; grid-template-columns: minmax(0, 1fr) 34px minmax(0, 1fr) 34px minmax(0, 1fr); gap: 12px; align-items: stretch; margin: 0 0 18px; }
  .method-row:last-child { margin-bottom: 0; }
  .method-row-branches { grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0 0 18px; }
  .method-node { min-height: 100px; padding: 15px; background: var(--surface); border: 1px solid var(--line); }
  .method-node-muted { background: #eef2f0; }
  .method-node-accent { border-color: var(--teal); }
  .method-node-wide { min-height: 88px; }
  .method-kicker { display: block; margin-bottom: 6px; color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .method-node strong { display: block; font-size: 15px; line-height: 1.2; }
  .method-node > span:last-child { display: block; margin-top: 7px; color: var(--muted); font-size: 12px; line-height: 1.35; }
  .method-arrow { align-self: center; height: 1px; background: var(--teal); position: relative; }
  .method-arrow::after { content: ""; position: absolute; right: 0; top: -4px; width: 7px; height: 7px; border-top: 1px solid var(--teal); border-right: 1px solid var(--teal); transform: rotate(45deg); }
  .case-explorer { margin: 42px 0 52px; padding: 28px; background: #eef2f0; border: 1px solid var(--line); border-radius: 8px; }
  .explorer-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
  .explorer-header h3 { margin: 0 0 8px; font-size: 23px; }
  .explorer-header p { margin: 0; color: var(--muted); font-size: 14px; }
  .explorer-control { display: grid; gap: 6px; min-width: 190px; }
  .explorer-control label { color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
  .explorer-control select { min-height: 40px; padding: 0 34px 0 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--ink); font: inherit; }
  #report-case-count { color: var(--muted); font-size: 12px; }
  .explorer-grid { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(240px, .7fr); gap: 28px; padding: 28px 0 8px; }
  .explorer-main { min-width: 0; }
  .explorer-outcome { padding-left: 28px; border-left: 1px solid var(--line); }
  .case-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
  .case-heading h4 { margin: 0; font-size: 23px; line-height: 1.15; overflow-wrap: anywhere; }
  .case-heading p { margin: 8px 0 24px; color: var(--muted); font-size: 14px; }
  .case-badge { flex: 0 0 auto; padding: 5px 9px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
  .case-badge-alert { background: rgba(214, 97, 75, .14); color: #99402f; }
  .case-badge-quiet { background: rgba(40, 125, 142, .12); color: #1c6472; }
  .score-line { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; color: var(--muted); font-size: 12px; }
  .score-line strong { color: var(--ink); font-size: 35px; line-height: 1; font-variant-numeric: tabular-nums; }
  .score-track { position: relative; height: 10px; margin-top: 10px; background: #dfe7e3; border-radius: 999px; }
  .score-fill { position: absolute; inset: 0 auto 0 0; width: 0; background: var(--coral); border-radius: inherit; transition: width 220ms ease-out; }
  .score-threshold { position: absolute; top: -7px; bottom: -7px; left: 0; width: 2px; background: var(--gold); transition: left 220ms ease-out; }
  .score-note { margin: 8px 0 24px; color: var(--muted); font-size: 11px; }
  .explorer-main h5 { margin: 0 0 10px; color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
  .context-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--line); border-left: 1px solid var(--line); }
  .context-item { min-width: 0; padding: 12px; background: var(--surface); border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
  .context-item span { display: block; color: var(--muted); font-size: 11px; }
  .context-item strong { display: block; margin-top: 4px; font-size: 15px; overflow-wrap: anywhere; }
  .outcome-label { display: block; color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .explorer-outcome h4 { margin: 10px 0; font-size: 23px; line-height: 1.15; }
  .explorer-outcome p { color: var(--muted); font-size: 14px; }
  .boundary { margin-top: 54px; padding-top: 16px; border-top: 1px solid var(--line); }
  .boundary p { margin-bottom: 0; font-size: 13px; }
  .explorer-footer { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; padding-top: 20px; border-top: 1px solid var(--line); }
  .explorer-footer p { margin: 0; color: var(--muted); font-size: 13px; }
  .site-footer { max-width: var(--max-page); margin: 0 auto; padding: 22px 32px 38px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); }
  @media (max-width: 1040px) {
    .page-layout { grid-template-columns: 1fr; gap: 18px; padding-top: 28px; }
    .contents { position: static; display: flex; align-items: center; gap: 18px; overflow-x: auto; white-space: nowrap; border-bottom: 1px solid var(--line); }
    .contents-title { margin: 0; }
    .contents ol { display: flex; gap: 18px; border: 0; }
    .contents li { border: 0; }
    .contents a { padding: 6px 0 14px; }
  }
  @media (max-width: 720px) {
    .site-header { align-items: flex-start; flex-direction: column; padding: 18px 16px 14px; gap: 6px; }
    .page-layout { padding: 24px 16px 54px; }
    article h1 { font-size: 38px; }
    article h2 { margin-top: 50px; font-size: 26px; }
    article h3 { font-size: 20px; }
    article table { display: block; overflow-x: auto; white-space: nowrap; }
    .method-row, .method-row-branches { grid-template-columns: 1fr; gap: 8px; }
    .method-arrow { width: 1px; height: 18px; margin-left: 18px; }
    .method-arrow::after { top: auto; bottom: 0; right: -3px; transform: rotate(135deg); }
    .case-explorer { padding: 18px; }
    .explorer-header, .explorer-grid, .explorer-footer { grid-template-columns: 1fr; display: grid; gap: 18px; }
    .explorer-control { min-width: 0; }
    .explorer-outcome { padding: 20px 0 0; border-top: 1px solid var(--line); border-left: 0; }
    .boundary { margin-top: 28px; }
    .context-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .site-footer { padding: 18px 16px 30px; }
  }
  @media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    *, *::before, *::after { transition-duration: .01ms !important; }
  }
  @media print {
    body { background: #fff; }
    .site-header, .contents, .explorer-control, .site-footer { display: none; }
    .page-layout { display: block; max-width: none; padding: 0; }
    article h2 { break-before: page; }
    .case-explorer { break-inside: avoid; }
  }
"""


def build_page(report_path: Path, output_path: Path, cases: list[dict[str, Any]], git_head: str | None) -> str:
    markdown = report_path.read_text(encoding="utf-8")
    markdown_renderer = mistune.create_markdown(escape=False, plugins=["table", "strikethrough"])
    body = markdown_renderer(markdown)
    body = replace_mermaid(body)
    body = inline_report_images(body, report_path)
    body = add_heading_ids(body)
    case_markup, case_script = case_explorer_markup(cases)
    marker = '<h2 id="reproducibility">'
    if marker in body:
        body = body.replace(marker, case_markup + marker, 1)
    else:
        body += case_markup
    revision = html_mod.escape(git_head or "working tree")
    output_label = html_mod.escape(output_path.name)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Evidence-led result analysis for the Ethereum token wallet-graph failure-screening project.">
  <title>Ethereum token project result analysis</title>
  <style>{page_css()}</style>
</head>
<body id="top">
  <a class="skip-link" href="#report-content">Skip to report</a>
  <header class="site-header">
    <div class="brand">Ethereum token result analysis</div>
      <div class="header-meta">Historical holdout / token symbols retained</div>
  </header>
  <div class="page-layout">
    <nav class="contents" aria-label="Report contents">
      <p class="contents-title">Contents</p>
      <ol>
        <li><a href="#abstract">Abstract</a></li>
        <li><a href="#study-question-and-use-case">Study question</a></li>
        <li><a href="#data-and-method">Method</a></li>
        <li><a href="#cohort-and-exploratory-analysis">Cohort and EDA</a></li>
        <li><a href="#model-results">Model results</a></li>
        <li><a href="#model-interpretation">Interpretation</a></li>
        <li><a href="#case-review">Cases</a></li>
        <li><a href="#reproducibility">Reproducibility</a></li>
      </ol>
    </nav>
    <main class="report-main" id="report-content">
      <div class="report-meta"><span>Version: wallet_graph_project_result_analysis_20261005_v1</span><span>Revision: {revision}</span><span>HTML edition: {output_label}</span></div>
      <article>{body}</article>
    </main>
  </div>
  <footer class="site-footer">This HTML edition preserves the Markdown report's measured claims and embeds its figure bundle. The interactive case review is retrospective; token symbols are retained while full contract addresses remain omitted.</footer>
  {case_script}
</body>
</html>
'''


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    report_path = (args.report or (project_root / "reports" / REPORT_NAME)).resolve()
    input_path = args.input.resolve()
    output_path = (args.output if args.output.is_absolute() else project_root / args.output).resolve()
    data = read_json(input_path)
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("analysis input does not contain a cases list")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_page(report_path, output_path, cases, data.get("git_head")), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "embedded_figures": 8, "cases": len(cases)}, indent=2))


if __name__ == "__main__":
    main()
