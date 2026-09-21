# Plan: Cryptocurrency scam detection mini-project

This plan implements [GOAL.md](GOAL.md). It is a five-week sequence of milestones, not a claim that collection or experiments have already been completed. Shift the schedule to the actual course deadlines.

## 1. Establish feasibility and contribution — slice 1

### Review the closest prior work

Compare existing work on temporal scam detection, limited-history prediction, unseen campaigns, GNN pretraining and multiple scam categories. Record each paper's prediction unit, sources, split protocol, historical feature availability, baselines and limitations. State precisely how our experiment differs; do not claim that early detection itself is new.

Candidate sources previously discussed (discovery pointers, not verified downloads):

- XBlock: https://www.xblock.pro/ — phishing transaction networks and Ponzi label resources.
- Ethereum Ponzi repository: https://github.com/blockchain-unica/ethereum-ponzi — supplementary contract labels and research material.
- TokenScout paper: https://cactilab.github.io/assets/pdf/3658644.3690234.pdf — token-level rug-pull, honeypot and Ponzi research; usable dataset access is unconfirmed.
- TMRugPull: https://arxiv.org/abs/2602.21529 — investigate temporally constrained project-level data; graph suitability and access need checking.
- Token Sniffer documentation: https://tokensniffer.readme.io/reference/response — candidate contract and liquidity signals; historical availability, API terms and costs must be checked. Current scores cannot stand in for historical observations.

### Audit real data and label evidence

For each source, record access method, license, retrieval date, chain, entity type, raw fields, time range, label meaning, class counts, missing timestamps and estimated collection/storage costs. Retain the original category and evidence rather than silently normalizing away disagreement.

Create separate tables for:

- Entities: chain, address, entity type, deployment/first-seen time, source.
- Events: transaction hash, block/time, sender, receiver, asset contract, raw amount, decimals and event/log index; trace identifier where relevant.
- Labels: target entity, scam type, evidence source, event time, report time, label availability time, confidence and disagreement status. Keep unavailable times explicitly missing.
- Cohorts/splits: target, observation cutoff, campaign identifier where supported, partition and exclusion reason.

Do not equate one address with one person. Deduplicate reports of the same incident. Keep automated/heuristic labels distinct from independently corroborated outcomes. A liquidity withdrawal alone is not sufficient proof of a rug pull.

### Build a pilot cohort

Aim for roughly 100 manually inspected target entities across supported scam and comparator groups, with bounded transaction neighborhoods. This pilot tests feasibility; it is not the final training sample or a prevalence estimate. Include source-labeled non-scam examples with comparable time, activity and entity type, and audit their evidence. Leave unresolved cases unknown.

Collect or reconstruct their histories, trace several examples back to the original evidence, and draw small labeled neighborhoods. Check whether the intended history windows and future/campaign evaluation can actually be implemented.

**Gate:** freeze the core task only after documenting available data and the proposed contribution. If only one category is feasible, report measured coverage for that category and retain other categories as case studies. If only a packaged benchmark is usable, explicitly acknowledge the reduced scope rather than quietly presenting it as original collection.

## 2. Construct the cohort, graph and EDA — slice 2

- Preserve immutable raw snapshots; write processed tables separately, preferably Parquet. Record download/query parameters, hashes, date ranges, versions and label provenance. Keep secrets out of source control.
- Normalize addresses while preserving chain identity; validate timestamps and token decimals. Deduplicate using transaction/event identifiers, not merely sender and receiver.
- Separate native transfers, token transfers, approvals, swaps and liquidity events. A transaction may create multiple transfers; approvals are permissions, not asset transfers.
- Keep assets distinct. Use raw integers and decimals; only calculate fiat-valued features if a suitable historical price source is available.
- Define directed address/contract graphs for address tasks. Token or pool tasks require explicit graph-level targets or a documented heterogeneous graph.
- Engineer historical in/out counts, degree, counterparties, value summaries, account age and activity timing. Add contract or liquidity features only when their value at the prediction cutoff can be established.
- Use bounded neighborhoods and document sampling. Exclude IDs, scam tags, report-derived flags and post-cutoff graph edges from predictive features.
- Fit transformations on training data only. Unknown nodes may provide context but do not become benign labels.

Deliver EDA covering class/source counts, missingness, time coverage, degree/value distributions and representative transaction neighborhoods. Audit whether collection source, entity type or observation duration trivially identifies the class.

