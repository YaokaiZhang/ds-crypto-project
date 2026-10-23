# Wallet GraphSAGE comparison: general stratified 2026-10-03

Status: three wallet-graph seeds, the matched tabular baseline, the
failure-positive evaluation, the topology-only capacity sweep, and the
edge-aware architecture sweep completed. The edge-aware sweep was also
rerun with GPU-resident graph-tensor caching for throughput validation.

This report compares the new wallet GraphSAGE input with a nine-feature
pre-cutoff tabular logistic baseline on the same 2,000 token rows and frozen
partitions. The older static-graph result is included only as historical
context because it uses a different cohort and an older graph input.

## Frozen contract

- Prediction unit: one token contract.
- Labels: 1,000 continued_activity and 1,000 low_volume_dead.
- Observation window: inclusive [t0, cutoff], with 7 days of input activity.
- Follow-up label: 90 days after cutoff; post-cutoff events are excluded from
  features.
- Primary split: token-level general stratified split, retaining overlap
  groups. Frozen counts are train 1,596, validation 195, and test 209.
- Test use: test thresholds and metrics are reported only after validation
  checkpoint and threshold selection.
- Wallet graph version: wallet-graph-input-0.1.
- Participant semantics: wallet identity is swap_sender; swap_recipient and
  transaction_from are retained role fields, not human-identity claims.

The split is class-wise and launch-period/overlap constrained, so it is not
exactly 80/10/10 within every label after frozen group assignment:

| Partition | continued_activity | low_volume_dead | total |
| --- | ---: | ---: | ---: |
| train | 800 | 796 | 1,596 |
| validation | 101 | 94 | 195 |
| test | 99 | 110 | 209 |

## Data gates

| Check | Result |
| --- | ---: |
| Selected tokens | 2,000 |
| Complete labels | 2,000 |
| Normalized events | 988,383 |
| Activity groups / pool records | 2,367 / 2,720 |
| Collection request rows | 2,970 |
| Missing swap_sender / swap_recipient / transaction_from | 0 / 0 / 0 |
| Feature rows complete | 2,000 / 2,000 |
| Pre-t0 events in feature audit | 0 |
| Post-cutoff events in feature audit | 0 |
| Missing event timestamps in feature audit | 0 |
| Wallet model-ready graphs | 2,000 / 2,000 |
| Wallet graph quality rows complete | 2,000 / 2,000 |
| Wallet-pool edge rows | 18,950 |
| Graph/tabular key differences | 0 / 0 |
| Graph label or partition mismatches against tabular targets | 0 / 0 |

The participant-aware collection used only official Uniswap v2/v3 subgraph
swap events through the The Graph gateway. Labels and partitions were reused
from the frozen target manifest; follow-up labels were not recollected.

The original v4 normalized product is preserved. The v5 product repairs its
supervised table by mapping the frozen target manifest's explicit
censoring_status: false to volume_complete: true; rows without either
completion signal remain excluded. This is why v4's empty supervised table is
not used as modeling evidence.

## Training

### Wallet GraphSAGE

- Input: data/wallet_graph_input_20261003_2000_v4/graphs.jsonl.
- Model: two-layer mean GraphSAGE with center-node readout.
- Batch size: 512.
- Device: NVIDIA GH200 120GB.
- Seeds: 20261001 (primary), 20261002, and 20261003.
- Best validation epoch: 62; 97 epochs were run.
- Train positive-class weight: 0.995.
- Threshold: validation balanced accuracy, then macro-F1.
- Slurm jobs: 2003168 (primary) and 2003314 (additional seeds), both completed
  with exit code 0.

### Capacity sweep

- Candidates: hidden width 32 / 2 layers (existing reference), 64 / 2 layers,
  128 / 2 layers, and 64 / 3 layers.
- Seeds: 20261001, 20261002, and 20261003 for every candidate.
- The same graph input, frozen split, batch size, optimizer settings, maximum
  epochs, patience, and failure-positive evaluation contract were retained.
