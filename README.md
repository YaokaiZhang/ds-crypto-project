# Chainrisk: Ethereum on-chain risk analysis

Graph models over Ethereum wallet and token activity for two task families:

- **Task A, Forecast:** predicts from a token's first week whether it stays
  active or ends up low-volume (`continued_activity`).
- **Task B, Scam screening:** `phishing` addresses, `ponzi` contracts,
  `honeypot` tokens and Uniswap v2 `rug_pull` liquidity withdrawal.

The trained models are published as checksummed bundles in the GitHub
[`Models` release](https://github.com/YaokaiZhang/ds-crypto-project/releases/tag/Models)
and served by one CPU model API.

## Reproduce (reviewers)

You need Docker (or podman) and `python3`. From a fresh clone, run:

```bash
deploy/reproduce.sh
```

The script:

1. builds the API image ([`deploy/Dockerfile`](deploy/Dockerfile));
2. downloads the model versions pinned in [`deploy/release.json`](deploy/release.json)
   and checks every checksum;
3. starts the API on `http://127.0.0.1:7860` with a random API key;
4. checks that all five models load, that a request without the key gets 401,
   and that two real held-out tokens in [`deploy/fixtures/`](deploy/fixtures)
   get the same scores the research run recorded.

It ends with `PASS`, then prints the API key and the command that stops the
server. It takes a few minutes, mostly for the build. CI runs the same script
on every push ([`model-api.yml`](.github/workflows/model-api.yml)).

No Docker? Use a plain Python 3.11 venv instead (the venv goes under
`deploy/.build/`):

```bash
deploy/reproduce.sh local
```

### Try a prediction

With the server running, set `KEY` to the key the script printed and send one
of the fixture tokens:

```bash
python3 -c 'import json; print(json.dumps(json.load(open("deploy/fixtures/forecast-continued_activity.json"))["packet"]))' | curl -s -X POST http://127.0.0.1:7860/predict -H "X-Inference-Key: $KEY" -H "Content-Type: application/json" -d @-
```

The response has the `score`, the `decision` and the exact `model_version`.

## More detail

- [deploy/README.md](deploy/README.md): model bundles, the API contract,
  Hugging Face and other hosts.
- [CONTRACT.md](CONTRACT.md) and [GOAL.md](GOAL.md): project scope and evaluation rules.
- [docs/](docs): data and training pipelines for each task.
- [apps/](apps): the backend and the web frontend.

Scores are research screening outputs, not calibrated probabilities of fraud.
