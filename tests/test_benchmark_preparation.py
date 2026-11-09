"""Source patch contracts: preserve author checkout, apply baseline then variant.

The fixture patches explicitly specify old->normal->broken content. Expected
strings come from those patch hunks, independently of the preparation code.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.build_variant import prepare


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.git('init', '-q')
        (self.source / 'page.txt').write_text('old\n')
        self.git('add', 'page.txt')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                 'commit', '-q', '-m', 'fixture')
        revision = self.git('rev-parse', 'HEAD').strip()
        self.app = {'id': 'fixture', 'split': 'development', 'revision': revision}
        (self.root / 'baselines').mkdir()
        (self.root / 'mutations/fixture').mkdir(parents=True)
        (self.root / 'baselines/fixture.patch').write_text(
            '--- a/page.txt\n+++ b/page.txt\n@@ -1 +1 @@\n-old\n+normal\n')
        (self.root / 'mutations/fixture/small.patch').write_text(
            '--- a/page.txt\n+++ b/page.txt\n@@ -1 +1 @@\n-normal\n+broken\n')
        (self.source / 'page.txt').write_text('author local edit\n')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.source), *args], text=True)

    def test_baseline_then_variant_and_author_edits_preserved(self):
        destination = self.root / 'build'
        with patch('benchmark.build_variant.ROOT', self.root):
            result = prepare(self.app, 'small', self.source, destination)
        self.assertEqual((destination / 'page.txt').read_text(), 'broken\n')
        self.assertEqual((self.source / 'page.txt').read_text(), 'author local edit\n')
        self.assertEqual([p['path'] for p in result['patches']],
                         ['baselines/fixture.patch', 'mutations/fixture/small.patch'])
        self.assertEqual(json.loads((destination / 'stepmeter-build.json').read_text()), result)

    def test_existing_destination_is_never_overwritten(self):
        destination = self.root / 'build'
        destination.mkdir()
        sentinel = destination / 'keep.txt'
        sentinel.write_text('keep')
        with patch('benchmark.build_variant.ROOT', self.root), self.assertRaises(ValueError):
            prepare(self.app, 'small', self.source, destination)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_public_preparation_rejects_holdout_before_reading_source(self):
        with self.assertRaises(ValueError):
            prepare({**self.app, 'split': 'holdout'}, 'baseline',
                    self.root / 'nonexistent-private-source', self.root / 'build')

    def test_missing_mutation_fails_before_creating_destination(self):
        destination = self.root / 'build'
        with patch('benchmark.build_variant.ROOT', self.root), self.assertRaises(ValueError):
            prepare(self.app, 'overlay', self.source, destination)
        self.assertFalse(destination.exists())
