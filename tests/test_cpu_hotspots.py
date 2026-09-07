"""Pinned real methods preserve temperature rules and bounded observation costs."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_playable_path import generated_sources, function_body
from support.pinned_upstream import original_sources

ROOT=Path(__file__).resolve().parents[1]
DECL='''struct level_map {
  int width,height,current_temperature_index;map_tile* cells;
  uint32_t thermal_neighbour(uint32_t&,bool,std::ptrdiff_t,map_tile*,int) const;
  void update_temperatures(uint16_t,uint16_t);
  cth3ds::ThermalGrid thermal_cache;
};'''

class CpuHotspotTests(unittest.TestCase):
    def test_real_temperature_and_input_cache_contract(self):
        with tempfile.TemporaryDirectory(prefix='cth-cpu-') as directory:
            directory=Path(directory)
            generated=generated_sources(directory)
            original=original_sources(directory/'reference')
            methods=[]
            for name,path,macro in [('original',original,'#undef CORSIXTH_3DS'),('improved',generated,'#define CORSIXTH_3DS 1')]:
                text=(path/'CorsixTH/Src/th_map.cpp').read_text()
                methods.append(macro+'\nnamespace '+name+'{\n'+DECL+'\n'+ '\n'.join(
                    function_body(text,signature) for signature in ('uint32_t level_map::thermal_neighbour(',
                    'void merge_temperatures(', 'void level_map::update_temperatures('))+'\n}')
            code=(ROOT/'tests/runtime_support/cpu_hotspots_probe.cpp').read_text().replace('// INSERT_METHODS','\n'.join(methods))
            source=directory/'probe.cpp';source.write_text(code)
            for optimization in ('-Oz','-O2'):
                binary=directory/optimization[1:]
                subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17',optimization,
                    '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    '-I'+str(ROOT/'include'),str(source),'-o',str(binary)],check=True)
                result=subprocess.run([str(binary)],capture_output=True,text=True,
                    env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('PASS 786432 temperature merges',result.stdout)
            runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
            self.assertIn('InputRefreshGate input_state;',runtime)
            self.assertEqual(runtime.count('input_state.invalidate();'),2)
            self.assertIn('cpu_scope(cth3ds::CpuWork::Pathfind)',(generated/'CorsixTH/Src/th_pathfind.cpp').read_text())
            app=(generated/'CorsixTH/Lua/app.lua').read_text()
            begin=app.index('function App:onTick(')
            tick=app[begin:app.index('\nend',begin)+4]
            import test_lua_runtime
            test_lua_runtime.LuaRuntimeTests.setUpClass()
            test_lua_runtime.LuaRuntimeTests().run_lua('App={}\n'+tick+r'''
local w,u=0,0
local ui={onTick=function()u=u+1;return false end}
local a=setmetatable({moviePlayer={playing=false},ui=ui},{__index=App})
assert(a:onTick()==true and u==1) -- unchanged desktop contract
a._3ds={native={cpu_profile=function(_,fn,...)return fn(...)end}}
assert(a:onTick()==false and u==2) -- idle menu, independent compatibility refresh
a.world={onTick=function()w=w+1 end}
assert(a:onTick()==true and w==1 and u==3)
a.world=nil;ui.onTick=function()u=u+1;return true end
assert(a:onTick()==true and u==4) -- tooltip timer still requests painting
a.moviePlayer.playing=true;assert(a:onTick()==true and u==4)
''')

    def test_r54_semantics_and_phase_modes(self):
        # Supplements, and does not replace, the assembled upstream 200-map test.
        with tempfile.TemporaryDirectory(prefix='cth-r54-thermal-') as d:
            for optimization in ('-Oz','-O2'):
                binary=Path(d)/optimization[1:]
                subprocess.run([shutil.which('clang++') or shutil.which('g++'),'-std=c++17',optimization,
                    '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    '-I'+str(ROOT/'include'),str(ROOT/'tests/runtime_support/r54_thermal_probe.cpp'),
                    '-o',str(binary)],check=True)
                result=subprocess.run([str(binary)],capture_output=True,text=True,
                    env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('PASS thermal upstream-method comparison',result.stdout)

if __name__=='__main__':unittest.main()
