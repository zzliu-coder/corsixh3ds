"""Real pinned native writer/reader: format equivalence and limited allocations."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from support.pinned_upstream import generated_sources, original_sources
from test_playable_path import function_body

ROOT=Path(__file__).resolve().parents[1]

class SaveMemoryTests(unittest.TestCase):
    def test_actual_native_serializer_compatibility_and_fragmented_budget(self):
        with tempfile.TemporaryDirectory(prefix='cth-save-memory-') as name:
            directory=Path(name)
            generated=generated_sources(directory)
            original=original_sources(directory/'reference')
            src=generated/'CorsixTH/Src'
            (src/'config.h').write_text('#pragma once\n')
            helpers=(src/'th_lua.cpp').read_text()
            bodies='\n'.join(function_body(helpers,s) for s in (
                'void luaT_getfenv52(', 'int luaT_setfenv52(', 'const uint8_t* luaT_checkfile('))
            code=(ROOT/'tests/runtime_support/save_memory_probe.cpp').read_text().replace('// INSERT_COMPAT',bodies)
            for label,tree in [('REFERENCE',original),('CANDIDATE',generated)]:
                source=(tree/'CorsixTH/Src/persist_lua.cpp').read_text()
                code=code.replace('// INSERT_'+label,source[source.index('namespace {'):])
            target=directory/'probe.cpp';target.write_text(code)
            closure=directory/'closure.lua'
            closure.write_text('function make_closure(value)\n  return --[[persistable:SaveMemoryClosure]] function() return value.answer end\nend\n')
            include=os.environ.get('CTH3DS_LUA_INCLUDE','/opt/homebrew/include/lua')
            library=os.environ.get('CTH3DS_LUA_LIBRARY','/opt/homebrew/lib/liblua.dylib')
            binary=directory/'probe'
            result=subprocess.run(['clang++','-std=c++17','-O2','-g','-fsanitize=address,undefined',
                '-fno-omit-frame-pointer','-I'+str(src),'-I'+str(ROOT/'include'),'-I'+include,
                str(target),library,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary),str(closure)],capture_output=True,text=True,timeout=90,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS native save compatibility',result.stdout)
            print(result.stdout,end='')
