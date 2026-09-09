"""Capacity's real Benchmark/observer entry and compiled runner input boundary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import test_lua_runtime
from test_r66_recovery_activity import script as activity_script
from test_r65_reception_recovery import method
import prepare_runner_benchmark as prepare

ROOT=Path(__file__).resolve().parents[1]
GENERATED=None

def benchmark_script():
    generated=GENERATED
    app_source=(generated/'CorsixTH/Lua/app.lua').read_text()
    return ('package.path='+repr(str(ROOT/'lua/?.lua')+';')+'..package.path\n'+activity_script()+
        '\nApp={}\n'+method(app_source,'function App:loadLevel(')+'\n'+method(app_source,'function App:_loadLevel(')+r'''
package.loaded['3ds.recovery_activity']=A
local B=require('3ds.benchmark');local S=require('3ds.benchmark_stress')
local now,active,checkpoints,exited=0,false,0,0
local root='sdmc:/3ds/ftpd-runner/runs/r73-test/'
local kinds={'Doctor','Doctor','Doctor','Nurse','Nurse','Handyman','Receptionist',
 'Handyman','Handyman','Nurse','Doctor','Receptionist','Nurse','Nurse','Doctor','Doctor','Nurse'}
_S.errors={load_level_prefix='level: '};tracy={Message=function()end};IS_3DS=true
function th3ds_stage()end
TH3DS={observe_memory=function()end,operation_boundary=function()end,probe_regular_heap=function()return true end}
local app={config={language='Chinese (simplified)',play_music=true,speech_language='zh',
 unicode_font='font',audio_music='Music',autosave_frequency=0},savegame_dir=root..'save/',
 eventHandlers={timer=function()end},_3ds={simulation_errors=0,simulation_progress={world_completed=0,hours_completed=0,entity_completed=0}},
 strings={checkLanguageExists=function()return true end},video={setBlueFilterActive=function()end},
 gfx={loadSpriteTable=function()end,loadFontAndSpriteTable=function()end}}
app.audio={background_playlist={{filename_music='Music/CANDY.wav'}},stopBackgroundTrack=function()end,
 playBackgroundTrack=function()return true end,playSoundEffects=function()end}
package.loaded['3ds.media']={setSpeech=function(a,code)a.config.speech_language=code;a.audio.speech_file_name=code;return true end,
 speechFile=function(a)return a.config.speech_language end}
function app:initLanguage()return true end
local function populate(level,continuity)
 local w={entities={},rooms={},game_date={tostring=function()return '1-01-01T00'end},
  setSpeed=function(self,s)self.speed=s end,getCurrentSpeed=function(self)return self.speed end,
  getCampaignData=function()return {}end,setCampaignData=function()end,createMapObjects=function()end,setUI=function()end,
  getLocalPlayerHospital=function(self)return self.hospital end}
 local h={balance=100,staff={}};w.hospital=h
 if continuity then
  for i=1,45 do w.entities[i]={ticks=true}end
  for i,kind in ipairs(kinds)do
   local index=i==17 and 45 or i+8
   local e
   if kind=='Receptionist' then
    local tmp=new_world();e=tmp.entities[1];local d=tmp.entities[2]
    e.world=w;e.hospital=h;d.world=w;d.hospital=h
    w.entities[index==15 and 1 or 2]=d
   else e=Staff();e.action_queue={{name='idle'}};e.timer_time=2;e.timer_function=function()end;e.ticks=true end
   e.humanoid_class=kind;e.profile=e.profile or {};e.profile.wage=100
   w.entities[index]=e;h.staff[#h.staff+1]=e
  end
 end
 local m={level_number=level,difficulty='full',th={getPlotCount=function()return 1 end,getPlotOwner=function()return 1 end},
  setBlocks=function()end,setDebugFont=function()end}
 w.map=m;app.map=m;app.world=w
 app.ui={app=app,hospital=h,screen_offset_x=0,screen_offset_y=0,windows={},modal_windows={},anyMustPauseWindowOpen=function()return false end}
 w.speed='Normal'
 -- Deliberately reset at each load to expose any stress subtraction after capacity.
 app._3ds.simulation_progress={world_completed=0,hours_completed=0,entity_completed=0}
 return w
end
local saved,load_names,save_names={}, {},{}
local function clone(value,seen)
 if type(value)~='table' or value==app then return value end
 seen=seen or {};if seen[value]then return seen[value]end
 local copy=setmetatable({},getmetatable(value));seen[value]=copy
 for k,v in pairs(value)do copy[clone(k,seen)]=clone(v,seen)end
 return copy
end
function app:load(file)
 assert(file:sub(1,#root)==root);load_names[#load_names+1]=file
 if load_fault then return false end
 if saved[file]then
  local snapshot=clone(saved[file]);self.world=snapshot[1];self.map=snapshot[2];self.ui=snapshot[3]
  return true
 end
 local continuity=file:find('continuity',1,true)~=nil
 populate(file:find('level12',1,true) and 12 or 1,continuity)
 return true
end
function app:save(file)
 assert(file:sub(1,#root)==root and app.savegame_dir==root..'save/')
 save_names[#save_names+1]=file
 if save_fault then return false end
 saved[file]=clone({self.world,self.map,self.ui})
 return true
end
function app:worldExited()end
app.loadLevel=App.loadLevel;app._loadLevel=App._loadLevel
function Map(a)
 local m={load=function(self,level,difficulty)
  assert(level==12 and difficulty=='full');self.level_number=level;self.difficulty=difficulty
  return {}end,setBlocks=function()end,setDebugFont=function()end,
  th={getPlotCount=function()return 1 end,getPlotOwner=function()return 1 end}}
 return m
end
function World(a)
 local m=a.map;local w=populate(12,false);a.map=m;w.map=m;return w
end
function GameUI(a,h)return a.ui end
function app:loadMainMenu()error('actual loadLevel failure fallback')end
function app:exit()exited=exited+1 end
local fields
local native={clock_ms=function()return now end,benchmark_active=function()return active end,
 benchmark_state=function(v)active=v end,set_notice=function()end,flush_observations=function()end,
 benchmark_mark=function()return now*1000,now end,runner_frames=function()return now end,
 music_state=function()return true,false end,
 memory=function()return{heap_available_estimate=1000,linear_free=2000,lua_current=3000,diagnostic_resources={gpu=100}}end,
 runner_context=function()return{root=root,profile='expanded-zh-on',warmup_ms='1000',sample_ms='1000',stress_ms='1',
 capacity='r73-v1',continuity_sha256=require('3ds.benchmark_capacity').sha,
 expanded_sha256='f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7'}end,
 diagnostic_line=function(line)assert(#line<=230)end,
 runner_checkpoint=function(f)
  checkpoints=checkpoints+1;local count,total=0,0
  for k,v in pairs(f)do count=count+1;total=total+#k+#v+2;assert(#k<=64 and #v<=1024)end
  assert(count<=128 and total<=12000 and checkpoints<=48)
  if checkpoint_fault then error('checkpoint fault')end
 end,
 runner_finish=function(outcome,reason,f)fields=f;fields.outcome=outcome;fields.reason=reason end}
local original_open=io.open;io.open=function()return nil end
local b=B.new(app,native);b:activate();b:tick();io.open=original_open
local function step(delta)
 now=now+delta
 local p=app._3ds.simulation_progress
 p.world_completed=p.world_completed+delta;p.hours_completed=p.hours_completed+delta;p.entity_completed=p.entity_completed+delta
 b:tick()
end
step(1000);step(1000);assert(b.phase=='stress')
-- Complete the already-tested window phase at the existing seam.
b.stress.tick=function()return true end
step(1);assert(b.phase=='capacity')
local stress_world=b.stress_end_progress.world-b.stress_progress.world
step(1);assert(b.capacity.phase=='reception_1')
local function services()
 for _,index in ipairs{15,20}do
  local staff=app.world.entities[index];local desk=staff.associated_desk
  local patient=Patient();patient.action_queue={{name='idle'}};desk.queue[1]=patient
  for i=1,4 do A.before(staff);staff:tick();A.after(staff,true);A.before(desk);desk:tick();A.after(desk,true)end
 end
 for i,e in ipairs(app.world.entities)do
  if class.is(e,Staff) and e.humanoid_class~='Receptionist' then A.before(e);e.timer_time=1;A.after(e,true)end
 end
end
''')

class CapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global GENERATED
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        if os.environ.get('CTH3DS_CAPACITY_GENERATED'):
            GENERATED=Path(os.environ['CTH3DS_CAPACITY_GENERATED'])
        else:
            from support.pinned_upstream import generated_sources
            cls.directory=tempfile.TemporaryDirectory(prefix='cth-r73-capacity-')
            cls.addClassCleanup(cls.directory.cleanup)
            GENERATED=generated_sources(Path(cls.directory.name))

    def test_real_reception_patient_vip_owner_event_bound_and_graph(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(activity_script()+r'''
function class.type(e)return class.is(e,Vip) and 'Vip' or 'Inspector'end
local w,c=recovered();A.start(w,c,true)
serve(w)
local report=A.patientReport();local e=report.events[1]
assert(report.rows[1].patient_services==1 and e.head_kind=='Patient' and e.owner_same)
assert(e.before==0 and e.after==1 and e.action_before=='idle' and e.tail_after=='seek_room')
local desk=w.entities[2];local vip=Vip()
vip.action_queue={{name='idle'}};vip.getCurrentAction=Patient.getCurrentAction;vip.queueAction=Patient.queueAction
function IdleAction()return{name='idle'}end
desk.queue[1]=vip
for i=1,4 do assert(observed(desk))end
report=A.patientReport();assert(report.rows[1].services==2 and report.rows[1].patient_services==1)
assert(report.events[2].head_kind=='Vip')
-- Successful return with a replaced owner must never attribute the event.
local patient=Patient();patient.action_queue={{name='idle'}};desk.queue[1]=patient
desk.queue_advance_timer=4
A.before(desk);assert(pcall(desk.tick,desk));desk.receptionist=Receptionist();A.after(desk,true)
assert(A.patientReport().rows[1].patient_services==1)
desk.receptionist=w.entities[1]
for i=1,40 do serve(w)end
report=A.patientReport();assert(#report.events==32 and report.event_drops==10)
assert(report.rows[1].patient_services==41)
-- All reports contain scalars only, never queue heads or worlds.
for _,event in ipairs(report.events)do for _,value in pairs(event)do assert(type(value)~='table')end end
local weak=setmetatable({w,w.entities[1],desk},{__mode='v'})
w=nil;desk=nil;c=nil;collectgarbage('collect');collectgarbage('collect')
assert(weak[1]==nil and weak[2]==nil and weak[3]==nil);A.stop()
''')

    def test_benchmark_actual_loadlevel_bounded_completion_and_stress_scope(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(benchmark_script()+r'''
services();step(180000);assert(b.capacity.phase=='reception_2')
services();step(180000);assert(b.capacity.phase=='level_run' and app.map.level_number==12)
step(60000);assert(b.capacity.phase=='return_run');step(5000)
assert(b.phase=='done' and fields.outcome=='PASS' and exited==1)
assert(fields.capacity_reception_outcome=='PASS' and fields.capacity_patient_services=='15=2;20=2')
assert(fields.capacity_level_outcome=='PASS' and fields.capacity_return_outcome=='PASS')
assert(fields.capacity_busy_hospital=='NOT_PROVEN' and fields.capacity_natural_promotion=='NOT_PROVEN')
assert(tonumber(fields.stress_world)==stress_world and tonumber(fields.stress_at)==1)
assert(fields.stress_annual_attempts=='0' and fields.stress_annual_outcome=='NOT_PROVEN')
assert(checkpoints==11 and not A.active and b.capacity.old==nil and b.capacity.cohort==nil)
assert(save_names[#save_names]==root..'save/completed.sav')
''')

    def test_capacity_missing_services_departure_fault_cancel_and_needs_input(self):
        cases=[
            "step(180000);step(180000);step(60000);step(5000);assert(fields.outcome=='PASS' and fields.capacity_reception_outcome=='NOT_PROVEN')",
            "app.world.entities[20]={ticks=true};step(180000);assert(b.capacity.phase=='level_run' and b.results.capacity_reception_outcome=='NOT_PROVEN');b:cancel('test')",
            "save_fault=true;step(180000);assert(fields.outcome=='FAIL' and fields.capacity_failure_outcome=='FAIL')",
            "load_fault=true;step(180000);assert(fields.outcome=='FAIL')",
            "checkpoint_fault=true;step(180000);assert(fields.outcome=='FAIL')",
            "app._3ds.operations={guard=function()error('failed lifecycle lock')end};step(180000);assert(fields.outcome=='FAIL')",
            "app._3ds.simulation_errors=1;step(1);assert(fields.outcome=='FAIL')",
            "app.ui.windows={{modal_class='salary',mustPause=function()return false end}};step(1);assert(fields.reason=='NEEDS_INPUT' and fields.outcome=='NOT_PROVEN')",
            "b.stress.annual_failed=true;step(1);assert(fields.outcome=='FAIL' and fields.reason=='CLEANUP_FAILED')",
            "b:cancel('lifecycle');assert(fields.reason=='CANCEL' and fields.outcome=='NOT_PROVEN');b:cancel('again');b:tick();assert(exited==1)",
            "A.before(app.world.entities[15]);A.after(app.world.entities[15],false);b:cancel('lifecycle');assert(fields.outcome=='FAIL')",
            "native.diagnostic_line=function()error('diagnostic failure')end;step(180000);assert(fields.outcome=='FAIL' and fields.failure_detail:find('diagnostic failure',1,true))",
        ]
        for case in cases:
            with self.subTest(case=case):
                test_lua_runtime.LuaRuntimeTests().run_lua(benchmark_script()+case+
                    "\nassert(not A.active and b.capacity.cohort==nil and not active)\n")

    def test_prepare_default_bytes_and_capacity_sha_paths_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'installed';(base/'Lua').mkdir(parents=True)
            (base/'Benchmark').mkdir();(base/'game/LEVELS').mkdir(parents=True)
            (base/'Lua/a.lua').write_text('return {}\n');(base/'config.txt').write_text('config')
            (base/'receipt.json').write_text('{}')
            for name in ('input','expanded','continuity'): (base/'Benchmark'/f'{name}.sav').write_bytes(name.encode())
            for name in prepare.CAPACITY_ASSETS: (base/'game/LEVELS'/name).write_bytes(name.encode())
            args=argparse.Namespace(installed_tree=base,integration_receipt='receipt.json',
                assets_receipt_sha256='a'*64,profile='expanded-zh-on',warmup_ms=30000,sample_ms=60000,
                stress_ms=180000,recovery=False,out=Path(temp)/'default')
            prepare.prepare(args)
            expected={'adapter':'corsixth-r63-v1','profile':args.profile,'stress_ms':'180000',
                'warmup_ms':'30000','sample_ms':'60000','assets_receipt_sha256':'a'*64,
                'lua_tree_sha256':hashlib.sha256(('a.lua|'+prepare.sha(base/'Lua/a.lua')+'\n').encode()).hexdigest(),
                'player_config_sha256':prepare.sha(base/'config.txt'),
                'verify_0':prepare.sha(base/'receipt.json')+'|sdmc:/3ds/corsixth/receipt.json',
                'expanded_sha256':prepare.sha(base/'Benchmark/expanded.sav')}
            self.assertEqual((args.out/'config.bin').read_text(),''.join(k+'='+v+'\n' for k,v in sorted(expected.items())))
            self.assertEqual(json.loads((args.out/'preparation.json').read_text())['command'][-1],'570')
            args.capacity=True;args.out=Path(temp)/'capacity'
            with self.assertRaisesRegex(ValueError,'identity mismatch'):prepare.prepare(args)
            self.assertFalse(args.out.exists())
            original_sha=prepare.sha
            def fake_sha(path):
                if path.name=='continuity.sav':return prepare.CONTINUITY_SHA
                if path.name=='expanded.sav':return 'f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7'
                return prepare.CAPACITY_ASSETS.get(path.name) or original_sha(path)
            with patch.object(prepare,'sha',fake_sha):
                prepare.prepare(args)
                self.assertEqual(json.loads((args.out/'preparation.json').read_text())['command'][-1],'1115')
                self.assertIn('capacity=r73-v1\n',(args.out/'config.bin').read_text())
                args.out=Path(temp)/'escape'
                (base/'Benchmark/continuity.sav').unlink()
                (base/'Benchmark/continuity.sav').symlink_to(base/'Benchmark/input.sav')
                with self.assertRaisesRegex(ValueError,'symlink'):prepare.prepare(args)
            args.stress_ms=1320000
            with self.assertRaisesRegex(ValueError,'requires expanded'):prepare.prepare(args)
