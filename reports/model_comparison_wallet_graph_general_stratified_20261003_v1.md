# Wallet GraphSAGE comparison: general stratified 2026-10-03

Status: three wallet-graph seeds and the matched tabular baseline completed.

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

### Tabular logistic baseline

- Input: nine pre-cutoff point-in-time token features.
- Scaling: StandardScaler fit on train rows only.
- Model: logistic regression, C=1.0, train-only class weighting.
- Seed: 20261001.
- Threshold: validation balanced accuracy, then macro-F1.
- Test was scored once after the threshold was fixed.

## Native validation/test results

The native threshold is selected by each trainer from the validation split.

| Model | Split | n | ROC-AUC | Average precision | Balanced accuracy | Macro-F1 | FPR | Active recall | Threshold |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Wallet GraphSAGE | validation | 195 | 0.9722 | 0.9765 | 0.9239 | 0.9231 | 0.0532 | 0.9010 | 0.4869 |
| Wallet GraphSAGE | test | 209 | 0.9478 | 0.9344 | 0.8662 | 0.8658 | 0.1364 | 0.8687 | 0.4869 |
| Tabular logistic | validation | 195 | 0.9206 | 0.9431 | 0.8694 | 0.8664 | 0.0532 | 0.7921 | 0.5858 |
| Tabular logistic | test | 209 | 0.9348 | 0.9327 | 0.8581 | 0.8597 | 0.0818 | 0.7980 | 0.5858 |

At the native threshold, wallet GraphSAGE has the stronger matched test
ranking metrics, but the difference is small in average precision. It also
produces more false positives at this threshold. For the failure objective,
the tabular model catches more dead tokens with fewer false active alarms.

The trainer's positive class is continued_activity. The failure-oriented
metrics below reverse the question: dead recall is the share of dead tokens
correctly flagged as dead, dead precision is the share of predicted dead
tokens that are truly dead, and false active rate is the share of dead tokens
incorrectly called continued_activity.

| Model / seed | Dead recall | Dead precision | False active rate |
| --- | ---: | ---: | ---: |
| Wallet GraphSAGE / 20261001 | 0.8636 | 0.8796 | 0.1364 |
| Wallet GraphSAGE / 20261002 | 0.8455 | 0.8774 | 0.1545 |
| Wallet GraphSAGE / 20261003 | 0.8636 | 0.8796 | 0.1364 |
| Tabular logistic | 0.9182 | 0.8347 | 0.0818 |

Across wallet seeds, test ROC-AUC ranges only from 0.9478 to 0.9480, while
threshold-dependent false active rate ranges from 0.1364 to 0.1545. Ranking
quality is stable; the exact operating threshold is more sensitive.

## Validation-only FPR calibration

The calibration sweep chooses the threshold on validation only, maximizing
continued_activity recall under the requested FPR budget. Test values are
reported after that threshold is fixed.

| Model | Target FPR | Validation FPR / active recall | Test FPR / active recall | Test Macro-F1 |
| --- | ---: | ---: | ---: | ---: |
| Wallet GraphSAGE | 0.05 | 0.0213 / 0.8515 | 0.0727 / 0.8182 | 0.8743 |
| Wallet GraphSAGE | 0.10 | 0.0532 / 0.9010 | 0.1364 / 0.8687 | 0.8658 |
| Wallet GraphSAGE | 0.15 | 0.1489 / 0.9208 | 0.1727 / 0.9091 | 0.8660 |
| Tabular logistic | 0.05 | 0.0426 / 0.7327 | 0.0727 / 0.7677 | 0.8493 |
| Tabular logistic | 0.10 | 0.0851 / 0.8119 | 0.1091 / 0.8081 | 0.8506 |
| Tabular logistic | 0.15 | 0.1383 / 0.8317 | 0.1182 / 0.8283 | 0.8557 |

The test FPR does not have to equal the validation budget; the budget
constrains threshold selection on validation, while the test remains a locked
estimate.

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

Threshold calibration artifacts are stored as
threshold_calibration.json inside each model output directory.

## Limitations and next run

Three wallet GraphSAGE seeds now support a stable ranking result on this test
set, but they are repeated runs on the same 209 tokens, not independent
evidence of generalization. The failure-oriented threshold metrics remain
sensitive to a small number of tokens. A larger or external cohort is needed
before treating wallet information as a confirmed improvement over the
tabular baseline.
