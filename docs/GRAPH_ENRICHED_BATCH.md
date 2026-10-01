# Pre-cutoff Enriched Batch

The project can collect more `continued_activity` examples without using the
90-day label during selection. `scripts/graph_screen.py` screens only the
first seven days after each token's `t0`, records early swap volume and other
pre-cutoff features, and then selects a development batch from fixed strata.

The current enrichment design targets 500 new tokens:

- 60% with first-seven-day swap volume at least USD 1,000;
- 30% with first-seven-day swap volume from USD 100 to 999.99;
- 10% with first-seven-day swap volume below USD 100.

The screen excludes candidates with incomplete pool/activity retrieval or
missing/nonpositive early swap USD values. It does not inspect the later
90-day follow-up. The selected rows retain `inclusion_probability` and
`sampling_weight`; these are required when reporting results from this
enriched candidate source. Enrichment does not define a separate balanced
development cohort.

After screening, run `scripts/graph_free_pilot.py` on
`selected_candidates.jsonl` to collect the complete 90-day follow-up and
assign the primary `low_volume_dead` / `continued_activity` label. The
After complete labels are available, combine eligible rows with the broader
labeled population and apply the general 80/10/10 split in
`config/model_split.json`. Preserve the inclusion probabilities and weights
for analysis; do not use enrichment to force a 50/50 train/validation split.
