# Classic Scam Screening Task Contract

Version: scam-task-contract-0.2. Revised: 2026-10-08.
Status: data pipelines and Phishing/Ponzi offline training code implemented;
Honeypot/Rug Pull data-only. Synthetic engineering checks only; no real-data
training, weights, performance claims, simulation, or services.

This contract extends the system scope in [GOAL.md](../GOAL.md). It does not
change Task A's token outcome, selected-pool scope, 7-day observation window,
90-day follow-up, or primary split. See the
[system design](SYSTEM_REQUIREMENTS_AND_ARCHITECTURE.md) and
[TrxLLM review](TRXLLM_REFERENCE_REVIEW.md) for evidence and rationale.

## 1. Tasks, entities, and permissible claims

| Task id | Target | Positive meaning | Not implied |
|---|---|---|---|
| `phishing_address` | Ethereum address with documented role | Evidence supports the specified malicious phishing role | Every counterparty, victim, router, or related deployer is malicious |
| `ponzi_contract` | Ethereum contract | Evidence supports a Ponzi mechanism under the source's audited definition | Inactivity, repeated payments, or a star graph proves Ponzi |
| `honeypot_sell_restriction` | Ethereum token contract | Documented deceptive sell restriction under specified state/conditions | A missing sell, one reverted swap, or a high graph score proves universal inability to sell |
| `rug_pull_liquidity_v2` | Ethereum token with verified Uniswap v2 pool/event mapping | Evidence supports malicious liquidity withdrawal and controller/fund-flow attribution | Ordinary LP withdrawal, reserve decline, inactivity, or a router as Burn.sender proves fraud |

CLI task names are `phishing`, `ponzi`, `honeypot`, and `rug_pull`.
They are independent, potentially overlapping binary tasks. Transaction
inputs resolve related entities; they neither inherit entity labels nor
produce transaction-level verdicts. V3 and other rug mechanisms are excluded.

Classic contract exploit-lure honeypots require a separate subtype and label
version; they must not be silently merged with ERC20 sell-restriction cases.
Blacklist membership is source evidence, not a fourth mutually exclusive
scam mechanism. A target can have multiple supported task labels.

The first release concerns historical or current pattern screening at a
cutoff. A claim of prediction before an incident requires an independently
defined incident onset, a cutoff strictly before that onset, a fixed forecast
horizon/lead time, and a new evaluation contract.

## 2. Source and label admission

Every admitted dataset must have a frozen source/version, retrieval date,
checksum, schema, chain, entity mapping, time range, source terms, and a data
card separating verified fields from unknown fields. Public metadata alone
does not establish file readability, graph coverage, or redistribution rights.

Every label record contains:

- task_id, entity_id, sample_id, source_label, mapped_label, label_version;
- evidence source/reference, source confidence and role, valid_from/to or
  an explicit unknown value, incident onset when supported;
- label_available_at (when available to the training process), source
  publication/discovery time when known, and the audit decision;
- label_status: supported_positive, supported_negative, unlabeled,
  disputed, invalid, or temporally_unresolved.

An unlabeled address is not a supported negative. A non-Ponzi source label
does not establish that the same address is non-phishing. Source conflicts,
error labels, and unresolved temporal mappings are excluded from definitive
binary supervision until resolved; their raw records remain in the audit.
Model-generated labels and third-party flags do not become independent
ground truth merely by being copied to the label table.

Where only positive and unlabeled data exist, use an explicitly named PU or
known-positive-versus-unlabeled experiment. Its nominal FPR and precision are
not population estimates on independently verified benign entities.

## 3. Time and graph views

The implemented reconstructable graph view `scam-egonet-1.0` uses one graph per
target and cutoff, with a default trailing 30-day interval `(cutoff-30d,
cutoff]`. This is a design choice to test, not a claim about a source dataset.
The exact window, hop count, direction policy, per-hop budget, and sampling
seed must be frozen in each experiment manifest. Whole-lifetime or first-N
event variants are separate graph-view versions.

Target addresses/contracts are roots. Nodes represent chain addresses with
explicit roles. Edges retain transfer/call types, original direction, asset,
amount units, event time, source identifiers, and aggregation lineage. A
token/pool relation is not a transfer. A swap is not an interchangeable alias
for an ERC20 transfer or an external ETH transaction.