## 3. Freeze the evaluation protocol before modeling — slice 3

### Prediction snapshots

Compare first 5, 10, 25 and 50 target transactions if supported; distinguish transactions from token-transfer events. Apply the target cutoff to all neighborhood edges and features. Keep cohorts comparable across windows, report eligibility/attrition, and avoid interpreting survival to 50 transactions as representative of all targets. Consider fixed elapsed-time windows if transaction counts create severe selection bias.

Use the same available snapshot information for every model. If pre-event detection is feasible, additionally evaluate lead time against independently established incident times. Otherwise explicitly limit claims to early observed history.

### Partitions and leakage

Prefer chronological partitions with campaign-disjoint targets where campaign evidence exists. Choose dates from observed coverage and class support; approximately 70/15/15 is only an initial size guide. Keep repeated snapshots of a target in one partition. Do not invent campaign identities where none exist; state the resulting generalization limitation.

Ensure training labels were available by the training cutoff for a deployment-style experiment. Otherwise describe the evaluation as retrospective. Exclude held-out targets and their incident edges from inductive pretraining/training. At test time, use only permitted historical context; shared historical counterparties can remain if documented. Audit duplicate and near-duplicate target neighborhoods across partitions.

Tune hyperparameters and alert thresholds on validation data only. Evaluate a locked test set once after model selection. Any separate random-split comparison is diagnostic, not the headline deployment estimate.

### Metrics

Report average precision (explicitly identify this PR-summary convention), macro-F1, per-type precision/recall, false-positive rate, confusion matrices and support counts. Include recall at a validation-selected false-positive-rate target or precision/recall at a fixed review budget; report the achieved test false-positive rate rather than guaranteeing it.

Preserve and disclose test prevalence. A balanced pilot cannot establish real-world alert precision. Summarize repeated seeds with mean and standard deviation; these are not population confidence intervals. If using bootstrap uncertainty, resample independent targets or campaigns rather than overlapping edges.

## 4. Train, pretrain and fine-tune — slice 4

1. Train logistic regression and gradient boosting on the same historical target-level features.
2. Train a small GraphSAGE model from scratch, using neighbor sampling and early stopping. Document how directed transfers and amounts enter the model: plain GraphSAGE does not automatically use edge attributes. Incoming/outgoing aggregates provide an initial baseline; explicitly document any symmetrization.
3. Pretrain the same encoder using self-supervised link prediction or graph contrastive learning on training-only history, then fine-tune it and its classifier using training scam labels. Link-prediction nonedges are reconstruction negatives, not non-scam labels.
4. Compare pretrained and scratch models under equal supervised data and a disclosed tuning/compute budget. Add a small training-label-budget ablation if feasible. No compatible public pretrained checkpoint is assumed.
5. Use class-weighted loss, a small validation search and three seeds when feasible. Prioritize sound splits over adding architectures.
6. If compatible historical code/liquidity features exist, compare feature-only, graph-only and combined models with identical targets and independent outcomes. Do not train on Token Sniffer flags and claim independent validation by testing against the same flags.

Save configurations, split manifests, checkpoints, metrics, seeds, software versions, runtime and memory usage. Record negative results and false alarms, including exchange-like activity that resembles scams.

## 5. Figures, interpretation and delivery — slice 5

Planned figures:

1. Data-source and modeling pipeline diagram.
2. Scam category, label source and unknown-label counts.
3. Temporal coverage and chronological split diagram.
4. Degree, value and activity distributions by supported class.
5. Small transaction neighborhoods for scams, comparators and errors.
6. Detection performance versus available history, with eligible sample counts.
7. Per-type precision-recall curves and confusion matrices where applicable.
8. Baseline, scratch-GNN and fine-tuned-GNN comparisons.

Optional: performance across time periods and training-label budgets, plus an interactive viewer filtering by time, score and category. Clearly distinguish known labels from predictions. Explanations or highlighted neighbors are not causal proof.

Deliver the report, slides, reproducibility instructions and data/model documentation. Mask addresses in public examples where identification is unnecessary, avoid victim narratives, honor source licenses and review university data-handling guidance. Discuss source bias, uncertain negatives, class imbalance and harms from false accusations.

## Immediate next milestone

Produce a source-feasibility matrix and the audited pilot cohort with several real transaction graphs. Only then freeze the category coverage, target definition and historical evaluation protocol. Model implementation follows this decision.
