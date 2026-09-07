"""Host model checks production draw/ownership code; hardware remains separate."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class GpuRendererTests(unittest.TestCase):
    def test_production_backend_delayed_queue(self):
        with tempfile.TemporaryDirectory(prefix='cth-gpu-') as directory:
            binary=Path(directory)/'probe'
            flags=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
            subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2',
                '-DCORSIXTH_3DS_GPU=1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                '-fno-omit-frame-pointer','-I'+str(ROOT/'tests/runtime_support/gpu_sdk'),
                '-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),
                str(ROOT/'src/3ds/runtime/gpu_renderer.cpp'),str(ROOT/'tests/runtime_support/gpu_renderer_probe.cpp'),
                *flags,'-o',str(binary)],check=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS production GPU',result.stdout)
            print(result.stdout,end='')

if __name__=='__main__':unittest.main()
