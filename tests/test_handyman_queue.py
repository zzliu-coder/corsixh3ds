"""Real queue/method decisions; walking/idle rendering and hospital task lookup are seams."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from integration import handyman_queue
from sound_lifetime import SoundPatchError


def method(text, signature):
    start = text.index(signature)
    return text[start:text.index("\nend", start) + 4]


def script():
    fixture = json.loads((ROOT / "tests/fixtures/handyman_queue_upstream.json").read_text())
    sources = fixture["sources"]
    for name, source in sources.items():
        assert hashlib.sha256(source.encode()).hexdigest() == fixture["sha256"][name]
    human = (ROOT / "tests/fixtures/humanoid.lua.pinned").read_text()
    staff = (ROOT / "tests/fixtures/staff.lua.pinned").read_text()
    actions = (ROOT / "tests/fixtures/r65_reception/humanoid_action.lua").read_text()
    walk = (ROOT / "tests/fixtures/r65_reception/walk.lua").read_text()
    originals = sources["entities/humanoids/staff/handyman.lua"]
    methods = "\n".join(method(human, "function Humanoid:" + name + "(")
                        for name in ["startAction", "queueAction", "finishAction", "setNextAction"])
    methods += "\n" + "\n".join(method(staff, "function Staff:" + name + "(")
                                for name in ["isMeandering", "isIdle"])
    walk_ctor = method(walk, "function WalkAction:WalkAction(")
    # Lua class and all decisions below are the actual pinned source. Graphics,
    # pathfinder result, and task-table lookup remain explicit bounded seams.
    return "\n".join([
        "local reference=" + json.dumps(originals),
        "local candidate=" + json.dumps(handyman_queue.patch(originals)),
        "local function setup(source)",
        "strict_declare_global=function()end;destrict=function(f)return f end",
        sources["class.lua"],
        "class 'Humanoid';class 'Staff'(Humanoid);class 'Doctor'(Staff);class 'Nurse'(Staff)",
        "permanent=function(_)return function(f)return f end end;corsixth={require=function()end}",
        actions,
        "class 'WalkAction'(HumanoidAction)", walk_ctor,
        "class 'IdleAction'(HumanoidAction);function IdleAction:IdleAction()self:HumanoidAction('idle')end",
        "class 'SweepFloorAction'(HumanoidAction);function SweepFloorAction:SweepFloorAction(o)self:HumanoidAction('sweep_floor');self.target=o end",
        methods,
        "assert(load(source))()",
        "local meander=assert(load(" + json.dumps(sources["humanoid_actions/meander.lua"]) + "))()",
        "CallsDispatcher={onCheckpointCompleted=function()end}",
        "function CallsDispatcher:answerCall(h)h:searchForHandymanTask();return true end",
        "local answer=assert(load(" + json.dumps(sources["humanoid_actions/answer_call.lua"]) + "))()",
        r'''
 local h=setmetatable({action_queue={},tile_x=10,tile_y=10,parcelNr=0,
  searches=0,walks=0,idles=0,sweeps=0,room_reads=0},Handyman._metatable)
 function h:getRoom()self.room_reads=self.room_reads+1;return self.room end
 function h:getCurrentAction()return self.action_queue[1]end
 function h:getAttribute()return 1/3 end
 function h:setDynamicInfoText()end
 function h:_handleEmptyActionQueue()error('unexpected empty action queue')end
 h.hospital={searchForHandymanTask=function(_,person,kind)
  h.searches=h.searches+1
  if h.work_available and kind=='cleaning' then return 1 end
  return -1
 end,assignHandymanToTask=function()h.work_available=false;return{tile_x=25,tile_y=11,object={}}end}
 h.world={dispatcher=CallsDispatcher,pathfinder={findIdleTile=function(_,x,y)
  return x+1,y end}}
 local handlers={meander=meander,answer_call=answer,
  idle=function(_,p)p.idles=p.idles+1 end,
  walk=function(a,p)p.walks=p.walks+1;p.tile_x,p.tile_y=a.x,a.y end,
  sweep_floor=function(_,p)p.sweeps=p.sweeps+1 end}
 TheApp={humanoid_actions=handlers}
 h.action_queue[1]=MeanderAction()
 return h,handlers
end
local function ordinary(h)
 return #h.action_queue==2 and h.action_queue[2].name=='meander'
  and (h.action_queue[1].name=='walk' or h.action_queue[1].name=='idle')
end
''',
    ])


class HandymanQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.lua = test_lua_runtime.LuaRuntimeTests.lua

    def run_lua(self, body):
        test_lua_runtime.LuaRuntimeTests.run_lua(self, script() + body)

    def test_no_task_1000_cycles_preserve_rng_search_and_movement(self):
        self.run_lua(r'''
local real_random=math.random
local function run(source)
 local h=setup(source);math.randomseed(1207)
 local rng={};math.random=function(...)
  local n=real_random(...);rng[#rng+1]=n;return n end
 h:startAction()
 for i=1,1000 do
  assert(h.action_queue[1].name=='idle' or h.action_queue[1].name=='walk')
  h:finishAction(h.action_queue[1])
 end
 math.random=real_random
 return h,rng
end
local before,br=run(reference);local after,ar=run(candidate)
assert(#before.action_queue==1003,'red oracle must retain original accumulation')
assert(ordinary(after) and #after.action_queue==2)
assert(before.searches==after.searches and before.walks==after.walks and before.idles==after.idles)
assert(before.tile_x==after.tile_x and before.tile_y==after.tile_y)
assert(#br==#ar);for i=1,#br do assert(br[i]==ar[i],'RNG changed at '..i)end
''')

    def test_controlled_and_room_actions_preserve_original_fallback(self):
        self.run_lua(r'''
local function shape(h)
 local r={};for i,a in ipairs(h.action_queue)do r[i]=a.name end;return table.concat(r,',')end
local setters={
 function(a)a.count=0 end,function(a)a.count=3 end,
 function(a)a.loop_callback=function()end end,function(a)a.after_use=function()end end,
 function(a)a.todo_interrupt=true end,function(a)a.must_happen=true end,
 function(a)a.on_interrupt=function()end end,function(a)a.on_remove=function()end end,
 function(a)a.uninterruptible=true end,function(a)a.is_leaving=true end,
 function(a)a.no_truncate=true end,
 function(a)setmetatable(a,{__index={}})end,
 function(a)a.name='answer_call'end,function(a)a.name='sweep_floor'end,
 function(a)a.name='walk'end,function(a)a.name='idle'end}
for _,change in ipairs(setters)do
 local a=setup(reference);change(a.action_queue[1]);local original=a.action_queue[1]
 a:doMeandering();local result=shape(a);assert(a.action_queue[1]==original)
 local b=setup(candidate);change(b.action_queue[1]);original=b.action_queue[1]
 b:doMeandering();assert(shape(b)==result and b.action_queue[1]==original)
 assert(a.room_reads==b.room_reads)
end
for _,source in ipairs({reference,candidate})do
 local h=setup(source)
 h.room={room_info={id='staff_room'},createLeaveAction=function()return{name='leave'}end}
 h:doMeandering();assert(shape(h)=='meander,leave,meander' and h.room_reads==2)
end
-- Existing walking/idle continuations retain the original no-op, no room lookup.
for _,name in ipairs({'walk','idle'})do
 local h=setup(candidate);table.insert(h.action_queue,1,{name=name})
 h:doMeandering();assert(#h.action_queue==2 and h.room_reads==0)
end
''')

    def test_task_arrival_and_saved_tail_keep_order_and_identity(self):
        self.run_lua(r'''
local h=setup(candidate);local original=h.action_queue[1]
local saved_tail=MeanderAction();h.action_queue[2]=saved_tail
local queue=h.action_queue
for i=1,1000 do h:searchForHandymanTask()end
assert(h.action_queue==queue and #queue==2 and queue[1]==original and queue[2]==saved_tail)
-- Recreated per-instance metatable after native persistence still names same class.
setmetatable(original,{__index=MeanderAction})
h:doMeandering();assert(#queue==2 and queue[1]==original and queue[2]==saved_tail)
h.work_available=true
assert(h:searchForHandymanTask())
assert(#queue==3 and queue[1].name=='walk' and queue[2].name=='sweep_floor' and queue[3].name=='answer_call')
h:finishAction();assert(h.sweeps==1 and queue[1].name=='sweep_floor')
h:finishAction();assert(ordinary(h),'completion resumes useful ordinary wandering')
-- Finite meander must retain its successor and terminate at count zero.
h=setup(candidate);h.action_queue[1]:setCount(0)
h:startAction();assert(ordinary(h))
-- Loop callback is executed; its own completion semantics remain in charge.
h=setup(candidate);local calls=0
h.action_queue[1]:setLoopCallback(function()calls=calls+1 end)
h:startAction();assert(calls==1 and #h.action_queue==3)
''')

    def test_transform_owner_is_idempotent_and_drift_fails_closed(self):
        fixture = json.loads((ROOT / "tests/fixtures/handyman_queue_upstream.json").read_text())
        original = fixture["sources"]["entities/humanoids/staff/handyman.lua"]
        patched = handyman_queue.patch(original)
        self.assertEqual(patched, handyman_queue.patch(patched))
        with self.assertRaises(SoundPatchError):
            handyman_queue.patch(original.replace("function Handyman:doMeandering()", "function Handyman:doMeandering(unknown)"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);path = root / handyman_queue.SOURCE
            path.parent.mkdir(parents=True);path.write_text(original)
            self.assertEqual(list(handyman_queue.transforms(root)), [(handyman_queue.SOURCE, patched)])
        owner = (ROOT / "tools/integration/cpu_hotspots.py").read_text()
        self.assertIn("yield from handyman_queue_transforms(root)", owner)


if __name__ == "__main__":
    unittest.main()
