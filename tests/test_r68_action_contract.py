"""R68-A: actual Platform and extracted production C++/Lua action boundary.

Hardware, window constructors and game callbacks are controlled seams. The
adapter, action codec, mixed mapper, protected call and Lua parser are real.
Old defect reproductions remain separate from these new-contract tests.
"""
import json
import hashlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_lua_runtime
from test_save_memory import native_inputs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
local P=assert(loadfile(adapter_path))()
local function fresh()
 local counts={redraw=0,pause=0,scroll=0,bottom=0,dispatch=0}
 local native={span_begin=function()return 1 end,span_end=function()end,
  observe_memory=function()end,operation_boundary=function()end,
  flush_observations=function()end,checkpoint=function()end,set_notice=function()end,
  begin_critical_io=function()end,end_critical_io=function()end,atomic_commit=function()return true end,
  request_redraw=function()counts.redraw=counts.redraw+1 end}
 local ui={windows={},textboxes={},cursor_x=200,cursor_y=200,editing_allowed=true,
  hospital={research_dep_built=true},getWindow=function()return nil end,
  screen_offset_x=1000,screen_offset_y=1000,down_count=0,buttons_down={},
  setMouseReleased=function()end,setCursor=function()end,
  addWindow=function(self,window)self.windows[#self.windows+1]=window end,
  showMenuBar=function()counts.menu=(counts.menu or 0)+1 end,
  toggleTransparent=function()counts.walls=(counts.walls or 0)+1 end,
  scrollMap=function(self,x,y)
   counts.scroll=counts.scroll+1;self.screen_offset_x=self.screen_offset_x+x
   self.screen_offset_y=self.screen_offset_y+y
  end,onCursorWorldPositionChange=function()end}
 ui.edit_room={phase='walls',setBlueprintRect=function()counts.rectangle=(counts.rectangle or 0)+1 end}
 ui.bottom_panel={message_windows={{}}}
 for _,name in ipairs({'UITownMap','UIStaffManagement','UIProgressReport','UIBankManager',
  'UICasebook','UIResearch','UIPolicy','UIGraphs'})do _G[name]={}end
 for _,method in ipairs({'dialogTownMap','dialogBuildRoom','dialogStaffManagement','dialogStatus',
  'dialogBankManager','openFirstMessage','dialogDrugCasebook','dialogResearch','dialogPolicy',
  'dialogCharts','dialogHireStaff','dialogFurnishCorridor','editRoom'})do
  ui.bottom_panel[method]=function()counts.bottom=counts.bottom+1;return false end
 end
 local world={speed='Normal',user_actions_allowed=true,
  getCurrentSpeed=function(self)return self.speed end,mustPause=function()return false end,
  setSpeed=function(self,value)self.speed=value;return false end,
  pauseOrUnpause=function(self)counts.pause=counts.pause+1;self.speed=self.speed=='Pause' and 'Normal' or 'Pause' end}
 local app={ui=ui,world=world,config={},savegame_dir='PRIVATE/',save=function()return true end,
  load=function()return true end,
  dispatch=function(self,event,button,x,y)
   counts.dispatch=counts.dispatch+1
   if event=='motion' then self.ui.cursor_x,self.ui.cursor_y=button,x
   elseif event=='buttondown' then self.ui.down_count=self.ui.down_count+1
   elseif event=='buttonup' then self.ui.down_count=math.max(0,self.ui.down_count-1) end
   return false -- Upstream returns repaint/handled flags, not adapter acceptance.
  end}
 ui.app=app
 UISaveGame=function()return {visible=true}end
 UIInformation=function()return {visible=true}end
 local p=P.attach(app,native,{epoch=1,resource_events=false})
 -- Save/load transaction results have separate AR2 tests; actions consume them.
 app.quickSave=function()counts.save=(counts.save or 0)+1;return true end
 app.quickLoad=function()counts.load=(counts.load or 0)+1;return true end
 TheApp=app
 return p,app,ui,counts
end
local function action(p,kind,expected,fields)
 local input=fields or {};input.type=kind
 local ok,outcome=p:handleAction(input)
 assert(ok==true and outcome==expected,kind..': '..tostring(outcome))
end
'''

CPP = r'''
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/action_codec.hpp"
#include "cth3ds/cpu_work.hpp"
#include "cth3ds/telemetry.hpp"
#include "runtime/observation.hpp"
#include <cassert>
#include <cmath>
#include <cstring>
#include <cstdio>
#include <string>
using namespace cth3ds;
void boot_log(const char*,...) {}
RuntimeObservations g_observations;
std::uint64_t now_us() noexcept {static std::uint64_t tick=100;return ++tick;}
int g_input_cursor_x{},g_input_cursor_y{};
std::uint64_t g_input_owner_epoch{};
'''

NATIVE_MAIN = r'''
Action encoded(int type) {
 Action action;action.type=static_cast<ActionType>(type);
 action.vector={1,1};action.position={100,100};action.rectangle={1,1,2,2};return action;
}
int invoke_type(lua_State* L) {
 const auto action=encoded(static_cast<int>(luaL_checkinteger(L,1)));
 const int base=lua_gettop(L);std::string error;
 const bool ok=call_platform_method(L,"handleAction",&action,&error);
 assert(lua_gettop(L)==base);
 lua_pushboolean(L,ok);lua_pushlstring(L,error.data(),error.size());return 2;
}
int raw_type(lua_State* L) {
 const auto action=encoded(static_cast<int>(luaL_checkinteger(L,1)));
 AdapterCall request{"handleAction",&action,nullptr};
 lua_pushcfunction(L,preserve_lua_error);const int handler=lua_gettop(L);
 lua_pushcfunction(L,l_protected_adapter_call);lua_pushlightuserdata(L,&request);
 if(lua_pcall(L,1,0,handler)!=LUA_OK)return lua_error(L);
 return 0;
}
int failing_batch(lua_State* L) {
 InputMapperConfig config;config.overview_controls=true;InputMapper mapper(config);
 RawInputSnapshot input;input.timestamp_us=1000000;input.touching=true;input.touch={20,30};
 input.held=button_mask(Button::Start);unsigned sent=0,cleanup=0;std::string error;
 const bool accepted=mapper.dispatch_mixed(input,0.016F,[]{return InputContext::World;},
  [&](const Action& a){++sent;return call_platform_method(L,"handleAction",&a,&error);});
 const bool cancelled=mapper.cancel_mixed([&](const Action& a){
  ++cleanup;assert(a.type==ActionType::PointerUp && a.value==1);
  return call_platform_method(L,"handleAction",&a,&error);});
 lua_pushboolean(L,accepted);lua_pushinteger(L,sent);
 lua_pushboolean(L,cancelled);lua_pushinteger(L,cleanup);return 4;
}
int input_state(lua_State* L) {
 InputContext context{};std::string error;const int base=lua_gettop(L);
 const bool ok=call_platform_method(L,"inputState",nullptr,&error,&context);
 assert(lua_gettop(L)==base);lua_pushboolean(L,ok);lua_pushinteger(L,g_input_owner_epoch);return 2;
}
int main(int argc,char** argv) {
 if(argc!=2)return 2;lua_State* L=luaL_newstate();assert(L);luaL_openlibs(L);
 lua_newtable(L);
 lua_pushcfunction(L,invoke_type);lua_setfield(L,-2,"invoke");
 lua_pushcfunction(L,raw_type);lua_setfield(L,-2,"raw");
 lua_pushcfunction(L,failing_batch);lua_setfield(L,-2,"failing_batch");
 lua_pushcfunction(L,input_state);lua_setfield(L,-2,"input_state");
 lua_newtable(L);
 for(int n=0;n<=static_cast<int>(ActionType::TextKeyboard);++n) {
  const auto name=action_name(static_cast<ActionType>(n));
  lua_pushinteger(L,n);lua_setfield(L,-2,std::string(name).c_str());
 }
 lua_setfield(L,-2,"types");lua_setglobal(L,"probe");
 cpu_work.clock_us=now_us;
 const int result=luaL_dofile(L,argv[1]);
 if(result)std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
 lua_close(L);return result?1:0;
}
'''

class ActionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def script(self, body):
        return 'local adapter_path=' + json.dumps(str(ROOT / 'lua/3ds/platform.lua')) + '\n' + FIXTURE + body

    def lua(self, body):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.script(body))

    def test_success_noop_unsupported_and_no_duplicate_redraw(self):
        self.lua(r'''
local p,app,ui,c=fresh()
action(p,'pause_toggle','applied');assert(c.pause==1 and c.redraw==1)
action(p,'open_build','applied');assert(c.bottom==1 and c.redraw==2)
action(p,'confirm','applied');assert(c.dispatch==3 and c.redraw==3)
local before=c.redraw
app.world=nil
for _,name in ipairs({'pause_toggle','speed_cycle','quick_save','quick_load','open_save_slots','toggle_walls'})do
 action(p,name,'noop:no-world')
end
action(p,'open_quick_menu','noop:no-world-menu')
action(p,'pan_camera','noop:pan-context',{dx=1,dy=0})
action(p,'text_keyboard','noop:no-text-focus')
action(p,'zoom_in','unsupported:engine-zoom')
assert(c.redraw==before)
p,app,ui,c=fresh()
app.world.mustPause=function()return true end
action(p,'pause_toggle','noop:mandatory-pause');action(p,'speed_cycle','noop:paused')
assert(c.pause==0 and c.redraw==0)
app.world.mustPause=function()return false end
ui.windows={{visible=true}}
action(p,'pan_camera','noop:pan-context',{dx=1,dy=0})
ui.windows={};ui.down_count=1
action(p,'pan_camera','noop:pointer-held',{dx=1,dy=0})
ui.down_count=0
action(p,'pan_camera','noop:zero-pan',{dx=0,dy=0})
ui.scrollMap=function()c.scroll=c.scroll+1 end
action(p,'pan_camera','noop:map-edge',{dx=1,dy=0})
assert(c.scroll==1 and c.redraw==0)
app.world.user_actions_allowed=false
action(p,'open_build','noop:actions-prohibited')
assert(c.bottom==1 and c.redraw==1,'upstream policy callback must still execute')
ui.bottom_panel.message_windows={}
action(p,'open_messages','noop:no-messages')
ui.bottom_panel=nil
action(p,'open_build','noop:no-bottom-panel')
ui.edit_room=true
action(p,'build_room_rectangle','noop:no-blueprint')
action(p,'cursor_step','noop:subpixel-or-edge',{dx=0,dy=0})
assert(c.redraw==1)
''')

    def test_original_error_objects_escape_once_and_required_methods_fail(self):
        self.lua(r'''
for _,spec in ipairs({{'pause_toggle','world','pauseOrUnpause'},
 {'toggle_walls','ui','toggleTransparent'},{'open_build','bottom','dialogBuildRoom'},
 {'build_room_rectangle','edit','setBlueprintRect'},{'pan_camera','ui','scrollMap'},
 {'speed_cycle','world','setSpeed'}})do
 local p,app,ui,c=fresh();local n=0;local token={reason='exact error object'}
 local owners={world=app.world,ui=ui,bottom=ui.bottom_panel,edit=ui.edit_room}
 local target=owners[spec[2]]
 target[spec[3]]=function()n=n+1;error(token)end
 local ok,error_value=pcall(p.handleAction,p,{type=spec[1],dx=1,dy=0})
 assert(not ok and error_value==token and n==1 and c.redraw==0,spec[1])
 target[spec[3]]=nil
 ok,error_value=pcall(p.handleAction,p,{type=spec[1],dx=1,dy=0})
 assert(not ok and c.redraw==0,spec[1]..' missing required method')
end
local p,app,ui,c=fresh();local token={}
app.dispatch=function()error(token)end
local ok,e=pcall(p.handleAction,p,{type='confirm'});assert(not ok and e==token and c.redraw==0)
ok,e=pcall(p.handleAction,p,{type='unknown_contract_probe'})
assert(not ok and e:find('unknown_contract_probe',1,true))
assert(not pcall(p.handleAction,p,{type=false}))
assert(not pcall(p.handleAction,p,{type='pan_camera',dx=0/0,dy=1}))
''')

    def test_keyboard_and_lifecycle_noops(self):
        self.lua(r'''
local p,app,ui,c=fresh()
local box={text='old',active=true,enabled=true,visible=true,char_limit=20,
 setText=function(self,v)self.text=v end,setActive=function()end,
 confirm=function()c.confirm=(c.confirm or 0)+1 end}
ui.textboxes={box}
action(p,'text_keyboard','unsupported:keyboard')
p.native.text_keyboard=function()return false end
action(p,'text_keyboard','noop:keyboard-cancelled');assert(box.text=='old')
p.native.text_keyboard=function()return true,'new' end
action(p,'text_keyboard','applied');assert(box.text=='new' and c.confirm==1 and c.redraw==1)
p.native.text_keyboard=function()return true,'/' end
action(p,'text_keyboard','noop:text-rejected')
p.native.text_keyboard=function()ui.textboxes={};return true,'other' end
action(p,'text_keyboard','noop:text-owner-changed');assert(box.text=='new' and c.confirm==1)
action(p,'lifecycle_resume','noop:not-resumable')
action(p,'lifecycle_suspend','applied');assert(app.world.speed=='Pause')
action(p,'lifecycle_suspend','noop:not-suspendable')
action(p,'lifecycle_resume','applied');assert(app.world.speed=='Normal')
action(p,'lifecycle_exit','noop:native-exit')
''')

    def test_pinned_toolbar_open_close_refusal_advice_and_edit_policy(self):
        from support.pinned_upstream import SOURCE_HASHES
        path = ROOT / 'tests/fixtures/bottom_panel.lua.pinned'
        text = path.read_text()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         SOURCE_HASHES['CorsixTH/Lua/dialogs/bottom_panel.lua'])
        methods = text[text.index('function UIBottomPanel:dialogBankManager('):
                       text.index('-- Do not remove, for savegame compatibility')]
        methods += text[text.index('function UIBottomPanel:editRoom('):
                        text.index('function UIBottomPanel:afterLoad(')]
        self.lua('UIBottomPanel={}\n' + methods + r'''
local p,app,ui,c=fresh()
local registry={}
for _,name in ipairs({'UITownMap','UIStaffManagement','UIProgressReport','UIBankManager',
 'UICasebook','UIResearch','UIPolicy','UIGraphs','UIBuildRoom','UIFurnishCorridor',
 'UIHireStaff','UIEditRoom','UIFullscreen','UIMachineMenu'})do
 local kind={}
 setmetatable(kind,{__call=function(_,owner)
  return {kind=kind,close=function()registry[kind]=nil;c.closed=(c.closed or 0)+1 end}
 end})
 _G[name]=kind
end
ui.getWindow=function(_,kind)return registry[kind]end
ui.setEditRoom=function(self,value)self.edit_room=value end
ui.addWindow=function(self,window)
 registry[window.kind]=window;c.opened=(c.opened or 0)+1
end
ui.tutorialStep=function()c.tutorial=(c.tutorial or 0)+1 end
ui.playSound=function(_,sound)c.sound=sound;c.sounds=(c.sounds or 0)+1 end
ui.adviser={say=function(_,message)c.advice=message end}
app.using_demo_files=false;app.world.available_rooms={{class='ResearchRoom'}}
_A={warnings={research_screen_open_1='can build research',research_screen_open_2='cannot build research'}}
local bottom=setmetatable({ui=ui,world=app.world,message_windows={},additional_buttons={}}, {__index=UIBottomPanel})
local function button()return {setToggleState=function(_,value)c.toggle_updates=(c.toggle_updates or 0)+1 end}end
for n=1,8 do bottom.additional_buttons[n]=button()end
bottom.bank_button=button();ui.bottom_panel=bottom
for _,row in ipairs({{'open_staff',UIStaffManagement},{'overview',UITownMap},
 {'open_patients',UIProgressReport},{'open_bank',UIBankManager},
 {'open_casebook',UICasebook},{'open_research',UIResearch},
 {'open_policy',UIPolicy},{'open_charts',UIGraphs}})do
 action(p,row[1],'applied');assert(registry[row[2]],row[1]..' must open')
 action(p,row[1],'applied');assert(not registry[row[2]],row[1]..' must close')
end
assert(c.opened==8 and c.closed==8)
local updates=c.toggle_updates
app.world.user_actions_allowed=false
action(p,'open_staff','noop:actions-prohibited')
assert(not registry[UIStaffManagement] and c.toggle_updates==updates+9)
ui.hospital.research_dep_built=false
updates=c.toggle_updates
action(p,'open_research','noop:actions-prohibited')
assert(c.sound=='wrong2.wav' and c.toggle_updates==updates+9)
app.world.user_actions_allowed=true
action(p,'open_research','noop:research-unavailable')
assert(c.advice=='can build research' and c.sound=='wrong2.wav' and not registry[UIResearch])
-- Room editing follows editing_allowed, including its own rejection sound;
-- unrelated World.user_actions_allowed must not suppress a valid edit.
app.world.user_actions_allowed=false;ui.editing_allowed=true;ui.edit_room=false
action(p,'edit_room','applied');assert(ui.edit_room==true and c.sound=='selectx.wav')
action(p,'edit_room','applied');assert(ui.edit_room==false)
ui.editing_allowed=false
action(p,'edit_room','noop:editing-prohibited');assert(c.sound=='wrong2.wav' and ui.edit_room==false)
app.world.user_actions_allowed=true
for _,row in ipairs({{'open_build',UIBuildRoom},{'hire_staff',UIHireStaff},
 {'furnish_corridor',UIFurnishCorridor}})do
 action(p,row[1],'applied');assert(registry[row[2]])
 action(p,row[1],'applied');assert(not registry[row[2]])
end
''')

    def test_embedded_copy_matches_and_executes_same_contract(self):
        from embed_platform_lua import render
        source = (ROOT / 'lua/3ds/platform.lua').read_text()
        self.assertEqual((ROOT / 'src/3ds/embedded_platform_lua.hpp').read_text(), render(source))
        embedded = re.search(r'R"cth3ds_lua\((.*)\)cth3ds_lua"',
                            (ROOT / 'src/3ds/embedded_platform_lua.hpp').read_text(), re.S).group(1)
        script = self.script("local p=fresh();action(p,'none','noop:none');assert(not pcall(p.handleAction,p,{type='unknown'}))")
        script = script.replace("local P=assert(loadfile(adapter_path))()",
                                'local P=assert(load(' + json.dumps(embedded) + ',"@builtin/3ds/platform.lua"))()')
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_real_cpp_boundary_all_codec_types_errors_stack_and_cancel(self):
        runtime = (ROOT / 'src/3ds/runtime_3ds.cpp').read_text()
        patterns = [r'(?ms)^lua_Integer table_integer\(.*?^\}',
                    r'(?ms)^void push_action\(.*?^\}',
                    r'(?ms)^int preserve_lua_error\(.*?^\}',
                    r'(?ms)^struct AdapterCall \{.*?^\};',
                    r'(?ms)^int l_protected_adapter_call\(.*?^\}',
                    r'(?ms)^bool call_platform_method\(.*?^\}']
        extracted = '\n'.join(re.search(pattern, runtime).group() for pattern in patterns)
        body = r'''
local count=0
for name,code in pairs(probe.types)do
 local p,app,ui,c=fresh()
 local ok,e=probe.invoke(code)
 assert(ok,name..': '..tostring(e));count=count+1
end
assert(count==50,'every canonical native ActionType must be tested')
local p,app,ui,c=fresh()
local ok,e=probe.invoke(99999)
assert(not ok and e:find('unknown action: unknown',1,true) and e:find('stack traceback:',1,true))
local tostring_calls=0
local token=setmetatable({}, {__tostring=function()
 tostring_calls=tostring_calls+1;error('error object must not be stringified')
end})
for _,error_value in ipairs({47,false,token})do
 app.world.pauseOrUnpause=function()error(error_value)end
 ok,e=pcall(probe.raw,probe.types.pause_toggle)
 assert(not ok and rawequal(e,error_value),'non-string Lua error identity/value lost')
 assert(type(e)==type(error_value),'raw error type changed')
 ok,e=probe.invoke(probe.types.pause_toggle)
 assert(not ok and e=='non-string Lua error ('..type(error_value)..')',
  'outer boundary must report error type without number conversion')
 assert(tostring_calls==0,'error __tostring executed')
end
app.world.pauseOrUnpause=function()error('precise game callback failure')end
ok,e=probe.invoke(probe.types.pause_toggle)
assert(not ok and e:find('precise game callback failure',1,true) and e:find('stack traceback:',1,true))
local original=p.handleAction
for _,malformed in ipairs({'missing','false','wrong','empty-noop'})do
 p.handleAction=function()
  if malformed=='missing' then return true end
  if malformed=='false' then return false,'explicit failure' end
  if malformed=='empty-noop' then return true,'noop:' end
  return true,'success'
 end
 assert(not probe.invoke(probe.types.none))
end
p.handleAction=original
p,app,ui,c=fresh()
local state,first=probe.input_state();assert(state)
ui.windows={{visible=true}}
local state,second=probe.input_state();assert(state and second>first)
p,app,ui,c=fresh()
local original_dispatch=app.dispatch
app.dispatch=function(self,event,...)
 original_dispatch(self,event,...)
 if event=='buttondown' then error('partial press failure')end
end
local accepted,sent,cancelled,cleanup=probe.failing_batch()
assert(not accepted and sent==2 and cancelled and cleanup==1)
assert(ui.down_count==0 and c.pause==0,'failed batch continued or cancellation clicked')
print('PASS 50 native types, protected error identity, stack, epochs, partial-press cancellation')
'''
        compiler, flags, links = native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-r68-action-') as directory:
            directory = Path(directory)
            source, binary, lua = directory/'probe.cpp', directory/'probe', directory/'probe.lua'
            source.write_text(CPP + extracted + NATIVE_MAIN)
            lua.write_text(self.script(body))
            command = [*compiler, '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined',
                       '-fno-omit-frame-pointer', '-I'+str(ROOT/'include'), '-I'+str(ROOT/'src/3ds'),
                       *flags, str(source), str(ROOT/'src/common/input_mapper.cpp'),
                       str(ROOT/'src/common/action_codec.cpp'), str(ROOT/'src/common/telemetry.cpp'),
                       str(ROOT/'src/common/screen_layout.cpp'), *links, '-o', str(binary)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout+built.stderr)
            ran = subprocess.run([str(binary), str(lua)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout+ran.stderr)
            self.assertIn('PASS 50 native types', ran.stdout)
            print(ran.stdout, end='')


if __name__ == '__main__':
    unittest.main()
