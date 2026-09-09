"""Strict sample bounds and identical ordered pixel stream with sampling on/off."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SubmitTests(unittest.TestCase):
    def test_transform_exact_owner_and_idempotence(self):
        sys.path.insert(0,str(ROOT/'tools'))
        from integration.render_gpu import SITES,patch_render_gpu
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=root/'CorsixTH/Src';src.mkdir(parents=True)
            gfx=src/'th_gfx_sdl.cpp';floor=src/'th_map.cpp'
            gfx.write_text('\n'.join(before for before,_ in SITES))
            floor.write_text('                           int iCanvasY) const {\n  for (map_tile_iterator unchanged_floor_and_shadow_order;\n}')
            self.assertEqual(len(patch_render_gpu(root,True)),2)
            self.assertNotIn('GpuSubmitFloorScope',floor.read_text())
            self.assertEqual(len(patch_render_gpu(root)),2)
            self.assertEqual(patch_render_gpu(root),[])
            self.assertEqual(floor.read_text().count('GpuSubmitFloorScope'),1)
            self.assertIn('unchanged_floor_and_shadow_order',floor.read_text())
            self.assertEqual(gfx.read_text().count('GpuSubmitBridgeScope'),1)

    def compile(self, directory, source, gpu=False):
        cpp = directory/'probe.cpp'
        cpp.write_text(source)
        output = directory/'probe'
        args = [shutil.which('clang++') or shutil.which('g++'), '-std=c++17', '-O2',
                '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                '-fno-omit-frame-pointer', '-I'+str(ROOT/'include')]
        if gpu:
            args += ['-DCORSIXTH_3DS_GPU=1', '-I'+str(ROOT/'tests/runtime_support/gpu_sdk'),
                     '-I'+str(ROOT/'src/3ds'), str(ROOT/'src/3ds/runtime/gpu_renderer.cpp')]
            args += shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
        subprocess.run(args+[str(cpp),'-o',str(output)],check=True)
        return output

    def test_bounds_rotation_cancel_and_clock(self):
        source = r'''
#include "cth3ds/gpu_submit_sample.hpp"
#include <cassert>
int main(){
  using S=cth3ds::GpuSubmitSample;S s;assert(sizeof(s)<=512);
  assert(!s.choose());s.begin(100);
  for(unsigned frame=0;frame<64;++frame){
    unsigned n=0;s.frame();
    for(unsigned i=0;i<640;++i)n+=s.choose();
    assert(n==10);
  }
  s.end(200,true);assert(s.eligible&&!s.enabled);
  s.inc(S::Calls);assert(s.count[S::Calls]==0);
  s.end(201,false);assert(s.eligible&&s.end_us==200);
  s.begin(200);s.end(199,true);assert(!s.eligible);
  s.begin(1);s.end(2,false);assert(!s.eligible);
  s.begin(1);s.floor=true;s.end(2,true);assert(!s.eligible);
  s.begin(1);s.bridge=true;s.end(2,true);assert(!s.eligible);
  s.begin(1);s.inc(S::Errors);s.end(2,true);assert(!s.eligible);
  s.begin(1);assert(s.delta(5,4)==0);s.end(2,true);assert(!s.eligible&&s.rollback);
  s.begin(1);s.count[S::Calls]=UINT64_MAX;s.inc(S::Calls);
  s.end(2,true);assert(!s.eligible&&s.overflow&&s.count[S::Calls]==UINT64_MAX);
  s.begin(1);s.ordinal=UINT32_MAX;assert(!s.choose());assert(s.choose());
}
'''
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([str(self.compile(Path(d),source))],check=True)

    def test_ordered_production_pixels_on_off(self):
        source=(ROOT/'tests/runtime_support/gpu_renderer_probe.cpp').read_text()
        source=source.replace('int main(){','int main(){\n  const bool sample=std::getenv("R66_SAMPLE")!=nullptr;')
        source=source.replace('corrupt_sampling=false;assert(gpu_initialize());',
            'corrupt_sampling=false;assert(gpu_initialize());\n  if(sample)gpu_submit_sample_begin(100);')
        source=source.replace('void paint(C3D_RenderTarget* target,int x,int y,u32 colour){',
            'unsigned long long trace=1469598103934665603ULL;\n'
            'void paint(C3D_RenderTarget* target,int x,int y,u32 colour){'
            'trace=(trace^colour)*1099511628211ULL;trace=(trace^unsigned(x))*1099511628211ULL;'
            'trace=(trace^unsigned(y))*1099511628211ULL;')
        source=source.replace('assert(gpu_image_draw(tex,&src,&dest,',
            'GpuSubmitBridgeScope bridge;assert(gpu_image_draw(tex,&src,&dest,')
        source=source.replace('gpu_image_destroy(background);gpu_images_release(renderer);',
            'assert(gpu_begin());{GpuSubmitFloorScope floor;'
            'u32 p=0xff2468acU;auto* tiny=gpu_image_create(renderer,1,1,&p);assert(tiny);'
            'for(int i=0;i<256;++i)draw(tiny,{0,0,1,1},{float(i),0,1,1},i&3);'
            'gpu_quiesce();gpu_image_destroy(tiny);}'
            'gpu_submit_sample_end(200,true);gpu_submit_sample_log();'
            'std::printf("TRACE %llu\\n",trace);'
            'if(sample){gpu_submit_sample_begin(300);'
            'assert(gpu_image_draw(nullptr,nullptr,&full,SDL_FLIP_NONE)<0);'
            'SDL_FRect nan_dst{NAN,0,1,1};assert(gpu_image_draw(background,nullptr,&nan_dst,SDL_FLIP_NONE)<0);'
            'SDL_Rect bad_src{-1,0,1,1};assert(gpu_image_draw(background,&bad_src,&full,SDL_FLIP_NONE)<0);'
            'SDL_Rect empty{0,0,0,0};gpu_clip(&empty);assert(gpu_image_draw(background,nullptr,&full,SDL_FLIP_NONE)==0);'
            'gpu_submit_sample_end(400,true);gpu_submit_sample_log();}'
            'gpu_image_destroy(background);gpu_images_release(renderer);')
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
        with tempfile.TemporaryDirectory() as d:
            binary=self.compile(Path(d),source,True)
            off=subprocess.check_output([str(binary)],env=env,text=True)
            on=subprocess.check_output([str(binary)],env=dict(env,R66_SAMPLE='1'),text=True)
        self.assertEqual(re.search(r'TRACE (\d+)',off)[1],re.search(r'TRACE (\d+)',on)[1])
        self.assertIn('gpu-submit-window: begin_us=100 end_us=200',on)
        self.assertIn('eligible=1 sampled_calls_only=1',on)
        first,errors=on.split('gpu-submit-window: begin_us=300')
        self.assertIn('eligible=0',errors)
        self.assertIn('name=errors value=3',errors)
        self.assertIn('name=culled value=1',errors)
        counts=dict((k,int(v)) for k,v in re.findall(r'gpu-submit-count: name=(\w+) value=(\d+)',first))
        self.assertGreater(counts['sampled'],0)
        self.assertGreater(counts['multi_excluded'],0)
        self.assertGreater(counts['checkpoint_commands'],0)
        self.assertGreater(counts['uploads'],0)
        self.assertGreater(counts['hits'],0)
        self.assertEqual(counts['floor_calls'],256)
        self.assertEqual(counts['floor_pieces'],256)
        self.assertEqual(counts['floor_switches'],0)
        self.assertEqual(counts['floors'],1)
        self.assertEqual(counts['sampled'],sum(map(int,re.findall(r'sampled_only=1 samples=(\d+)',first))))

if __name__=='__main__':unittest.main()