- Slurm job 2008121 ran all nine new trainings concurrently on exactly one
  NVIDIA GH200 120GB, with nine exclusive 8-core CPU slots. All nine steps
  completed with exit code 0 in 3:05.
- Validation-only selection chose hidden width 64 / 2 layers. The non-selected
  candidates were not used for held-out test scoring.

### Edge-aware architecture sweep

- Input: the same frozen wallet graph input, including all 11 named edge
  features.
- Architectures: edge-aware GraphSAGE, edge-aware GCN, and edge-aware GAT.
  All three use edge values in message construction; no plain topology-only
  GCN/GAT implementation was used.
- Configurations: hidden width 32 / 2 layers, 64 / 2 layers, 128 / 2 layers,
  and 64 / 3 layers. Each configuration used seeds 20261001, 20261002, and
  20261003.
- Edge normalization was fit on training graph edges only and persisted in
  each model checkpoint, metrics file, and normalization sidecar.
- Slurm job 2012135 ran all 36 trainings in four nine-step waves on exactly
  one NVIDIA GH200 120GB allocation. The cluster serialized some child-step
  starts; the parent completed with exit code 0 in 37:55.
- All 36 outputs passed structural checks: train/validation/test counts of
  1,596/195/209 and 2,000 prediction rows per output.
- The launcher was then corrected to use one batch task, discover the actual
  Slurm CPU set, run nine trainers concurrently per wave, and cache normalized
  graph tensors on the GPU. Job 2014563 completed the equivalent 36-model
  rerun in 2:28 with exit code 0. Active telemetry samples averaged 96.2% SM
  utilization at 171.9 W; the maximum framebuffer use was 8,437 MiB, so the
  small graph workload remains compute-busy without filling the 120 GB device.
- The cached `v4` rerun produced 36 checkpoints, 72,000 prediction rows, and
  byte-identical prediction files to the original `v1` outputs. It is a
  throughput-equivalence rerun; validation selection and locked-test scoring
  remain tied to the already audited `v1` artifacts.
- Validation-only selection chose edge-aware GCN, width 128 / 2 layers. The
  non-selected edge-aware families were not used for locked-test scoring.

### Tabular logistic baseline

- Input: nine pre-cutoff point-in-time token features.
- Scaling: StandardScaler fit on train rows only.
- Model: logistic regression, C=1.0, train-only class weighting.
- Seed: 20261001.
- Threshold: validation balanced accuracy, then macro-F1.
- Test was scored once after the threshold was fixed.

## Native validation/test results

The native threshold is selected by each trainer from the validation split.
The ranking and threshold-dependent fields in this context table retain the
trainer's native `continued_activity`-positive convention; they are not the
failure-positive operating-point results below.

| Model | Split | n | ROC-AUC | Average precision | Balanced accuracy | Macro-F1 | FPR | Active recall | Threshold |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wallet GraphSAGE | validation | 195 | 0.9722 | 0.9765 | 0.9239 | 0.9231 | 0.0532 | 0.9010 | 0.4869 |
| Wallet GraphSAGE | test | 209 | 0.9478 | 0.9344 | 0.8662 | 0.8658 | 0.1364 | 0.8687 | 0.4869 |
| Tabular logistic | validation | 195 | 0.9206 | 0.9431 | 0.8694 | 0.8664 | 0.0532 | 0.7921 | 0.5858 |
| Tabular logistic | test | 209 | 0.9348 | 0.9327 | 0.8581 | 0.8597 | 0.0818 | 0.7980 | 0.5858 |

At the native threshold, wallet GraphSAGE has the stronger matched test
ranking metrics, but the difference is small in average precision. The native
threshold is selected for balanced accuracy with continued_activity as the
positive class, so it is not a matched failure-screening operating point.

## Failure-positive evaluation

The project question is evaluated explicitly with `low_volume_dead` as the
positive class:

