# Ponzi Source Verification

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

Verified on 2026-10-20. This records a downloaded label source and local schema
inspection. It does not adopt a collection window, publish admitted training
supervision, query Etherscan, or change the Ponzi graph/training contract.

## Frozen source and storage

The retained source snapshot is `data/scam/ponzi/xblock-unica-recent-v1/`.
Workspace cleanup on 2026-10-23 verified that the former `xblock-v1/sources/`
and this snapshot's eight source files were byte-identical, moved the original
`inspection/` here unchanged, and removed the redundant `xblock-v1/` directory.
Source version identifiers inside the evidence remain unchanged. `sources/`
contains original source bytes; `inspection/` contains derived checks. A later
cohort/collection must record its own parameters rather than interpreting the
source directory name as a cutoff.

```text
data/scam/ponzi/xblock-unica-recent-v1/
  sources/
    xblock-v1.zip
    Ponzi_label.csv
    README.txt
    kaggle_metadata.json
    xblock_metadata.json
    manifest.json
    cross_reference/
      unica_commit.json
      unica_ponzi-addresses.csv
  inspection/
    records.jsonl
    summary.json
```

Downloaded from [XBlock's Kaggle dataset](https://www.kaggle.com/datasets/xblock/smart-ponzi-scheme-labels)
using the download API with `datasetVersionNumber=1`. The ZIP contains only
`Smart Ponzi Scheme Labels/Ponzi_label.csv` and its `README.txt`. The manifest
records download URLs, retrieval timestamps, sizes, archive member names and
SHA256 checksums. Extracted files preserve the original bytes.

The archive SHA256 is
`1ef8d24d4391d71b3f608683e349e7266c79a68fe6c01e0474a3a9d8b21bfb98`.

## Verified fields and label meaning

The bundled README attributes the dataset to InPlusLab, Sun Yat-sen University,
and explains that researchers read contract source code to assign Ponzi labels.
Each CSV row represents an Ethereum smart contract. Its two fields are
`Contract` and `Ponzi`; `1` denotes a Ponzi contract. The binary `0` class is
therefore the source's non-Ponzi class, rather than an unlabeled address pool.
The [official XBlock metadata endpoint](https://xblock.pro/api/info/dataset?id=22)
independently describes the manual source-code labeling process. Its raw response
is retained locally for inspection.

This supports a **source-defined supervised Ponzi/non-Ponzi experiment**. It is
not a new independent code audit of each row or a general benign certification.
Per-address incident periods, review dates and labeling rationales are absent.
The existing importer continues to mark binary labels `temporally_unresolved`
until the collection/label protocol is settled; no `admitted` flags were added.

| Local inspection | Result |
|---|---:|
| CSV rows | 3,793 |
| `Ponzi=1` | 200 |
| `Ponzi=0` | 3,590 |
| `Ponzi=error` | 3 |
| Syntactically valid Ethereum addresses | 3,793 |
| Duplicate addresses, ignoring case | 0 |
| Conflicting labels within XBlock | 0 |
| Address-valid rows with a binary label | 3,790 |

Address syntax validation does not independently establish historical contract
code or chain activity. `inspection/records.jsonl` retains original addresses,
lowercase identities, CSV line numbers, raw labels and check results. Error rows
remain in the original file and the inspection report; they must not become
negative examples.

## Version and time information

- The bundled README identifies release 1.0 dated 2018-11-22.
- Kaggle reports dataset version 1, uploaded on 2020-03-23, and license `Unknown`.
- The CSV contains no timestamps, deployment blocks, transaction histories,
  incident dates, or per-contract label-availability dates.
- A website update date, upload date or download date is not an observation
  cutoff or a contract's deployment/incident time.

The README cites Chen et al., *Detecting Ponzi Schemes on Ethereum: Towards
Healthier Blockchain Technology*, WWW 2018, DOI
[10.1145/3178876.3186046](https://doi.org/10.1145/3178876.3186046).
The [author-hosted paper](https://user.it.uu.se/~eding810/conferences/WWW18.pdf),
Section 3, discusses 131 Ponzi and 1,251 non-Ponzi contracts; Section 4.4 uses
contracts created before 2017-05-07 for a separate population application.
Those counts differ from the released CSV. That population date does not
establish a uniform transaction cutoff for all 3,793 released rows. Exact
historical collection parameters remain unconfirmed.

## Cross-reference with Unica

A read-only comparison uses the [Unica repository](https://github.com/blockchain-unica/ethereum-ponzi)
at commit `e083ce720f934e17ea1fe9124b70ea874aa042bf`. Its original address file
contains 184 rows and 182 unique addresses, with two repeated addresses and no
syntactically invalid addresses. Of the unique addresses overlapping XBlock,
133 have XBlock label `1` and two have XBlock label `0`:

- `0x5158cf97c3e001b402ccb0f9063736ee8d6dad5a`
- `0xd361e374be9e3907fceac60c6ea5cbdce89fc9ae`

These are recorded as source disagreements. Neither source automatically
overrides the other; no cross-source label merge or training exclusion has been
published. The report retains the matching original Unica line numbers/names.

## Reproduce the local checks

From the repository root, run:

```bash
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage sources
```

This performs no network requests. It verifies every frozen file checksum and
size, archive/extracted byte identity, source versions, CSV structure, row
counts, duplicates/conflicts and the existing label importer's mapping. It
recreates only the derived inspection files. It does not alter source bytes or
start collection/training.

## Subsequent protocol adoption

The source-verification stage itself did not create a cohort, query Etherscan
or fit a model. The user subsequently adopted the separate
[Ponzi offline pipeline](PONZI_OFFLINE_PIPELINE.md): 247 conflict-free merged
positives plus 1,000 deterministic XBlock negatives, with source-specific
2017-05-07 / 2018-11-22 UTC end-of-day reconstruction anchors and bounded
descending graphs. Those anchors are experiment conventions, not new source
facts about per-contract observation times. The original files and this audit's
counts remain unchanged.
