"""Pinned real reception action/tick path, conservative eligibility and native saves."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/r65_reception'
sys.path.insert(0, str(ROOT / 'tools/integration'))
import staff_hotspots
# Unmodified MIT sources at upstream 56bd5d00f76331c7f76d7b696726a7926303ca0c.
HASHES = {
    'entity.lua': '92f06d2808aa77ac7fd0ae276ffb1749aee7e965accf66b65c66b7d5d6f0793c',
    'humanoid_action.lua': 'cfe26dc24a09e8bc1c315969ce9d7d80b18cd7d169363acbe168578c4ad38c0a',
    'reception_desk.lua': '1495273eb8789f8fdde19e2511cc876acd93ac2e6a9e6b75203159c60b6c44d0',
    'staff_reception.lua': 'fb75f01c22952413994b20a8ebad4989973b007091c23676e375a2ca05c9ae01',
    'walk.lua': '2f87264676d308263f98da58aa4a3c073fd83b9bd92a4446dedc5bdfa45bf372',
}


def method(text, signature):
    begin = text.index(signature)
    return text[begin:text.index('\nend', begin) + 4]


def reception_script():
    sources = {}
    for name, digest in HASHES.items():
        data = (FIXTURE / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name
        sources[name] = data.decode()
    script = r'''
class=setmetatable({}, {__call=function(_,name)
 return function(base)
  local c={};c.__index=c
  setmetatable(c,{__index=base,__call=function(cls,...)
   local value=setmetatable({},cls);if cls[name] then cls[name](value,...)end;return value
  end})
  _G[name]=c;return c
 end
end})
function class.is(value,target)
 while value do
  if value==target then return true end
  local mt=getmetatable(value);value=mt and mt.__index
 end
 return false
end
local registered={}
function permanent(name)return function(value)registered[name]=value;return value end end
corsixth={require=function()end}
_S={object={reception_desk='Desk'},tooltip={objects={reception_desk='Desk'}}}
TheApp={gfx={loadMainCursor=function()return 1 end}}
Date={hoursPerDay=function()return 24 end}
class 'Entity' ();class 'Object' (Entity);class 'Staff' (Entity)
class 'Receptionist' (Staff);class 'Patient' (Entity)
class 'Inspector' (Entity);class 'Vip' (Entity)
class 'HumanoidAction' ()
function Entity:_tick()self.animation_ticks=(self.animation_ticks or 0)+1 end
function Object:tick()return Entity.tick(self)end
function Object:getDrawingLayer()return 1 end
function Object:Object(w,h)self.world=w;self.hospital=h;self.ticks=true end
local QueueMethods={}
function QueueMethods:setBenchThreshold(n)self.bench_threshold=n end
function QueueMethods:setMaxQueue(n)self.max_queue=n end
function QueueMethods:front()return self[1]end
function QueueMethods:pop()return table.remove(self,1)end
function Queue()return setmetatable({visitor_count=0},{__index=QueueMethods})end
function Receptionist:setAnimation(id,flags)self.animation=id;self.animation_flags=flags end
function Receptionist:setTilePositionSpeed(x,y)self.tile_x=x;self.tile_y=y end
function Receptionist:getCurrentAction()return self.action_queue[1]end
function Receptionist:setNextAction(action)self.action_queue={action}end
function Receptionist:queueAction(action)self.action_queue[#self.action_queue+1]=action end
function Receptionist:finishAction()table.remove(self.action_queue,1)end
function Patient:getCurrentAction()return self.action_queue[1]end
function Patient:agreesToPay(service)assert(service=='diag_gp');return true end
function Patient:queueAction(action)self.action_queue[#self.action_queue+1]=action end
function SeekRoomAction(room)return{name='seek_room',room=room}end
'''
    script += method(sources['entity.lua'], 'function Entity:tick(') + '\n'
    script += method(sources['entity.lua'], 'function Entity:setTimer(') + '\n'
    script += 'assert(loadfile(' + repr(str(FIXTURE / 'humanoid_action.lua')) + '))()\n'
    script += 'class "WalkAction" (HumanoidAction)\n'
    script += method(sources['walk.lua'], 'function WalkAction:WalkAction(') + '\n'
    script += 'local flag_flip_h=1\n' + method(sources['walk.lua'], 'local function action_walk_raw(') + '\n'
    script += 'HumanoidRawWalk=action_walk_raw\n'
    script += 'local desk_definition=assert(loadfile(' + repr(str(FIXTURE / 'reception_desk.lua')) + '))()\n'
    # Preserve the original source label and line numbers for callback provenance.
    script += 'package.loaded["3ds.state_health"]=nil\npackage.preload["3ds.state_health"]=function()return dofile(' + \
        repr(str(ROOT / 'lua/3ds/state_health.lua')) + ')end\n'
    script += 'package.loaded.th3ds=nil;package.preload.th3ds=function()return{is_platform=function()return true end}end\n'
    script += 'local reception_start=assert(load([====[' + staff_hotspots.reception_binding(sources['staff_reception.lua']) + \
        ']====], "@CorsixTH/Lua/humanoid_actions/staff_reception.lua"))()\n'
    script += 'local H=require("3ds.state_health")\nlocal HEALTH_PATH=' + repr(str(ROOT / 'lua/3ds/state_health.lua')) + '\n'
    return script + r'''
local function new_world()
 local w={entities={},objects={},map={width=64},game_log={
  'Error in timer handler: ',
  "sdmc:/3ds/corsixth/Lua/entities/humanoids/staff.lua:127: use of undeclared variable 'TH3DS'",
  'Recovering from error in timer handler...'}}
 function w:getObjectToNotifyOfOccupants()return nil end
 local hospital={world=w,staff={}}
 local desk=ReceptionDesk(w,hospital)
 desk.object_type=desk_definition;desk.tile_x=10;desk.tile_y=10
 desk.th={makeVisible=function()end,getTile=function()return nil,10,10 end,setTile=function()end}
 local staff=Receptionist()
 staff.world=w;staff.hospital=hospital;staff.ticks=true;staff.humanoid_class='Receptionist'
 staff.profile={profession='Receptionist',skill=1}
 staff.walk_anims={walk_east=1,walk_north=2,idle_east=3,idle_north=4}
 staff.tile_x=10;staff.tile_y=11;staff.associated_desk=desk;desk.reserved_for=staff
 staff.action_queue={StaffReceptionAction(desk)}
 hospital.staff={staff};hospital.reception_desks={desk};hospital.staffed_reception_desks={desk}
 w.entities={staff,desk};w.objects[(desk.tile_y-1)*w.map.width+desk.tile_x]={desk}
 reception_start(staff.action_queue[1],staff)
 assert(staff.timer_time==8 and type(staff.timer_function)=='function')
 assert(staff.action_queue[1].on_interrupt==registered.action_staff_reception_interrupt_early)
 for tick=1,8 do Entity.tick(staff)end
 assert(staff.timer_time==nil and staff.timer_function==nil)
 assert(desk.receptionist==staff and desk.reserved_for==nil and staff.associated_desk==desk)
 assert(staff.action_queue[1].on_interrupt==registered.action_staff_reception_interrupt)
 assert(staff.tile_x==desk.tile_x and staff.tile_y==desk.tile_y)
 return w
end
local function future_service(w)
 local staff,desk=w.entities[1],w.entities[2]
 local patient=Patient();patient.action_queue={{name='idle'}}
 desk.queue[#desk.queue+1]=patient
 for tick=1,3 do desk:tick();assert(not patient.has_passed_reception)end
 desk:tick()
 assert(patient.has_passed_reception and desk.queue.visitor_count==1)
 assert(patient.action_queue[2].name=='seek_room' and patient.action_queue[2].room=='gp')
 assert(desk.queue:front()==nil and desk.queue_advance_timer==0)
 assert(staff.timer_time==nil and staff.timer_function==nil)
end
local function frozen(root,allow_ticks)
 local saved={}
 local function visit(t)
  if type(t)~='table' or saved[t]then return end
  local row={};saved[t]=row
  for k,v in next,t do row[k]=v;visit(k);visit(v)end
 end
 visit(root)
 return function()
  for t,row in next,saved do
   for k,v in next,row do
    local current=rawget(t,k)
    assert(current==v or (type(v)=='number' and v~=v and type(current)=='number' and current~=current) or
      (allow_ticks and t==root.entities[1] and k=='ticks' and v==false and t.ticks==true),
      'changed field '..tostring(k))
   end
   for k,v in next,t do assert(row[k]~=nil,'added field '..tostring(k))end
  end
 end
end
local function permanence(graph)
 local save,load={[_G]='_G'},{_G=_G}
 local function add(v,name)if not save[v] then save[v]=name;load[name]=v end end
 for _,name in ipairs{'Staff','Receptionist','ReceptionDesk','Patient','Object','Entity','HumanoidAction','StaffReceptionAction'}do
  add(_G[name],name)
 end
 local seen={};local ordinal=0
 local function scan(t)
  if type(t)=='function'then ordinal=ordinal+1;add(t,'fn'..ordinal);return end
  if type(t)~='table' or seen[t] or save[t]then return end
  seen[t]=true
  for k,v in next,t do scan(k);scan(v)end
  scan(getmetatable(t))
 end
 for name,fn in pairs(registered)do add(fn,name)end
 scan(graph)
 return save,load
end
'''


class R65ReceptionRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def test_real_normal_timer_to_desk_schedule_and_future_patient(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(reception_script() + r'''
local w=new_world();future_service(w)
print('PASS SHA-pinned reception start -> raw walk -> real Entity timer -> seated nil timer -> real desk tick serves patient')
''')

    def test_real_action_hook_transform_is_present_and_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='cth-r65-bind-') as name:
            root = Path(name)
            action = root / 'CorsixTH/Lua/humanoid_actions/staff_reception.lua'
            action.parent.mkdir(parents=True)
            action.write_text((FIXTURE / 'staff_reception.lua').read_text())
            # Reception binding has its own transform. Staff's final source
            # is installed by the complete pipeline and tested separately.
            first = next(staff_hotspots.transforms(root))
            self.assertEqual(first[0], str(action.relative_to(root)))
            action.write_text(first[1])
            self.assertEqual(first, next(staff_hotspots.transforms(root)))
            text = first[1]
            self.assertEqual(text.count('CORSIXTH_3DS_RECEPTION_IDENTITY_R65'), 1)
            self.assertIn('require("3ds.state_health").bindReceptionInterrupt(action_staff_reception_interrupt)', text)
            self.assertLess(text.index('if IS_3DS then'), text.index('local action_staff_reception_idle_phase'))

    def test_native_roundtrip_normal_and_recovered_future_service(self):
        from test_save_stream_native import build_stream_probe
        with tempfile.TemporaryDirectory(prefix='cth-r65-reception-') as name:
            directory = Path(name)
            binary, closure, _ = build_stream_probe(directory)
            script = directory / 'reception.lua'
            script.write_text(reception_script() + r'''
for _,recover in ipairs{false,true}do
 local w=new_world()
 if recover then
  w.entities[1].ticks=false
  local check=frozen(w,true);assert(H.repairR62(w)==1);check()
 end
 local permanents,inverse=permanence(w)
 local bytes=assert(candidate.dump(w,permanents))
 local path=directory..'/reception-roundtrip.save'
 local file=assert(io.open(path,'wb'));assert(candidate.dump_file(w,permanents,file));assert(file:close())
 file=assert(io.open(path,'rb'));local streamed=file:read('*a');assert(file:close())
 assert(streamed==bytes,'file/string reception save bytes differ')
 for _,reader in ipairs{reference,candidate}do
  local restored=assert(reader.load(streamed,inverse))
  local staff,desk=restored.entities[1],restored.entities[2]
  assert(staff.associated_desk==desk and staff.action_queue[1].object==desk and desk.receptionist==staff)
  assert(desk.world==restored and desk.hospital==staff.hospital and staff.hospital.staff[1]==staff)
  assert(restored.objects[586][1]==desk and staff.ticks and staff.timer_time==nil and staff.timer_function==nil)
  future_service(restored)
 end
end
print('PASS actual native writer and both readers: seated/recovered aliases, callbacks, no timer, future reception service')
''')
            result = subprocess.run([str(binary), str(closure), str(directory), str(script)],
                                    capture_output=True, text=True, timeout=120,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                                             UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS actual native writer and both readers', result.stdout)
            print(result.stdout, end='')

    def test_strict_refusals_preserve_all_objects_and_atomic_recovery(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(reception_script() + r'''
local changes={
 function(w,s,d)s.profile.skill=nil end,
 function(w,s,d)s.profile.skill=0/0 end,
 function(w,s,d)s.profile.skill=math.huge end,
 function(w,s,d)s.profile.skill=-math.huge end,
 function(w,s,d)s.profile.skill=-0.01 end,
 function(w,s,d)s.profile.skill=1.01 end,
 function(w,s,d)s.profile={}end,
 function(w,s,d)s.associated_desk=nil end,
 function(w,s,d)s.action_queue[1].object={}end,
 function(w,s,d)d.receptionist={}end,
 function(w,s,d)d.reserved_for=s end,
 function(w,s,d)d.world={}end,
 function(w,s,d)d.hospital={}end,
 function(w,s,d)d.ticks=false end,
 function(w,s,d)d.destroyed=true end,
 function(w,s,d)d.picked_up=true end,
 function(w,s,d)d.being_destroyed=true end,
 function(w,s,d)d.tile_x=11 end,
 function(w,s,d)w.entities[3]=d end,
 function(w,s,d)w.objects[586][2]=d end,
 function(w,s,d)w.objects[587]=w.objects[586];w.objects[586]=nil end,
 function(w,s,d)w.objects={}end,
 function(w,s,d)d.object_type={id='bench'}end,
 function(w,s,d)d.queue=nil end,
 function(w,s,d)d.queue.front=false end,
 function(w,s,d)d.queue.pop=false end,
 function(w,s,d)d.queue.visitor_count=-1 end,
 function(w,s,d)d.tick=function()end end,
 function(w,s,d)d.queue_advance_timer=-1 end,
 function(w,s,d)w.entities[2]=nil;w.entities.hidden=d end,
 function(w,s,d)w.objects[586]={hidden=d}end,
 function(w,s,d)w.objects[586]={[2]=d}end,
 function(w,s,d)s.action_queue[2]={name='idle'}end,
 function(w,s,d)s.action_queue.hidden={name='idle'}end,
 function(w,s,d)s.action_queue[1].must_happen=false end,
 function(w,s,d)s.action_queue[1].uninterruptible=true end,
 function(w,s,d)s.action_queue[1].todo_interrupt=true end,
 function(w,s,d)s.action_queue[1].on_interrupt=registered.action_staff_reception_interrupt_early end,
 function(w,s,d)s.action_queue[1].on_interrupt=function()end end,
 function(w,s,d)
  local original=registered.action_staff_reception_interrupt
  local clone=assert(load(string.dump(original)))
  assert(clone~=original and debug.getinfo(clone,'S').linedefined==debug.getinfo(original,'S').linedefined)
  s.action_queue[1].on_interrupt=clone
 end,
 function(w,s,d)s.action_queue[1].on_interrupt=nil end,
 function(w,s,d)s.action_queue[1].on_restart=function()end end,
 function(w,s,d)setmetatable(s.action_queue[1],nil)end,
 function(w,s,d)setmetatable(s,Staff)end,
 function(w,s,d)s.timer_time=0 end,
 function(w,s,d)s.timer_function=function()end end,
 function(w,s,d)s.fired=true end,
 function(w,s,d)s.dead=true end,
 function(w,s,d)s.pickup=true end,
 function(w,s,d)s.hospital.staff[2]=s end,
 function(w,s,d)w.game_log={}end,
 function(w,s,d)w.game_log[2]='other engine error'end,
 function(w,s,d)w.game_log[4]='Warning: Empty action queue.'end,
}
for i,change in ipairs(changes)do
 local w=new_world();local s,d=w.entities[1],w.entities[2];s.ticks=false
 change(w,s,d);local check=frozen(w)
 local ok,reason=pcall(H.repairR62,w);assert(not ok,'unsafe eligibility '..i);check()
end
local w=new_world();w.entities[1].ticks=false
local check=frozen(w);local dbg=debug;debug=nil
local ok,reason=pcall(H.repairR62,w);debug=dbg
assert(ok and w.entities[1].ticks,'bound identity must not depend on debug')
-- An earlier valid seated employee must stay disabled when a later one fails.
w=new_world();local first=w.entities[1];first.ticks=false
local other=Staff();other.world=w;other.hospital=first.hospital;other.ticks=false
other.action_queue={{name='idle'}};w.entities[3]=other;first.hospital.staff[2]=other
for i=1,3 do w.game_log[i+3]=w.game_log[i]end
check=frozen(w);assert(not pcall(H.repairR62,w));check()
w=new_world();first=w.entities[1];first.ticks=false
local action,desk=first.action_queue,w.entities[2]
check=frozen(w,true);assert(H.repairR62(w)==1);check()
assert(first.action_queue==action and desk.receptionist==first and first.timer_time==nil)
future_service(w)
-- Missing registration and a conflicting registration both fail closed.
w=new_world();w.entities[1].ticks=false
local unbound=assert(loadfile(HEALTH_PATH))()
check=frozen(w);local success,why=pcall(unbound.repairR62,w)
assert(not success and why:find('reception=interrupt-unbound',1,true));check()
H.bindReceptionInterrupt(registered.action_staff_reception_interrupt)
assert(not pcall(H.bindReceptionInterrupt,function()end))
check=frozen(w);success,why=pcall(H.repairR62,w)
assert(not success and why:find('reception=interrupt-binding-conflict',1,true));check()
print('PASS '..#changes..' structural/evidence refusals, unbound/conflict gates, no-debug identity and atomic late refusal; only ticks restored')
''')


if __name__ == '__main__':
    unittest.main()