- `failure_label = 1 - label_int`;
- `score_low_volume_dead = 1 - score_continued_activity`;
- thresholds are selected on validation rows only and applied once to the
  locked test rows.

For each target failure-positive FPR budget, the evaluator selects the
validation threshold with maximum dead recall, breaking ties by
failure-positive F1. Here, failure-positive FPR is the share of continued
tokens incorrectly flagged dead. `False active rate` is reported separately:
the share of dead tokens incorrectly called continued. Validation support is
94 dead and 101 continued tokens; locked test support is 110 dead and 99
continued tokens, so locked-test prevalence is 52.6% low_volume_dead and
47.4% continued_activity.

The analyst review budget was fixed at 20 tokens before test evaluation. `K`
was selected from 1 through 20 using validation data only, by maximum mean
failure-positive F1 across the four model outputs, then mean precision and
smaller K as tie-breakers. This selected `K=20`. The confusion-matrix column
uses `(true dead, continued flagged dead, dead called active, true
continued)`.

| Model / seed | Target FPR | Threshold | Validation FPR / dead recall | Test dead recall / precision | Failure F1 / macro-F1 | Test FPR / false active | ROC-AUC / AP | Precision@20 | Test confusion |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Wallet GraphSAGE / 20261001 | 0.05 | 0.7371 | 0.0495 / 0.8191 | 0.7818 / 0.9348 | 0.8515 / 0.8563 | 0.0606 / 0.2182 | 0.9478 / 0.9547 | 1.0000 | 86 / 6 / 24 / 93 |
| Wallet GraphSAGE / 20261001 | 0.10 | 0.5172 | 0.0990 / 0.9468 | 0.8636 / 0.8796 | 0.8716 / 0.8658 | 0.1313 / 0.1364 | 0.9478 / 0.9547 | 1.0000 | 95 / 13 / 15 / 86 |
| Wallet GraphSAGE / 20261001 | 0.15 | 0.5131 | 0.1485 / 0.9787 | 0.9273 / 0.8500 | 0.8870 / 0.8743 | 0.1818 / 0.0727 | 0.9478 / 0.9547 | 1.0000 | 102 / 18 / 8 / 81 |
| Wallet GraphSAGE / 20261002 | 0.05 | 0.7422 | 0.0495 / 0.8298 | 0.7818 / 0.9247 | 0.8473 / 0.8516 | 0.0707 / 0.2182 | 0.9480 / 0.9553 | 1.0000 | 86 / 7 / 24 / 92 |
| Wallet GraphSAGE / 20261002 | 0.10 | 0.5827 | 0.0891 / 0.9149 | 0.8455 / 0.8942 | 0.8692 / 0.8660 | 0.1111 / 0.1545 | 0.9480 / 0.9553 | 1.0000 | 93 / 11 / 17 / 88 |
| Wallet GraphSAGE / 20261002 | 0.15 | 0.5307 | 0.1485 / 0.9681 | 0.9364 / 0.8512 | 0.8918 / 0.8790 | 0.1818 / 0.0636 | 0.9480 / 0.9553 | 1.0000 | 103 / 18 / 7 / 81 |
| Wallet GraphSAGE / 20261003 | 0.05 | 0.7713 | 0.0495 / 0.8191 | 0.8000 / 0.9263 | 0.8585 / 0.8612 | 0.0707 / 0.2000 | 0.9479 / 0.9562 | 1.0000 | 88 / 7 / 22 / 92 |
| Wallet GraphSAGE / 20261003 | 0.10 | 0.5918 | 0.0891 / 0.9043 | 0.8545 / 0.9038 | 0.8785 / 0.8755 | 0.1010 / 0.1455 | 0.9479 / 0.9562 | 1.0000 | 94 / 10 / 16 / 89 |
| Wallet GraphSAGE / 20261003 | 0.15 | 0.5610 | 0.1089 / 0.9255 | 0.8636 / 0.8796 | 0.8716 / 0.8658 | 0.1313 / 0.1364 | 0.9479 / 0.9562 | 1.0000 | 95 / 13 / 15 / 86 |
| Tabular logistic | 0.05 | 0.9011 | 0.0495 / 0.6064 | 0.6364 / 0.9333 | 0.7568 / 0.7818 | 0.0505 / 0.3636 | 0.9348 / 0.9416 | 1.0000 | 70 / 5 / 40 / 94 |
| Tabular logistic | 0.10 | 0.8041 | 0.0891 / 0.6809 | 0.7364 / 0.9419 | 0.8265 / 0.8367 | 0.0505 / 0.2636 | 0.9348 / 0.9416 | 1.0000 | 81 / 5 / 29 / 94 |
| Tabular logistic | 0.15 | 0.7973 | 0.1089 / 0.7660 | 0.7727 / 0.9140 | 0.8374 / 0.8420 | 0.0808 / 0.2273 | 0.9348 / 0.9416 | 1.0000 | 85 / 8 / 25 / 91 |

