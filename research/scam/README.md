# Scam data and training

Run from the repository root with the existing Python environment:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --help
```

`chainrisk-scam` and `python -m research.scam` are aliases of the same entrypoint.
The four tasks use independent frozen inputs, weights and thresholds.

## Stages

| Stage | Action |
|---|---|
| `sources` | Freeze/verify sources and select collection targets |
| `collect` | Collect, normalize and build graphs |
| `prepare` | Validate graph/label admission and freeze splits/configuration |
| `train` | Validate prepared inputs, fit and export the model bundle/results |
| `all` | Run `sources → collect → prepare → train` |
| `status` | Read preparation, collection and model-run status |

`train` and `all` require `--run NAME`; use a new name to avoid overwriting an
existing model. Individual data stages never train or automatically run earlier
stages. Provider access requires `--allow-network` and configured credentials.

## Retained runs

| Task | Snapshot | Graph run | Model run |
|---|---|---|---|
| Phishing | forta-recent-v1 | — | mean-sage-v1 |
| Ponzi | xblock-unica-recent-v1 | — | mean-sage-v1 |
| Honeypot | trapdoor-api-v1 | all-recent-v1 | sage-v1 |
| Rug Pull | tokenscout-eligible-1500-v2 | recent-v1 | sage-v1 |

All four models have completed training. For Honeypot, explicitly select
`--graph-run all-recent-v1`; token tasks otherwise default to `recent-v1`.

```bash
# Read status or validate a complete run plan without writes/network/fitting:
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage status
.venv/bin/python scripts/scam/run_pipeline.py --task honeypot --snapshot trapdoor-api-v1 --graph-run all-recent-v1 --stage all --run sage-v2 --dry-run

# Train a new run from already prepared data:
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage train --run mean-sage-v2
```

For a full collection/training run, use `--stage all --run NEW_RUN
--allow-network`. Inspect `--help` for task-specific source selection and training
overrides. A dry run checks existing prepared inputs, but a fresh-snapshot plan
cannot validate data that has not yet been produced. Failed admission stops
training; optimizer-state resume is not supported.

## Data and results

- Task inputs: `data/scam/<task>/<snapshot>/`; token preparation is under
  `graph_runs/<graph-run>/prepared/`.
- Shared replay dependencies: `data/shared/`; preserve referenced
  `events.jsonl.gz` files and their checksums.
- Models: `artifacts/scam/<task>/<snapshot>/<run>/`.
- Experiment/quality results: `reports/`.

Keep frozen sources, exclusions, recipes and prepared inputs intact. New Scam
runs use grouped/stratified 90/10 train/validation; validation selects checkpoints
and thresholds and is not an independent test. Task definitions and limitations
are in [the project contract](../../CONTRACT.md).

Run repository checks with `.venv/bin/python checks/run.py`; see
[checks](../../checks/README.md).
