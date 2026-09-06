"""R47 real mapper -> action encoding -> Lua -> pinned C integer conversion.

SDL/libctru hardware, constructors and menu hit geometry are explicit seams.
The parser boundary is real Lua 5.4; no permissive replacement of checkinteger.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest
import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]
CURSOR = r"""
int l_cursor_position(lua_State* L) {
  render_target* pCanvas =
      luaT_testuserdata<render_target>(L, 1, luaT_upvalueindex(1));
  lua_pushboolean(L, cursor::set_position(
                         pCanvas, static_cast<int>(luaL_checkinteger(L, 2)),
                         static_cast<int>(luaL_checkinteger(L, 3)))
                         ? 1
                         : 0);
  return 1;
}
"""
CPP = r"""
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/action_codec.hpp"
#include <cstring>
#include <cstdio>
static_assert(LUA_VERSION_NUM==504,"test requires Lua 5.4");
using namespace cth3ds;
struct render_target {};
template<class T> T* luaT_testuserdata(lua_State*,int,int) { static T c;return &c; }
#define luaT_upvalueindex lua_upvalueindex
namespace cursor { bool set_position(render_target*,int,int) { return true; } }
"""
MAIN = r"""
int action_for_sample(lua_State* L) {
  RawInputSnapshot input;
  input.timestamp_us=1000000;
  input.circle_x=static_cast<int>(luaL_checkinteger(L,1));
  input.circle_y=static_cast<int>(luaL_checkinteger(L,2));
  const float seconds=static_cast<float>(luaL_checknumber(L,3));
  const auto context=std::strcmp(luaL_optstring(L,4,"menu"),"world")==0 ? InputContext::World : InputContext::Menu;
  input.held=static_cast<uint32_t>(luaL_optinteger(L,5,0));
  InputMapper mapper;bool emitted=false;
  const bool accepted=mapper.dispatch_mixed(input,seconds,[context]{return context;},
    [&](const Action& a){push_action(L,a);emitted=true;return true;});
  if(!accepted)return luaL_error(L,"mapper rejected test sample");
  if(!emitted)lua_pushnil(L);
  return 1;
}
int main(int argc,char** argv) {
  if(argc!=2)return 2;
  auto* L=luaL_newstate();if(!L)return 3;luaL_openlibs(L);
  lua_newtable(L);
  lua_pushcfunction(L,l_cursor_position);lua_setfield(L,-2,"cursor_position");
  lua_pushcfunction(L,action_for_sample);lua_setfield(L,-2,"action_for_sample");
  lua_setglobal(L,"probe");
  const int result=luaL_dofile(L,argv[1]);
  if(result)std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
  lua_close(L);return result?1:0;
}
"""
EXTRA = r"""
-- The pinned conversion must reject a fractional control, proving this test
-- would catch the original failure independently of the adapter.
assert(not pcall(probe.cursor_position,{},200.5,200))
for _,mode in ipairs({'menu','game-dialog'}) do
 for _,raw in ipairs({{156,0},{0,156},{90,90},{-90,-90},{29,0},{0,-29}}) do
  local p,app,ui=fresh()
  if mode=='menu' then app.world=nil else
   ui.onMouseMove=GameUI.onMouseMove
   ui.onCursorWorldPositionChange=function()return false end
   ui._isMouseScrollButtonDown=function()return false end
   ui.ScreenToWorld=function(_,x,y)return x,y end
   app.map={th={size=function()return 128,128 end,getCellFlags=function()return {passable=false} end}}
   ui.windows={{visible=true}}
  end
  local action=assert(probe.action_for_sample(raw[1],raw[2],0.016))
  for frame=1,100 do
   local ok,err=p:handleAction(action);assert(ok,tostring(err))
   assert(math.tointeger(ui.cursor_x) and math.tointeger(ui.cursor_y))
   assert(ui.cursor_x>=0 and ui.cursor_x<640 and ui.cursor_y>=0 and ui.cursor_y<480)
  end
  assert(ui.cursor_x~=200 or ui.cursor_y~=200,'lost low-speed movement')
 end
end
local slow=probe.action_for_sample(29,0,0.016)
do
 local p,app,ui=fresh();app.world=nil
 for i=1,100 do assert(p:handleAction(slow)) end
 assert(ui.cursor_x==200+math.floor(slow.dx*16*100))
 assert(p:handlePointer{kind='motion',x=100,y=100})
 assert(p.cursor_remainder_x==0)
 assert(p:handleAction(slow));assert(ui.cursor_x==100)
 assert(p:cancelPointer());assert(p.cursor_remainder_x==0)
 ui.windows={{visible=true}};assert(p:inputState())
 assert(p.cursor_remainder_x==0)
 assert(p:handleAction{type='cursor_step',dx=1/16,dy=0,value=1})
 assert(ui.cursor_x==101 and p.cursor_remainder_x==0)
 assert(p:handlePointer{kind='motion',x=639,y=479})
 for i=1,20 do assert(p:handleAction(slow)) end
 assert(p.cursor_remainder_x==0 and ui.cursor_x==639)
 assert(p:moveCursor(-1/16,0));assert(ui.cursor_x==638)
 for _,bad in ipairs({0/0,math.huge,-math.huge}) do
  local ok=p:moveCursor(bad,0);assert(ok==false and ui.cursor_x==638)
 end
