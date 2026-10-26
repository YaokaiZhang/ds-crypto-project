"""Atomic caches must work on Windows without sharing/deletion violations."""
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packages.io import atomic_bytes, compress_file
from apps.backend.app.adapters.feed_store import FeedStore


class AtomicFileChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_immutable_cache_publishes_once_and_leaves_no_temporary_files(self):
        target=self.root/'cache.json'
        self.assertTrue(atomic_bytes(target,b'first',immutable=True))
        self.assertFalse(atomic_bytes(target,b'second',immutable=True))
        self.assertEqual(target.read_bytes(),b'first')
        self.assertEqual(list(self.root.glob('.publish-*')),[])

    def test_mutable_file_can_replace_existing_content(self):
        target=self.root/'state.json'
        self.assertTrue(atomic_bytes(target,b'first'))
        self.assertTrue(atomic_bytes(target,b'second'))
        self.assertEqual(target.read_bytes(),b'second')
        self.assertEqual(list(self.root.glob('.publish-*')),[])

    def test_failed_publication_keeps_old_data_and_cleans_up(self):
        target=self.root/'state.json';target.write_bytes(b'old')
        with patch('packages.io.os.replace',side_effect=OSError('simulated publication failure')):
            with self.assertRaisesRegex(OSError,'publication failure'):
                atomic_bytes(target,b'new')
        self.assertEqual(target.read_bytes(),b'old')
        self.assertEqual(list(self.root.glob('.publish-*')),[])

    def test_gzip_publication_preserves_original_and_is_repeatable(self):
        source=self.root/'input.jsonl';source.write_bytes(b'{"observation":1}\n'*100)
        target=self.root/'input.jsonl.gz'
        compress_file(source,target);first=target.read_bytes()
        self.assertEqual(gzip.decompress(first),source.read_bytes())
        compress_file(source,target)
        self.assertEqual(target.read_bytes(),first)
        self.assertEqual(list(self.root.glob('.compress-*')),[])

    def test_feed_ownership_is_exclusive_and_released_on_close(self):
        path=str(self.root/'feed.sqlite3')
        first=FeedStore(path);second=FeedStore(path)
        try:
            first.acquire()
            with self.assertRaises(RuntimeError):first.acquire()
            with self.assertRaises(RuntimeError):second.acquire()
            first.close();second.acquire()
            self.assertIsNotNone(second.owner)
        finally:
            if first.owner is not None:first.close()
            second.close()
