"""Deploy the prepared inference service on Modal

Run from the repository root after preparing deploy/.build/modal:
    .venv/bin/python -m modal deploy deploy/modal_app.py
"""
from pathlib import Path
import json
import os

import modal

HERE = Path(__file__).resolve().parent
REMOTE_ROOT = '/srv/chainrisk'
REQUIRED_FILES = ('app.py', 'runtime.py', 'policies.py', 'requirements.txt',
                  'models.json', 'risk_policies.json', 'forecast_policy.json')
ALLOWED_ENTRIES = {*REQUIRED_FILES, 'README.md', 'DEPLOYMENT.md', 'MODAL.md', 'packages', 'bundles', '__pycache__'}


def prepared_directory(value):
    """Only upload a prepared package, never a checkout or credentials folder."""
    directory = Path(value).expanduser().resolve()
    if not directory.is_dir() or any(not (directory / name).is_file() for name in REQUIRED_FILES):
        raise ValueError('Prepare the service first with prepare.py --output deploy/.build/modal')
    unexpected = {path.name for path in directory.iterdir()} - ALLOWED_ENTRIES
    if unexpected:
        raise ValueError(f'Unexpected files in deployment package: {sorted(unexpected)}')
    tasks = json.loads((directory / 'models.json').read_text())['tasks']
    if not tasks or set(tasks) - {'phishing', 'ponzi', 'honeypot', 'rug_pull', 'continued_activity'}:
        raise ValueError('The prepared package has no supported model tasks')
    for task, relative in tasks.items():
        bundle = (directory / relative).resolve()
        if not bundle.is_relative_to(directory / 'bundles') or not (bundle / 'manifest.json').is_file():
            raise ValueError(f'Bundle for {task} must be inside the prepared bundles/ directory')
    for path in directory.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(directory):
            raise ValueError('Deployment packages cannot link to files outside the package')
    return directory


def create_modal_app(package_dir=None, gpu=None):
    directory = prepared_directory(package_dir or os.getenv('MODAL_PACKAGE_DIR') or HERE / '.build/modal')
    device = (gpu or os.getenv('MODAL_GPU', 'CPU')).upper()
    if device not in ('CPU', 'T4', 'L4'):
        raise ValueError('MODAL_GPU must be CPU, T4 or L4')
    image = modal.Image.debian_slim(python_version='3.11')
    if device == 'CPU':
        image = image.pip_install('torch==2.14.1', index_url='https://download.pytorch.org/whl/cpu')
    image = (image
             .pip_install_from_requirements(str(directory / 'requirements.txt'))
             .add_local_dir(directory, remote_path=REMOTE_ROOT, copy=True,
                            ignore=['**/__pycache__/**', '**/*.pyc'])
             .env({'INFERENCE_DEVICE': 'cpu' if device == 'CPU' else 'cuda',
                   'PORT': '7860', 'GRADIO_ANALYTICS_ENABLED': 'False',
                   'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}))
    application = modal.App('chainrisk-inference', include_source=False)

    @application.function(name='serve', image=image, gpu=None if device == 'CPU' else device,
                          cpu=1, memory=4096, min_containers=0, max_containers=1,
                          buffer_containers=0, scaledown_window=30, timeout=180,
                          secrets=[modal.Secret.from_name('chainrisk-inference', required_keys=['INFERENCE_API_KEY'])],
                          serialized=True, include_source=False)
    @modal.concurrent(max_inputs=8)
    @modal.web_server(7860, startup_timeout=180)
    def serve():
        import os
        import subprocess
        import sys

        if not os.environ.get('INFERENCE_API_KEY', '').strip():
            raise RuntimeError('Set INFERENCE_API_KEY in the chainrisk-inference Modal Secret')
        subprocess.Popen([sys.executable, '/srv/chainrisk/app.py'], cwd='/srv/chainrisk')

    return application, serve


app, serve = create_modal_app()
