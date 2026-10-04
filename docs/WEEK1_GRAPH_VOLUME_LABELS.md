# Graph Volume Labels

## Primary definition

The wallet-enriched graph is a separate model-input contract. Adding swap
participant addresses does not change the primary label, its USD threshold, or
the follow-up evidence rules. The current normalized event artifacts do not
contain the participant fields required by
GRAPH_WALLET_INPUT_CONTRACT.md, so the existing graph results are not
wallet-graph results.

The primary label is `low_volume_dead` when the sum of historical
`Swap.amountUSD` values across the selected Uniswap v2/v3 pools is strictly
less than USD 1,000 during the complete 90-day follow-up window. A value of
exactly USD 1,000 is not low-volume under this rule.

The collector uses the earliest selected-pool creation timestamp as `t0`, with
the first selected-DEX activity timestamp as a fallback. The first 7 days
after `t0` are the primary observation window. The next 90 days are the label
window. Only swaps contribute to trading volume; mint and burn events remain
available for liquidity features but do not contribute to the USD total.

Fourteen-day and 30-day observation windows are sensitivity analyses. They are
reported separately and must not be mixed with the primary 7-day cohort.

The Graph's historical `Swap.amountUSD` value is copied into the normalized
event row as `amount_usd`. The labeler sums positive decimal strings exactly.
It does not estimate historical USD from today's token price or ETH price. If
a follow-up swap has a missing, invalid, or nonpositive USD value, the token is
censored because a real swap should not be silently counted as zero dollars.

## Current cohort and split requirement

The 100-token result below was collected under the earlier 30-day observation
window. It is a historical engineering pilot, not a result for the current
7-day primary task or the final balanced
development cohort. The current modelling policy is now the general
token-level split in `config/model_split.json`: 80% training, 10% validation,
and 10% test within label and launch-period strata, with overlap groups kept
together. With 1,000 active and 1,000 dead rows, the intended allocation is
800/800 training, 100/100 validation, and 100/100 test. The full candidate
frame and selection weights must be retained. The earlier 50/50 quota and
chronological holdout are historical design choices for older runs, not the
current primary split.

## Sensitivity definition

`sensitivity_zero_activity_outcomes.jsonl` preserves the former rule:
starting at the tenth swap, a token is `failure` when it has no swap, mint, or
burn during the next 90 days. Tokens with fewer than ten swaps are excluded
under this sensitivity definition only.

## Historical 30-day collection result

The results below were generated before the primary cutoff changed to 7 days.
They remain useful as historical engineering evidence, but must not be used as
the current 7-day cohort or as current model-support evidence.

The five-token implementation check was written to
`data/week1_graph_free_volume_pilot_20260925`. The complete merged result is
in `data/week1_graph_free_volume_results_20260925`; its raw source archives
remain separate and are listed in `manifests/source_archives.jsonl`.

| Primary label, five-token check | Count |
| --- | ---: |
| `low_volume_dead` | 3 |
| `continued_activity` | 2 |
| `censored` | 0 |

The same five tokens under the old sensitivity rule produced four
`continued_activity` rows and one `excluded_early_death` row. This difference
is expected: the new rule treats a token with nine swaps and zero later volume
as low-volume dead, while the old rule discarded it before labeling.

The five-token run had complete pool and activity retrieval and 42,407 swap
rows with a USD amount. It was an engineering check, not enough data for
modeling.

The merged 100-token result has:

| Measure | Count |
| --- | ---: |
| Tokens | 100 |
| Normalized events | 933,385 |
| Swap events with USD | 915,304 |
| `low_volume_dead` | 80 |
| `continued_activity` | 18 |
| Primary censored | 2 |
| Complete activity histories | 100 / 100 |
| Complete pool scope | 100 / 100 |
| Duplicate B(token, event_id)` keys | 0 |

The former sensitivity labels are 74 `continued_activity`, 2 `failure`,
22 `excluded_early_death`, and 2 `censored`. The primary volume labels are
reproducible, but the dataset still does not pass the modelling gate: the
18 `continued_activity` versus 80 `low_volume_dead` split plus 2 censored
tokens is below the 50-per-class development target, and source terms,
feature completeness, chronological support, and sampling metadata still
need audit.
