# Synthetic Task B fixtures

These invented addresses, transactions and audit labels test code paths only.
They are not chain evidence, a research dataset, or model-performance evidence.
The `synthetic://` references are deliberately non-verifiable outside these tests.

Regenerate with `uv run --frozen python -m checks.generate_fixtures`.
Engineering checks may perform a single forward/backward pass, but no dataset
training or model selection is required for this release.