At all three target FPR budgets, each wallet seed has higher dead recall and
failure-positive F1 than the tabular reference. The tabular model has higher
dead precision at the 0.10 and 0.15 budgets, while the wallet models miss
fewer dead tokens. `Precision@20` does not separate the models in this cohort:
the top 20 scores are dead tokens for every output. Thus, under a controlled
failure-screening operating point, wallet information shows an operational
advantage on this matched test set, but not a confirmed generalization gain.

The test FPR does not have to equal the validation budget; the budget
constrains threshold selection on validation, while the test remains a locked
estimate.

## Topology-only capacity sweep selection

The architecture decision was made from validation rows only. For each of the
four candidate families, the table reports the mean over its three seeds. The
selection score is mean failure-positive F1 across the 0.05, 0.10, and 0.15
FPR budgets; ties were broken by mean failure-positive average precision,
precision@20, and smaller width-times-depth.

| Candidate | Mean validation F1 | Mean validation AP | F1 at 0.05 / 0.10 / 0.15 | Mean Precision@20 | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Width 32 / 2 layers | 0.9000 | 0.9706 | 0.8771 / 0.9122 / 0.9106 | 1.0000 | Existing reference |
| Width 64 / 2 layers | 0.9031 | 0.9713 | 0.8872 / 0.9142 / 0.9078 | 1.0000 | Selected |
| Width 128 / 2 layers | 0.8987 | 0.9716 | 0.8891 / 0.9084 / 0.8986 | 1.0000 | Not selected |
| Width 64 / 3 layers | 0.9026 | 0.9708 | 0.8996 / 0.9068 / 0.9014 | 1.0000 | Not selected |

After that validation decision, held-out test scoring was run for the selected
width-64 / 2-layer family. The width-32 values below come from the previously
locked baseline artifact; the non-selected width-128 and three-layer families
were not test-scored.

| Model family | Mean test ROC-AUC / AP | Failure F1 at 0.05 / 0.10 / 0.15 | Dead recall at 0.05 / 0.10 / 0.15 |
| --- | ---: | ---: | ---: |
| Width 32 / 2 layers | 0.9479 / 0.9554 | 0.8524 / 0.8731 / 0.8834 | 0.7879 / 0.8545 / 0.9091 |
| Width 64 / 2 layers (selected) | 0.9489 / 0.9571 | 0.8515 / 0.8694 / 0.8755 | 0.7909 / 0.8576 / 0.8879 |

The larger model slightly improves ranking metrics but does not improve the
locked failure-screening F1 or dead recall at the 0.10 and 0.15 operating
points. This sweep therefore does not support the claim that the original
width-32 model was simply too small. It supports a modest validation benefit
from width 64, without a held-out operational gain.

## Edge-aware architecture selection