end
UIMenuBar={}
assert(loadfile(menu_methods))()
function GameUI:showMenuBar() self.menu_bar:appear() end
do
 local p,app,ui=fresh()
 local focused,selected,saved_config=0,0,0
 app.saveConfig=function()saved_config=saved_config+1 end
 p.native.focus_view=function(x,y) focused=focused+1;assert(x==ui.cursor_x and y==ui.cursor_y) end
 ui.sendToTop=function()end;ui.sendToBottom=function()end;ui.playSound=function()end
 local root={x=0,width=64,level=1,items={{handler=function()selected=selected+1 end}}}
 root.hitTest=function(_,x,y) if y<16 then return false end;if y<48 then return 1 end;return false end
 local menu=setmetatable({ui=ui,visible=false,on_top=true,menus={root},open_menus={},active_menu=false}, {__index=UIMenuBar})
 menu.hitTestBar=function(_,x,y) if x<64 and y<16 then return root end;return false end
 ui.menu_bar=menu;ui.windows={menu};ui.showMenuBar=GameUI.showMenuBar
 -- Route through real App events plus real menu press/release; layout is a seam.
 app.eventHandlers.buttondown=function(self,b,x,y) return menu:onMouseDown(b==1 and 'left' or 'right',x,y) end
 app.eventHandlers.buttonup=function(self,b,x,y) return menu:onMouseUp(b==1 and 'left' or 'right',x,y) end
 assert(p:handleAction{type='open_quick_menu'})
 assert(menu.visible and ui.cursor_x==32 and ui.cursor_y==8 and focused==1)
 assert(p:inputState().input_context=='menu')
 local action=probe.action_for_sample(156,0,0.016,p:inputState().input_context)
 assert(action.type=='cursor_step')
 assert(p:prepareInput());assert(focused==1)
 assert(p:handleAction{type='confirm'});assert(menu.active_menu==root)
 assert(p:handlePointer{kind='motion',x=32,y=32})
 assert(p:handleAction{type='confirm'});assert(selected==1 and not menu.visible)
 assert(p:inputState().input_context=='world')
 assert(p:handleAction{type='open_quick_menu'})
 assert(p:handleAction{type='cancel'})
 assert(not menu.visible and ui.cursor_y>=24 and selected==1 and saved_config==2)
 local dialog={visible=true,x=450,y=350,width=120,height=100}
 ui.windows={dialog};assert(p:prepareInput())
 assert(ui.cursor_x==510 and ui.cursor_y==390)
 ui.windows={}
 app.eventHandlers.buttondown=App.onMouseDown;app.eventHandlers.buttonup=App.onMouseUp
 assert(p:handlePointer{kind='down',x=300,y=300})
 ui.windows={{visible=true,x=0,y=0,width=100,height=100,onMouseUp=function()return false end}}
 assert(p:prepareInput());assert(ui.cursor_x==300 and ui.cursor_y==300)
 assert(p:handlePointer{kind='up'});assert(p:prepareInput())
 assert(ui.cursor_x==50 and ui.cursor_y==40)
end
do
 local p,app,ui=fresh();local samples=0
 ui.hospital={patients={a={},b={}},staff={a={}},rooms={a={},b={},c={}}}
 app.world.game_speed=1;app.world.game_date={tostring=function()return '1-1-1' end}
 app.config.language='English';app.config.play_music=false
 p.native.workload=function(v)
  samples=samples+1;assert(v.patients==2 and v.staff==1 and v.rooms==3)
  assert(v.game_date=='1-1-1' and v.language=='English' and not v.music)
 end
 for i=1,100 do assert(p:prepareInput()) end
 assert(samples==0);assert(p:samplePerformanceContext());assert(samples==1)
end
print('R47 PASS integer boundary 1200 frames slow accumulation focus menu select cancel drag workload')
"""

class InputNativeBoundaryTests(unittest.TestCase):
    def test_real_lua_integer_boundary_menu_focus_and_sampling(self):
        case=test_lua_runtime.LuaRuntimeTests('test_mixed_input_frozen_upstream_ui_methods')
        scripts=[];case.run_lua=scripts.append
        case.test_mixed_input_frozen_upstream_ui_methods()
        script=scripts[0]
        old="UpdateCursorPosition=function(_,x,y) events[#events+1]={'motion',x,y};return true end"
        self.assertEqual(script.count(old),1)
        script=script.replace(old,"UpdateCursorPosition=function(c,x,y) local ok=probe.cursor_position(c,x,y);events[#events+1]={'motion',x,y};return ok end")
        script="local menu_methods="+repr(str(ROOT/'tests/fixtures/menu_input.lua'))+"\n"+script+EXTRA
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        push=re.search(r'(?ms)^void push_action\(.*?^\}',runtime).group()
        pkg=next((x for x in ('lua5.4','lua-5.4','lua') if subprocess.run(['pkg-config','--exists',x]).returncode==0),None)
        self.assertIsNotNone(pkg,'Lua development package required')
        include=os.environ.get('CTH3DS_LUA_INCLUDE')
        flags=['-I'+include] if include else shlex.split(subprocess.check_output(['pkg-config','--cflags',pkg],text=True))
        library=os.environ.get('CTH3DS_LUA_LIBRARY')
        links=[library] if library else shlex.split(subprocess.check_output(['pkg-config','--libs',pkg],text=True))
        with tempfile.TemporaryDirectory(prefix='cth3ds-input-native-') as temp:
            temp=Path(temp);source=temp/'probe.cpp';binary=temp/'probe';lua=temp/'probe.lua'
            source.write_text(CPP+CURSOR+push+MAIN);lua.write_text(script)
            cmd=[os.environ.get('CXX','c++'),'-std=c++17','-O1','-g','-I'+str(ROOT/'include'),*flags,
                 str(source),str(ROOT/'src/common/input_mapper.cpp'),str(ROOT/'src/common/action_codec.cpp'),
                 str(ROOT/'src/common/screen_layout.cpp'),*links,'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                cmd[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer']
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary),str(lua)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('R47 PASS integer boundary 1200 frames',result.stdout)
