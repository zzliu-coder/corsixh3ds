"""R74 real Textbox/window constructors and native applet lifecycle contracts.

Original UI chunks are shared with the save regression fixture. Services mock
only drawing, UI registration/event transport, disk and the system applet.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from handheld_ui import patch_handheld_ui
from support.pinned_upstream import generated_sources
from support.save_ui import install_ui_infrastructure
import test_lua_runtime
from test_playable_path import function_body

ROOT = Path(__file__).resolve().parents[1]

SETUP = r'''
local loadUI=assert(loadfile(loader_path))()
local uiLib=loadUI(lua_root)
local env=uiLib.environment
rawset(env,'UIMainMenu',function()return {visible=true}end) -- parent menu presentation service
rawset(env,'Colours',{PanelDefault={},Setting={},SettingActive={},Scrollbar={},Disabled={},Title={},Caption={},Textbox={}})
local labels={caption='Caption',player_name='Player',medium='Medium',difficulty='Difficulty',
 tutorial='Tutorial',start='Start',cancel='Cancel',scrollspeed='Scroll',apply='Apply',
 apply_scrollspeed='Apply',cancel_scrollspeed='Cancel',start_game='Start',on='On',off='Off'}
env._S.new_game_window=labels;env._S.options_window=labels
env._S.tooltip.new_game_window=labels;env._S.tooltip.options_window=labels
assert(loadfile(lua_root..'/dialogs/resizables/new_game.lua','t',env))()
assert(loadfile(lua_root..'/dialogs/resizables/options.lua','t',env))()
local module=assert(loadfile(adapter_path))()
local function fresh()
 local count={keyboard=0,saves=0,config=0,redraw=0,dispatch=0}
 local ui={windows={},textboxes={},cursor_x=0,cursor_y=0,down_count=0,editing_allowed=true,
  registerTextBox=function(self,b)self.textboxes[#self.textboxes+1]=b end,
  unregisterTextBox=function(self,b)for i,v in ipairs(self.textboxes)do if b==v then table.remove(self.textboxes,i);return end end end,
  removeKeyHandler=function()end,playSound=function()end,setMouseReleased=function()end,
  removeWindow=function(self,w)for i,v in ipairs(self.windows)do if v==w then table.remove(self.windows,i);return end end end,
  addWindow=function(self,w)w.parent=self;table.insert(self.windows,1,w);count.dialog=w end}
 local app={ui=ui,savegame_dir='/PRIVATE/',config={language='Chinese (simplified)',ui_scale=1,player_name='PLAYER',scroll_speed=2},
  runtime_config={},save=function(_,path)count.saves=count.saves+1;count.write_path=path;return true end,load=function()return true end,
  saveConfig=function()count.config=count.config+1 end,
  gfx={loadSpriteTable=function()return {}end},fs={fileExists=function()return false end}}
 ui.app=app;rawset(env,'TheApp',app)
 local native={}
 for _,name in ipairs({'span_begin','span_end','span_abandon','observe_memory','operation_boundary',
  'flush_observations','atomic_commit','begin_critical_io','end_critical_io','operation_block','checkpoint','set_notice'})do
  native[name]=function()return true end
 end
 native.request_redraw=function()count.redraw=count.redraw+1 end
 local p=module.attach(app,native,{epoch=74,resource_events=false})
 native.text_keyboard=function(initial,limit,policy)
  assert(not count.in_release,'applet must run after real mouse-up method returns')
  assert(ui.down_count==0,'pen release must be complete')
  count.keyboard=count.keyboard+1;count.initial=initial;count.limit=limit;count.policy=policy
  if count.during then count.during() end
  return count.accept,count.value
 end
 function app:dispatch(kind,a,x,y)
  count.dispatch=count.dispatch+1
  if kind=='motion' then ui.cursor_x,ui.cursor_y=a,x;return end
  local w=ui.windows[1]
  if not w then return end
  if kind=='buttondown' then
   ui.down_count=ui.down_count+1
   -- Window:onMouseDown's geometry service is retained by assigning the
   -- exact real button at these deterministic local panel coordinates.
   for _,b in ipairs(w.buttons)do if b.x<=x and x<b.r and b.y<=y and y<b.b then w.active_button=b;break end end
  else
   ui.down_count=math.max(0,ui.down_count-1);count.in_release=true
   env.Window.onMouseUp(w,a==1 and 'left' or 'right',x,y)
   count.in_release=false
  end
 end
 -- Graphics-only panel construction; Panel->makeTextbox->Window->Textbox,
 -- Button toggle/click, setActive and field callbacks remain real methods.
 local function setup_window(w,width,height)
  w:Window();w.ui=ui;w.width=width;w.height=height;w.col_bg={}
  function w:setDefaultPosition()end
  function w:addBevelPanel(x,y,width,height)
   local panel=setmetatable({window=self,x=x,y=y,w=width,h=height,visible=true},env.Panel._metatable)
   function panel:setLabel(text)self.label=text;return self end
   function panel:setTooltip()return self end
   function panel:setAutoClip()return self end
   return panel
  end
 end
 local function make(kind)
  local class=kind=='save' and env.UISaveGame or kind=='player' and env.UINewGame or env.UIScrollSpeed
  local w=setmetatable({},class._metatable)
  function w:UIResizable(_,width,height)setup_window(self,width,height)end
  function w:UIFileBrowser()setup_window(self,450,235);self.control={sortByDate=function()end}end
  if kind=='save' then w:UISaveGame(ui)
  elseif kind=='player' then w:UINewGame(ui)
  else w:UIScrollSpeed(ui,function(value)count.applied=value end)end
  ui.windows={w};w.parent=ui
  local box=w.new_savegame_textbox or w.name_textbox or w.scrollspeed_textbox
  return w,box
 end
 local function tap(box)
  local b=box.button;local x,y=b.x+1,b.y+1
  local before=count.keyboard
  p:handlePointer{kind='down',x=x,y=y};assert(count.keyboard==before,'press must not open keyboard')
  return p:handlePointer{kind='up',x=x,y=y}
 end
 return p,app,ui,count,make,tap
end
'''


class R74KeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-r74-keyboard-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.generated=generated_sources(Path(cls.temp.name))
        cls.lua_root=install_ui_infrastructure(cls.generated)
        # These additional full UI chunks are omitted by the compact 44-file
        # fixture; run the same final production owner after adding them.
        patch_handheld_ui(cls.generated)
        assert patch_handheld_ui(cls.generated)==[]

    def lua(self,body):
        test_lua_runtime.LuaRuntimeTests().run_lua('local lua_root='+repr(str(self.lua_root))+'\n'+
            'local adapter_path='+repr(str(ROOT/'lua/3ds/platform.lua'))+'\n'+
            'local loader_path='+repr(str(ROOT/'tests/runtime_support/save_ui_loader.lua'))+'\n'+SETUP+body)

    def test_real_save_click_cancel_owner_and_once(self):
        self.lua(r'''
local p,app,ui,c,make,tap=fresh();local w,b=make('save')
assert(b._3ds_keyboard_kind=='filename')
local localized=0
for _,button in ipairs(w.buttons)do
 if button.panel_for_sprite.label=='存档槽 '..tostring(localized+1)then localized=localized+1 end
end
assert(localized==3,'three localized slots retain their buttons')
assert(w.panels[1]==nil) -- service panels carry no native graphics allocation
b:setActive(true);assert(c.keyboard==0,'initial focus must not open keyboard')
b:setText('中文旧值');c.accept=false;tap(b)
assert(c.keyboard==1 and c.initial=='中文旧值' and b.text=='中文旧值' and b.active and c.saves==0)
p:handlePointer{kind='up'};assert(c.keyboard==1,'duplicate release must not reopen')
c.accept=true
for _,invalid in ipairs({'','  ','../bad','a/b','a\\b','a.b','a\n','a\0','中文',string.rep('x',41)})do
 c.value=invalid;tap(b);assert(b.text=='中文旧值' and c.saves==0)
end
c.value='SlotA';c.during=function()b.enabled=false end;tap(b)
assert(b.text=='中文旧值' and c.saves==0)
b.enabled=true;c.during=function()ui.windows={{visible=true}}end;ui.windows={w};tap(b)
assert(b.text=='中文旧值' and c.saves==0)
ui.windows={w};c.during=function()w:close()end;tap(b)
assert(c.saves==0 and w.closed)
assert(p.keyboard_request==nil and p.keyboard_release_ui==nil)
for _,change in ipairs({'ui','owner','unregister','hidden','disabled'})do
 p,app,ui,c,make,tap=fresh();w,b=make('save');c.accept=true;c.value='New'
 c.during=function()
  if change=='ui'then app.ui={textboxes={},windows={}}
  elseif change=='owner'then b.panel.window={ui=ui}
  elseif change=='unregister'then ui:unregisterTextBox(b)
  elseif change=='hidden'then w.visible=false
  else w.enabled=false end
 end
 tap(b);assert(c.saves==0 and b.text=='Slot1',change..' must reject stale completion')
end
p,app,ui,c,make,tap=fresh();p.save_prefix='R62-Recovered-';w,b=make('save')
c.accept=false;tap(b);assert(b.text=='R62-Recovered-Slot1' and c.saves==0)
p.native.text_keyboard=nil;tap(b);assert(c.saves==0 and b.text=='R62-Recovered-Slot1')
''')

    def test_actual_native_applet_audio_input_clock_and_exit_contract(self):
        source=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        body=function_body(source,'bool text_keyboard(')
        code=r'''
#include <atomic>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include "cth3ds/simulation_clock.hpp"
#define CORSIXTH_3DS_GPU 1
using cth3ds::SimulationClock;
SimulationClock clock_owner;
int boundaries=0,gpu_waits=0,notices=0;
void runtime_operation_boundary(){++boundaries;clock_owner.interrupt();}
void gpu_quiesce(){++gpu_waits;}
void boot_log(const char*,...){}
void boot_log_memory(const char*){}
std::array<bool,32> paused{};
bool music=false,callbacks=false;
int Mix_Paused(int i){return paused[i];}
void Mix_Pause(int i){paused[i]=true;}
void Mix_Resume(int i){paused[i]=false;}
int Mix_PausedMusic(){return music;}
void Mix_PauseMusic(){music=true;}
void Mix_ResumeMusic(){music=false;}
unsigned SDL_GetTicks(){return 0;}
void cth3ds_suspend_sound_callbacks(bool enabled,unsigned){callbacks=enabled;}
enum {SWKBD_TYPE_NORMAL,SWKBD_TYPE_NUMPAD};
enum {SWKBD_BUTTON_LEFT,SWKBD_BUTTON_RIGHT,SWKBD_BUTTON_NONE};
constexpr std::uint32_t kLifecycleExit=1;
struct SwkbdState{int type{},limit{};};
int next_button=SWKBD_BUTTON_RIGHT,last_type=-1;
void swkbdInit(SwkbdState* s,int type,int buttons,int limit){assert(buttons==2);s->type=type;s->limit=limit;}
void swkbdSetInitialText(SwkbdState*,const char*){}
void swkbdSetHintText(SwkbdState*,const char*){}
void swkbdSetButton(SwkbdState*,int,const char*,bool){}
int swkbdInputText(SwkbdState* s,char* output,std::size_t capacity){
 assert(callbacks&&music);for(bool value:paused)assert(value);
 assert(capacity==164&&s->limit==4);last_type=s->type;
 std::strcpy(output,"1234");return next_button;
}
int swkbdGetResult(SwkbdState*){return 0;}
struct Runtime{
 struct Collector{bool paused{};unsigned calls{};void pause(bool value){paused=value;++calls;}}input_collector_;
 std::uint64_t last_input_us_=123;
 std::atomic<std::uint32_t>pending_lifecycle_{0};
 void set_notice(const char*,bool){++notices;}
// ACTUAL_FUNCTION
};
int main(){
 for(int choice:{SWKBD_BUTTON_RIGHT,SWKBD_BUTTON_LEFT,SWKBD_BUTTON_NONE}){
  for(bool exit:{false,true}){
   Runtime r;boundaries=0;gpu_waits=0;next_button=choice;notices=0;
   for(int i=0;i<32;++i)paused[i]=(i%3)==0;
   const auto original=paused;music=exit;const bool original_music=music;
   r.pending_lifecycle_=exit?kLifecycleExit:0;
   clock_owner.reset();clock_owner.begin(0);clock_owner.begin(36000);
   assert(clock_owner.statistics().debt_us==36000);
   char output[164]{};
   const bool accepted=r.text_keyboard("1234",4,"numbers",output,sizeof(output));
   assert(accepted==(choice==SWKBD_BUTTON_RIGHT&&!exit));
   assert(last_type==SWKBD_TYPE_NUMPAD&&boundaries==2&&gpu_waits==1);
   assert(paused==original&&music==original_music&&!callbacks);
   assert(r.input_collector_.calls==2&&!r.input_collector_.paused&&r.last_input_us_==0);
   assert(notices==(choice==SWKBD_BUTTON_NONE));
   clock_owner.begin(900000000);assert(clock_owner.statistics().debt_us==0&&!clock_owner.take_step(900000000));
  }
 }
 Runtime r;char result[164]{};next_button=SWKBD_BUTTON_LEFT;
 assert(!r.text_keyboard("name",4,"player",result,sizeof(result))&&last_type==SWKBD_TYPE_NORMAL);
 std::puts("PASS native keyboard: actual applet function, 6 return/exit cases, audio state, input release, clock rebase");
}
'''.replace('// ACTUAL_FUNCTION',body)
        with tempfile.TemporaryDirectory(prefix='cth-r74-native-keyboard-') as name:
            directory=Path(name);cpp=directory/'keyboard.cpp';cpp.write_text(code)
            binary=directory/'keyboard'
            compiler=shutil.which('clang++') or shutil.which('g++')
            self.assertIsNotNone(compiler)
            built=subprocess.run([compiler,'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror',
                '-fsanitize=address,undefined','-I'+str(ROOT/'include'),str(cpp),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS native keyboard:',result.stdout)
            print(result.stdout,end='')

    def test_real_player_confirm_and_numeric_apply(self):
        self.lua(r'''
local p,app,ui,c,make,tap=fresh();local w,b=make('player')
c.accept=true;c.value='Mary + Ann';tap(b)
assert(c.policy=='player' and c.limit==15 and w.player_name=='Mary + Ann' and c.config==1 and not b.active)
c.value='';tap(b);assert(w.player_name=='Mary + Ann' and b.text=='Mary + Ann' and c.config==1)
c.value='Bad_Name';tap(b);assert(b.text=='Mary + Ann' and c.config==1)
c.value=string.rep('A',16);tap(b);assert(c.config==1)
c.value='Alice';b:setActive(true);p:editText();assert(w.player_name=='Alice' and c.config==2,'A fallback')
w:close();w,b=make('numeric');c.value='9999';tap(b)
assert(c.policy=='numbers' and c.limit==4 and b.text=='9999' and app.config.scroll_speed==2 and not b.active)
c.value='2x';tap(b);assert(b.text=='9999' and app.config.scroll_speed==2)
w:ok();assert(app.config.scroll_speed==10 and c.applied==10,'original Apply clamps only at apply')
assert(rawget(env,'IS_3DS')==nil)
''')

    def test_real_keyboard_save_confirmation_and_overwrite_transaction(self):
        self.lua(r'''
local p,app,ui,c,make,tap=fresh();local w,b=make('save')
c.accept=true;c.value=string.rep('A',40);tap(b)
assert(c.limit==40 and c.policy=='filename' and c.saves==1 and w.closed and not b.active)
assert(c.write_path=='/PRIVATE/'..c.value..'.sav.tmp' and p.operations.last.committed)
p:handlePointer{kind='up'};assert(c.saves==1 and c.keyboard==1,'no second confirm on extra release')
p,app,ui,c,make,tap=fresh();w,b=make('save')
uiLib.services.attributes=function()return 10 end
c.accept=true;c.value='Existing';tap(b)
assert(c.saves==0 and not w.closed and c.dialog and ui.windows[1]==c.dialog)
c.dialog:cancel();assert(c.saves==0 and not w.closed)
tap(b);assert(c.keyboard==2 and c.saves==0)
c.dialog:ok();assert(c.saves==1 and w.closed and p.operations.last.committed)
assert(c.write_path=='/PRIVATE/Existing.sav.tmp')
''')

    def test_real_release_error_clears_queue_and_unknown_fields_stay_original(self):
        self.lua(r'''
local p,app,ui,c,make,tap=fresh();local w,b=make('player')
local dispatch=app.dispatch
function app:dispatch(kind,...)
 dispatch(self,kind,...)
 if kind=='buttonup' then error('transport failure after callback')end
end
assert(not pcall(tap,b));assert(c.keyboard==0 and p.keyboard_request==nil and p.keyboard_release_ui==nil)
app.dispatch=dispatch;b._3ds_keyboard_kind=nil;b:setActive(false)
c.accept=true;c.value='ignored';tap(b);assert(c.keyboard==0 and b.active)
b:setText({'multiline'});assert(select(2,p:editText())=='noop:no-text-focus')
''')
