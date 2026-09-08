"""Real generated EntityMap: sparse ownership, legacy migration and equivalence."""
from pathlib import Path
import tempfile
import unittest
from support.pinned_upstream import generated_sources, original_sources
import test_lua_runtime

def index_script(reference, generated):
    return r'''
class=setmetatable({is=function(e,k)return e.kind==k end},
  {__call=function(_,name)_G[name]={}end})
Humanoid="human";Object="object";Patient="patient"
table_merge=function(a,b)local r={};for _,v in ipairs(a)do r[#r+1]=v end;for _,v in ipairs(b)do r[#r+1]=v end;return r end
''' + (reference/'CorsixTH/Lua/entity_map.lua').read_text() + '''
local reference_index=EntityMap
''' + (generated/'CorsixTH/Lua/entity_map.lua').read_text() + r'''
local candidate_index=EntityMap
local function make(proto,width,height)
  local obj=setmetatable({},{__index=proto})
  obj:EntityMap({th={size=function()return width,height end}})
  return obj
end
local function count(root)
  local seen,n={},0
  local function visit(t)
    if type(t)~="table" or seen[t] then return end
    seen[t]=true;n=n+1
    for _,v in pairs(t)do visit(v)end
  end
  visit(root);return n
end
collectgarbage("collect")
local before=collectgarbage("count")
local dense=make(reference_index,128,128)
local dense_kib=collectgarbage("count")-before
collectgarbage("collect");before=collectgarbage("count")
local sparse=make(candidate_index,128,128)
local sparse_kib=collectgarbage("count")-before
assert(count(dense.entity_map)==49281)
assert(count(sparse.entity_map)==129)
for x=1,128 do for y=1,128 do
  assert(#sparse:peekHumanoidsAtCoordinate(x,y)==0)
  assert(#sparse:peekObjectsAtCoordinate(x,y)==0)
end end
assert(count(sparse.entity_map)==129,'reading empty cells materialized them')
local empty=sparse:peekObjectsAtCoordinate(1,1)
assert(not pcall(function()empty[1]={}end))
assert(not pcall(table.insert,empty,{}))
assert(not pcall(sparse.peekObjectsAtCoordinate,sparse,0,1))
assert(not pcall(sparse.peekObjectsAtCoordinate,sparse,129,1))
local a,b=make(reference_index,20,17),make(candidate_index,20,17)
local entities={}
local seed=12345
local function next_int(maximum)
  seed=(seed*48271)%2147483647;return seed%maximum+1
end
local function check(x,y)
  for _,kind in ipairs{"Humanoids","Objects"}do
    local expected=a["get"..kind.."AtCoordinate"](a,x,y)
    local actual=b["peek"..kind.."AtCoordinate"](b,x,y)
    assert(#expected==#actual)
    for i,obj in ipairs(expected)do assert(actual[i]==obj)end
  end
end
for i=1,4000 do
  local id=next_int(120);local e=entities[id]
  if e then a:removeEntity(e.x,e.y,e);b:removeEntity(e.x,e.y,e)
  else e={kind=id%2==0 and Humanoid or Object};entities[id]=e end
  e.x=next_int(20);e.y=next_int(17)
  a:addEntity(e.x,e.y,e);b:addEntity(e.x,e.y,e)
  if i%100==0 then for x=1,20 do for y=1,17 do check(x,y)end end end
end
-- Legacy public getters are still distinct mutable live aliases.
local c=make(candidate_index,4,4)
local alias=c:getObjectsAtCoordinate(2,2);local other=c:getObjectsAtCoordinate(2,3)
assert(alias~=other)
local object={kind=Object};c:addEntity(2,2,object);assert(alias[1]==object)
c:removeEntity(2,2,object);c:compact();assert(#alias==0)
c:addEntity(2,2,object);assert(alias==c:getObjectsAtCoordinate(2,2) and alias[1]==object)
-- Borrowed reads never keep empty cells alive after the last entity leaves.
local transient={kind=Humanoid};c:addEntity(4,4,transient);c:removeEntity(4,4,transient)
assert(c.entity_map[4][4]==nil)
-- Decode-time migration retains occupied cells and their list/object aliases.
local occupied=dense.entity_map[15][16];local objects=occupied.objects
local shared={kind=Object};objects[1]=shared;objects[2]=shared
setmetatable(dense,{__index=candidate_index});dense:compact();dense:compact()
assert(dense.entity_map[15][16]==occupied and occupied.objects==objects)
assert(objects[1]==shared and objects[2]==shared)
assert(count(dense.entity_map)==133)
print(string.format("PASS sparse index empty_tables=49281->129 host_kib=%.1f->%.1f random_operations=4000 legacy_aliases=PASS",dense_kib,sparse_kib))
-- Export the actual prepared indexes for the native writer/reader probe.
index_save_graph={index=dense,alias=occupied,objects=objects,shared=shared,legacy=c,legacy_alias=alias}
index_save_permanents={[candidate_index]="entity-index-class"}
index_load_permanents={["entity-index-class"]=candidate_index}
'''

class EntityIndexTests(unittest.TestCase):
    def test_real_sparse_index_and_ordered_migration(self):
        with tempfile.TemporaryDirectory(prefix='cth-entity-index-') as d:
            d=Path(d)
            generated=generated_sources(d)
            reference=original_sources(d/'reference')
            script=index_script(reference,generated)
            test_lua_runtime.LuaRuntimeTests.setUpClass()
            test_lua_runtime.LuaRuntimeTests().run_lua(script)
