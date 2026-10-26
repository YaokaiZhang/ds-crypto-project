"""Declare the Modal app and exercise its launcher without any cloud calls."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / 'deploy'


@unittest.skipUnless(importlib.util.find_spec('modal'), 'Install Modal SDK for deployment checks')
class ModalDeploymentChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name) / 'package'
        self.package.mkdir()
        # Image declarations do not execute these files or load any model.
        for name in ('app.py', 'runtime.py', 'policies.py', 'requirements.txt'):
            (self.package / name).write_text('')
        for name in ('risk_policies.json', 'forecast_policy.json'):
            (self.package / name).write_text('{}')
        (self.package / 'packages').mkdir()
        (self.package / 'bundles/phishing').mkdir(parents=True)
        (self.package / 'bundles/phishing/manifest.json').write_text('{}')
        (self.package / 'models.json').write_text(json.dumps({'tasks': {'phishing': 'bundles/phishing'}}))
        with patch.dict(os.environ, {'MODAL_PACKAGE_DIR': str(self.package), 'MODAL_GPU': 'CPU'}):
            self.entry = runpy.run_path(str(ROOT / 'modal_app.py'))

    def test_sdk_app_declares_without_authentication_or_network(self):
        self.assertEqual(self.entry['app'].name, 'chainrisk-inference')
        self.assertTrue(callable(self.entry['serve'].local))
        self.assertEqual(self.entry['prepared_directory'](self.package), self.package.resolve())

    def test_refuses_extra_credentials_and_paths_outside_the_package(self):
        (self.package / '.modal.toml').write_text('not a real token')
        with self.assertRaises(ValueError):
            self.entry['prepared_directory'](self.package)
        (self.package / '.modal.toml').unlink()
        outside = Path(self.temp.name) / 'external'
        outside.mkdir()
        (outside / 'manifest.json').write_text('{}')
        (self.package / 'models.json').write_text(json.dumps({'tasks': {'phishing': '../external'}}))
        with self.assertRaises(ValueError):
            self.entry['prepared_directory'](self.package)

    def test_launcher_requires_key_and_starts_only_prepared_server(self):
        function = self.entry['serve'].local
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.Popen') as process:
            with self.assertRaises(RuntimeError):
                function()
            process.assert_not_called()
        with patch.dict(os.environ, {'INFERENCE_API_KEY': 'local-test-key'}), patch('subprocess.Popen') as process:
            function()
            self.assertEqual(process.call_args.args[0][1], '/srv/chainrisk/app.py')
            self.assertEqual(process.call_args.kwargs['cwd'], '/srv/chainrisk')

    def test_no_package_and_invalid_gpu_are_local_errors(self):
        with self.assertRaises(ValueError):
            self.entry['prepared_directory'](self.package / 'missing')
        with self.assertRaises(ValueError):
            self.entry['create_modal_app'](self.package, 'B300')
