"""Four fixed opaque fullscreen windows; actual generated bodies and GPU owner.

No full hospital/Old3DS FPS claim. Lua rendering services are fixtures. GPU
storage/order/pixels use the existing delayed SDK model and production backend.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT=Path(__file__).resolve().parents[1]

class R73FloorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from support.pinned_upstream import original_sources
        sys.path.insert(0,str(ROOT/'tools'))
        from integrate_corsixth import generate_private
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r73-floor-')
        cls.work=Path(cls.temp.name);cls.original=original_sources(cls.work/'original')
        fixture=json.loads((ROOT/'tests/fixtures/r73_floor_upstream.json').read_text())
        assert fixture['commit']=='56bd5d00f76331c7f76d7b696726a7926303ca0c'
        files=json.loads(zlib.decompress(base64.b64decode(fixture['sources_zlib_base64'])))
        for name,text in files.items():
            assert hashlib.sha256(text.encode()).hexdigest()==fixture['sha256'][name]
            path=cls.original/name;assert not path.exists();path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        cls.generated=cls.work/'generated'
        cls.receipt=generate_private(cls.original,ROOT,cls.generated)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_complete_successful_bodies_and_generation_guards(self):
        from test_playable_path import function_body
        from integration.floor_occlusion import FILES,transform,check_floor_occlusion
        from integrate_corsixth import generate_private
        from sound_lifetime import SoundPatchError
        def read(root,name):return (root/'CorsixTH'/name).read_text()
        old=read(self.original,'Src/th_map.cpp');new=read(self.generated,'Src/th_map.cpp')
        guard='#ifdef CORSIXTH_3DS\n  if (!skip_opaque_floor)\n#else\n  (void)skip_opaque_floor;\n#endif\n'
        normalized=function_body(new,'void level_map::draw(').replace('int iCanvasY, bool skip_opaque_floor)','int iCanvasY)',1).replace(guard,'',1)
        self.assertEqual(normalized,function_body(old,'void level_map::draw('))
        floor=function_body(new,'void level_map::draw_floor(').replace('#ifdef CORSIXTH_3DS_GPU\n  cth3ds::GpuSubmitFloorScope submit_floor;\n#endif\n','',1)
        self.assertEqual(floor,function_body(old,'void level_map::draw_floor('))
        for file,name in [('hospital_policy','UIPolicy'),('progress_report','UIProgressReport'),('research_policy','UIResearch'),('staff_management','UIStaffManagement')]:
            path='Lua/dialogs/fullscreen/'+file+'.lua'
            pattern=r'(?ms)^function '+name+r':draw\(.*?^end'
            self.assertEqual(re.search(pattern,read(self.generated,path)).group(),re.search(pattern,read(self.original,path)).group())
        for path in FILES:
            text=read(self.generated,path);self.assertEqual(transform(path,text),text)
        with self.assertRaises(SoundPatchError):transform('Src/th_map.cpp',old.replace('  draw_floor(pCanvas,','  missing_floor(pCanvas,',1))
        self.assertEqual(check_floor_occlusion(self.generated),[])
        repeat=generate_private(self.original,ROOT,self.work/'repeat')
        self.assertEqual(repeat['view_sha256'],self.receipt['view_sha256'])
        self.assertEqual((self.generated/'CorsixTH/Lua/3ds/floor_occlusion.lua').read_bytes(),(ROOT/'lua/3ds/floor_occlusion.lua').read_bytes())

    def test_actual_lua_four_windows_prefix_resize_reload_preview_rng(self):
        from test_lua_runtime import LuaRuntimeTests
        LuaRuntimeTests.setUpClass()
        script='local product='+repr(str(ROOT))+'\nlocal generated='+repr(str(self.generated))+'\n'+(ROOT/'tests/runtime_support/r73_floor_cases.lua').read_text()
        LuaRuntimeTests().run_lua(script)

    def test_actual_raw_bitmap_gpu_pixels_lifetimes(self):
        from test_playable_path import function_body
        engine=(self.generated/'CorsixTH/Src/th_gfx_sdl.cpp').read_text()
        header=(self.generated/'CorsixTH/Src/th_gfx_sdl.h').read_text()
        start=header.index('class raw_bitmap {');end=header.index('\n};',start)+3
        methods='\n'.join(function_body(engine,key)for key in ['bool raw_bitmap::opaque_canvas_for(','raw_bitmap::~raw_bitmap()','void raw_bitmap::set_palette(','void raw_bitmap::load_from_th_file(','void raw_bitmap::draw(render_target* pCanvas, int iX, int iY)','void raw_bitmap::draw(render_target* pCanvas, int iX, int iY, int iSrcX,'])
        code=(ROOT/'tests/runtime_support/gpu_renderer_probe.cpp').read_text().split('int main(){',1)[0]+(ROOT/'tests/runtime_support/r73_floor_gpu.cpp.in').read_text()
        parts={'GEOMETRY':function_body(header,'  bool opaque_canvas_geometry()'),'RAW_CLASS':header[start:end],'SCALE':function_body(engine,'void getScaleRect('),'DRAW':function_body(engine,'void render_target::draw(SDL_Texture*'),'CONVERT':function_body(engine,'uint8_t* convertLegacySprite('),'RAW_METHODS':methods}
        for key,value in parts.items():code=code.replace('// INSERT_'+key,value)
        source=self.work/'gpu.cpp';source.write_text(code)
        flags=shlex.split(subprocess.check_output(['sdl2-config','--cflags','--libs'],text=True))
        for sanitize in [False,True]:
            binary=self.work/('gpu-asan'if sanitize else 'gpu')
            cmd=[shutil.which('clang++') or 'c++','-std=c++17','-O2','-DCORSIXTH_3DS_GPU=1','-Wall','-Wextra','-Werror',*(['-fsanitize=address,undefined','-fno-omit-frame-pointer']if sanitize else []),'-I'+str(ROOT/'tests/runtime_support/gpu_sdk'),'-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),str(ROOT/'src/3ds/runtime/gpu_renderer.cpp'),str(source),*flags,'-o',str(binary)]
            built=subprocess.run(cmd,text=True,capture_output=True);self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            run=subprocess.run([str(binary)],text=True,capture_output=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);self.assertIn('PASS actual bitmap/GPU proof',run.stdout)

    def test_native_map_boolean_and_software_false(self):
        from test_lua_runtime import LuaRuntimeTests
        from test_playable_path import function_body
        LuaRuntimeTests.setUpClass()
        cpp=(ROOT/'tests/runtime_support/r73_floor_bridge.cpp.in').read_text()
        cpp=cpp.replace('// INSERT_MAP',function_body((self.generated/'CorsixTH/Src/th_lua_map.cpp').read_text(),'int l_map_draw('))
        cpp=cpp.replace('// INSERT_SOFTWARE',function_body((self.generated/'CorsixTH/Src/th_gfx_sdl.cpp').read_text(),'bool raw_bitmap::opaque_canvas_for('))
        source=self.work/'bridge.cpp';source.write_text(cpp)
        lib=Path(os.environ.get('CTH3DS_LUA_LIBRARY',LuaRuntimeTests.lua._name))
        include=os.environ.get('CTH3DS_LUA_INCLUDE')
        flags=['-I'+include]if include else shlex.split(subprocess.check_output(['pkg-config','--cflags','lua5.4'],text=True))
        libs=[str(lib)]if lib.is_file()else shlex.split(subprocess.check_output(['pkg-config','--libs','lua5.4'],text=True))
        for platform in [False,True]:
            binary=self.work/('bridge-3ds'if platform else 'bridge-desktop')
            cmd=[shutil.which('clang++') or 'c++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',*(['-DCORSIXTH_3DS']if platform else []),*flags,str(source),*libs,'-o',str(binary)]
            built=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);self.assertIn('PASS actual l_map_draw',run.stdout)

    def test_existing_software_raw_replacement_assertions(self):
        # Reuse the exact R62 test body against this fully generated view. Its
        # fixed success/20 failure assertions and sanitizer flags stay intact.
        # The only shared fixture is the already prepared disposable directory.
        from test_r62_contracts import R62Contracts
        case=R62Contracts('test_fallback_raw_exception_preserves_old_image_and_releases_conversion')
        case.generated=self.generated;case.directory=self.work
        case.test_fallback_raw_exception_preserves_old_image_and_releases_conversion()

if __name__=='__main__':unittest.main()
