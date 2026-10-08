# Temporal wallet-graph comparison

Status: completed temporal validation on the frozen 2,000-token matched cohort.

This report is a separate temporal holdout from the general stratified comparison. The model-selection contract remains validation-only threshold selection, with `low_volume_dead` treated as the failure-positive class.

## Scope and split

- Temporal split: [`wallet_graph_temporal_20261005_v1`](../data/model_split_temporal_wallet_graph_20261005_v1/split_manifest.json)
- Input rows: 2000; eligible rows: 2000; discarded rows: 0.
- Cutoffs: train before `2024-01-01T00:00:00Z`, validation before `2025-01-01T00:00:00Z`, test before `2026-06-24T00:00:00Z`.
- Partition counts: train 1,338, validation 477, test 185.
- Test labels: `{'continued_activity': 40, 'low_volume_dead': 145}`. The calendar test set is imbalanced: 185 rows, with 145 failures and 40 continued tokens.

The split is assigned from `t0` before labels are used. No rows were censored or discarded in this run, and the graph and tabular prediction keys were required to match the temporal sidecar.

### Active/inactive composition

Active means `continued_activity`; inactive means `low_volume_dead`.

| Split | Active | Inactive | Total |
| --- | ---: | ---: | ---: |
| Train | 720 | 618 | 1,338 |
| Validation | 240 | 237 | 477 |
| Test | 40 | 145 | 185 |

The newest test period is failure-heavy rather than balanced: 145 inactive tokens and 40 active tokens.

## Main result

The three-seed `Edge GCN` ensemble reaches temporal test ROC-AUC 0.933 and average precision 0.980 for `low_volume_dead`. At the 0.10 validation false-positive-rate budget, it reaches failure recall 0.848, failure precision 0.939, F1 0.891, and flags 131 of 185 test tokens.

The topology-only GraphSAGE control is a useful guard against over-crediting edge features. It ranks the temporal test set slightly better than the edge-aware model, so this run supports graph structure but does not establish a benefit from edge features specifically.

### How to read the operating point

At the 0.10 validation target, the Edge GCN family mean correctly flags 123 inactive tokens, misses 22, raises 8 false alerts, and correctly leaves 32 active tokens unflagged.
The realized test false-positive rate is 0.200, rather than the validation target of 0.100. That gap is evidence of temporal shift and is why the threshold should be treated as a review operating point, not a guarantee.

## Test metrics by threshold budget

Thresholds are selected separately on validation data for each family and target budget. Test columns are evaluated once the threshold is frozen.

| Model | Target FPR | Test FPR | Failure recall | Failure precision | Failure F1 | Alerts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Edge GCN | 0.050 | 0.025 | 0.669 | 0.990 | 0.798 | 98 |
| Edge GCN | 0.100 | 0.200 | 0.848 | 0.939 | 0.891 | 131 |
| Edge GCN | 0.150 | 0.250 | 0.883 | 0.928 | 0.905 | 138 |
| Topology GraphSAGE | 0.050 | 0.075 | 0.690 | 0.971 | 0.806 | 103 |
| Topology GraphSAGE | 0.100 | 0.100 | 0.717 | 0.963 | 0.822 | 108 |
| Topology GraphSAGE | 0.150 | 0.100 | 0.759 | 0.965 | 0.849 | 114 |
| Tabular logistic | 0.050 | 0.150 | 0.759 | 0.948 | 0.843 | 116 |
| Tabular logistic | 0.100 | 0.200 | 0.821 | 0.937 | 0.875 | 127 |
| Tabular logistic | 0.150 | 0.200 | 0.821 | 0.937 | 0.875 | 127 |

## Seed stability

The following values are mean +/- population standard deviation across the saved seeds. The aggregate rows above average scores before threshold selection and are the primary family-level analysis.

