# Token failure model comparison

Generated 2026-10-01 from the current remote checkout at `90cf9290af506aabff7a9908437ae5777cb9e1d8`.

## Scope

The primary comparison uses the same frozen general stratified split for both
models:

- 10,449 complete supervised token labels; 820 censored rows were excluded.
- Train: 8,359; validation: 1,048; test: 1,042.
- No overlap group crosses a partition.
- The test set is used once after validation checkpoint and threshold selection.
- The tabular model uses nine pre-cutoff scalar features. Its
  `StandardScaler` and class weighting are fit on training rows only.
- GraphSAGE uses the static pre-cutoff graph artifact, train-only positive class
  weighting, and batch size 512 on the NVIDIA GH200.

Source artifacts: [split manifest](../data/model_split_general_stratified_20261001_v1/split_manifest.json), [tabular metrics](../data/tabular_baseline_general_stratified_20261001_v1/metrics.json), and [GraphSAGE metrics](../data/graphsage_general_stratified_20261001_v1/metrics.json).

## Primary test results

Scores are for `continued_activity` as the positive class. Precision, recall,
and F1 are evaluated at the threshold selected on validation data.

| Model | ROC-AUC | Average precision | Balanced accuracy | Continued precision | Continued recall | Continued F1 | Dead recall | Macro F1 | False-positive rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GraphSAGE | 0.938987 | 0.750759 | 0.859052 | 0.377193 | 0.868687 | 0.525994 | 0.849417 | 0.718888 | 0.150583 |
| Tabular logistic | 0.941044 | 0.781657 | 0.860894 | 0.397196 | 0.858586 | 0.543131 | 0.863203 | 0.731193 | 0.136797 |

The tabular model's selected threshold was `0.417619`; GraphSAGE's was
`0.467930`. Their primary-test confusion matrices are, respectively,
GraphSAGE `TN=801, FP=142, FN=13, TP=86` and tabular `TN=814, FP=129,
FN=14, TP=85`.

## Interpretation

On this held-out split, the nine aggregate pre-cutoff features slightly
outperform the graph model on ranking metrics and macro-F1. The tabular model
has 0.030898 higher average precision, 0.017137 higher continued-activity F1,
and a 0.013786 lower false-positive rate. GraphSAGE has 0.010101 higher
continued-activity recall, at the cost of more false positives.

This is not evidence that graph features are harmful in general. It is evidence
that this GraphSAGE configuration does not add measurable value over the
current aggregate features on this split. The comparison uses one seed and no
confidence intervals, so small differences should not be treated as
statistically established.

## Chronological stress test

As a secondary check, the same tabular implementation was retrained with the
historical chronological partitions from the recovered v4 split manifest:
6,469 train, 2,670 validation, and 1,310 test rows. The chronological test
set has 40 continued-activity tokens versus 99 in the primary test set, so
average precision is not directly comparable without accounting for class
prevalence.

| Split | ROC-AUC | Average precision | Balanced accuracy | Continued precision | Continued recall | Continued F1 | Dead recall | Macro F1 | False-positive rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Historical chronological test | 0.936909 | 0.471146 | 0.857874 | 0.230216 | 0.800000 | 0.357542 | 0.915748 | 0.655215 | 0.084252 |

The chronological result keeps strong ranking and dead-token recall, but the
rarer positive class and temporal shift materially reduce average precision
and continued-activity precision. This is a stress test for the tabular model,
not a matched chronological GraphSAGE-vs-tabular comparison; GraphSAGE was not
rerun on this alternate partition in this step.

Source artifact: [chronological tabular metrics](../data/tabular_baseline_chronological_20261001_v1/metrics.json).

## Next decision

Use the tabular logistic model as the current reference model. Before spending
more GPU time on graph architecture changes, run repeated-seed evaluation and
feature ablations to establish whether graph structure contributes beyond the
nine scalar aggregates. Keep the chronological split as a secondary robustness
check, not as a replacement for the frozen primary split.
