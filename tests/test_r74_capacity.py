"""R74 busy protocol and real hire/place UI calls; domain/graphics are seams.

These host cases establish controller/entry contracts. They do not claim real
hospital simulation, native saving, or device capacity acceptance.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import prepare_runner_benchmark as prepare
import test_lua_runtime
import test_r73_capacity as previous
from support.save_ui import install_ui_infrastructure
from test_r65_reception_recovery import method

ROOT=Path(__file__).resolve().parents[1]

class BusyCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous.CapacityTests.setUpClass.__func__(cls)
        cls.generated=previous.GENERATED
        cls.uiroot=install_ui_infrastructure(cls.generated)

    def run_lua(self,script):
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_r74_configuration_preserves_legacy_and_requires_clock(self):
        script=previous.benchmark_script()
        # Same Benchmark, native callback services; an old runtime cannot claim R74.
        self.run_lua(script.replace("capacity='r73-v1'","capacity='r74-v1'")
            .split("step(1);assert(b.phase=='capacity')")[0]+
            "step(1);assert(fields.outcome=='FAIL' and fields.failure_detail:find('native simulation clock',1,true))")
        self.run_lua(script.replace("capacity='r73-v1'","capacity='r74-v1'")
            .replace("runner_context=function()", "simulation_clock=function()return {at_us=now*1000,nominal_timer_us=18000,completed_steps=now,failed_steps=0,dropped_us=now,debt_us=20,rebases=0,budget_exits=0}end,\n runner_context=function()")+r'''
services();step(180000);services();step(180000)
assert(b.capacity.busy and b.capacity.phase=='busy_recruit')
assert(b.results.capacity_protocol=='r74-v1')
local work=b.results.capacity_reception_2_work
assert(work:find('nominal_timer_us=18000',1,true) and work:find('dropped_us=180000',1,true))
b:cancel('lifecycle');assert(fields.reason=='CANCEL' and fields.outcome=='NOT_PROVEN')
''')

    def test_busy_complete_controller_and_boundaries_with_explicit_ui_services(self):
        script=previous.benchmark_script().replace("capacity='r73-v1'","capacity='r74-v1'")
        script=script.replace("runner_context=function()", "simulation_clock=function()return {at_us=now*1000,nominal_timer_us=18000,completed_steps=now,failed_steps=0,dropped_us=now,debt_us=20,rebases=0,budget_exits=0}end,\n runner_context=function()")
        self.run_lua(script+r'''
services();step(180000);services();step(180000)
local busy=b.capacity.busy;assert(busy)
app.world.tick_rate=3;app.world.hours_per_tick=1
-- Explicit domain service used only by this controller test. Real hiring's
-- normal UI/profile/placement implementation has its own full-module case.
function busy:hire()
 local e=Staff();e.humanoid_class='Nurse';e.ticks=true;e.profile={wage=100}
 e.action_queue={{name='idle'}};e.timer_time=2;e.timer_function=function()end
 table.insert(app.world.entities,e);table.insert(app.ui.hospital.staff,e)
 self.hires=self.hires+1;return true
end
for i=1,27 do step(250)end
assert(b.capacity.phase=='busy_1' and busy.count==43)
local saves=0
app._3ds.operations={guard=function()end}
local function attach_save_service()
 UISaveGame=function(ui)
  local window={new_savegame_textbox={setText=function(self,text)self.text=text end}}
  function window:confirmName()
   self.closed=true
   assert(app:save(app.savegame_dir..self.new_savegame_textbox.text..'.sav'))
   app._3ds.operations.last={method='save',committed=true,completed=true,ready=true}
   saves=saves+1
  end
  return window
 end
 app.ui.addWindow=function()end
end
attach_save_service();lfs={attributes=function()return nil end}
services();step(60000)
assert(b.capacity.phase=='busy_2' and saves==1 and b.results.capacity_busy_save_ui=='PASS')
services();step(60000)
assert(b.capacity.phase=='level_run' and b.results.capacity_busy_hospital=='PASS')
assert(b.results.capacity_busy_roundtrip=='PASS')
step(60000);step(5000)
assert(b.phase=='done' and fields.outcome=='PASS')
assert(checkpoints==15 and fields.capacity_level_outcome=='PASS' and fields.capacity_return_outcome=='PASS')
assert(fields.capacity_busy_1_work:find('world_tick_rate=3',1,true))
assert(fields.capacity_busy_2_work:find('failed_steps=0',1,true))
assert(save_names[#save_names]==root..'save/completed.sav')
''')

    def hiring_script(self):
        # Infrastructure/strict and entire hire/place chunks are source-pinned.
        return ("local spec=dofile("+repr(str(ROOT/'tests/runtime_support/save_ui_loader.lua'))+")("+
            repr(str(self.uiroot))+",{})\nlocal env=spec.environment\n"+r'''
local function put(k,v)rawset(env,k,v)end
put('DrawFlags',{Nearest=1})
local animation={setLayer=function()end,setAnimation=function()end}
env.require=function(name)assert(name=='TH');return {animation=function()return animation end}end
put('Humanoid',{getIdleAnimation=function()return 1 end})
assert(load('class "Staff";class "UIBottomPanel";class "UIFullscreen";class "UIStaffManagement"','classes','t',env))()
function env.Staff:Staff()end
function env.UIBottomPanel:UIBottomPanel()end
''' + "assert(loadfile("+repr(str(self.uiroot/'dialogs/hire_staff.lua'))+",'t',env))()\n"+
            "assert(loadfile("+repr(str(self.uiroot/'dialogs/place_staff.lua'))+",'t',env))()\n"+
            "assert(load("+repr(method((ROOT/'tests/fixtures/bottom_panel.lua.pinned').read_text(),'function UIBottomPanel:dialogHireStaff()'))+",'bottom','t',env))()\n"+r'''
-- Declare native/graphics services. The real class, strict and domain-facing
-- hire/place methods are preserved; the hire visual constructor is isolated.
function env.UIHireStaff:UIHireStaff(ui)
 self:Window();self.ui=ui;self.world=ui.app.world;self.modal_class='main'
 self.tabs={};self.skill_bg_panel={};self.complete_blanker={};self.abilities_blanker={}
 self.tooltip_regions={{},{},{},{},{},{}}
end
local h={balance=100000,staff={},getPlayerIndex=function()return 1 end}
local w={entities={},available_staff={Doctor={},Nurse={},Handyman={},Receptionist={}},user_actions_allowed=true,
 anims={setAnimationGhostPalette=function()end,Alt32_GreyScale={}},getRoom=function()end}
local map={width=3,height=3,th={getCellFlags=function(_,x,y,out)
 out.owner=1;out.hospital=true;out.passable=x==2 and y==2;out.roomId=0 end}}
w.map=map
local app={world=w,map=map,config={ui_scale=1},_3ds={},eventHandlers={timer=function()end},
 gfx={getPalette=function()return {},{} end}}
local ui={app=app,hospital=h,windows={},modal_windows={},tutorialStep=function()end,playSound=function()end,
 setEditRoom=function()end,ScreenToWorld=function(_,x,y)return x,y end,WorldToScreen=function(_,x,y)return x,y end,
 removeKeyHandler=function()end,unregisterTextBox=function()end,unregisterHotkeyBox=function()end}
app.ui=ui;w.ui=ui;put('TheApp',app)
local bottom=env.UIBottomPanel();bottom.ui=ui;bottom.world=w
function ui:getWindow(cls)
 if cls==env.UIBottomPanel then return bottom end
 for _,window in ipairs(self.windows)do if getmetatable(window)==cls._metatable then return window end end
end
function ui:removeWindow(window)
 for i,v in ipairs(self.windows)do if v==window then table.remove(self.windows,i);break end end
 self.modal_windows[window.modal_class]=nil
end
function ui:addWindow(window)
 local old=self.modal_windows[window.modal_class]
 if old then old:close()end
 self.windows[#self.windows+1]=window;window.parent=self;self.modal_windows[window.modal_class]=window
end
local calls={new=0,profile=0,tile=0,hospital=0,corridor=0}
function w:newEntity(kind)
 calls.new=calls.new+1;local e=env.Staff();e.ticks=true;e.humanoid_class=kind
 function e:setProfile(p)calls.profile=calls.profile+1;self.profile=p end
 function e:setTile(x,y)calls.tile=calls.tile+1;self.tile_x=x;self.tile_y=y end
 function e:setHospital(owner)calls.hospital=calls.hospital+1;self.hospital=owner end
 function e:getRoom()return nil end
 function e:onPlaceInCorridor()calls.corridor=calls.corridor+1 end
 self.entities[#self.entities+1]=e;return e
end
function h:addStaff(e)self.staff[#self.staff+1]=e;self.balance=self.balance-e.profile.wage end
local function profile(wage)
 return {humanoid_class='Doctor',wage=wage,isType=function(_,kind)return kind=='Doctor' end,
 is_surgeon=0,is_psychiatrist=0,is_researcher=0}
end
w.available_staff.Doctor={profile(300),profile(100)}
-- Health reads the real class membership. Controller imports are unchanged.
class=env.class;Staff=env.Staff;Patient={}
UIHireStaff=env.UIHireStaff;UIPlaceStaff=env.UIPlaceStaff;UIBottomPanel=env.UIBottomPanel
local Busy=require('3ds.benchmark_busy')
local c={app=app,b={results={}},normal=function()end,snapshot=function()end}
local busy=Busy.new(c)
''')

    def test_actual_hire_place_success_and_refusal_do_not_inject_staff(self):
        self.run_lua(self.hiring_script()+r'''
assert(busy:hire());assert(#h.staff==1 and #w.entities==1 and h.balance==99900)
assert(w.available_staff.Doctor[1].wage==300 and #w.available_staff.Doctor==1)
assert(h.staff[1].tile_x==2 and h.staff[1].tile_y==2 and #ui.windows==0)
assert(calls.new==1 and calls.profile==1 and calls.tile==1 and calls.hospital==1 and calls.corridor==1)
h.balance=0;local ok,reason=busy:hire();assert(not ok and reason=='available_pool_or_balance' and calls.new==1)
h.balance=100000;map.th.getCellFlags=function(_,x,y,out)out.hospital=false end
ok,reason=busy:hire();assert(not ok and reason=='no_owned_corridor' and calls.new==1)
assert(#w.available_staff.Doctor==1 and #ui.windows==0)
''')
        self.run_lua(self.hiring_script()+r'''
w.user_actions_allowed=false
local ok,err=pcall(busy.hire,busy)
assert(not ok and tostring(err):find('hire window did not open',1,true))
assert(calls.new==0 and #w.available_staff.Doctor==2)
''')

    def test_busy_preparer_budget_and_legacy_default_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            base=Path(name)/'installed';(base/'Lua').mkdir(parents=True)
            (base/'Benchmark').mkdir();(base/'game/LEVELS').mkdir(parents=True)
            (base/'Lua/a.lua').write_text('return {}');(base/'config.txt').write_text('config')
            (base/'receipt.json').write_text('{}')
            for part in ('input','expanded','continuity'):(base/'Benchmark'/f'{part}.sav').write_text(part)
            for part in prepare.CAPACITY_ASSETS:(base/'game/LEVELS'/part).write_text(part)
            args=argparse.Namespace(installed_tree=base,integration_receipt='receipt.json',assets_receipt_sha256='a'*64,
                profile='expanded-zh-on',warmup_ms=30000,sample_ms=60000,stress_ms=180000,recovery=False,
                capacity=True,out=Path(name)/'legacy')
            original=prepare.sha
            def digest(path):
                if path.name=='continuity.sav':return prepare.CONTINUITY_SHA
                if path.name=='expanded.sav':return 'f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7'
                return prepare.CAPACITY_ASSETS.get(path.name) or original(path)
            with patch.object(prepare,'sha',digest):
                prepare.prepare(args);legacy=(args.out/'config.bin').read_text()
                args.busy_capacity=True;args.out=Path(name)/'busy';prepare.prepare(args)
                self.assertEqual((args.out/'config.bin').read_text(),legacy.replace('capacity=r73-v1','capacity=r74-v1'))
                self.assertEqual(json.loads((args.out/'preparation.json').read_text())['command'][-1],'1415')
                args.capacity=False;args.out=Path(name)/'busy_without_legacy_flag';prepare.prepare(args)
                self.assertEqual((args.out/'config.bin').read_text(),legacy.replace('capacity=r73-v1','capacity=r74-v1'))
                args.profile='zh-on';args.out=Path(name)/'bad'
                with self.assertRaises(ValueError):prepare.prepare(args)
                self.assertFalse(args.out.exists())

    def test_actual_native_clock_export_reads_owner_without_reset(self):
        source=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        begin=source.index('int l_simulation_clock(lua_State* state){')
        body=source[begin:source.index('\nint l_music_state',begin)]
        harness=r'''
#include <cassert>
#include <map>
#include <string>
#include "cth3ds/simulation_clock.hpp"
using cth3ds::SimulationClock;
using lua_Integer=long long;
struct lua_State{std::map<std::string,lua_Integer> fields;lua_Integer value=0;};
SimulationClock g_simulation_clock;
std::uint64_t stamp=1000000;
std::uint64_t now_us(){return stamp;}
void lua_createtable(lua_State* s,int,int){s->fields.clear();}
void lua_pushinteger(lua_State* s,lua_Integer value){s->value=value;}
void lua_setfield(lua_State* s,int,const char* key){s->fields[key]=s->value;}
'''+body+r'''
int main(){
 g_simulation_clock.begin(1);g_simulation_clock.begin(18001);
 assert(g_simulation_clock.take_step(18001));g_simulation_clock.complete_step(true);
 g_simulation_clock.begin(1000000);lua_State first,second;
 assert(l_simulation_clock(&first)==1);assert(l_simulation_clock(&second)==1);
 assert(first.fields==second.fields&&first.fields.size()==8);
 assert(first.fields.at("nominal_timer_us")==18000&&first.fields.at("completed_steps")==1);
 assert(first.fields.at("debt_us")==144000&&first.fields.at("dropped_us")==837999);
 assert(first.fields.at("failed_steps")==0&&first.fields.at("rebases")==1);
 g_simulation_clock.interrupt();stamp++;
 l_simulation_clock(&second);assert(second.fields.at("debt_us")==0);
 assert(second.fields.at("completed_steps")==1&&second.fields.at("dropped_us")==837999);
}
'''
        from test_save_memory import native_inputs
        compiler,_,_=native_inputs()
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'clock.cpp';path.write_text(harness);binary=Path(name)/'clock'
            subprocess.run([*compiler,'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                '-I'+str(ROOT/'include'),str(path),'-o',str(binary)],check=True,capture_output=True)
            completed=subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'))
            self.assertEqual(completed.returncode,0,completed.stderr)

if __name__=='__main__':unittest.main()
