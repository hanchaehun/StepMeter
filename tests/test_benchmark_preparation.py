"""Source patch contracts: preserve author checkout, apply baseline then variant.

The fixture patches explicitly specify old->normal->broken content. Expected
strings come from those patch hunks, independently of the preparation code.
"""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import build_variant, serve_variants
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

    def test_manifest_patch_paths_have_no_backslash(self):
        """ADR 0010 #7: stepmeter-build.json records patch paths with as_posix() on every OS."""
        destination = self.root / 'build'
        with patch('benchmark.build_variant.ROOT', self.root):
            prepare(self.app, 'small', self.source, destination)
        manifest = json.loads((destination / 'stepmeter-build.json').read_text(encoding='utf-8'))
        paths = [p['path'] for p in manifest['patches']]
        self.assertEqual(paths, ['baselines/fixture.patch', 'mutations/fixture/small.patch'])
        for path in paths:
            self.assertNotIn('\\', path)

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


class BuildCommandTests(unittest.TestCase):
    """--build starts npm/npx through the Windows launcher lookup shared with serve_variants.

    Expected executables are a platform fact, not read from the code: Windows ships
    npm and npx as .cmd batch files, and a bare 'npm' cannot be started there
    (FileNotFoundError, WinError 2).
    """

    def run_build_on_windows(self, app_id):
        ran = []

        def windows_resolve(command):
            return serve_variants.resolve_command(command, os_name='nt', which=lambda name: f'C:/tools/{name}')

        with patch('benchmark.build_variant.prepare', return_value={}), \
                patch('benchmark.build_variant.resolve_command', windows_resolve), \
                patch('benchmark.build_variant.subprocess.run', lambda command, **_kwargs: ran.append(command)), \
                patch('sys.argv', ['build_variant', app_id, 'baseline', '--build']), \
                contextlib.redirect_stdout(io.StringIO()):
            build_variant.main()
        return ran

    def test_npm_build_uses_cmd_launcher_on_windows(self):
        ran = self.run_build_on_windows('material-kit-react')
        self.assertTrue(ran)
        self.assertEqual({command[0] for command in ran}, {'C:/tools/npm.cmd'})

    def test_npx_build_uses_cmd_launcher_on_windows(self):
        ran = self.run_build_on_windows('shadcn-admin')
        self.assertTrue(ran)
        self.assertEqual({command[0] for command in ran}, {'C:/tools/npx.cmd'})
