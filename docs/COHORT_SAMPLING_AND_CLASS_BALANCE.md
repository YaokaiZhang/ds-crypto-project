# Cohort Sampling and Class Balance

## Status

This is the sampling requirement for the primary `low_volume_dead` task. It
does not change the label threshold or the censoring rules in
`config/label_specification.json`.

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
2. Freeze the chronological test boundary and development-selection rule
   before inspecting any primary outcomes.
3. Collect all selected pools and the complete 7-day observation plus
   90-day follow-up for each candidate.
4. Assign the primary label, or record a specific censoring reason.
5. Retain the full candidate frame, including candidates that are censored or
   not selected for the modelling cohort.
6. After labels are complete, select the 50/50 development cohort only from
   the predeclared development pool. Do not relabel or duplicate tokens to
   satisfy it.
7. Keep the chronological test holdout untouched and report its observed class
   prevalence rather than forcing a 1:1 ratio.

## Development quota

The target development cohort is:

| Primary label | Target |
| --- | ---: |
| `low_volume_dead` | 50 |
| `continued_activity` | 50 |

This is a 1:1 case-control sample for development and comparison. It is not
an estimate of the real market prevalence of dead and active tokens. Collect a
buffer of candidates because censoring, overlap exclusions, launch-period
coverage, and chronological split constraints can reduce the usable count.

If the quota cannot be reached, report the shortfall and its cause. Do not
lower the USD threshold, count mints or burns as trading volume, or treat
censored tokens as either class to fill the quota.

## Required metadata

The candidate and sampling manifests must preserve:

- candidate-frame selection rule and selection probability;
- launch-period and activity or pool-count strata;
- complete primary label and censoring reason;
- cohort role: development, validation, test, or excluded;
- quota-selection reason;
- case-control or inverse-probability weight;
- predeclared split boundary and test-selection rule;
- chronological cutoff, follow-up end, and overlap group.

## Evaluation rule

Train and tune using the declared development and validation design. Report
the class balance and sampling weights. Evaluate the final model on the
chronological holdout with its observed prevalence. Use prevalence-preserving
test metrics and review-budget measures such as `Precision@K`; do not present
metrics from the balanced development sample as market-level prevalence
estimates.
