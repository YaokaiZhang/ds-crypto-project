"""Release cache reuse, version pinning and archive-boundary checks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from deploy.fetch_release import fetch


class ReleaseChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'downloads'
        self.cache.mkdir()
        self.asset = 'chainrisk-phishing-test.zip'
        self.bundle = self.asset[:-4]
        self.release = self.root / 'release.json'
        self.release.write_text(json.dumps({'repository':'example/models','tag':'Models',
            'bundles':{'phishing':{'asset':self.asset,'model_version':'phishing-test'}}}))
        files = {'manifest.json':json.dumps({'task_id':'phishing','model_version':'phishing-test'}).encode(),
                 'scaler.json':b'{}', 'model.pt':b'fixture-weights'}
        with zipfile.ZipFile(self.cache / self.asset, 'w') as archive:
            for name, data in files.items():
                archive.writestr(self.bundle + '/' + name, data)
            archive.writestr(self.bundle + '/SHA256SUMS', ''.join(
                f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in files.items()))
        self.hash_archive()

    def hash_archive(self):
        digest = hashlib.sha256((self.cache / self.asset).read_bytes()).hexdigest()
        (self.cache / 'SHA256SUMS').write_text(f'{digest}  {self.asset}\n')

    def test_reuses_cached_downloads_and_requires_matching_version(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected download')):
            tasks = fetch(self.release, self.root / 'models', self.cache)
            self.assertEqual(tasks, {'phishing':self.bundle})
            self.assertEqual(json.loads((self.root/'models/models.json').read_text()), {'tasks':tasks})
            with self.assertRaises(FileExistsError):
                fetch(self.release, self.root / 'models', self.cache)
            content = json.loads(self.release.read_text())
            content['bundles']['phishing']['model_version'] = 'wrong'
            self.release.write_text(json.dumps(content))
            with self.assertRaises(ValueError):
                fetch(self.release, self.root / 'wrong-version', self.cache)

    def test_corrupt_cache_fails_before_extraction(self):
        with (self.cache / self.asset).open('ab') as handle:
            handle.write(b'corrupt')
        with self.assertRaises(ValueError):
            fetch(self.release, self.root / 'models', self.cache)
        self.assertFalse((self.root / 'models' / self.bundle).exists())

    def test_archive_cannot_write_outside_bundle(self):
        with zipfile.ZipFile(self.cache / self.asset, 'a') as archive:
            archive.writestr(self.bundle + '/../escape', b'unsafe')
        self.hash_archive()
        with self.assertRaises(ValueError):
            fetch(self.release, self.root / 'models', self.cache)
        self.assertFalse((self.root / 'models/escape').exists())
