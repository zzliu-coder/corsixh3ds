"""Runtime delta packaging uses the existing full-tree validator."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from make_sd_delta import make_delta, runtime_path
from validate_sd_tree import (ValidationError, sha256_path, validate_sd_tree,
                              write_boot_contract, write_sd_manifest)
import test_validate_sd_tree as fixture


class MakeSdDeltaTests(unittest.TestCase):
    def baseline(self, root):
        package = fixture.ValidateSdTreeTests().make_runtime(root)
        for name in ('DATA', 'LEVELS', 'QDATA', 'SOUND'):
            directory = package / 'game' / name; directory.mkdir(parents=True)
            (directory / 'synthetic.bin').write_bytes(b'private unchanged resource')
        for name in ('Lua/languages/english.lua', 'Lua/languages/original_strings.lua',
                     'game/DATA/LANG-0.DAT', 'game/SOUND/DATA/SOUND-0.DAT',
                     'Lua/3ds/platform.lua'):
            path = package / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic baseline')
        (package / 'loose-assets.json').write_text(json.dumps({'language': 'English', 'device': 'NOT_PROVEN'}))
        fixture.ValidateSdTreeTests().seal(package, 'loose')
        return package

    def replacements(self, root):
        binary = root / 'new.3dsx'; binary.write_bytes(fixture.valid_3dsx() + b'new code')
        lua = root / 'new.lua'; lua.write_text('-- new adapter\n')
        return {'CorsixTH-3DS.3dsx': binary, 'Lua/3ds/platform.lua': lua}

    def test_delta_reuses_assets_preserves_baseline_and_reconstructs_valid_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = self.baseline(root)
            before = {p.relative_to(baseline).as_posix(): sha256_path(p) for p in baseline.rglob('*') if p.is_file()}
            output = root / 'delta'
            result = make_delta(baseline, self.replacements(root), output, {'commit': '3'*40, 'tree': '4'*40})
            self.assertEqual(result['package_validation']['result'], 'PASS')
            self.assertEqual(len(result['files']), 4)
            self.assertEqual(result['files'][-1]['path'], 'CorsixTH-3DS.3dsx')
            self.assertEqual(result['device_acceptance'], 'NOT_PROVEN')
            self.assertFalse((output / 'files/game').exists())
            self.assertFalse((output / 'files/config.txt').exists())
            after = {p.relative_to(baseline).as_posix(): sha256_path(p) for p in baseline.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            reconstructed = root / 'reconstructed'; shutil.copytree(baseline, reconstructed)
            shutil.copytree(output / 'files', reconstructed, dirs_exist_ok=True)
            self.assertEqual(validate_sd_tree(reconstructed)['candidate']['commit'], '3'*40)
            self.assertFalse(list(root.glob('cth3ds-delta-*')))

    def test_delta_scope_excludes_assets_user_data_language_and_unsafe_paths(self):
        for path in ('game/DATA/x', 'config.txt', 'hotkeys.txt', 'Saves/x.sav',
                     'Lua/languages/chinese.lua', 'Lua/../config.txt', '/Lua/new.lua',
                     'Lua//new.lua', 'boot-contract.json', 'Lua/new.bin'):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                runtime_path(path)
        self.assertEqual(runtime_path('Lua/3ds/platform.lua'), 'Lua/3ds/platform.lua')

    def test_delta_rejects_stale_baseline_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = self.baseline(root); sources = self.replacements(root)
            output = root / 'existing'; output.mkdir(); (output / 'keep').write_text('keep')
            with self.assertRaisesRegex(ValidationError, 'already exists'):
                make_delta(baseline, sources, output, {'commit': '3'*40, 'tree': '4'*40})
            self.assertEqual((output / 'keep').read_text(), 'keep')
            (baseline / 'game/DATA/synthetic.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValidationError, 'identity mismatch'):
                make_delta(baseline, sources, root / 'delta', {'commit': '3'*40, 'tree': '4'*40})
            self.assertFalse((root / 'delta').exists())

    def test_delta_failure_preserves_source_and_does_not_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = self.baseline(root); sources = self.replacements(root)
            original = sha256_path(baseline / 'CorsixTH-3DS.3dsx')
            sources['CorsixTH-3DS.3dsx'].write_bytes(b'not a compiled binary')
            with self.assertRaisesRegex(ValidationError, 'not a 3DSX'):
                make_delta(baseline, sources, root / 'delta', {'commit': '3'*40, 'tree': '4'*40})
            self.assertFalse((root / 'delta').exists())
            self.assertFalse(list(root.glob('cth3ds-delta-*')))
            self.assertEqual(sha256_path(baseline / 'CorsixTH-3DS.3dsx'), original)
            self.assertEqual(validate_sd_tree(baseline)['result'], 'PASS')
