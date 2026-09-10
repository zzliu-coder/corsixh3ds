"""Pinned dispatch/room entry/queue/walk/checkpoint methods; explicit service seams."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zlib

import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from integration import staff_handoff
from sound_lifetime import SoundPatchError


def sources():
    fixture = json.loads((ROOT / "tests/fixtures/staff_handoff_upstream.json").read_text())
    result = json.loads(zlib.decompress(base64.b64decode(fixture["sources_zlib_base64"])))
    for name, text in result.items():
        assert hashlib.sha256(text.encode()).hexdigest() == fixture["sha256"][name]
    return result


def method(text, signature):
    start = text.index(signature)
    return text[start:text.index("\nend", start) + 4]


def script():
    src = sources()
    human = (ROOT / "tests/fixtures/humanoid.lua.pinned").read_text()
    staff = (ROOT / "tests/fixtures/staff.lua.pinned").read_text()
    methods = "\n".join(method(human, "function Humanoid:" + name + "(") for name in
        ("startAction", "setNextAction", "queueAction", "finishAction", "setCallCompleted", "unexpectFromRoom"))
    methods += "\n" + method(staff, "function Staff:isIdle(")
    methods += "\n" + method(staff, "function Staff:isMeandering(")
    room_methods = "\n".join(method(src["room.lua"], "function Room:" + name + "(") for name in
        ("createEnterAction", "createLeaveAction", "onHumanoidEnter", "commandEnteringStaff"))
    prelude = [
        "strict_declare_global=function()end;destrict=function(f)return f end",
        src["class.lua"],
        "class 'Humanoid';class 'Staff'(Humanoid);class 'Doctor'(Staff);class 'Nurse'(Staff);"
        "class 'Handyman'(Staff);class 'Patient'(Humanoid);class 'Vip'(Humanoid);class 'Room'",
        "permanent=function(_)return function(f)return f end end;corsixth={require=function()end}",
        (ROOT / "tests/fixtures/r65_reception/humanoid_action.lua").read_text(), methods,
        "local walk=assert(load(" + json.dumps((ROOT / "tests/fixtures/r65_reception/walk.lua").read_text()) + "))()",
        "local answer=assert(load(" + json.dumps(src["humanoid_actions/answer_call.lua"]) + "))()",
        "class 'MeanderAction'(HumanoidAction);function MeanderAction:MeanderAction()self:HumanoidAction('meander')end",
        src["queue.lua"], room_methods,
        "local original_dispatch=" + json.dumps(src["calls_dispatcher.lua"]),
        "local candidate_dispatch=" + json.dumps(staff_handoff.patch(src["calls_dispatcher.lua"], staff_handoff.DISPATCH_SITES)),
        "local original_checkpoint=" + json.dumps(src["humanoid_actions/call_checkpoint.lua"]),
        "local candidate_checkpoint=" + json.dumps(staff_handoff.patch(src["humanoid_actions/call_checkpoint.lua"], staff_handoff.CHECKPOINT_SITES)),
        r'''
_S={dynamic_info={staff={actions={heading_for='heading %s'}}},calls_dispatcher={staff='%s %s'}}
_A={warnings={}}
local function setup(candidate, kind)
 assert(load(candidate and candidate_dispatch or original_dispatch))()
 local checkpoint=assert(load(candidate and candidate_checkpoint or original_checkpoint))()
 local h=setmetatable({action_queue={},tile_x=1,tile_y=1,profile={},empty=0},(kind=='nurse' and Nurse or Doctor)._metatable)
 function h:getRoom()return self.in_room end
 function h:getCurrentAction()return self.action_queue[1]end
 function h:fulfillsCriterion(_)return true end
 function h:getAttribute(_)return 0 end
 function h:setDynamicInfoText(text)self.info=text end
 function h:setTimer(n,fn)self.timer_function=fn;self.timer_count=n end
 function h:_handleEmptyActionQueue()self.empty=self.empty+1;self:queueAction(MeanderAction())end
 local world={entities={h},rooms={}}
 function world:getPath()return nil end -- controlled actual path failure seam
 function world:getPathDistance(x1,y1,x2,y2)
  self.distance_reads=(self.distance_reads or 0)+1
  self.distance_target={x2,y2}
  if self.exterior_only and x2==9 then return 4 end
  return self.distance
 end
 world.distance=nil
 h.hospital={policies={staff_allowed_to_move=true},giveAdvice=function()end}
 h.world=world
 local d=CallsDispatcher(world);world.dispatcher=d
 local room=setmetatable({is_active=true,world=world,hospital=h.hospital,x=10,y=10,
  humanoids={},room_info={name='GP',id='gp',required_staff={Doctor=1}},id=1},Room._metatable)
 room.door={queue=Queue(),updateDynamicInfo=function()end};world.rooms[1]=room
 function room.door.queue:reportedSize()return 0 end
 function room.door.queue:hasEmergencyPatient()return false end
 function room:getEntranceXY(inside)return inside and 10 or 9,10 end
 function world:getRoom(x,y)if x==10 and y==10 then return room end end
 function room:staffFitsInRoom()return self.fits~=false end
 function room:getStaffMember()return self.staff_member end
 function room:staffMeetsRoomRequirements()return true end
 function room:tryAdvanceQueue()end
 function room:tryToFindNearbyPatients()self.patient_search=(self.patient_search or 0)+1 end
 function room:getRequiredStaffCriteria()return self.room_info.required_staff end
 function room:testStaffCriteria()return self.humanoids[h] or false end
 function room:getMissingStaff()return {Doctor=1}end
 function room:onHumanoidLeave(person)self.humanoids[person]=nil;person.in_room=nil end
 function h:adviseWrongPersonForThisRoom()self.wrong=true end
 local handlers={walk=walk,call_checkpoint=checkpoint,answer_call=answer,
  idle=function()end,meander=function()end,service=function(a,p)p.served=(p.served or 0)+1 end}
 TheApp={humanoid_actions=handlers}
 h.action_queue[1]=MeanderAction()
 local call={object=room,key='Doctor1',dispatcher=d,description='room',
  verification=function(person)return CallsDispatcher.verifyStaffForRoom(room,'Doctor',person)end,
  priority=function(person)return CallsDispatcher.getPriorityForRoom(room,'Doctor',person)end,
  execute=function(person)return CallsDispatcher.sendStaffToRoom(room,person)end}
 d.call_queue[room]={[call.key]=call}
 return h,room,call,d,handlers
end
local function assign(h,c,d)d:executeCall(c,h);assert(h.action_queue[1].name=='walk')end
local function finish_walk(h)assert(h.timer_function);local fn=h.timer_function;h.timer_function=nil;fn(h)end
''',
    ]
    return "\n".join(prelude)


class StaffHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.lua = test_lua_runtime.LuaRuntimeTests.lua

    def run_lua(self, body):
        test_lua_runtime.LuaRuntimeTests.run_lua(self, script() + body)

    def test_original_unreachable_red_and_candidate_bounded_reassignment(self):
        self.run_lua(r'''
local h,r,c,d=setup(false);assign(h,c,d);finish_walk(h)
assert(h.empty==1 and c.dropped and not h.on_call,'original risk must reproduce')
for _,kind in ipairs({'doctor','nurse'})do
 h,r,c,d=setup(true,kind);assign(h,c,d)
 TH3DS={diagnostic_line=function(line)assert(#line<=230);error('diagnostic failure')end}
 assert(r.door.queue.expected[h]);finish_walk(h)
 TH3DS=nil
 assert(h.empty==0 and not c.dropped and not c.assigned and not h.on_call)
 assert(d.call_queue[r][c.key]==c and not r.door.queue.expected[h])
 assert(#h.action_queue==1 and h.action_queue[1].name=='meander')
 for i=1,100 do assert(not d:answerCall(h))end
 -- Restore reachability: the same retained demand dispatches normally.
 h.world.distance=4;assert(d:answerCall(h));assert(c.assigned==h and h.on_call==c)
end
''')

    def test_real_room_entry_and_same_room_keep_service_owner(self):
        self.run_lua(r'''
for _,same in ipairs({false,true})do
 for _,kind in ipairs({'doctor','nurse'})do
  local h,r,c,d=setup(true,kind)
  if same then h.in_room=r;r.humanoids[h]=true end
  d:executeCall(c,h)
  if not same then r:onHumanoidEnter(h)end
  assert(c.dropped and not c.assigned and not h.on_call and h.empty==0)
  assert(r.humanoids[h] and r.staff_member==h and r.patient_search==1)
  assert(h.action_queue[1].name=='meander' and #h.action_queue==1)
  assert(d.call_queue[r]==nil or d.call_queue[r][c.key]==nil)
 end
end
''')

    def test_room_priority_matches_walk_destination_without_extra_search(self):
        self.run_lua(r'''
local h,r,c,d=setup(false);h.world.exterior_only=true
assert(c.priority(h)~=nil,'original chooses reachable exterior only')
h,r,c,d=setup(true);h.world.exterior_only=true
assert(c.priority(h)==nil and h.world.distance_reads==1)
assert(h.world.distance_target[1]==10 and h.world.distance_target[2]==10)
assert(not d:findSuitableStaff(c) and not h.on_call)
-- Legitimate zero distance remains usable, including a member already inside.
h.world.distance=0;assert(type(c.priority(h))=='number')
''')

    def test_closed_room_replacement_and_external_interrupt(self):
        self.run_lua(r'''
local h,r,c,d=setup(true);assign(h,c,d);r.is_active=false;finish_walk(h)
assert(h.empty==0 and not c.assigned and not h.on_call and not d:answerCall(h))
-- Existing normal rejection path owns leave + wander and cancels assignment.
h,r,c,d=setup(true);assign(h,c,d);r.is_active=false;r:onHumanoidEnter(h)
assert(not h.on_call and not c.assigned and h.empty==0)
assert(h.action_queue[1].name=='walk' and h.action_queue[2].name=='meander')
-- Ordinary external cancellation uses the original interrupt protocol.
h,r,c,d=setup(true);assign(h,c,d);h:setNextAction(MeanderAction())
assert(not h.on_call and not c.assigned and not r.door.queue.expected[h])
assert(h.empty==0 and #h.action_queue==1)
''')

    def test_stale_checkpoint_preserves_new_owner_and_saved_tail(self):
        self.run_lua(r'''
local h,r,c,d,handlers=setup(true);assign(h,c,d)
local checkpoint=h.action_queue[2]
local tail={name='service'};h:queueAction(tail)
-- Native-style reconstructed action instance keeps the registered on_remove.
setmetatable(checkpoint,{__index=CallCheckPointAction})
finish_walk(h)
assert(h.empty==0 and h.served==1 and h.action_queue[1]==tail and #h.action_queue==1)
assert(not c.dropped and not c.assigned)
-- Stale saved checkpoint cannot clear another person's current assignment.
h,r,c,d=setup(true);assign(h,c,d)
local other={on_call=c};c.assigned=other;h.on_call=nil
finish_walk(h)
assert(c.assigned==other and other.on_call==c and not c.dropped and h.empty==0)
''')

    def test_real_room_replacement_and_busy_incumbent_refusal(self):
        self.run_lua(r'''
for _,busy in ipairs({false,true})do
 local h,r,c,d=setup(true);assign(h,c,d)
 local old=setmetatable({},Doctor._metatable)
 for key,value in pairs(h)do old[key]=value end
 old.action_queue={{name='service'}};old.on_call=nil;old.in_room=r
 old.profile={};old.dealing_with_patient=busy
 r.humanoids[old]=true;r.staff_member=old;r.fits=false
 r:onHumanoidEnter(h)
 if not busy then
  assert(r.staff_member==h and c.dropped and not h.on_call)
  assert(old.action_queue[1].name=='walk' and old.action_queue[2].name=='meander')
  assert(h.action_queue[1].name=='meander' and r.patient_search==1)
 else
  assert(r.staff_member==old and not h.on_call and not c.assigned)
  assert(old.action_queue[1].name=='service' and #old.action_queue==1)
  assert(h.action_queue[1].name=='walk' and h.action_queue[2].name=='meander')
 end
 assert(h.empty==0 and old.empty==0)
end
''')

    def test_other_call_completion_and_unreachable_preemption(self):
        self.run_lua(r'''
local h,r,c,d=setup(true);c.assigned=h;h.on_call=c
h.action_queue={CallCheckPointAction(c,CallsDispatcher.actionInterruptHandler),{name='service'}}
h:startAction();assert(c.dropped and h.served==1 and h.empty==0)
-- A prior assignee whose route disappears has nil priority. A reachable staff
-- can preempt without nil <= number or deleting the call.
h,r,c,d=setup(true);h.world.distance=4
local previous={on_call=c,setNextAction=function(self,a)self.next=a end}
c.assigned=previous;c.priority=function(p)if p==h then return 4 end end
assert(d:answerCall(h));assert(c.assigned==h and previous.on_call==nil)
assert(previous.next.name=='answer_call')
''')

    def test_transform_idempotence_pair_contract_and_drift(self):
        src=sources()
        for name, sites in [('calls_dispatcher.lua', staff_handoff.DISPATCH_SITES),
                            ('humanoid_actions/call_checkpoint.lua', staff_handoff.CHECKPOINT_SITES)]:
            patched=staff_handoff.patch(src[name],sites)
            self.assertEqual(staff_handoff.patch(patched,sites),patched)
            with self.assertRaises(SoundPatchError):
                staff_handoff.patch(src[name].replace(sites[0][0], '-- drift'),sites)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(list(staff_handoff.transforms(root)),[])
            path=root/staff_handoff.DISPATCH;path.parent.mkdir(parents=True)
            path.write_text(src['calls_dispatcher.lua'])
            with self.assertRaises(SoundPatchError):list(staff_handoff.transforms(root))
            path=root/staff_handoff.CHECKPOINT;path.parent.mkdir(parents=True)
            path.write_text(src['humanoid_actions/call_checkpoint.lua'])
            self.assertEqual(len(list(staff_handoff.transforms(root))),2)


if __name__ == '__main__':
    unittest.main()
