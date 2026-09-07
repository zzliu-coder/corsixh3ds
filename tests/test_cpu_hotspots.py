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

if __name__=='__main__':unittest.main()
