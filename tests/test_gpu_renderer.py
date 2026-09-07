"""Host model checks production draw/ownership code; hardware remains separate."""
import os
import json
import math
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class GpuRendererTests(unittest.TestCase):
    def test_prepared_pixels_exact_storage_and_upload(self):
        with tempfile.TemporaryDirectory(prefix='cth-gpu-pixels-') as directory:
            binary=Path(directory)/'pixels'
            subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2',
                '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                '-I'+str(ROOT/'include'),str(ROOT/'tests/runtime_support/gpu_pixels_probe.cpp'),
                '-o',str(binary)],check=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS prepared GPU pixels',result.stdout)
            print(result.stdout,end='')

    def test_retained_device_samples_explain_row_contract(self):
        evidence=json.loads((ROOT/'tests/fixtures/r54_gpu_device_samples.json').read_text())
        self.assertEqual(evidence['source_commit'],'ceeda5e913b2003502293c78ee18ec8fa24732f1')
        self.assertEqual(len(evidence['samples']),22)
        for row in evidence['samples']:
            if row['stage'] in ('raster-and-clip','atlas-crop-four-flips'):
                raw=int(row['alternate_y_raw'],16)
                direct=int.from_bytes(raw.to_bytes(4,'little'),'big')
                self.assertEqual(direct,int(row['expected'],16))
                self.assertNotEqual(int(row['actual'],16),direct)
            else:
                # Retained LCD colours match the OLD 512-y UV mapping. This
                # fixture supports the host model; it never makes R55 hardware PASS.
                x,y=int(row['x']),int(row['y'])
                sx,sy,sh=(x+120,96,240) if row['stage']=='canvas-to-top-buffer' else (2*x,0,480)
                y=math.floor(512-sy-(y+0.5)*sh/240)
                value=0 if y<0 or y>=480 else ((0x0000ff if y<240 else 0xff0000) if sx<320
                                             else (0x00ff00 if y<240 else 0x00ffff))
                self.assertEqual(value,int(row['actual'],16))

    def test_upload_matches_official_tex3ds(self):
        tool=shutil.which('tex3ds')
        if not tool:
            if os.environ.get('CTH3DS_REQUIRE_TEX3DS') == '1':
                self.fail('mandatory official tex3ds tool missing')
            self.skipTest('official tex3ds tool unavailable; required in 3DS device lane')
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

    def test_lcd_readback_bounds(self):
        with tempfile.TemporaryDirectory(prefix='cth-r54-lcd-') as d:
            binary=Path(d)/'probe'
            subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2',
                '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                '-I'+str(ROOT/'include'),str(ROOT/'tests/runtime_support/r54_lcd_probe.cpp'),
                '-o',str(binary)],check=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS independent LCD decoder',result.stdout)

if __name__=='__main__':unittest.main()
