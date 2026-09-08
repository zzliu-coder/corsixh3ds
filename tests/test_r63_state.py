"""Execute complete generated modules under the pinned upstream strict globals."""
from pathlib import Path
import tempfile
import unittest
import re
from support.pinned_upstream import generated_sources
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

class R63StateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r63-')
        cls.generated=generated_sources(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_complete_staff_and_bottom_modules_in_actual_strict_environment(self):
        lua=self.generated/'CorsixTH/Lua'
        script=f'''
local strict={str(ROOT/'tests/fixtures/strict.lua.pinned')!r}
local staff_path={str(lua/'entities/humanoids/staff.lua')!r}
local panel_path={str(lua/'dialogs/bottom_panel.lua')!r}
'''+r'''
local function environment()
  local e={};for k,v in pairs(_G)do e[k]=v end;e._G=e
  e.class=setmetatable({is=function()return false end},{__call=function(_,name)
    rawset(e,name,{});return function()end
  end})
  e.corsixth={require=function()end};e.Humanoid={};e.Window={}
  e.AnnouncementPriority={High=1}
  e.Entity={tick=function(s)s.base=s.base+1 end}
  e.UIEditRoom={};e.UIConfirmDialog=function()error('unexpected modal')end
  assert(loadfile(strict,'t',e))()
  e.strict_declare_global('TheApp') -- declared upstream global may be nil
  return e
end
local e=environment()
assert(loadfile(staff_path,'t',e))()
local marks=0
local native={cpu_phase=function(label,previous)
  marks=marks+1;if label then assert(previous)end;return marks
end}
e.TheApp={_3ds={native=native}}
local s=setmetatable({base=0,world={},hospital={},speed=0,rest=0,raise=0,litter=0,
  checkIfNeedRest=function(s)s.rest=s.rest+1 end,
  checkIfWaitedTooLongForRaise=function(s)s.raise=s.raise+1 end,
  isTiring=function()return false end,getAttribute=function()return 1 end,
  findObjectsInSquare=function(s,size,kind,visit)
    assert(size==2 and kind=='litter' and type(visit)=='function');s.litter=s.litter+1
  end,updateSpeed=function(s)s.speed=s.speed+1 end},{__index=e.Staff})
for i=1,64 do s:tick()end
assert(s.base==64 and s.speed==64 and s.rest==64 and s.raise==64 and s.litter==64)
assert(marks==24,'four full six-mark staff samples')
e.TheApp._3ds=nil
for i=1,32 do s:tick()end
assert(s.base==96 and s.speed==96 and marks==24)
s.fired=true
for i=1,32 do s:tick()end
assert(s.base==128 and s.speed==96)
local ok,err=pcall(function()return e.TH3DS end)
assert(not ok and err:find('undeclared'),'regression requires strict TH3DS rejection')

local p=environment();assert(loadfile(panel_path,'t',p))()
local mutations,notices,prepared=0,0,false
local gfx={loadRaw=function()error('injected allocation failure')end}
local ui={app={gfx=gfx,_3ds={native={set_notice=function()notices=notices+1 end}}},
  getWindow=function()return nil end,
  setEditRoom=function()assert(prepared);mutations=mutations+1 end,
  addWindow=function(_,w)assert(w.ready and prepared)end}
p.strict_declare_global('UIResearch')
p.UIResearch=function()assert(prepared);return{ready=true}end
local panel=setmetatable({ui=ui,updateButtonStates=function()end},{__index=p.UIBottomPanel})
assert(panel:addDialog('UIResearch')==false and mutations==0 and notices==1)
gfx.loadRaw=function(_,name)assert(name=='Res01V');prepared=true end
panel:addDialog('UIResearch');assert(mutations==1)
ui.app._3ds=nil;panel:addDialog('UIResearch');assert(mutations==2)
print('PASS complete Staff/BottomPanel modules: strict globals, 128 staff ticks, platform absent, failed and successful window preparation')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_generated_modules_never_borrow_another_modules_th3ds_local(self):
        # Whole-module tripwire complements executable strict-module tests.
        for path in (self.generated/'CorsixTH/Lua').rglob('*.lua'):
            text=path.read_text()
            if 'TH3DS' in text:
                self.assertTrue(re.search(r'local \w+, TH3DS = pcall\(require,\s*"th3ds"\)',text),
                    str(path)+' lacks a module-local native binding')

    def test_recovery_requires_exact_evidence_and_preserves_action_state(self):
        script='local H=dofile('+repr(str(ROOT/'lua/3ds/state_health.lua'))+')\n'+r'''
class={is=function(e,k)return e.kind==k end};Staff='staff';Patient='patient'
local header='Error in timer handler: '
local detail="sdmc:/3ds/corsixth/Lua/entities/humanoids/staff.lua:127: use of undeclared variable 'TH3DS'"
local recovered='Recovering from error in timer handler...'
local function world()
 return {game_log={header,detail,recovered},entities={
  {kind=Staff,ticks=false,timer_time=12,timer_function=math.sin,
   action_queue={{name='walk',must_happen=true},{name='seek_room'}},profile={wage=105}},
  {kind=Patient,ticks=true,action_queue={{name='wait'}}},
  {kind='furniture',ticks=false}}}
end
local w=world();local staff=w.entities[1];local queue=staff.action_queue
local app={world=w,eventHandlers={timer=function()end}}
assert(not pcall(H.assertActive,app))
assert(H.repairR62(w)==1 and staff.ticks and not w.entities[3].ticks)
assert(staff.action_queue==queue and #queue==2 and queue[1].must_happen)
assert(staff.timer_time==12 and staff.timer_function==math.sin and staff.profile.wage==105)
assert(H.assertActive(app).staff==1 and H.repairR62(w)==0)
local before=H.fingerprint(w);staff.timer_time=13;assert(H.fingerprint(w)~=before)
staff.timer_time=12;queue[2].name='idle';assert(H.fingerprint(w)~=before)
queue[2].name='seek_room';assert(H.fingerprint(w)==before)
app.eventHandlers.timer=nil;assert(not pcall(H.assertActive,app))
for _,mutate in ipairs{
 function(w)w.game_log={}end,
 function(w)w.game_log[2]=detail:gsub(':127:',':128:')end,
 function(w)w.game_log[2]=detail:gsub('TH3DS','other')end,
 function(w)w.game_log[1]='Error in frame handler: 'end,
 function(w)w.game_log[3]=nil end,
 function(w)table.insert(w.game_log,header);table.insert(w.game_log,'out of memory')end,
 function(w)w.entities[2].ticks=false end,
 function(w)w.entities[4]={kind=Staff,ticks=false}end,
 function(w)w.game_log={recovered,header,detail,recovered}end,
}do
 w=world();mutate(w);assert(not pcall(H.repairR62,w),'must refuse ambiguous recovery')
 assert(w.entities[1].ticks==false,'failure must not partially enable entities')
end
print('PASS R63 recovery evidence, atomic validation, timer/action preservation, invalid benchmark health')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_litter_fast_path_tracks_changes_and_mutable_aliases(self):
        lua=self.generated/'CorsixTH/Lua'
        source=(lua/'entities/humanoid.lua').read_text()
        start=source.index('function Humanoid:findObjectsInSquare(')
        query=source[start:source.index('\nend',start)+4]
        script=r'''
class=setmetatable({is=function(e,k)return e.kind==k end},{__call=function(_,n)_G[n]={}end})
Object='object';Patient='patient';Humanoid={}
'''+(lua/'entity_map.lua').read_text()+'\n'+query+r'''
local m=setmetatable({},{__index=EntityMap});m:EntityMap({th={size=function()return 20,20 end}})
assert(not m:hasAnyLitter())
local calls=0
local h=setmetatable({tile_x=10,tile_y=10,world={entity_map=m,
 map={th={getRoomId=function()calls=calls+1;return 0 end,
  size=function()return 20,20 end}}}}, {__index=Humanoid})
assert(#h:findObjectsInSquare(2,'litter')==0 and calls==0)
assert(h:findObjectsInSquare(2,'litter',function()error('empty visitor')end)==nil and calls==0)
local litter={kind=Object,id='litter'}
m:addEntity(10,10,litter);assert(m:hasAnyLitter())
local found=h:findObjectsInSquare(2,'litter');assert(found[1]==litter and #found==1 and calls>0)
m:removeEntity(10,10,litter);assert(not m:hasAnyLitter())
m:addEntity(19,19,litter);assert(m:hasAnyLitter());assert(#h:findObjectsInSquare(2,'litter')==0)
m:removeEntity(19,19,litter);m:compact();assert(not m:hasAnyLitter())
local alias=m:getObjectsAtCoordinate(10,10);assert(m:hasAnyLitter())
alias[1]=litter;m:compact();assert(m:hasAnyLitter())
assert(h:findObjectsInSquare(2,'litter')[1]==litter)
alias[1]=nil;m:compact();assert(m:hasAnyLitter(),'borrowed mutable alias stays conservative')
assert(#h:findObjectsInSquare(2,'litter')==0)
for name in pairs(m)do assert(name~='litter_counts','derived cache must remain outside save graph')end
print('PASS empty litter skip, spawn/remove/move, compact and mutable alias fallback')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_benchmark_rejects_stopped_simulation_and_copy_roundtrip_damage(self):
        script='package.path='+repr(str(ROOT/'lua/?.lua')+';')+'..package.path\n'+r'''
local B=require('3ds.benchmark');local Health=require('3ds.state_health')
class={is=function(e,k)return e.kind==k end};Staff='staff';Patient='patient'
local now,events=0,{}
local native={clock_ms=function()return now end,set_notice=function()end,
 benchmark_state=function()end,flush_observations=function()end,
 benchmark_mark=function(event)events[#events+1]=event end}
local function make()
 local app={savegame_dir='USER/',config={autosave_frequency=2},
  eventHandlers={timer=function()end},_3ds={simulation_errors=0}}
 function app:load(name)
  self.ui={hospital={staff={},balance=200}}
  self.world={entities={{kind=Staff,ticks=true,timer_time=12,
    action_queue={{name='walk',must_happen=true}}},{kind=Patient,ticks=true}},
   rooms={},map={th={getPlotCount=function()return 0 end}},
   getCurrentSpeed=function(w)return w.speed end,setSpeed=function(w,s)w.speed=s end,
   game_date={tostring=function()return '1/1/1' end}}
  return true
 end
 return app
end
for _,break_state in ipairs{
 function(a)a._3ds.simulation_errors=1 end,
 function(a)a.eventHandlers.timer=nil end,
 function(a)a.world.entities[1].ticks=false end,
 function(a)a.world.entities[2].ticks=false end,
}do
 now=0;events={};local a=make();local b=B.new(a,native);b:tick()
 assert(b.phase=='warmup');break_state(a);now=5001;b:tick()
 assert(b.phase=='done' and events[#events]=='FAILED' and a.world.speed=='Pause')
 for _,event in ipairs(events)do assert(event~='COMPLETE' and event~='SAMPLE-END')end
 assert(a.savegame_dir=='USER/')
end
local root='sdmc:/3ds/corsixth/Benchmark/'
local open=io.open
io.open=function(path,mode)
 if path==root..'r62-recovery.sav' then return {close=function()end} end
 return nil
end
for _,damage in ipairs{false,true}do
 now=0;events={};local a=make();local load=a.load;local writes=0
 function a:save(path)
  assert(path==root..'Saves/r63-recovery-roundtrip.sav' and self.savegame_dir==root..'Saves/')
  writes=writes+1;return true
 end
 function a:load(path)
  assert(path:sub(1,#root)==root and self.savegame_dir==root..'Saves/')
  load(self,path)
  if damage and path==root..'Saves/r63-recovery-roundtrip.sav' then
   self.world.entities[1].timer_time=13
  end
  return true
 end
 local b=B.new(a,native);b:tick();assert(writes==1)
 if damage then assert(b.phase=='done' and events[#events]=='FAILED')
 else assert(b.phase=='warmup' and b.recovery_verified);b:cancel('test')end
 assert(a.savegame_dir=='USER/')
end
io.open=open
print('PASS benchmark rejects engine error, missing timer, disabled people and roundtrip timer damage; private-only writes')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)
