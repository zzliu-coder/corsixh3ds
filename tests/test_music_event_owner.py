"""Compile and exercise the actual cross-thread completion identity owner."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MusicEventOwnerTests(unittest.TestCase):
    def test_real_generated_adapters_are_repeatable_and_drift_checked(self):
        from test_playable_path import generated_sources
        from integration.music_events import transforms
        from sound_lifetime import SoundPatchError
        with tempfile.TemporaryDirectory(prefix='cth-music-generated-') as directory:
            generated = generated_sources(Path(directory))
            current = dict(transforms(generated))
            for name, value in current.items():
                self.assertEqual((generated / name).read_text(), value)
            core = generated / 'CorsixTH/Src/sdl_core.cpp'
            core.write_text(core.read_text().replace(
                'music_event_owner.consume(e.user.code)',
                'music_event_owner.consume(0)', 1))
            with self.assertRaisesRegex(SoundPatchError, 'source drift'):
                dict(transforms(generated))

    def test_native_completion_identity_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='cth-music-owner-') as directory:
            directory = Path(directory)
            other = directory / 'other.cpp'
            other.write_text('#include "cth3ds/music_event_owner.hpp"\n'
                'cth3ds::MusicEventOwner* other_translation_unit_owner() {\n'
                ' return &cth3ds::music_event_owner;\n}\n')
            binary = directory / 'probe'
            compiler = shlex.split(os.environ.get('CXX', 'c++'))
            build = subprocess.run([*compiler, '-std=c++17', '-O2', '-g',
                '-Wall', '-Wextra', '-Wconversion', '-Wsign-conversion', '-Werror',
                '-pthread', '-fsanitize=address,undefined',
                '-I' + str(ROOT / 'include'),
                str(ROOT / 'tests/runtime_support/music_event_owner_probe.cpp'),
                str(other), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True,
                timeout=30, env=dict(os.environ,
                    ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                    UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(run.stdout.count('PASS '), 6, run.stdout)
            print(run.stdout, end='')


if __name__ == '__main__':
    unittest.main()