Only events and state valid by cutoff may enter inputs. Immutable historical
events can be retrieved later for reconstruction, with provenance proving
their historical existence. Third-party classifications and mutable metadata
must have a known-at rule; today's risk label cannot become yesterday's
feature. Historical balance/code must use the relevant block or remain
missing. Current state is not a substitute.

Labels must apply to the relevant entity role and graph period. An old Ponzi
address with no recent events cannot acquire a valid recent positive sample
merely because its address appears in an old list. Record the incident-active
period or perform a separately identified historical reconstruction. Static
datasets lacking usable time metadata may support a separately named
retrospective structural benchmark; they do not satisfy the online graph
contract and cannot support early-warning claims.

Common routers/exchanges may occur in multiple graphs. Preserve and report
this overlap; do not propagate hidden states or outcomes between partitions.
Store source data independently of filtered model inputs.

## 4. Model and inference contract

Start with shared GraphSAGE implementation code and independent task models,
feature adapters, scalers, heads, thresholds, and calibration. The existing
activity checkpoint is not compatible solely because dimensions match.
Every model manifest identifies consumed features and relation handling;
stored edge attributes are not claimed as inputs unless actually consumed.

The graph/tensor inference schema must not require a label. Unknown labels
are masked in supervised or multi-task training, never filled with zero.
Quality failures return a status and null score. Missing numeric fields
retain explicit missingness, not fabricated zeros interpreted as facts.

Honeypot screening keeps graph scores separate from rule or isolated
simulation evidence. Simulation records block, sender, route, amounts,
balance/allowance setup, slippage, execution sequence and failure reason.
Insufficient or ambiguous execution evidence remains uncertain.

## 5. Splitting, evaluation, and leakage gates

Freeze a per-task entity/group split before selecting models. The initial
offline protocol uses 80/10/10 train/validation/test where class and group
support permit; do not split transactions of the same target across sets.
Group repeated snapshots, duplicated contracts, established campaigns and
strong near-duplicates. If support is inadequate, pre-register a different
grouped protocol or keep the branch descriptive; do not repeatedly search
splits until favorable metrics appear.

For temporally resolved data, additionally evaluate a later cohort with
models fitted only to labels available at training-as-of. Prospective shadow
validation is required before making broad live generalization claims.
Fit transformations on train only; thresholds/calibration on validation only;
lock test for final evaluation. Deduplicate across data sources before split.

Compare rules, tabular/own-feature baselines, neighborhood-summary baselines,
and GraphSAGE on identical eligible samples and cutoffs. Report per-task
positive meaning, counts, prevalence/selection, AP, ROC-AUC, precision,
recall, macro-F1, FPR, Precision@K, and group-level uncertainty. Metrics with
unverified negative labels must retain their limited interpretation. No
single averaged score across incomparable tasks is a release claim.

If using shared pretraining or multi-task weights, audit held-out entities,
campaigns, neighborhood overlap, and time across the union of tasks. Exclude
held-out target entities and known related groups from shared fitting under
the conservative first protocol. Do not use a test entity from one task as a
supervised training target in another. Record permitted common-neighbor
overlap and run sensitivity checks where it may dominate results.

## 6. Collection, training, and serving lifecycle

Incremental chain data may support inference, EDA and drift analysis before
labels exist. Supervised retraining consumes only frozen, quality-approved,
temporally applicable labels available at training-as-of. Self-supervised
experiments require their own training-period and holdout audit. No automatic
online learning from the model's own alerts is part of this contract.

Serving returns entity/task, feature cutoff, data freshness, model version,
score meaning/calibration status, evidence and quality status. A token can
link to a deployer's assessment as separately scoped evidence; that relation
does not transfer the deployer's label to the token or its holders.

Unknown, unsupported, stale, insufficient_history, data_incomplete,
insufficient_evidence and model_unavailable are not healthy labels.
Scores support investigation, not automatic public accusations or trading.

Each branch advances from data-admitted to offline-evaluated to shadow-only
to limited-release only with recorded evidence. All four branches remain
in project scope; an unavailable branch is honestly marked as unavailable
rather than filled with demo results or another task's predictions.
