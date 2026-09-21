# Goal: Real-data cryptocurrency scam detection with graph neural networks

Status: Initial proposal based on project discussions; data access and final experiment scope remain to be verified.

## Purpose

Build and evaluate a GNN-based cryptocurrency scam detector using real blockchain activity. Produce multiple informative diagrams that explain the data, scam behavior, model performance and failure cases. The intended users are blockchain security analysts who need to prioritize suspicious activity for investigation.

The project should go beyond reproducing a standard classification benchmark. Public datasets contain real data and may supply labels or transaction records, but downloading a prepared benchmark and repeating its existing task is not the intended contribution. We will construct a documented study cohort from real transactions and independently sourced scam evidence where feasible, then evaluate a concrete operational question.

## Main research question

How does a fine-tuned GNN perform when transaction history is limited and evaluation involves later, previously unseen scam campaigns, and does graph information improve detection over account-level or contract-level features?

Supporting questions:

- Does self-supervised pretraining help compared with the same GNN trained from scratch, particularly with fewer training labels?
- Which supported scam types are detected reliably, and which produce false negatives or false positives?
- How much history is necessary to produce useful alerts at a controlled false-positive rate or analyst review budget?

These questions are research directions, not claims of novelty already established by a literature review.

## Scope

Start with Ethereum so transactions can be aligned within one chain. Aim to investigate phishing, Ponzi schemes, rug pulls and honeypots. Quantitative coverage depends on label quality, compatible prediction units and available timestamps; do not promise a four-class classifier before the data audit.

Phishing labels may describe addresses, Ponzi labels contracts, and rug-pull or honeypot labels tokens or pools. Define each target explicitly. Use separate tasks or a justified heterogeneous representation when the units differ. Do not merge these labels into interchangeable classes.

Use historical real transactions, contract metadata and, where available, liquidity events. Public datasets are candidate inputs, not the sole definition of the project. Additional collection through blockchain RPC or explorer APIs is an option subject to access, cost and coverage. New collection and public-data reuse are both acceptable; neither alone establishes originality.

## Claims we can support

The default objective is scam detection with limited observed history. A claim of warning before a scam occurs requires verified event timestamps and features restricted to information available before that event. A report timestamp is not necessarily the scam onset time. If these timestamps are unavailable, label the experiment as limited-history or retrospective detection.

A successful project need not beat every baseline. It must produce a reproducible comparison and explain when graph learning or pretraining helps, fails or adds unnecessary complexity.

## Deliverables and acceptance criteria

1. A source and label audit with provenance, licenses, access constraints, entity definitions, time coverage and unknowns.
2. A documented study cohort and reproducible graph construction from real transactions, with versioned data manifests and split definitions.
3. Feature-only baselines, a GNN trained from scratch, and a pretrained GNN fine-tuned on scam labels, evaluated under the same protocol.
4. Held-out results with class support, per-type metrics where valid, three random seeds when feasible, error analysis and explicit leakage checks.
5. At least six useful figures, including transaction neighborhoods, limited-history performance and baseline comparisons. All empirical plots must come from actual data or measured results.
6. A short report and presentation explaining motivation, methods, evidence, limitations and privacy considerations; runnable scripts or notebooks with environment instructions.

## Boundaries

No live trading, investment recommendations, automatic blocking, public accusations or promised detection accuracy. Unknown accounts are not confirmed benign. Model scores are investigative evidence, not proof of fraud. Synthetic examples may illustrate mechanisms but cannot substitute for real evaluation data.

## Decisions still open

- Exact core dataset/cohort, date range and accessible transaction source.
- Which scam types have enough independent evidence and compatible data for evaluation.
- Final prediction unit, history windows, split dates, label budget and graph size.
- Whether independent historical contract/liquidity features are available for a combined model.
- Whether the course requires original data collection in addition to a new analysis; verify before freezing scope.
