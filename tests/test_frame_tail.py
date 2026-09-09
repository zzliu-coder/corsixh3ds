"""Actual bounded owner, Lua mark/request, native flush and generated GC/wait."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from support.pinned_upstream import generated_sources
from test_playable_path import function_body
from test_save_memory import native_inputs

ROOT=Path(__file__).resolve().parents[1]

class FrameTailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r69-tail-')
        cls.addClassCleanup(cls.temp.cleanup)
        directory=Path(cls.temp.name)
        generated=generated_sources(directory)
        text=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        methods='\n'.join(function_body(text,name) for name in (
            'void seal_observation_tail(', 'void reset_runtime_observations(',
            'int l_shutdown(', 'int l_request_observation_flush(', 'int l_benchmark_mark(',
            'void runtime_flush_observations(', 'FrameTail::Token runtime_phase_begin(',
            'void runtime_phase_end(', 'void runtime_frame_skipped(', 'void runtime_shutdown('))
        shutdown=function_body(text,'  void shutdown() noexcept {')
        shutdown_prefix=shutdown.split('{',1)[1].split('    reset_benchmark_activation();',1)[0]
        loop=(generated/'CorsixTH/Src/sdl_core.cpp').read_text()
        wait=loop[loop.index('  auto u3_wait ='):loop.index('  while ((wait_error = u3_wait()')]
        start=loop.index('#ifdef CORSIXTH_3DS\n    if (!do_frame && fps.limit_fps)')
        end=loop.index('    cth3ds::runtime_flush_observations();',start)
        end=loop.index('#endif',end)+len('#endif')
        gc=loop[start:end]
        code=(ROOT/'tests/runtime_support/frame_tail_probe.cpp').read_text()
        code=code.replace('// INSERT_NATIVE',methods).replace('// INSERT_WAIT',wait).replace('// INSERT_GC',gc)
        code=code.replace('// INSERT_SHUTDOWN_PREFIX',shutdown_prefix)
        source=directory/'probe.cpp';source.write_text(code)
        cls.binary=directory/'probe'
        compiler,includes,links=native_inputs()
        result=subprocess.run([*compiler,'-std=c++17','-O2','-DCORSIXTH_3DS',
            '-Wall','-Wextra','-Wpedantic','-Wconversion','-Wsign-conversion','-Wshadow','-Werror',
            '-fsanitize=address,undefined','-fno-omit-frame-pointer',
            '-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),*includes,str(source),
            str(ROOT/'src/3ds/runtime/observation.cpp'),str(ROOT/'src/common/telemetry.cpp'),
            *links,'-o',str(cls.binary)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)

    def run_probe(self,mode):
        result=subprocess.run([str(self.binary),mode,str(ROOT/'lua')],capture_output=True,text=True,
            env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'),timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout,end='')

    def test_bounded_ledger_conservation_scope_and_partial(self):
        self.run_probe('ledger')

    def test_actual_deferred_flush_generated_gc_wait_and_real_lua_marks(self):
        self.run_probe('seam')

if __name__=='__main__':unittest.main()
