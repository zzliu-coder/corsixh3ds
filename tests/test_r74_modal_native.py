"""Native save/load of constructed UI graphs, with real strict/classes/guards.

Window/UI/Watch/Annual/Button initialization, persistence registry and afterLoad
are real. Graphics, audio, hospital money services and World are host fixtures;
this does not load a complete saved hospital or establish device acceptance.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zlib

from test_playable_path import function_body
from test_save_memory import native_inputs

ROOT = Path(__file__).resolve().parents[1]


class ModalNativeTests(unittest.TestCase):
    def test_construct_native_restore_afterload_and_exact_guard(self):
        with tempfile.TemporaryDirectory(prefix='cth-r74-modal-') as name:
            work = Path(name)
            # Reuse an existing assembly when provided, including local builds.
            generated = Path(os.environ.get('CTH3DS_CAPACITY_GENERATED', ROOT/'external/CorsixTH'))
            if not (generated/'CorsixTH/Src/persist_lua.cpp').is_file():
                from support.pinned_upstream import generated_sources
                generated = generated_sources(work/'generated')
            src = generated/'CorsixTH/Src'
            helpers = (src/'th_lua.cpp').read_text()
            compat = '\n'.join(function_body(helpers, signature) for signature in (
                'void luaT_getfenv52(', 'int luaT_setfenv52(', 'const uint8_t* luaT_checkfile('))
            code = '#include "lua.hpp"\n#include "th_lua.h"\n#include "persist_lua.h"\n'
            code += compat + '\n' + (src/'persist_lua.cpp').read_text() + r'''
int main(int argc, char** argv) {
  assert(argc == 2);
  lua_State* L = luaL_newstate(); luaL_openlibs(L);
  lua_pushglobaltable(L); lua_pushcclosure(L, luaopen_persist, 1);
  lua_call(L, 0, 1); lua_setglobal(L, "P");
  int status = luaL_dofile(L, argv[1]);
  if(status) std::fprintf(stderr, "%s\n", lua_tostring(L, -1));
  lua_close(L); return status ? 1 : 0;
}
'''
            (work/'probe.cpp').write_text(code)
            (work/'config.h').write_text('#pragma once\n')
            compiler, flags, links = native_inputs()
            build = subprocess.run([*compiler, '-std=c++17', '-O1', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                '-I'+str(work), '-I'+str(src), '-I'+str(ROOT/'include'), *flags,
                str(work/'probe.cpp'), *links, '-o', str(work/'probe')],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout+build.stderr)

            fixture = json.loads((ROOT/'tests/fixtures/annual_upstream.json').read_text())
            sources = json.loads(zlib.decompress(base64.b64decode(fixture['sources_zlib_base64'])))
            # Unmodified source from the same fixed upstream commit. Retain it
            # independently so CI needs neither a download nor a complete tree.
            machine = (ROOT/'tests/fixtures/machine_dialog.lua.pinned').read_text()
            machine_sha = '25c4c28900cbfec1f5a81a5cf1bf0bc1ff0a2d1824c9cb460aab18b3b9f5d475'
            self.assertEqual(hashlib.sha256(machine.encode()).hexdigest(), machine_sha)
            sources['dialogs/machine_dialog.lua'] = machine
            fixture['sha256']['dialogs/machine_dialog.lua'] = machine_sha
            paths = {}
            for filename, source in sources.items():
                self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), fixture['sha256'][filename])
                path = generated/'CorsixTH/Lua'/filename
                if not path.is_file():
                    path = work/'lua'/filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source)
                paths[filename] = path
            strict = generated/'CorsixTH/Lua/strict.lua'
            if not strict.is_file():
                strict = ROOT/'tests/fixtures/strict.lua.pinned'
            # Keep the complete actual registry implementation, saved_permanents
            # and permanent(), including native persistable closure processing.
            persistence = (generated/'CorsixTH/Lua/persistance.lua').read_text()
            registry = work/'registry.lua'
            registry.write_text(persistence[:persistence.index('local function NameOf(')]
                                + '\nreturn MakePermanentObjectsTable\n')
            prelude = 'local product=' + repr(str(ROOT)) + '\n'
            prelude += 'local source={\n' + ''.join(
                '['+repr(k)+']='+repr(str(v))+',\n' for k, v in paths.items()) + '}\n'
            prelude += 'local strict='+repr(str(strict))+'\nlocal registry='+repr(str(registry))+'\n'
            script = work/'cases.lua'
            script.write_text(prelude+(ROOT/'tests/runtime_support/modal_roundtrip_cases.lua').read_text())
            run = subprocess.run([str(work/'probe'), str(script)], capture_output=True,
                text=True, timeout=30, env=dict(os.environ,
                    ASAN_OPTIONS='detect_leaks=0:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            for marker in ('PASS strict initialization', 'PASS native restored countdowns',
                           'PASS native annual and Button confirmation',
                           'PASS native refusal boundaries', 'PASS current owned window identity'):
                self.assertIn(marker, run.stdout)
            self.assertIn('PASS restored machine information and native diagnostics', run.stdout)
            print(run.stdout, end='')


if __name__ == '__main__':
    unittest.main()