The architecture and size decision was made from validation rows only. Each
candidate below is the mean over its three seeds. The selection score is mean
failure-positive F1 across the 0.05, 0.10, and 0.15 FPR budgets; ties were
broken by mean failure-positive average precision, validation Precision@20,
and smaller width-times-depth.

| Architecture | Width / layers | Mean validation F1 | Mean validation AP | Mean Precision@20 | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Edge GraphSAGE | 32 / 2 | 0.9030 | 0.9704 | 1.0000 | Not selected |
| Edge GraphSAGE | 64 / 2 | 0.9047 | 0.9714 | 1.0000 | Not selected |
| Edge GraphSAGE | 128 / 2 | 0.9062 | 0.9724 | 1.0000 | Not selected |
| Edge GraphSAGE | 64 / 3 | 0.8985 | 0.9698 | 1.0000 | Not selected |
| Edge GCN | 32 / 2 | 0.9055 | 0.9716 | 1.0000 | Not selected |
| Edge GCN | 64 / 2 | 0.9072 | 0.9727 | 1.0000 | Not selected |
| Edge GCN | 128 / 2 | 0.9107 | 0.9719 | 1.0000 | Selected |
| Edge GCN | 64 / 3 | 0.9022 | 0.9692 | 1.0000 | Not selected |
| Edge GAT | 32 / 2 | 0.9087 | 0.9730 | 1.0000 | Not selected |
| Edge GAT | 64 / 2 | 0.9042 | 0.9709 | 1.0000 | Not selected |
| Edge GAT | 128 / 2 | 0.8988 | 0.9688 | 1.0000 | Not selected |
| Edge GAT | 64 / 3 | 0.8975 | 0.9687 | 1.0000 | Not selected |

After that validation decision, held-out test scoring was run only for the
selected edge GCN family. The comparison controls are the previously
validation-selected topology-only width-64 GraphSAGE family and the matched
tabular logistic baseline. Values are means over three seeds where the family
has three seeds; thresholds were selected on validation only. `K=20` was
frozen before this evaluation.

| Model family | Mean test ROC-AUC / AP | Failure F1 at 0.05 / 0.10 / 0.15 | Dead recall at 0.05 / 0.10 / 0.15 | Dead precision at 0.05 / 0.10 / 0.15 | Test FPR at 0.05 / 0.10 / 0.15 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Edge GCN, width 128 / 2 layers (selected) | 0.9588 / 0.9636 | 0.8684 / 0.8861 / 0.8891 | 0.8212 / 0.8727 / 0.9000 | 0.9218 / 0.9000 / 0.8794 | 0.0774 / 0.1077 / 0.1380 |
| Topology-only GraphSAGE, width 64 / 2 layers | 0.9489 / 0.9571 | 0.8515 / 0.8694 / 0.8755 | 0.7909 / 0.8576 / 0.8879 | 0.9223 / 0.8817 / 0.8648 | 0.0741 / 0.1279 / 0.1549 |
| Tabular logistic | 0.9348 / 0.9416 | 0.7568 / 0.8265 / 0.8374 | 0.6364 / 0.7364 / 0.7727 | 0.9333 / 0.9419 / 0.9140 | 0.0505 / 0.0505 / 0.0808 |

On this locked test set, the selected edge GCN has higher failure-positive F1
and dead recall than the width-64 topology-only control at all three budgets,
with lower false-active rate. It also has higher failure-positive F1 and dead
recall than the tabular model, while the tabular model remains more
conservative and has higher dead precision. The top-20 failure scores are all
dead tokens for every comparison output, so Precision@20 does not separate
the models. These are repeated seeds on the same 209 test tokens, not
independent evidence of generalization.

## Historical reference

The historical general-stratified GraphSAGE result is retained for context:

| Model | Test rows | Test ROC-AUC | Test AP | Test balanced accuracy | Test Macro-F1 | Test FPR | Test active recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Older static graph reference | 1,042 | 0.9390 | 0.7508 | 0.8591 | 0.7189 | 0.1506 | 0.8687 |

