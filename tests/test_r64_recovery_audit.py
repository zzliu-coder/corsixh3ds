"""Run the real read-only recovery audit in Lua, including corrupt save fields."""
from pathlib import Path
import unittest
import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]


class R64RecoveryAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def script(self):
        return 'local H=dofile(' + repr(str(ROOT / 'lua/3ds/state_health.lua')) + ')\n' + r'''
-- Upstream class.is walks class metatables; use that actual classification rule.
class={}
function class.is(instance, class)
 local typ=type(instance)
 if typ~='table' and typ~='userdata' then return false end
 local methods=instance
 while methods do
  if methods==class then return true end
  local mt=getmetatable(methods);methods=mt and mt.__index
 end
 return false
end
Staff={};Patient={}
local forbidden=0
local function fail()forbidden=forbidden+1;error('must not call entity/action methods')end
Staff.getCurrentAction=fail;Staff.getRoom=fail;Staff.updateSpeed=fail
local callback=assert(load('return function(entity) error("must not run timer") end',
 '@private/location/humanoid_actions/walk.lua'))()
local function world(n)
 local w={entities={},game_log={
  'Error in timer handler: ',
  "sdmc:/3ds/corsixth/Lua/entities/humanoids/staff.lua:127: use of undeclared variable 'TH3DS'",
  'Recovering from error in timer handler...'}}
 local hospital={world=w,staff={}}
 for i=1,n do
  local e=setmetatable({world=w,hospital=hospital,ticks=true,humanoid_class='Doctor',
   profile={profession='Doctor',private_name='MUST_NOT_APPEAR'},timer_time=12,timer_function=callback,
   action_queue={{name='walk',must_happen=false,uninterruptible=true,todo_interrupt=false,
    path_index=2,path_x={1,2,3},path_y={4,5,6},on_interrupt=fail,on_restart=callback}},
   fired=false,dead=false,pickup=false,destroyed=false},{__index=Staff})
  w.entities[i]=e;hospital.staff[i]=e
 end
 return w
end
-- Retain exact original identities/field values of every reachable table.
-- This checks the full fixture graph, including cycles, timer and queue aliases.
local function frozen(root)
 local saved={}
 local function visit(t)
  if type(t)~='table' or saved[t] then return end
  local copy={};saved[t]=copy
  for k,v in next,t do copy[k]=v;visit(k);visit(v)end
 end
 visit(root)
 return function()
  for t,copy in next,saved do
   for k,v in next,copy do assert(rawget(t,k)==v,'changed field '..tostring(k))end
   for k,v in next,t do assert(rawget(copy,k)==v,'added field '..tostring(k))end
  end
  assert(forbidden==0)
 end
end
local function audit(w)
 local check=frozen(w);local rows={}
 local result=H.auditR62(w,function(s)
  assert(type(s)=='string' and #s<=230 and not s:find('[\r\n]'))
  rows[#rows+1]=s
 end)
 check();assert(result.lines==#rows)
 for _,v in pairs(result)do assert(type(v)=='number' or type(v)=='boolean')end
 return result,table.concat(rows,'\n'),rows
end
'''

    def test_nil_timer_is_world_index_15_and_refusal_unchanged(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script() + r'''
local w=world(15);w.entities[15].ticks=false
w.entities[15].timer_time=nil;w.entities[15].timer_function=nil
local check=frozen(w)
local ok,reason=pcall(H.repairR62,w)
assert(not ok and reason:find('staff has no resumable timer: 15',1,true));check()
local r,text=audit(w)
assert(r.shown==1 and r.disabled==1 and not r.truncated)
assert(text:find('idx=15',1,true) and not text:find('idx=1 ',1,true))
assert(text:find('timer_time=nil timer_type=nil',1,true))
assert(text:find('world_members=1',1,true) and text:find('staff_members=1',1,true))
assert(text:find('path_index=2 path_x=3 path_y=3',1,true))
assert(text:find('must=false uintr=true intr=false',1,true))
assert(text:find('cb_i=function cb_r=function',1,true))
assert(not text:find('MUST_NOT_APPEAR',1,true))
local ok2,reason2=pcall(H.repairR62,w);assert(not ok2 and reason2==reason);check()
print('PASS exact nil-timer index 15; original recovery refusal and full object graph unchanged')
''')

    def test_duplicate_ownership_malformed_queues_and_debug_absence(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script() + r'''
local w=world(2);local e=w.entities[1];e.ticks=false;w.entities[2]=e
e.hospital.staff={e,e};e.hospital.world={};e.world={}
e.action_queue={42,'bad',{name=string.rep('x',1000)..'\nsecret',path_x='bad',
 path_y=false,on_interrupt={},on_restart=false},false}
local r,text=audit(w)
assert(r.shown==2 and text:find('world_members=2',1,true))
assert(text:find('staff_members=2',1,true) and text:find('world_ok=false',1,true))
assert(text:find('action=1 type=number',1,true) and text:find('action=4 type=boolean',1,true))
assert(text:find('path_x=<string> path_y=<boolean>',1,true))
assert(text:find('source=walk.lua:1',1,true) and not text:find('private/location',1,true))
local old=debug;debug=nil
local _,without=audit(w);debug=old
assert(without:find('source=unavailable',1,true))
e.action_queue='broken';local _,broken=audit(w)
assert(broken:find('queue_type=string queue_len=0',1,true))
print('PASS duplicate memberships, bad world links, malformed queues, source basename, missing debug')
''')

    def test_output_and_scan_limits_emit_failure_and_no_world_retention(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script() + r'''
local w=world(30)
for _,e in ipairs(w.entities)do
 e.ticks=false
 for i=2,7 do e.action_queue[i]={name='wait'}end
end
local r,text,rows=audit(w)
assert(r.disabled==30 and r.shown==24 and r.objects_truncated and r.actions_truncated and r.truncated)
assert(#rows==24*9+1 and not text:find('idx=25 ',1,true))
local check=frozen(w);local writes=0
local ok,reason=pcall(H.auditR62,w,function()
 writes=writes+1;if writes==3 then error('emitter rejected')end
end)
assert(not ok and reason:find('emitter rejected',1,true));check()
local crowded=world(1);crowded.entities[1].ticks=false
for i=2,8300 do crowded.entities[i]={}end
local bounded=audit(crowded)
assert(bounded.scanned==8192 and bounded.scan_truncated and bounded.truncated)
local owner=world(1);owner.entities[1].ticks=false
for i=2,8300 do owner.entities[1].hospital.staff[i]=owner.entities[1]end
local limited,ownership=audit(owner)
assert(limited.membership_truncated and ownership:find('staff_members=8192+?',1,true))
local weak=setmetatable({},{__mode='v'})
do local temporary=world(1);temporary.entities[1].ticks=false;weak[1]=temporary;audit(temporary)end
collectgarbage('collect');collectgarbage('collect');assert(weak[1]==nil)
print('PASS 24-object/4-action/230-byte and 8192-entry limits; emit failure is read-only; no retained World')
''')


if __name__ == '__main__':
    unittest.main()
