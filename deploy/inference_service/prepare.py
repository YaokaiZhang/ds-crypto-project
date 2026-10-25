"""Prepare an allowlisted, self-contained Space folder; never upload anything."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

try:
    from .runtime import InferenceRuntime, read_config
except ImportError:
    from runtime import InferenceRuntime, read_config

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE_FILES = ('__init__.py', 'bundle.py', 'forecast.py', 'graph.py', 'models.py', 'tasks.py', 'token.py', 'transactions.py')


def bundle_files(directory, task):
    if task != 'continued_activity':
        return ('manifest.json', 'scaler.json', 'model.pt')
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    return ('manifest.json', 'scaler.json', *(member['weights_file'] for member in manifest['members']))


def prepare(output, config, tasks=None):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Use a new output directory; existing files are never overwritten')
    paths = read_config(config)
    selected = list(tasks) if tasks else list(paths)
    if not selected or len(selected) != len(set(selected)) or set(selected) - paths.keys():
        raise ValueError('Select unique tasks present in the model config')
    # Validate before copying, including weights, scalers and display policies.
    InferenceRuntime(config, tasks=selected,
                     risk_policy_path=HERE.parent / 'registry/risk_policies.json')
    output.mkdir(parents=True)
    for filename in ('app.py', 'runtime.py', 'policies.py', 'requirements.txt', 'README.md'):
        shutil.copy2(HERE / filename, output / filename)
    shutil.copy2(HERE.parent / 'README.md', output / 'DEPLOYMENT.md')
    (output / 'packages').mkdir()
    for filename in PACKAGE_FILES:
        shutil.copy2(ROOT / 'packages' / filename, output / 'packages' / filename)
    config_out = {'tasks': {task: f'bundles/{task}' for task in selected}}
    for task in selected:
        destination = output / 'bundles' / task
        destination.mkdir(parents=True)
        for filename in bundle_files(paths[task], task):
            shutil.copy2(paths[task] / filename, destination / filename)
    (output / 'models.json').write_text(json.dumps(config_out, indent=2) + '\n')
    shutil.copy2(HERE.parent / 'registry/risk_policies.json', output / 'risk_policies.json')
    shutil.copy2(HERE.parent / 'registry/forecast_policy.json', output / 'forecast_policy.json')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=HERE / 'models.json')
    parser.add_argument('--tasks', nargs='+', choices=('phishing', 'ponzi', 'honeypot', 'rug_pull', 'continued_activity'))
    args = parser.parse_args()
    print(prepare(args.output, args.config, args.tasks))


if __name__ == '__main__':
    main()
