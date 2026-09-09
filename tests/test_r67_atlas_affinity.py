"""Fixed preference contract and actual renderer ordered-pixel A/B matrix."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class AffinityTests(unittest.TestCase):
    def compile(self,directory,source,mode=1,gpu=False):
        cpp=directory/f'probe{mode}.cpp';cpp.write_text(source)
        binary=directory/f'probe{mode}'
        args=[shutil.which('clang++') or shutil.which('g++'),'-std=c++17','-O2',
              '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
              '-DCTH3DS_GPU_ATLAS_AFFINITY='+str(mode),'-I'+str(ROOT/'include')]
        if gpu:
            args+=['-DCORSIXTH_3DS_GPU=1','-I'+str(ROOT/'tests/runtime_support/gpu_sdk'),
                   '-I'+str(ROOT/'src/3ds'),str(ROOT/'src/3ds/runtime/gpu_renderer.cpp')]
            args+=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
        subprocess.run(args+[str(cpp),'-o',str(binary)],check=True)
        return binary

    def test_bounded_preference_and_generation(self):
        source=r'''
#include "cth3ds/gpu_atlas_affinity.hpp"
#include <cassert>
struct Page{std::uint64_t generation=1,used=0;};
int main(){
  cth3ds::GpuAtlasAffinity a;std::array<Page,3> p{};
  auto check=[&](unsigned x,unsigned y,unsigned z){auto q=a.order(p);
    assert(q[0]==x&&q[1]==y&&q[2]==z);};
  check(0,1,2);p[0].used=1;a.floor=true;check(1,0,2);
  a.placed(1,1);p[1].used=1;check(1,0,2);
  a.floor=false;check(0,2,1); // every page still borrowable once
  ++p[1].generation;check(0,1,2);assert(a.page==-1);
  a.floor=true;check(2,0,1);p[2].used=1;
  check(0,1,2);a.placed(0,1);check(0,1,2); // no empty page
  a={};assert(a.page==-1&&!a.floor&&a.generation==0);
  a.floor=true;a.page=3;check(0,1,2);assert(a.page==-1);
}
'''
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([str(self.compile(Path(d),source))],check=True)

    def test_real_renderer_ordered_pixels_layout_and_sampling(self):
        source=(ROOT/'tests/runtime_support/gpu_renderer_probe.cpp').read_text()
        source=source.replace('void paint(C3D_RenderTarget* target,int x,int y,u32 colour){',
            'unsigned long long r67_pixels=1469598103934665603ULL,r67_layout=1469598103934665603ULL;'
            'void r67_hash(unsigned long long& h,unsigned n){h=(h^n)*1099511628211ULL;}'
            'std::vector<C3D_Tex*> r67_pages;'
            'void paint(C3D_RenderTarget* target,int x,int y,u32 colour){'
            'r67_hash(r67_pixels,colour);r67_hash(r67_pixels,unsigned(x));r67_hash(r67_pixels,unsigned(y));')
        source=source.replace('emitted();const auto sub=*image.subtex;',
            'if(current->width==1024&&image.tex->width==512){'
            'auto it=std::find(r67_pages.begin(),r67_pages.end(),image.tex);'
            'if(it==r67_pages.end()){r67_pages.push_back(image.tex);it=r67_pages.end()-1;}'
            'r67_hash(r67_layout,unsigned(it-r67_pages.begin()));'
            'r67_hash(r67_layout,unsigned(image.subtex->left*512));'
            'r67_hash(r67_layout,unsigned((1-image.subtex->top)*512));}'
            'emitted();const auto sub=*image.subtex;')
        source=source.replace('gpu_images_release(renderer);gpu_log_statistics();',
            'gpu_images_release(renderer);\n'+(ROOT/'tests/runtime_support/r67_atlas_workload.inc').read_text()+
            '\ngpu_log_statistics();')
        results={}
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
        with tempfile.TemporaryDirectory() as d:
            for mode in (0,1):
                binary=self.compile(Path(d),source,mode,True)
                for sampling in (0,1):
                    runenv=dict(env)
                    if sampling:runenv['R67_SAMPLE']='1'
                    output=subprocess.check_output([str(binary)],env=runenv,text=True)
                    results[mode,sampling]=tuple(map(int,re.search(r'R67 pixels=(\d+) layout=(\d+)',output).groups()))
                    if sampling:
                        all_windows=output.split('gpu-submit-window:')[1:]
                        crossed=[w for w in all_windows if w.startswith(' begin_us=300')]
                        self.assertEqual(len(crossed),2)
                        for window in crossed:self.assertIn('eligible=0 sampled_calls_only=1',window)
                        windows=[w for w in all_windows if w.startswith(' begin_us=100')]
                        self.assertEqual(len(windows),2)
                        for window in windows:
                            self.assertIn('eligible=1 sampled_calls_only=1',window)
                            counts=dict((k,int(v)) for k,v in re.findall(r'name=(\w+) value=(\d+)',window))
                            self.assertGreater(counts['floor_pieces'],counts['floor_calls'])
                            self.assertGreater(counts['floor_switches'],0)
                            self.assertGreater(counts['checkpoint_eviction'],0)
                            self.assertEqual(counts['floors'],33)
        self.assertEqual(len({v[0] for v in results.values()}),1,results)
        for mode in (0,1):self.assertEqual(results[mode,0],results[mode,1])
        self.assertNotEqual(results[0,0][1],results[1,0][1])
        print('PASS R67 actual renderer A/B: identical ordered pixels; distinct atlas layouts; sampling invariant',results)

if __name__=='__main__':unittest.main()
