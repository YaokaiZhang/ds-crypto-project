# Backend model-input contracts

These files ship with the backend; `deploy/` is not a backend runtime dependency.

- `eth_models.json`: Phishing/Ponzi input directories.
- `token_models.json`: Honeypot/Rug Pull input directories.
- `eth_inputs/`, `token_inputs/`: unchanged model manifests and fitted scalers,
  without weights. They define task-specific graph collection/sampling, feature
  ordering and the model identity sent to the service.

Paths in each index resolve relative to that index file. `MODEL_REGISTRY_PATH`
and `TOKEN_MODEL_REGISTRY_PATH` can override the index files. Default resolution
is relative to the backend source directory, independent of working directory.

Manifests retain their original training metadata, including binary thresholds,
for checksum compatibility. Backend code does not use those thresholds to assign
labels. Runtime threshold/display policy files belong to the model server.

Forecast retains its separate first-week wallet-graph input builder. Its final
model manifest/scaler is still pending; current mock inputs explicitly say so.
See [the model-service contract](../../docs/MODEL_SERVICE_CONTRACT.md).
