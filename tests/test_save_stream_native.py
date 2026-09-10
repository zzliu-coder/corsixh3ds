"""Actual generated writer, standard FILE handles and bounded-output probes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support.pinned_upstream import generated_sources, original_sources
from test_playable_path import function_body
from test_save_memory import native_inputs

ROOT = Path(__file__).resolve().parents[1]


def build_stream_probe(directory):
    """Build actual readers/writer once; optional argv[3:] are extra Lua cases.

    Returns (binary, closure_file, generated_upstream). Additional scripts see
    reference/candidate modules and package.loaded.persist == candidate.
    """
    compiler, flags, links = native_inputs()
    generated = generated_sources(directory)
    reference = original_sources(directory/'reference')
    src = generated/'CorsixTH/Src'
    (src/'config.h').write_text('#pragma once\n')
    helpers = (src/'th_lua.cpp').read_text()
    bodies = '\n'.join(function_body(helpers, signature) for signature in (
        'void luaT_getfenv52(', 'int luaT_setfenv52(', 'const uint8_t* luaT_checkfile('))
    code = (ROOT/'tests/runtime_support/save_stream_probe.cpp').read_text()
    code = code.replace('// INSERT_COMPAT', bodies)
    for label, tree in [('REFERENCE', reference), ('CANDIDATE', generated)]:
        source = (tree/'CorsixTH/Src/persist_lua.cpp').read_text()
        code = code.replace('// INSERT_'+label, source[source.index('namespace {'):])
    target = directory/'probe.cpp'
    target.write_text(code)
    closure = directory/'closure.lua'
    closure.write_text('function make_closure(value)\n'
        ' return --[[persistable:StreamClosure]] function() return value.answer end\nend\n')
    binary = directory/'probe'
    result = subprocess.run([*compiler, '-std=c++17', '-O2', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I'+str(src), '-I'+str(ROOT/'include'), *flags, str(target),
        str(ROOT/'src/common/atomic_save.cpp'), *links, '-o', str(binary)],
        capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout+result.stderr)
    return binary, closure, generated


class SaveStreamNativeTests(unittest.TestCase):
    def test_actual_file_writer_formats_failures_and_peak(self):
        with tempfile.TemporaryDirectory(prefix='cth-save-stream-') as name:
            directory = Path(name)
            binary, closure, generated = build_stream_probe(directory)
            result = subprocess.run([str(binary), str(closure), str(directory)],
                capture_output=True, text=True, timeout=90,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                         UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            for marker in ('PASS format cross-read', 'PASS native block boundaries',
                           'PASS clock contract',
                           'PASS real FILE failures', 'PASS output memory bound',
                           'PASS failed writer GC and retry'):
                self.assertIn(marker, result.stdout)
            print(result.stdout, end='')

    def test_actual_generated_lua_file_transaction_and_reload(self):
        with tempfile.TemporaryDirectory(prefix='cth-save-stream-glue-') as name:
            directory = Path(name)
            binary, closure, generated = build_stream_probe(directory)
            source = (ROOT/'tests/sound_lifetime_support/native_persistence_cases.lua').read_text()
            source = source.replace('"flush_observations",', '"operation_boundary", "flush_observations",', 1)
            begin = source.index('function native.atomic_commit(')
            end = source.index('\nend', begin)+4
            source = (source[:begin] + 'function native.atomic_commit(temporary, final)\n'
                      '  return host_atomic_commit(temporary, final)\nend' + source[end:])
            extra = (ROOT/'tests/runtime_support/save_stream_glue_cases.lua').read_text()
            anchor = 'assert(prepared == cleaned)'
            self.assertEqual(source.count(anchor), 1)
            script = directory/'full-glue.lua'
            script.write_text(source.replace(anchor, extra+'\n'+anchor))
            result = subprocess.run([str(binary), str(closure), str(directory), str(script)],
                capture_output=True, text=True, timeout=90,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                    UBSAN_OPTIONS='halt_on_error=1', CTH3DS_PERSIST_TESTDIR=str(directory),
                    CTH3DS_PERSIST_SOURCE=str(generated/'CorsixTH/Lua/persistance.lua'),
                    CTH3DS_PLATFORM_SOURCE=str(ROOT/'lua/3ds/platform.lua')))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('native_persistence_cases=', result.stdout)
            self.assertIn('save-stream: mode=stream16k', result.stdout)
            self.assertIn('PASS native-persistence stream-native-faults-preserve-final-and-backup', result.stdout)
            self.assertIn('PASS native-persistence original-reader-loads-streamed-world', result.stdout)
            for line in result.stdout.splitlines():
                if line.startswith(('PASS ', 'MEMORY ', 'native_persistence_cases=',
                                    'model_lua_kib_', 'device_and_native_map=')):
                    print(line)


if __name__ == '__main__':
    unittest.main()
