"""Download, verify and extract the pinned model bundles listed in deploy/release.json.

Standard library only. Every ZIP is checked against the Release's SHA256SUMS
before extraction, and every extracted file against the bundle's own
SHA256SUMS. Writes <output>/models.json for inference_service/prepare.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def read_sums(path: Path) -> dict[str, str]:
    sums = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            sums[name.lstrip('*')] = digest
    return sums


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, target.open('wb') as handle:
        while block := response.read(1 << 20):
            handle.write(block)


def fetch(release_path: Path, output: Path) -> dict:
    release = json.loads(release_path.read_text(encoding='utf-8'))
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f'{output} exists; use a new directory')
    downloads = output / 'downloads'
    downloads.mkdir(parents=True)
    base = f"https://github.com/{release['repository']}/releases/download/{release['tag']}"
    download(f'{base}/SHA256SUMS', downloads / 'SHA256SUMS')
    sums = read_sums(downloads / 'SHA256SUMS')
    tasks = {}
    for task, entry in release['bundles'].items():
        asset = entry['asset']
        if asset not in sums:
            raise ValueError(f'{asset} is not listed in the Release SHA256SUMS')
        download(f'{base}/{asset}', downloads / asset)
        if sha256(downloads / asset) != sums[asset]:
            raise ValueError(f'checksum mismatch for {asset}')
        bundle = asset.removesuffix('.zip')
        with zipfile.ZipFile(downloads / asset) as archive:
            if any(not name.startswith(bundle + '/') or '..' in Path(name).parts for name in archive.namelist()):
                raise ValueError(f'{asset} has entries outside {bundle}/')
            archive.extractall(output)
        for name, digest in read_sums(output / bundle / 'SHA256SUMS').items():
            if sha256(output / bundle / name) != digest:
                raise ValueError(f'checksum mismatch for {bundle}/{name}')
        manifest = json.loads((output / bundle / 'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('model_version') != entry['model_version']:
            raise ValueError(f"{bundle} model_version {manifest.get('model_version')} != {entry['model_version']}")
        tasks[task] = bundle
        print(f'verified {asset} ({entry["model_version"]})', flush=True)
    (output / 'models.json').write_text(json.dumps({'tasks': tasks}, indent=2) + '\n', encoding='utf-8')
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release', type=Path, default=HERE / 'release.json')
    args = parser.parse_args()
    fetch(args.release, args.output)


if __name__ == '__main__':
    main()
