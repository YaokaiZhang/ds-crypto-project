# Token failure model comparison

Generated 2026-10-01 from the current remote checkout.

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

## Graph structure audit

The graphs are not isolated: all 10,449 target graphs contain at least one
pool and one counterparty. However, they are structurally very sparse:

- 10,283 graphs (98.4%) contain exactly one pool, one counterparty, three
  nodes, and four edges.
- Only 166 graphs have at least two pools, and only 88 have at least two
  counterparties.
- Across all graphs there are 87 unique counterparty addresses. WETH appears
  in 10,151 of the 10,560 counterparty incidences, so most graph relationships
  point to the same common asset.
- Continued-activity tokens are somewhat more likely to have multiple pools
  than low-volume/dead tokens (7.7% versus 0.9%), but the richer cases are rare.

Therefore the graph representation contains valid pool relationships, but its
topology has very little variation. GraphSAGE is mostly seeing a center token
plus one pool and one counterparty, with the informative differences coming
from the node activity features rather than from complex connectivity. This
helps explain why it does not beat the tabular model in practical screening.
The general and chronological graph artifacts have the same structure because
they use the same tokens and cutoff-bounded data; only the partition assignment
differs.

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

As a secondary check, both models were retrained with the historical
chronological partitions from the recovered v4 split manifest: 6,469 train,
2,670 validation, and 1,310 test rows. Training tokens run from 2020-05 through
2023-12, validation tokens from 2024-01 through 2024-09, and test tokens from
2025-01 through 2026-02. The chronological test set contains 40
continued-activity tokens and 1,270 low-volume/dead tokens. This is the class
mix in the collected test sample, not a claim about all Ethereum tokens.

| Model | ROC-AUC | Average precision | Balanced accuracy | Continued precision | Continued recall | Continued F1 | Dead recall | Macro F1 | False-positive rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Tabular logistic | 0.936909 | 0.471146 | 0.857874 | 0.230216 | 0.800000 | 0.357542 | 0.915748 | 0.655215 | 0.084252 |
| GraphSAGE | 0.950374 | 0.539910 | 0.826280 | 0.096606 | 0.925000 | 0.174941 | 0.727559 | 0.508044 | 0.272441 |

The chronological comparison gives a mixed result. GraphSAGE ranks the future
tokens better (ROC-AUC 0.950 versus 0.937; average precision 0.540 versus
0.471), which suggests that graph structure may contain useful ranking signal
under time shift. However, its validation-selected threshold transfers poorly:
it flags 346 dead tokens as continued, compared with 107 for the tabular model.
The tabular model therefore has much better precision, dead-token recall,
macro-F1, and false-positive rate at the operating thresholds selected without
test labels. GraphSAGE found 37 of 40 continuing tokens; the tabular model found
32 of 40.

This is not evidence that GraphSAGE is useless, and it is not evidence that it
is ready for deployment. It separates ranking quality from decision-threshold
quality: GraphSAGE may order candidates well but needs calibration or a more
conservative operating threshold for a rare-positive future population.

## Repeated seeds

GraphSAGE was retrained with seeds `20261001`, `20261002`, and `20261003` in
parallel inside one Slurm allocation with one shared GH200. The three processes
produced 10,449 predictions each on the same chronological split.

| Test metric | Mean | Standard deviation | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: |
| ROC-AUC | 0.948694 | 0.001899 | 0.946634 | 0.950374 |
| Average precision | 0.500174 | 0.049402 | 0.444860 | 0.539910 |
| Balanced accuracy | 0.824180 | 0.001818 | 0.823130 | 0.826280 |
| Continued recall | 0.925000 | 0.000000 | 0.925000 | 0.925000 |
| Macro F1 | 0.505550 | 0.002160 | 0.504303 | 0.508044 |
| False-positive rate | 0.276640 | 0.003637 | 0.272441 | 0.278740 |

The ranking result is stable across seeds. The average-precision variation is
larger because there are only 40 continued-activity tokens in this test sample.
The main operational conclusion is stable too: GraphSAGE finds most continuing
tokens, but its default validation-selected threshold labels roughly 28% of
dead tokens as continuing.

## Threshold calibration

We then calibrated GraphSAGE using validation predictions only. For each seed,
we selected the threshold that maximized continued-activity recall while keeping
the validation false-positive rate below a chosen budget. We applied that fixed
threshold once to the chronological test predictions.

| Validation FPR budget | Model | Test FPR | Continued precision | Continued recall | Macro F1 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 5% | GraphSAGE, mean across 3 seeds | 4.6% | 34.2% | 75.0% | 0.721 |
| 5% | Tabular logistic | 2.1% | 52.6% | 75.0% | 0.802 |
| 10% | GraphSAGE, mean across 3 seeds | 17.0% | 15.0% | 85.8% | 0.578 |
| 10% | Tabular logistic | 7.2% | 25.4% | 77.5% | 0.671 |
| 15% | GraphSAGE, mean across 3 seeds | 26.9% | 9.7% | 91.7% | 0.509 |
| 15% | Tabular logistic | 8.7% | 22.4% | 80.0% | 0.650 |

This answers the calibration question: a stricter GraphSAGE threshold does reduce
false alarms, but the tabular model remains better at the same intended operating
budget. At the 5% target, both models retain 75% continued-token recall, while
the tabular model has higher precision and macro-F1. The chronological test has
only 40 continued tokens, so these threshold estimates are still noisy.

Source artifacts: [chronological split manifest](../data/model_split_chronological_20261001_v1/split_manifest.json), [chronological tabular metrics](../data/tabular_baseline_chronological_20261001_v1/metrics.json), [single-seed GraphSAGE metrics](../data/graphsage_chronological_20261001_v2/metrics.json), and the [three fresh shared-GPU seed directories](../data/).

## Wallet-enriched graph input revision

The next graph experiment is a model-input contract change, documented in
docs/GRAPH_WALLET_INPUT_CONTRACT.md. It keeps the same token-level prediction
unit, 7-day cutoff, labels, split, validation-only tuning, and locked-test
procedure. It changes the graph from the current token-pool-counterparty
representation to separate target-token graphs with the typed structure
wallet --swap activity--> pool --contains--> target token.

The current normalized event artifacts do not contain a canonical swap
participant address, so this report contains no wallet-graph result. The
existing metrics above remain results for the older graph-input version. A
wallet-graph run must first collect source-mapped participant fields, record
missing-participant coverage, and prove zero post-cutoff wallet activity in
the graph inputs. It must then use the same eligible tokens and split so the
comparison isolates the added wallet information.

## Next decision

Use the tabular logistic model as the current reference model for thresholded
screening. GraphSAGE has stable ranking signal but does not currently improve
the practical precision/recall tradeoff after validation-only calibration.
The next graph experiment is the wallet-enriched input revision, not a larger
architecture. Larger architectures should wait until that input revision
shows a stable benefit over this reference.
