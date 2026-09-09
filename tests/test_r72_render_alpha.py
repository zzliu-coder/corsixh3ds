"""Actual generated draw vs frozen pre-R72 oracle; private GPU queue model."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class R72RenderAlphaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.pinned_upstream import generated_sources
        cls.directory=tempfile.TemporaryDirectory(prefix='cth-r72-alpha-')
        cls.work=Path(cls.directory.name)
        cls.generated=generated_sources(cls.work)
        cls.engine=(cls.generated/'CorsixTH/Src/th_gfx_sdl.cpp').read_text()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_actual_order_counters_scope_idempotent_missing_anchor(self):
        sys.path.insert(0,str(ROOT/'tools'))
        from integration.render_fast import transform
        from sprite_residency import transform as residency
        from sound_lifetime import SoundPatchError
        from test_playable_path import function_body
        draw=function_body(self.engine,'void render_target::draw(SDL_Texture*')
        self.assertEqual(draw.count('++cth3ds::render_work.draws;'),1)
        self.assertEqual(draw.count('GpuSubmitBridgeScope submit_bridge;'),1)
        self.assertEqual(draw.count('++cth3ds::render_work.flipped_fallback;'),1)
        self.assertIn('(iFlags & thdf_alpha_50) ? 0x80',draw)
        self.assertEqual(transform(self.engine),self.engine)
        self.assertEqual(residency(self.engine),self.engine)
        damaged=self.engine.replace('SDL_SetTextureAlphaMod(pTexture,','SDL_SetTextureAlphaBroken(pTexture,')
        with self.assertRaises(SoundPatchError):transform(damaged)
        damaged_head=self.engine.replace('const SDL_Rect* prcDstRect, int iFlags) {','const SDL_Rect* prcDstRect, int brokenFlags) {')
        with self.assertRaises(SoundPatchError):residency(damaged_head)
        order=(ROOT/'tools/integrate_corsixth.py').read_text()
        self.assertLess(order.index('for path in patch_sprite_residency(root)'),order.index('for path in patch_render_fast(root)'))

    def test_fixed_original_draw_production_gpu_delayed_queue(self):
        from test_playable_path import function_body
        oracle=(ROOT/'tests/fixtures/r72_render_original.cpp').read_text()
        self.assertEqual(hashlib.sha256(oracle.encode()).hexdigest(),'9269edffca119edf70f137fb2bf8672a1b8126947e4ce3ad36979f1fd99b2174')
        model=(ROOT/'tests/runtime_support/gpu_renderer_probe.cpp').read_text().split('int main(){',1)[0]
        code=(ROOT/'tests/runtime_support/r72_gpu_alpha_probe.cpp.in').read_text()
        for marker,body in [('SCALE',function_body(oracle,'void getScaleRect(')),('DRAW',function_body(self.engine,'void render_target::draw(SDL_Texture*')),('REFERENCE_DRAW',function_body(oracle,'void render_target::draw(SDL_Texture*').replace('render_target::draw(', 'render_target::reference_draw(',1))]:
            code=code.replace('// INSERT_'+marker,body)
        source=self.work/'r72_gpu_alpha.cpp';source.write_text(model+code)
        flags=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
        for sanitized in (False,True):
            binary=self.work/('gpu-alpha-sanitized' if sanitized else 'gpu-alpha')
            command=[shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2','-DCORSIXTH_3DS_GPU=1','-Wall','-Wextra','-Werror',*(['-fsanitize=address,undefined','-fno-omit-frame-pointer'] if sanitized else []),'-I'+str(ROOT/'tests/runtime_support/gpu_sdk'),'-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),str(ROOT/'src/3ds/runtime/gpu_renderer.cpp'),str(source),*flags,'-o',str(binary)]
            subprocess.run(command,check=True)
            result=subprocess.run([str(binary)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS R72 alpha production GPU delayed queue',result.stdout)
            print(result.stdout,end='')

if __name__=='__main__':unittest.main()
