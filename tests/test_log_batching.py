"""Complete log owner + real stdio, and real GPU/native report consumers."""
import os
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
import zlib
from test_playable_path import function_body
from test_save_memory import native_inputs

ROOT=Path(__file__).resolve().parents[1]
SUPPORT=ROOT/'tests/runtime_support'

class LogBatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r70-logging-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory=Path(cls.temp.name)
        private=cls.directory/'include/cth3ds'
        private.mkdir(parents=True)
        source=(ROOT/'include/cth3ds/bounded_log.hpp').read_text()
        if source.count('std::fopen(')!=1:raise RuntimeError('logging FILE open seam changed')
        (private/'bounded_log.hpp').write_text(source.replace('std::fopen(','logging_open('))

    def compile(self,name,sources,extra=(),include_root=None):
        compiler,_,_=native_inputs()
        target=self.directory/name
        command=[*compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
            '-fsanitize=address,undefined','-fno-omit-frame-pointer',
            '-include',str(SUPPORT/'logging_io_probe.hpp'),
            '-I'+str(include_root or self.directory/'include'),'-I'+str(ROOT/'include'),
            '-I'+str(ROOT/'src/3ds'),'-I'+str(SUPPORT),
            *map(str,sources),*extra,'-o',str(target)]
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return target

    def run_probe(self,binary,*args):
        result=subprocess.run([str(binary),*map(str,args)],capture_output=True,text=True,timeout=30,
            env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout,end='')
        return result.stdout

    def io_probe(self):
        if not hasattr(type(self),'io_binary'):
            type(self).io_binary=self.compile('io',[SUPPORT/'logging_io_probe.cpp'])
        return self.io_binary

    def test_complete_bounded_log_real_stdio_failure_and_terminal(self):
        binary=self.io_probe()
        self.assertIn('PASS real stdio',self.run_probe(binary))

    def test_retained_r69_compact_bytes_and_real_stdio_write_counts(self):
        fixture=json.loads((ROOT/'tests/fixtures/r70_compact_reports.json').read_text())
        stream=zlib.decompress(base64.b64decode(fixture['zlib_base64']))
        rows=stream.split(b'---REPORT---\n')[1:]
        self.assertEqual([len(row) for row in rows],fixture['bytes'])
        self.assertEqual([hashlib.sha256(row).hexdigest() for row in rows],fixture['sha256'])
        source=self.directory/'reports.txt';source.write_bytes(stream)
        baseline=self.directory/'baseline/cth3ds';baseline.mkdir(parents=True)
        header=(self.directory/'include/cth3ds/bounded_log.hpp').read_text()
        self.assertEqual(header.count('kBufferSize = 8192U'),1)
        (baseline/'bounded_log.hpp').write_text(header.replace('kBufferSize = 8192U','kBufferSize = 4096U'))
        old=self.compile('io4096',[SUPPORT/'logging_io_probe.cpp'],include_root=baseline.parent)
        outputs=[self.run_probe(binary,source) for binary in (old,self.io_probe())]
        for text,writes in zip(outputs,(2,1)):
            lines=text.splitlines();self.assertEqual(len(lines),6)
            for line,size in zip(lines,fixture['bytes']):
                self.assertIn('bytes='+str(size),line)
                self.assertIn('explicit_flushes=1 underlying_writes='+str(writes),line)

    def test_actual_gpu_native_sample_flush_errors_partial_reset_and_scope(self):
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        methods='\n'.join(function_body(runtime,name) for name in (
            'void boot_log(const char* format, ...) {','void boot_log_flush(',
            'void runtime_diagnostic_line(','void runtime_diagnostic_flush(',
            'void seal_observation_tail(','void reset_runtime_observations(',
            'int l_benchmark_mark(','void runtime_flush_observations('))
        include=(SUPPORT/'runtime_logging_probe.inc').read_text().replace('// INSERT_NATIVE_LOGGING',methods)
        harness=(SUPPORT/'gpu_renderer_probe.cpp').read_text()
        first=harness.index('namespace cth3ds{\nvoid runtime_diagnostic_line')
        last=harness.index('\nint main(){',first)
        harness=harness[:first]+include+harness[last:]
        harness=harness.replace('using namespace cth3ds;assert(SDL_Init(0)==0);',
            'using namespace cth3ds;assert(SDL_Init(0)==0);'
            'assert(g_log.open("/no-r70-fixture/current","/no-r70-fixture/previous","/no-r70-fixture/oldest"));')
        harness=harness.replace('diagnostic_lines.clear();','diagnostic_lines.clear();logging_io::delivered.clear();')
        harness=harness.replace('bool saw_failure=false;for(const auto& line:diagnostic_lines)',
            'bool saw_failure=false;std::istringstream diagnostic_text(logging_io::delivered);'
            'std::string line;while(std::getline(diagnostic_text,line))')
        anchor='corrupt_sampling=false;assert(gpu_initialize());'
        self.assertEqual(harness.count(anchor),1)
        harness=harness.replace(anchor,anchor+'\n  exercise_report_boundaries();')
        path=self.directory/'gpu.cpp';path.write_text(harness)
        _,includes,links=native_inputs()
        sdl=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
        binary=self.compile('gpu',[path,SUPPORT/'logging_io_probe.cpp',
            ROOT/'src/3ds/runtime/gpu_renderer.cpp',ROOT/'src/3ds/runtime/observation.cpp',
            ROOT/'src/common/telemetry.cpp'],
            ['-DLOGGING_IO_NO_MAIN=1','-DCORSIXTH_3DS_GPU=1',
             '-I'+str(SUPPORT/'gpu_sdk'),*includes,*links,*sdl])
        self.assertIn('PASS actual GPU/native report boundaries',self.run_probe(binary))

if __name__=='__main__':unittest.main()
