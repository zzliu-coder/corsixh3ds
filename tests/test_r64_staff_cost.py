"""Execute pinned and generated staff methods; no shared generated-tree writes."""
from pathlib import Path
import tempfile
import unittest
from support.pinned_upstream import generated_sources, original_sources
import test_lua_runtime


def method(text, signature):
    begin = text.index(signature)
    return text[begin:text.index('\nend', begin) + 4]


class R64StaffCost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp = tempfile.TemporaryDirectory(prefix='cth-r64-staff-')
        cls.directory = Path(cls.temp.name)
        cls.original = original_sources(cls.directory / 'reference')
        cls.generated = generated_sources(cls.directory / 'assembly')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def script(self):
        script = "class={is=function(s,c)return s and s.kind==c end}; Receptionist='receptionist'; Handyman='handyman'; StaffRoom='staff_room'\n"
        for label, root in [('before', self.original), ('after', self.generated)]:
            staff = (root / 'CorsixTH/Lua/entities/humanoids/staff.lua').read_text()
            human = (root / 'CorsixTH/Lua/entities/humanoid.lua').read_text()
            script += 'local ' + label + '\ndo\nlocal Humanoid,Entity,Staff={},{},{}\n'
            script += 'setmetatable(Staff,{__index=Humanoid})\n'
            script += 'local speed_crack_up, speed_very_tired, speed_get_attribute\n'
            for name in ['getAttribute', 'changeAttribute', 'getRoom', 'getCurrentAction']:
                script += method(human, 'function Humanoid:' + name + '(') + '\n'
            # The fixed fixture contains Humanoid and Staff; Entity/world form
            # the spatial boundary, outside this staff-method comparison.
            script += 'function Entity:getRoom()return self.world:getRoom(self.tile_x,self.tile_y)end\n'
            for name in ['isVeryTired', 'isCrackUpTired', 'updateSpeed', 'checkIfNeedRest', 'goToStaffRoom']:
                script += method(staff, 'function Staff:' + name + '(') + '\n'
            if label == 'after':
                start = staff.index('speed_crack_up, speed_very_tired = Staff.')
                script += staff[start:staff.index('\n', staff.index('speed_get_attribute =', start))] + '\n'
            script += label + '={staff=Staff,human=Humanoid}\nend\n'
        return script + r'''
local function snapshot(v)
 if type(v)~='table' then return type(v)..':'..tostring(v) end
 local keys={}; for k,x in pairs(v) do if type(x)~='function' then keys[#keys+1]=k end end
 table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
 local out={};for _,k in ipairs(keys)do out[#out+1]=tostring(k)..'='..snapshot(v[k])end
 return '{'..table.concat(out,',')..'}'
end
SeekStaffRoomAction=function()return{name='seek_staffroom'}end
local function create(api,kind,fatigue,roomid,flag,action,cheat,rank)
 local room=roomid and {kind=roomid,room_info={id=roomid},patient=flag==5} or nil
 if room then
  function room:getPatient()return self.patient end
  function room:createLeaveAction()return{name='leave',room=self.room_info.id}end
 end
 local s=setmetatable({kind=kind,humanoid_class=kind,profile={profession=kind,wage=10,
   is_junior=rank==1,is_consultant=rank==3},attributes={fatigue=fatigue,happiness=0.5},
   tile_x=1,tile_y=1,action_queue={{name=action}},trace={},
   waiting_for_staffroom=flag==1 or nil,staffroom_needed=flag==2 or nil,
   going_to_staffroom=flag==3 or nil,pickup=flag==4 or nil,
   hospital={policies={goto_staffroom=0.6},hosp_cheats={isCheatActive=function()return cheat end}},
   world={room=room,map={level_config={gbv={VeryTired=700,CrackUpTired=800},payroll={MaxSalary=100}}}}},
   {__index=api.staff})
 function s.world:getRoom()return self.room end
 function s.world:findRoomNear()return flag~=6 end
 function s:fulfillsCriterion(c)return c=='Doctor' and self.kind=='doctor' end
 function s:setMood(k,v)self.trace[#self.trace+1]='mood:'..k..':'..v end
 function s:setNextAction(a)self.action_queue={a};self.trace[#self.trace+1]='next:'..a.name end
 function s:queueAction(a)self.action_queue[#self.action_queue+1]=a;self.trace[#self.trace+1]='queue:'..a.name end
 return s
end
local function equal(a,b,where)assert(snapshot(a)==snapshot(b),where..'\n'..snapshot(a)..'\n'..snapshot(b))end
'''

    def test_actual_methods_boundaries_queues_and_saved_fields(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script() + r'''
local count=0
for _,n in ipairs{1,15,17,32} do
 for _,kind in ipairs{'doctor','nurse','handyman','receptionist'} do
  for _,f in ipairs{0,0.599999,0.6,0.699999,0.7,0.700001,0.799999,0.8,0.800001,1}do
   for _,rid in ipairs{false,'training','ward','gp','staff_room'}do
     for _,cheat in ipairs{false,true}do
      -- Every population executes multiple updates, with state compared after each.
      for ordinal=1,n do
       local flag=(ordinal-1)%7
       local action=({'idle','walk','queue'})[(ordinal-1)%3+1]
       local rank=(ordinal-1)%3+1
       local a=create(before,kind,f,rid,flag,action,cheat,rank)
       local b=create(after,kind,f,rid,flag,action,cheat,rank)
       for tick=1,2 do
        a:updateSpeed();b:updateSpeed();equal(a,b,'speed')
        a:checkIfNeedRest();b:checkIfNeedRest();equal(a,b,'rest')
        count=count+1
       end
      end
     end
   end
  end
 end
end
-- Reversed thresholds preserve crack-up priority; maximum salary keeps happiness.
for _,api in ipairs{before,after}do
 local s=create(api,'doctor',0.75,false,1,'idle',false,3)
 s.world.map.level_config.gbv={VeryTired=900,CrackUpTired=700}
 s.profile.wage=100;s:updateSpeed();s:checkIfNeedRest()
 assert(s.speed=='slow' and s.attributes.happiness==1)
end
print('PASS actual staff methods: '..count..' paired steps, populations 1/15/17/32, all persistent fixture fields and action traces')
''')

    def test_virtual_fallback_rng_and_room_side_effects(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script() + r'''
for mode=1,6 do
 local results={}
 for _,api in ipairs{before,after}do
  math.randomseed(12345)
  local s=create(api,'doctor',0.72,'gp',mode==5 and 1 or 0,'idle',false,3)
  if mode==1 then
   function s:isCrackUpTired()self.trace[#self.trace+1]=math.random();return false end
   function s:isVeryTired()self.trace[#self.trace+1]=math.random();return true end
  elseif mode==2 then
   function s:isCrackUpTired()self.trace[#self.trace+1]=math.random();return true end
   function s:isVeryTired()error('must short circuit')end
  elseif mode==3 then
   function s:getAttribute(k)self.trace[#self.trace+1]=math.random();return self.attributes[k]end
  elseif mode==4 then
   function s:getRoom()self.trace[#self.trace+1]=math.random();return self.world.room end
  elseif mode==5 then
   function s:changeAttribute(k,v)api.human.changeAttribute(self,k,v)
    self.trace[#self.trace+1]=math.random();self.world.room=nil
   end
  else
   function s:isVeryTired()self.trace[#self.trace+1]=math.random();return true end
  end
  s:updateSpeed()
  if mode~=2 then s:checkIfNeedRest() end
  s.trace[#s.trace+1]=math.random();results[#results+1]=snapshot(s)
 end
 assert(results[1]==results[2],'virtual fallback '..mode)
end
print('PASS virtual tiredness, attribute and room overrides, changeAttribute room mutation, RNG sequence')
''')

    def test_query_counts_and_repeatable_host_microbench(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script() + r'''
local queries={}
for _,api in ipairs{before,after}do
 local s=create(api,'doctor',0.5,false,0,'idle',false,2)
 local attribute,room=0,0
 debug.sethook(function()
  local f=debug.getinfo(2,'f').func
  if f==api.human.getAttribute then attribute=attribute+1 end
  if f==api.human.getRoom then room=room+1 end
 end,'c')
 s:updateSpeed()
 debug.sethook()
 queries[#queries+1]={attribute,room}
end
assert(queries[1][1]==2 and queries[2][1]==1)
assert(queries[1][2]==1 and queries[2][2]==1)
for index,api in ipairs{before,after}do
 local s=create(api,'nurse',0.65,'gp',2,'walk',false,2)
 local count=0
 debug.sethook(function()if debug.getinfo(2,'f').func==api.human.getRoom then count=count+1 end end,'c')
 s:checkIfNeedRest();debug.sethook()
 assert(count==(index==1 and 2 or 1),'rest query count '..count)
end
local function benchmark(api,n,fatigue)
 local staff={};for i=1,n do staff[i]=create(api,({'doctor','nurse','handyman','receptionist'})[(i-1)%4+1],fatigue,false,0,'idle',false,2)end
 local begin=os.clock()
 for tick=1,12000 do for i=1,n do staff[i]:updateSpeed() end end
 return os.clock()-begin
end
for _,fatigue in ipairs{0.5,0.75,0.85}do for _,n in ipairs{1,15,17,32}do
 local old,new={},{}
 for rep=1,5 do
  collectgarbage('collect');old[rep]=benchmark(before,n,fatigue)
  collectgarbage('collect');new[rep]=benchmark(after,n,fatigue)
 end
 table.sort(old);table.sort(new)
 print(string.format('HOST MICROBENCH speed staff=%d fatigue=%.2f iterations=12000 median5 before=%.6fs after=%.6fs ratio=%.3f',n,fatigue,old[3],new[3],new[3]/old[3]))
end end
print('PASS speed fatigue queries 2->1; rest room queries 2->1; timing is host-only evidence')
''')


if __name__ == '__main__':
    unittest.main()
