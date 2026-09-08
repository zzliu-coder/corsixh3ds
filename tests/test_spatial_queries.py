"""Compare the actual original/assembled Lua search, including list order."""
from pathlib import Path
import tempfile
import unittest
from support.pinned_upstream import generated_sources,original_sources
import test_lua_runtime

class SpatialQueryTests(unittest.TestCase):
    def test_real_query_equivalence_and_native_call_reduction(self):
        with tempfile.TemporaryDirectory(prefix='cth-spatial-') as d:
            d=Path(d);generated=generated_sources(d);reference=original_sources(d/'reference')
            methods=[]
            for label,root in [('original',reference),('improved',generated)]:
                text=(root/'CorsixTH/Lua/entities/humanoid.lua').read_text()
                begin=text.index('function Humanoid:findObjectsInSquare(')
                methods.append('Humanoid={}\n'+text[begin:text.index('\nend',begin)+4]+'\nlocal '+label+'=Humanoid.findObjectsInSquare')
            script='\n'.join(methods)+r'''
local rooms,cells={},{}
local query_count=0
for x=1,20 do rooms[x]={};cells[x]={};for y=1,17 do
 rooms[x][y]=x<10 and 1 or 2;cells[x][y]={}
 if (x*17+y)%11==0 then cells[x][y]={{id='litter',tag=x..':'..y},{id='bench'},{id='litter'}} end
end end
local th={size=function()return 20,17 end,getRoomId=function(_,x,y)query_count=query_count+1;return rooms[x][y] end}
local me={world={map={th=th},entity_map={getObjectsAtCoordinate=function(_,x,y)return cells[x][y]end}}}
local old_count,new_count=0,0
for x=1,20 do for y=1,17 do for _,size in ipairs{-2,0,1,2,5,40} do
 for _,spec in ipairs{'litter',{'bench','litter','missing'}} do
  me.tile_x=x;me.tile_y=y;query_count=0;local a=original(me,size,spec);old_count=old_count+query_count
  query_count=0;local b=improved(me,size,spec);new_count=new_count+query_count
  if type(spec)=='string' then a={litter=a};b={litter=b} end
  for key,list in pairs(a)do assert(#list==#b[key]);for i,obj in ipairs(list)do assert(obj==b[key][i])end end
 end
end end end
assert(new_count<old_count/3,'no material room-query reduction')
me.tile_x=10;me.tile_y=8;rooms[9][8]=2;cells[9][8]={{id='litter'}}
local a,b=original(me,2,'litter'),improved(me,2,'litter');assert(#a==#b)
for i,obj in ipairs(a)do assert(obj==b[i])end
print('PASS occupied query original_native_calls='..old_count..' candidate_native_calls='..new_count)
'''
            test_lua_runtime.LuaRuntimeTests.setUpClass()
            test_lua_runtime.LuaRuntimeTests().run_lua(script)
