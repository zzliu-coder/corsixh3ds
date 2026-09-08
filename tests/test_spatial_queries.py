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
local me={world={map={th=th},entity_map={getObjectsAtCoordinate=function(_,x,y)return cells[x][y]end,peekObjectsAtCoordinate=function(_,x,y)return cells[x][y]end}}}
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
local visited={}
assert(improved(me,2,'litter',function(owner,obj)assert(owner==me);visited[#visited+1]=obj end)==nil)
assert(#visited==#a)
for i,obj in ipairs(a)do assert(obj==visited[i])end
print('PASS occupied query original_native_calls='..old_count..' candidate_native_calls='..new_count)
'''
            original_staff=(reference/'CorsixTH/Lua/entities/humanoids/staff.lua').read_text()
            candidate_staff=(generated/'CorsixTH/Lua/entities/humanoids/staff.lua').read_text()
            start=original_staff.index('  for _, litter in ipairs(self:findObjectsInSquare(2, "litter"))')
            old_litter=original_staff[start:original_staff.index('\n  end',start)+6]
            start=candidate_staff.index('local function apply_litter_happiness')
            new_litter=candidate_staff[start:candidate_staff.index('\nend',start)+4]
            humanoid=(reference/'CorsixTH/Lua/entities/humanoid.lua').read_text()
            start=humanoid.index('function Humanoid:changeAttribute(')
            change=humanoid[start:humanoid.index('\nend',start)+4]
            script += '\n'+change+'\n'+new_litter+'\nlocal function reference_litter(self)\n'+old_litter+'\nend\n'
            script += r'''
class={is=function(obj,kind)return obj.humanoid_class==kind end}
Receptionist="Receptionist"
me.world.map.level_config={payroll={MaxSalary=1000}}
for _,initial in ipairs{0,0.0001,0.5,1}do for _,kind in ipairs{"Doctor","Receptionist","max-pay"}do
  local touched={}
  local litters={}
  for i=1,6 do litters[i]={id='litter',anyLitter=function()touched[#touched+1]=i;return i%2==0 end}end
  cells[10][8]=litters;me.tile_x=10;me.tile_y=8
  local snapshots={}
  for _,optimized in ipairs{false,true}do
    me.attributes={happiness=initial};me.humanoid_class=kind
    me.profile={wage=kind=="max-pay" and 1000 or 10}
    me.changeAttribute=Humanoid.changeAttribute;me.findObjectsInSquare=optimized and improved or original
    touched={}
    -- Other cells contain query-only fixture objects: constrain both queries.
    local before_size=th.size
    local saved_cell=cells[10][8];local saved_rooms=rooms
    me.tile_x=1;me.tile_y=1
    me.world.entity_map={getObjectsAtCoordinate=function()return saved_cell end,
      peekObjectsAtCoordinate=function()return saved_cell end}
    th.size=function()return 1,1 end;rooms={{1}}
    if optimized then me:findObjectsInSquare(2,'litter',apply_litter_happiness)
    else reference_litter(me)end
    snapshots[#snapshots+1]={value=me.attributes.happiness,order=table.concat(touched,',')}
    th.size=before_size;rooms=saved_rooms
  end
  assert(snapshots[1].value==snapshots[2].value and snapshots[1].order==snapshots[2].order)
end end
print('PASS actual staff litter effect ordered clamping equivalent')
'''
            test_lua_runtime.LuaRuntimeTests.setUpClass()
            test_lua_runtime.LuaRuntimeTests().run_lua(script)
