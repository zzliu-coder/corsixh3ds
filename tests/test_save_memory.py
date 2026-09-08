"""Real pinned native writer/reader: format equivalence and limited allocations."""
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest
from support.pinned_upstream import generated_sources, original_sources
from test_playable_path import function_body
from test_entity_index import index_script

ROOT=Path(__file__).resolve().parents[1]

def native_inputs():
    compiler=os.environ.get('CXX') or shutil.which('clang++') or shutil.which('c++')
    if not compiler:raise RuntimeError('C++ compiler required for native save tests')
    include=os.environ.get('CTH3DS_LUA_INCLUDE')
    library=os.environ.get('CTH3DS_LUA_LIBRARY')
    if include and library:return shlex.split(compiler),['-I'+include],[library]
    pkg=next((p for p in ('lua5.4','lua-5.4','lua') if subprocess.run(
        ['pkg-config','--exists',p],check=False).returncode==0),None)
    if not pkg:raise RuntimeError('Lua development package required for native save tests')
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags',pkg],text=True))
    links=shlex.split(subprocess.check_output(['pkg-config','--libs',pkg],text=True))
    return shlex.split(compiler),flags,links

class SaveMemoryTests(unittest.TestCase):
    def test_varint_boundaries_same_bytes_without_temporary_allocations(self):
        compiler,flags,_=native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-varint-') as name:
            directory=Path(name)
            generated=generated_sources(directory)
            reference=original_sources(directory/'reference')
            outputs=[];counts=[]
            for label,tree in [('reference',reference),('candidate',generated)]:
                src=tree/'CorsixTH/Src';(src/'config.h').write_text('#pragma once\n')
                binary=directory/label
                if label=='reference':binary=directory/'reference-probe'
                subprocess.run([*compiler,'-std=c++17','-O2','-fsanitize=address,undefined',
                    '-I'+str(src),*flags,
                    str(ROOT/'tests/runtime_support/varint_probe.cpp'),'-o',str(binary)],check=True)
                result=subprocess.run([str(binary)],capture_output=True,
                    env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
                self.assertEqual(result.returncode,0,result.stderr)
                outputs.append(result.stdout)
                counts.append(int(result.stderr.decode().strip().split('=')[-1]))
            self.assertEqual(outputs[0],outputs[1])
            self.assertGreater(counts[0],6000)
            self.assertEqual(counts[1],0)
            print('PASS varint 8/16/32/64 boundaries, int zigzag, identical bytes; allocations %s -> 0'%counts[0])

    def test_actual_native_serializer_compatibility_and_fragmented_budget(self):
        compiler,flags,links=native_inputs()
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
            closure.write_text('function make_closure(value)\n  return --[[persistable:SaveMemoryClosure]] function() return value.answer end\nend\n'
                'function make_tick_callback()\n return --[[persistable:R63FutureTick]] function(e) e.completed=(e.completed or 0)+1 end\nend\n')
            index_probe=directory/'index.lua'
            index_probe.write_text(index_script(original,generated))
            binary=directory/'probe'
            result=subprocess.run([*compiler,'-std=c++17','-O2','-g','-fsanitize=address,undefined',
                '-fno-omit-frame-pointer','-I'+str(src),'-I'+str(ROOT/'include'),*flags,
                str(target),*links,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary),str(closure),str(index_probe),str(ROOT/'lua/3ds/state_health.lua'),
                str(ROOT/'tests/fixtures/entity_tick.lua.pinned')],capture_output=True,text=True,timeout=90,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS native save compatibility',result.stdout)
            print(result.stdout,end='')
