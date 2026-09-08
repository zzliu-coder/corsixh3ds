"""R56 actual pinned mutation and World calls, not replicas of game logic."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from support.pinned_upstream import original_sources,generated_sources
from test_playable_path import function_body
from integration.thermal_cache import MAP_MUTATORS,LUA_MUTATORS
from integration.latency import APP,GRAPHICS
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

class RuntimeHotspotsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r56-hotspots-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory=Path(cls.temp.name)
        cls.generated=generated_sources(cls.directory)
        cls.original=original_sources(cls.directory/'original')
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def lua(self,script):
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_real_thermal_mutation_owners_and_reuse(self):
        header=(self.generated/'CorsixTH/Src/th_map.h').read_text()
        source=(self.generated/'CorsixTH/Src/th_map.cpp').read_text()
        lua=(self.generated/'CorsixTH/Src/th_lua_map.cpp').read_text()
        for signature in MAP_MUTATORS:
            self.assertIn(signature+'\n#ifdef CORSIXTH_3DS\n  invalidate_thermal_structure();',source)
        flags=function_body(header,'struct map_tile_flags {')+';\n'
        flags+=function_body(source,'bool& map_tile_flags::operator[]')
        flags+=function_body(source,'map_tile_flags& map_tile_flags::operator=')
        flags+=function_body(lua,'const std::map<std::string, map_tile_flags::key> lua_tile_flag_map')+';\n'
        methods='\n'.join(function_body(lua,'int '+name+'(') for name in LUA_MUTATORS)
        self.assertEqual(methods.count('pMap->invalidate_thermal_structure();'),5)
        registration='\n'.join('lua_pushcfunction(L,'+name+');lua_setglobal(L,"'+alias+'");'
            for name,alias in zip(LUA_MUTATORS,('erase','remove','set','mark','unmark')))
        text=(ROOT/'tests/runtime_support/thermal_mutation_probe.cpp').read_text()
        text=text.replace('// INSERT_FLAGS',flags).replace('// INSERT_MUTATORS',methods).replace('// INSERT_REGISTRATION',registration)
        cpp=self.directory/'thermal.cpp';cpp.write_text(text)
        binary=self.directory/'thermal'
        pkg=next((p for p in ('lua5.4','lua-5.4','lua') if subprocess.run(
            ['pkg-config','--exists',p]).returncode==0),None)
        self.assertIsNotNone(pkg,'Lua 5.4 development package required')
        include=os.environ.get('CTH3DS_LUA_INCLUDE')
        flags=['-I'+include] if include else shlex.split(subprocess.check_output(['pkg-config','--cflags',pkg],text=True))
        library=os.environ.get('CTH3DS_LUA_LIBRARY')
        links=[library] if library else shlex.split(subprocess.check_output(['pkg-config','--libs',pkg],text=True))
        subprocess.run([shutil.which('clang++') or 'c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
            '-fsanitize=address,undefined','-fno-omit-frame-pointer',*flags,'-I'+str(ROOT/'include'),
            str(cpp),*links,'-o',str(binary)],check=True)
        result=subprocess.run([str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS real Lua map mutators',result.stdout)

    def test_real_world_tick_preserves_calls_dates_rates_and_returns(self):
        def method(root):
            text=(root/'CorsixTH/Lua/world.lua').read_text()
            begin=text.index('function World:onTick()')
            prefix='local entity_profile_iteration = 0\n' if 'local entity_profile_iteration = 0' in text else ''
            return prefix+text[begin:text.index('\nend',begin)+4]
        # The mock supplies dependencies; the complete World:onTick is actual
        # pinned/generated code. Every downstream call/order/date is compared.
        setup=r'''
local start_date={}
local outside_temperatures=setmetatable({},{__index=function()return 0.1 end})
local calls,phases={},{}
local function call(n) calls[#calls+1]=n end
local Date={}
Date.__index=Date
function Date:plusHours(h)return setmetatable({hour=self.hour+h},Date)end
function Date:dayOfMonth()return math.floor(self.hour/50)+1 end
function Date:monthOfYear()return 1 end
function Date:hourOfDay()return self.hour%50 end
function Date:isLastDayOfMonth()return false end
local function date(h)return setmetatable({hour=h},Date)end
local function make(hours,rate)
 local w={hours_per_tick=hours,tick_rate=rate,tick_timer=0,autosave_next_tick=true,
   game_date=date(49),spawn_hours={[1]=1,[2]=2}}
 w._executeAutosave=function()call('save')end
 w.isCurrentSpeed=function(_,s)return s=='Pause' and hours==0 end
 w.earthquake={tick=function()call('earthquake')end}
 w.anims={tick=function()call('animations')end}
 w.hospitals={{opened=true,heating={radiator_heat=0.3},tick=function()call('hospital')end,
   onEndDay=function()call('hospital-day')end}}
 w.onEndDay=function()call('day')end
 w.spawnPatient=function()call('spawn')end
 w.entities={{ticks=true,tick=function()call('entity')end},{ticks=false,tick=function()error('inactive')end}}
 w.map={level_number=1,onTick=function()call('map')end,
   th={updateTemperatures=function(_,a,b)assert(a==0.1 and b==0.25+0.3*0.3);call('heat')end}}
 w.ui={onWorldTick=function()call('ui')end}
 w.dispatcher={onTick=function()call('dispatch')end}
 w.floating_dollars={{}};w.floating_dollars={}
 return w
end
World={}
'''
        script=setup+method(self.original)+'\nlocal reference=World.onTick\n'+method(self.generated)+r'''
local improved=World.onTick
for _,mode in ipairs({{0,1},{1,3},{1,1},{2,1},{5,1}})do
 local a,b=make(mode[1],mode[2]),make(mode[1],mode[2])
 for frame=1,30 do
  calls={};local ra=reference(a);local expected=table.concat(calls,',')
  calls={};phases={}
  TheApp={_3ds={native={cpu_phase=function(n,start)
    if n then assert(type(start)=='number');if not n:match('^sample_entity_') then phases[#phases+1]=n end end
    return #phases+1
  end}}}
  local rb=improved(b)
  assert(ra==rb and table.concat(calls,',')==expected,expected)
  assert(a.game_date.hour==b.game_date.hour and a.tick_timer==b.tick_timer)
  if #phases>0 then
    assert(phases[1]=='world_calendar')
    for i=2,#phases,6 do
      assert(table.concat(phases,',',i,i+5)=='world_animations,world_hospitals,world_entities,world_map,world_ui,world_dispatch')
    end
  end
 end
end
local w=make(1,3);w.map.level_number='MAP EDITOR';calls={}
assert(improved(w)==nil and #calls==0 and w.game_date.hour==49)
TheApp=nil;w=make(1,3);improved(w);assert(w.game_date.hour==50)
'''
        self.lua(script)

    def test_cold_resource_wrappers_preserve_results_errors_and_cache_hits(self):
        for path,fragment in (('CorsixTH/Lua/app.lua',APP),('CorsixTH/Lua/graphics.lua',GRAPHICS)):
            self.assertEqual((self.generated/path).read_text().count(fragment.strip()),1)
        self.lua(r'''
local traces,calls={},0
local TH3DS={trace_call=function(kind,id,fn,...)
 traces[#traces+1]=kind..':'..id;return fn(...)
end}
App={readDataFile=function(_,dir,name)
 calls=calls+1;if name=='bad' then error('read failed')end
 return dir..'/'..name,nil,false
end}
Graphics={}
function Graphics:loadRaw(n,...)
 calls=calls+1;self.cache.raw[n]=self.cache.raw[n] or {n,...};return self.cache.raw[n]
end
function Graphics:loadSpriteTable(d,n,...)
 calls=calls+1;self.cache.tabled[n]=self.cache.tabled[n] or {d,n,...};return self.cache.tabled[n]
end
'''+APP+GRAPHICS+r'''
local value,a,b=App:readDataFile('Data','good');assert(value=='Data/good' and a==nil and b==false)
local ok,err=pcall(App.readDataFile,App,'Data','bad');assert(not ok and err:find('read failed'))
local g=setmetatable({cache={raw={},tabled={}}},{__index=Graphics})
local raw=g:loadRaw('Face',65);assert(raw[2]==65)
local sheet=g:loadSpriteTable('QData','Req',true);assert(sheet[3]==true)
assert(#traces==4);assert(g:loadRaw('Face')==raw and g:loadSpriteTable('QData','Req')==sheet)
assert(#traces==4 and calls==4) -- hot hits do not enter the wrapped loader at all
TH3DS=nil;g:loadRaw('Other');assert(#traces==4)
''')

if __name__=='__main__':unittest.main()
