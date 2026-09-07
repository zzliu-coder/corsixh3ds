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
    def test_upload_matches_official_tex3ds(self):
        tool=shutil.which('tex3ds')
        if not tool:self.skipTest('official tex3ds tool unavailable; required in 3DS device lane')
        with tempfile.TemporaryDirectory(prefix='cth-tex3ds-') as directory:
            directory=Path(directory)
            width=height=64
            pixels=bytes(c for y in range(height) for x in range(width)
                         for c in (x*7%256,y*11%256,37^x^y))
            source=directory/'pattern.ppm'
            source.write_bytes(b'P6\n64 64\n255\n'+pixels)
            encoded=directory/'pattern.bin'
            subprocess.run([tool,'-f','rgba8','-r','-z','none','-o',str(encoded),str(source)],check=True)
            # Compile the production uploader; the oracle is the installed
            # official converter, not a second copy of our address formula.
            cpp=directory/'upload.cpp'
            cpp.write_text('''#include "cth3ds/gpu_layout.hpp"
#include <array>
#include <cstdio>
int main(){std::array<std::uint32_t,4096> src{},dst{};
for(unsigned y=0;y<64;++y)for(unsigned x=0;x<64;++x)
src[y*64+x]=0xff000000U|((37U^x^y)<<16U)|((y*11U%256U)<<8U)|(x*7U%256U);
cth3ds::gpu_upload_rgba(dst.data(),64,0,0,src.data(),64,64,64);
return std::fwrite(dst.data(),4,dst.size(),stdout)==dst.size()?0:1;}
''')
            binary=directory/'upload'
            subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2',
                '-I'+str(ROOT/'include'),str(cpp),'-o',str(binary)],check=True)
            actual=subprocess.check_output([str(binary)])
            expected=encoded.read_bytes()
            self.assertEqual(expected[:4],bytes((0,0,64,0)))
            self.assertEqual(actual,expected[4:])

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