| Model | ROC-AUC (dead) | AP (dead) | Failure F1 at 0.10 |
| --- | ---: | ---: | ---: |
| Edge GCN | 0.932 +/- 0.006 | 0.980 +/- 0.002 | 0.878 +/- 0.010 |
| Topology GraphSAGE | 0.948 +/- 0.000 | 0.984 +/- 0.000 | 0.823 +/- 0.003 |
| Tabular logistic | 0.887 +/- 0.000 | 0.924 +/- 0.000 | 0.875 +/- 0.000 |

## Result illustration

- [What the temporal result means](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/figures/result_story.png)
- [Chronological cohort and class composition](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/figures/cohort_timeline.png)

These two views are the short presentation path: first establish the time ordering and class mix, then connect ranking quality to the chosen review operating point.

## Score distributions and tradeoffs

- [Score distributions](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/figures/score_distributions.png)
- [Threshold tradeoffs](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/figures/threshold_tradeoffs.png)
- [Model summary](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/figures/model_summary.png)
- [Selected case scores](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/figures/case_scores.png)

The score plots show the family-level mean failure score and the frozen validation-derived thresholds. They are descriptive diagnostics, not calibration claims.

## Anonymized cases

Cases use the `Edge GCN` family mean at the 0.10 validation FPR budget. The displayed fingerprint is a truncated SHA-256 of the token address; the address itself is intentionally omitted.

| Case | Fingerprint | Observed outcome | Failure score | Threshold | t0 | Swaps | Volume USD | Active days | Nodes | Wallet-pool edges |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| TP-1 | `d0fce8d550dfb4ef` | `low_volume_dead` (flag_failure) | 0.981 | 0.563 | 2025-03-09T01:58:11Z | 149 | 7690.89 | 1 | 5 | 3 |
| FP-1 | `7f37b21a826e7fde` | `continued_activity` (flag_failure) | 0.862 | 0.563 | 2025-03-10T20:12:59Z | 38 | 4062.94 | 1 | 5 | 3 |
| FN-1 | `0d76eac9d638a22f` | `low_volume_dead` (do_not_flag_failure) | 0.001 | 0.563 | 2026-02-16T20:19:23Z | 36 | 14.29 | 6 | 10 | 9 |
| TN-1 | `7faaad4e55fb0584` | `continued_activity` (do_not_flag_failure) | 0.001 | 0.563 | 2025-03-10T15:04:11Z | 1,978 | 289424.77 | 8 | 72 | 89 |

Transaction and graph context are measured descriptors attached to each case. They are not feature-attribution results. In particular, the case table cannot establish that connectivity, volume, or activity caused a prediction.

## Measured findings and hypotheses

Measured in this run:

- Temporal test ranking quality is high for all three graph seeds, but the calendar test prevalence is strongly failure-heavy.
- The topology-only control is at least as strong as the edge-aware family on the reported temporal metrics, so edge-aware message passing should not be presented as a demonstrated improvement.
- The tabular baseline provides a lower-complexity reference and remains materially below the graph families on temporal ROC-AUC and AP.

Still hypotheses:

- Graph connectivity may capture useful structure beyond the nine tabular features; this needs a matched ablation or attribution analysis under the same temporal split.
- The false positives and false negatives may represent distinct launch or liquidity regimes; the four cases are examples for inspection, not evidence of a subgroup mechanism.

## Limits and next use

- This is one frozen temporal cohort with 185 test rows, including only 40 continued-activity positives for the continued class.
- The labels are the project proxy defined in `CONTRACT.md`; they are not a production failure oracle, and no uncensored external future outcome was added here.
- Thresholds and the review budget were not tuned on test rows. The displayed alert counts are operating points, not deployment recommendations.
- The artifact is suitable for the analysis/demo walkthrough. Any deployment claim would require prospective evaluation, monitoring, and an operational decision policy.

## Reproducibility artifacts

- [Temporal split manifest](../data/model_split_temporal_wallet_graph_20261005_v1/split_manifest.json)
- [Failure-positive evaluator output](../data/failure_positive_evaluation_wallet_graph_temporal_20261005_v1.json)
- [Analysis JSON](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/analysis.json)
- [Anonymized cases JSONL](../data/temporal_analysis_wallet_graph_temporal_20261005_v1/cases.jsonl)
