# Synthetic Scam engineering inputs

`checks/generate_fixtures.py` generates invented addresses, transfers and
`synthetic://` audit references inside each CLI test's temporary directory.
They exercise normalization, audited-label admission, splitting and graph/CLI
contracts. They have no real fraud labels or performance meaning.

The generated JSONL/CSV files are deliberately not duplicated in the repository.
To inspect an example locally, run `python -m checks.generate_fixtures`; output
is written to ignored `checks/.runtime/synthetic-scam/`.

Real model-serving regression packets live in `../model_api/`. They are separate
from these synthetic pipeline inputs and never depend on this generator.