This reference uses the recovered imbalanced cohort (943 low_volume_dead and
99 continued_activity in test) and a static pool graph, not the new
wallet-pool-token graph. It must not be interpreted as a direct head-to-head
comparison with the matched 209-row wallet results.

## Artifacts

- Collection report:
  data/wallet_graph_events_20261003_2000/wallet_graph_collection_report.json
- Corrected normalized product:
  data/derived_wallet_graph_20261003_2000_v5
- Wallet graph input:
  data/wallet_graph_input_20261003_2000_v4
- Matched tabular target manifest:
  data/tabular_wallet_graph_20261003_v1/targets.jsonl
- Wallet GraphSAGE output:
  data/graphsage_wallet_general_stratified_20261003_v1
- Additional wallet seeds:
  data/graphsage_wallet_general_stratified_20261003_seed20261002_v1 and
  data/graphsage_wallet_general_stratified_20261003_seed20261003_v1
- Tabular logistic output:
  data/tabular_logistic_wallet_general_stratified_20261003_v1
- Historical reference:
  data/graphsage_general_stratified_20261001_v1
- GPU launcher:
  scripts/run_graphsage_wallet_graph_gpu.sh
- Multi-seed GPU launcher:
  scripts/run_graphsage_wallet_graph_seeds_gpu.sh
- Failure-positive evaluator:
  scripts/evaluate_failure_predictions.py
- Failure-positive evaluation artifact:
  data/failure_positive_evaluation_wallet_graph_general_stratified_20261003_v1.json
- Capacity sweep launcher:
  scripts/run_graphsage_wallet_capacity_sweep_gpu.sh
- Capacity validation selector:
  scripts/select_capacity_validation.py
- Capacity validation selection artifact:
  data/graphsage_capacity_sweep_validation_selection_20261004_v1.json
- Selected capacity failure-positive artifact:
  data/failure_positive_capacity_selected_wallet_graph_general_stratified_20261004_v1.json
- Capacity model outputs:
  data/graphsage_wallet_capacity_hidden64_seed*_v1,
  data/graphsage_wallet_capacity_hidden128_seed*_v1, and
  data/graphsage_wallet_capacity_3layer_hidden64_seed*_v1
- Edge-aware architecture launcher:
  scripts/run_graphsage_edge_architectures_gpu.sh
- Edge-aware validation selection artifact:
  data/edge_architecture_selection_validation_20261004_v1.json
- Selected edge-aware failure-positive artifact:
  data/failure_positive_edge_architecture_selected_wallet_graph_general_stratified_20261004_v2.json
- Edge-aware model outputs:
  data/graphsage_wallet_edge_edge_sage_*_v1,
  data/graphsage_wallet_edge_edge_gcn_*_v1, and
  data/graphsage_wallet_edge_edge_gat_*_v1
- Cached throughput-equivalence outputs:
  data/graphsage_wallet_edge_edge_sage_*_v4,
  data/graphsage_wallet_edge_edge_gcn_*_v4, and
  data/graphsage_wallet_edge_edge_gat_*_v4

Threshold calibration artifacts are stored as
threshold_calibration.json inside each model output directory; those files
retain the native continued_activity-positive calibration. The explicit
failure-positive evaluation is the versioned artifact listed above.

## Limitations and next run

The edge-aware sweep selected width-128, two-layer GCN on validation and
showed a higher locked-test failure-screening F1/dead-recall tradeoff than the
validation-selected topology-only width-64 control on this cohort. The result
is still based on repeated seeds over the same 209 test tokens, not independent
evidence of generalization. Edge GCN also trades some dead precision for
additional dead recall relative to the tabular model, and the threshold
metrics remain sensitive to a small number of tokens. Precision@20 is tied at
the frozen `K=20`; a larger or external cohort remains necessary before
treating wallet information or edge-aware architecture as a confirmed
general improvement.
