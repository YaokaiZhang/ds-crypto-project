# Cohort Sampling and Class Balance

## Status

This is the sampling and split requirement for the primary `low_volume_dead`
task. It does not change the label threshold or the censoring rules in
`config/label_specification.json`. The governing split configuration is
`config/model_split.json`.

## Primary labels

For each token with complete evidence:

- `low_volume_dead`: less than USD 1,000 in historical swap volume during the
  complete 90-day follow-up after the fixed 7-day observation window.
- `continued_activity`: at least USD 1,000 in historical swap volume during
  that follow-up.
- `censored`: the primary label cannot be assigned because the follow-up,
  pool scope, retrieval, timestamps, or historical USD amounts are
  incomplete or unreliable.

There is no minimum number of swaps for the primary label. The former
first-10-swaps/no-activity definition is a sensitivity analysis only.

The 14-day and 30-day observation windows are sensitivity analyses. They use
the same label threshold and follow-up duration, but shift the cutoff and
therefore the feature window and label window.

## Required collection procedure

1. Build a candidate frame without inspecting primary labels. Cover multiple
   launch periods and activity or pool-count strata.
2. Freeze the general split rule and grouping policy before model selection.
3. Collect all selected pools and the complete 7-day observation plus
   90-day follow-up for each candidate.
4. Assign the primary label, or record a specific censoring reason.
5. Retain the full candidate frame, including candidates that are censored or
   not selected for the modelling cohort.
6. After labels are complete, retain all eligible labeled rows. Do not
   relabel, duplicate, or discard tokens to manufacture a balanced development
   sample.
7. Assign each eligible token to train or validation using the 2026-10-20
   90/10 policy. Stratify within label and launch-period strata and keep
   each overlap group in one partition.

## General split policy

The wallet-enriched graph uses this same token split. Graph construction does
not create a second wallet-level split, and it does not change the label or
class allocation. Build separate cutoff-bounded target-token graph artifacts
after assigning partitions; the same address may occur in different graph
files, but the initial experiment does not share learned wallet state across
partitions.

The primary model split is:

| Partition | Share within each label/launch stratum |
| --- | ---: |
| Training | 90% |
| Validation | 10% |

For example, if the eligible population contains 1,000
`continued_activity` and 1,000 `low_volume_dead` rows, the intended counts are
900 active plus 900 dead in training and 100 active plus 100 dead in validation.
Overlap-group constraints may adjust an
individual count slightly; the final manifest is authoritative.

Use all eligible training rows. If the complete population is not balanced,
record any class weighting, training-only sampling, or inverse-probability
weighting used by the model. Censored rows remain outside supervised splits.
An optional chronological split can be reported as a secondary stress test
when it has adequate class support.

## Required metadata

The candidate and sampling manifests must preserve:

- candidate-frame selection rule and selection probability;
- launch-period and activity or pool-count strata;
- complete primary label and censoring reason;
- cohort role: training, validation, or excluded;
- candidate-selection or enrichment reason;
- case-control or inverse-probability weight, when applicable;
- split version, ratio, seed, and stratum assignment;
- cutoff, follow-up end, and overlap group.

## Evaluation rule

Record the wallet-graph input version, participant-field coverage, and
missing-participant counts separately from the sampling manifest.

Train on the general training partition and tune thresholds, calibration, and
hyperparameters on validation only. Report final validation Accuracy and mark
validation as reused for model/threshold selection, not an independent test
estimate. There is no test partition. Preserve historical results and create
new split/output versions instead of rewriting old archives. Report per-partition
class counts, validation prevalence, Balanced Accuracy, raw and row-normalized
confusion matrices, sampling
weights, and review-budget measures such as `Precision@K`. Do not treat a
balanced class allocation as a market-prevalence estimate. A chronological
stress-test result is secondary to the general split.
