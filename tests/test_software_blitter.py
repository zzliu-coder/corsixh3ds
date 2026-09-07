"""Actual SDL2 pixel/ownership comparison. Host evidence, no device FPS claim."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class SoftwareBlitterTests(unittest.TestCase):
    def test_generated_engine_calls_the_fast_path(self):
        from test_playable_path import generated_sources, function_body
        with tempfile.TemporaryDirectory(prefix='cth-engine-blit-') as td:
            td=Path(td)
            upstream=generated_sources(td)
            engine=(upstream/'CorsixTH/Src/th_gfx_sdl.cpp').read_text()
            code=(ROOT/'tests/runtime_support/engine_blitter_probe.cpp').read_text()
            for name,signature in [('SCALE','void getScaleRect('),('CREATE','SDL_Texture* render_target::create_texture(int iWidth'),('DRAW','void render_target::draw(SDL_Texture*')]:
                code=code.replace('// INSERT_'+name,function_body(engine,signature))
            code=code.replace('// INSERT_REFERENCE_DRAW',function_body(engine,'void render_target::draw(SDL_Texture*').replace('render_target::draw(', 'render_target::reference_draw(',1))
            source=td/'engine.cpp';source.write_text(code)
            flags=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
            binary=td/'probe'
            for sanitized in (False,True):
                subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2',
                    '-Wall','-Wextra','-Werror',*(['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if sanitized else []),
                    '-I'+str(ROOT/'include'),str(source),*flags,'-o',str(binary)],check=True)
                result=subprocess.run([str(binary)],capture_output=True,text=True,
                    env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('PASS generated engine',result.stdout)
                if not sanitized:print(result.stdout, end='')

    def test_real_sdl_pixels_and_ownership(self):
        with tempfile.TemporaryDirectory(prefix='cth-blit-') as td:
            flags=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
            compiler=shutil.which('clang++') or shutil.which('g++')
            binary=Path(td)/'probe'
            subprocess.run([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(ROOT/'include'),
                str(ROOT/'tests/runtime_support/software_blitter_probe.cpp'),*flags,'-o',str(binary)],check=True)
            env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
            result=subprocess.run([str(binary)],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS blitter 1296 pixel cases',result.stdout)

if __name__=='__main__':unittest.main()
