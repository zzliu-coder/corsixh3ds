"""R49 actual adapter/World/viewport regressions; HID/LCD remain device gates."""
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

import test_lua_runtime
from test_playable_path import original_sources

ROOT = Path(__file__).resolve().parents[1]


def cpp_method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, at = 1, brace + 1
    while depth:
        depth += (source[at] == '{') - (source[at] == '}')
        at += 1
    return source[start:at]


class HandheldControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def run_lua(self, body):
        case = test_lua_runtime.LuaRuntimeTests('test_mixed_input_frozen_upstream_ui_methods')
        scripts = []
        case.run_lua = scripts.append
        case.test_mixed_input_frozen_upstream_ui_methods()
        fixture = scripts[0].split('local count=0\n')[0]
        source = ROOT / 'tests/fixtures/handheld_world.lua.pinned'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         '8b5e0ca533c74a0e40320b0429fd84b76cc8a301f2c627ef1367720ef166f2e0')
        test_lua_runtime.LuaRuntimeTests.run_lua(case, fixture + '\ndofile(' + repr(str(source)) + ')\n' + body)

    def test_named_speed_cycle_pause_and_rejected_change(self):
        self.run_lua(r'''
local p,app,ui=fresh()
local notices,checkpoints={},{}
p.native.set_notice=function(message)notices[#notices+1]=message end
p.native.checkpoint=function(name,phase,identity)checkpoints[#checkpoints+1]=identity end
tracy={Message=function()end}
app.audio={onEndPause=function()end}
ui.hospital={tickEarthquake=function()end}
ui.anyMustPauseWindowOpen=function()return false end
local w=setmetatable({ui=ui,hours_per_tick=1,tick_rate=3,tick_timer=3},{__index=World})
w.updateUserActionsAllowed=function()end
w.updateScreenBlueFilter=function()end
app.world=w
for _,name in ipairs({'Max speed','And then some more','Normal'}) do
  assert(p:handleAction{type='speed_cycle'})
  assert(w:getCurrentSpeed()==name and checkpoints[#checkpoints]==name)
end
-- No implicit resume and no bypass of a must-pause window.
w:setSpeed('Pause')
assert(p:handleAction{type='speed_cycle'} and w:getCurrentSpeed()=='Pause')
w:setSpeed('Normal');ui.anyMustPauseWindowOpen=function()return true end
assert(p:handleAction{type='speed_cycle'} and w:getCurrentSpeed()=='Normal')
ui.anyMustPauseWindowOpen=function()return false end
local count=#checkpoints
w.setSpeed=function()end
assert(p:handleAction{type='speed_cycle'} and #checkpoints==count)
assert(notices[#notices]:find('UNCHANGED',1,true))
w.setSpeed=function()error('injected speed failure')end
local ok,detail=p:handleAction{type='speed_cycle'}
assert(ok==false and detail:find('injected speed failure',1,true))
app.world=nil;assert(p:handleAction{type='speed_cycle'})
''')

    def test_camera_sign_and_placement_cancel_vs_rotate(self):
        with tempfile.TemporaryDirectory() as temp:
            upstream = original_sources(Path(temp)/'upstream')
            game_ui = (upstream/'CorsixTH/Lua/game_ui.lua').read_text()
            scroll = re.search(r'(?ms)^function GameUI:scrollMap\(dx, dy\).*?^end', game_ui).group()
        self.run_lua('GameUI={};local floor=math.floor\n' + scroll + r'''
local p,app,ui,events,keys=fresh()
ui.scrollMap=GameUI.scrollMap
ui.limitPointToDiamond=function(x,y)return x,y,true end
for _,d in ipairs({{0,-10},{0,10},{-10,0},{10,0}})do
  ui.screen_offset_x,ui.screen_offset_y=1000,1000
  assert(p:handleAction{type='pan_camera',dx=d[1],dy=d[2]})
  assert(ui.screen_offset_x==1000+d[1] and ui.screen_offset_y==1000+d[2])
end
local rotations=0
local object_window={visible=true,phase='objects',place_objects=true,x=0,y=0,width=100,height=100,
 onMouseDown=function()return false end,onMouseMove=function()return false end,
 world={user_actions_allowed=true},tryNextOrientation=function()rotations=rotations+1 end}
ui.windows={object_window};assert(p:inputContext()=='place_object')
app.eventHandlers.keydown=function(_,key)keys[#keys+1]={'down',key}end
app.eventHandlers.keyup=function(_,key)keys[#keys+1]={'up',key}end
Window.onMouseUp=function()return false end
app.eventHandlers.buttonup=function(_,button,x,y)
 return UIPlaceObjects.onMouseUp(object_window,button==3 and 'right' or 'left',x,y)
end
assert(p:handleAction{type='cancel'});assert(rotations==0 and #keys==2)
assert(keys[1][1]=='down' and keys[1][2]=='Escape' and keys[2][1]=='up')
assert(p:handleAction{type='rotate_object'});assert(rotations==1 and #keys==2)
''')

    def test_runtime_pointer_authority_view_modes_and_real_pixels(self):
        runtime = (ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        signatures = ['  void focus_view(', '  void set_view_context(', '  void toggle_view(',
                      '  void move_view(', '  bool activation_needs_focus(',
                      '  bool valid_output_surface(', '  bool present_game(']
        methods = '\n'.join(cpp_method(runtime, sig) for sig in signatures)
        members = runtime[runtime.index('  SDL_Window* game_window_{'):runtime.index('  Uint32 game_window_id_')]
        harness = r'''
#include <SDL.h>
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <string>
#include "cth3ds/events.hpp"
#include "cth3ds/input_mapper.hpp"
#include "cth3ds/hid_snapshot.hpp"
#include "cth3ds/framebuffer_scaler.hpp"
using namespace cth3ds;
int g_input_cursor_x=320,g_input_cursor_y=240;
SDL_Surface* destination{};
std::uint64_t now_us(){static std::uint64_t t=0;return ++t;}
void boot_log(const char*,...){}
#define SDL_GetWindowSurface(window) destination
#define SDL_UpdateWindowSurface(window) 0
struct ViewProbe {
''' + members + r'''
 std::string notice;
 void request_redraw(){}
 void set_notice(std::string text,bool){notice=text;}
 bool display_failure(const char*,const char*){return false;}
''' + methods + r'''
};
int main(){
 destination=SDL_CreateRGBSurfaceWithFormat(0,400,240,32,SDL_PIXELFORMAT_RGBA8888);
 auto* source=SDL_CreateRGBSurfaceWithFormat(0,640,480,32,SDL_PIXELFORMAT_ABGR8888);
 assert(destination && source);
 auto* pixels=static_cast<std::uint32_t*>(source->pixels);
 for(int i=0;i<640*480;++i)pixels[i]=0xff000000U+static_cast<std::uint32_t>(i);
 ViewProbe v;v.game_window_=reinterpret_cast<SDL_Window*>(1);v.game_surface_=source;
 v.set_view_context(InputContext::World);assert(v.present_game(0,0));
 assert(v.top_origin_.x==120 && v.top_origin_.y==120);
 InputMapperConfig c;c.overview_controls=true;InputMapper mapper(c);
 RawInputSnapshot s;s.timestamp_us=8000;s.circle_x=156;s.circle_y=-156;
 InputContext context=InputContext::World;
 auto read=[&]{v.set_view_context(context);return context;};
 auto dispatch=[&](const Action& a){
   if(a.type==ActionType::MoveViewport)v.move_view(a.vector);
   if(a.type==ActionType::ToggleView)v.toggle_view();return true;
 };
 assert(mapper.dispatch_mixed(s,.1F,read,dispatch));
 const auto moved=v.top_origin_;assert(moved.x>120 && moved.y>120);
 for(int i=0;i<20;++i)assert(v.present_game(0,0));
 assert(v.top_origin_==moved); // the dead renderer cursor must not reset a manual view
 s.circle_x=s.circle_y=0;
 // Read the real shared-memory parser as well as mapper + viewport + scaler.
 std::uint32_t hid[128]{};hid[4]=hid[46]=1;hid[14]=button_mask(Button::L);
 for(auto ctx:{InputContext::World,InputContext::Menu,InputContext::Dialog,InputContext::TextInput}){
   context=ctx;read();
   assert(v.view_width_==400);
   for(int toggle=0;toggle<2;++toggle){
     hid[14]=0;assert(read_hid_snapshot(hid,s.timestamp_us+8000,s));
     assert(mapper.dispatch_mixed(s,.008F,read,dispatch));
     hid[14]=button_mask(Button::L);assert(read_hid_snapshot(hid,s.timestamp_us+8000,s));
     assert(mapper.dispatch_mixed(s,.008F,read,dispatch));
     assert(v.view_width_==(toggle==0?480:400) && v.view_height_==(toggle==0?288:240));
     assert(v.present_game(0,0));
     auto* output=static_cast<const std::uint32_t*>(destination->pixels);
     for(int y=0;y<240;++y)for(int x=0;x<400;++x){
       const auto word=pixels[(v.top_origin_.y+y*v.view_height_/240)*640+v.top_origin_.x+x*v.view_width_/400];
       assert(output[y*400+x]==__builtin_bswap32(word));
     }
   }
 }
 v.set_view_context(InputContext::World);v.toggle_view();assert(v.view_width_==480);
 v.set_view_context(InputContext::Dialog);assert(v.view_width_==400);
 v.set_view_context(InputContext::World);assert(v.view_width_==480);
 v.toggle_view();g_input_cursor_x=g_input_cursor_y=10;assert(v.present_game(639,479));
 assert(v.top_origin_.x==0 && v.top_origin_.y==0);
 v.move_view({300,300});assert(v.present_game(0,0));
 assert(v.top_origin_.x==240 && v.top_origin_.y==240);
 Action a;a.type=ActionType::Confirm;assert(v.activation_needs_focus(a));
 v.focus_view(10,10);assert(v.present_game(0,0));assert(!v.activation_needs_focus(a));
 SDL_FreeSurface(source);SDL_FreeSurface(destination);
 std::puts("PASS R49 actual viewport, HID-to-L modes, pixels, offscreen confirmation");
}
'''
        with tempfile.TemporaryDirectory(prefix='cth3ds-r49-view-') as temp:
            source, binary = Path(temp)/'view.cpp', Path(temp)/'view'
            source.write_text(harness)
            flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
            command = [os.environ.get('CXX','c++'),'-std=c++17','-I'+str(ROOT/'include'),str(source),
                       str(ROOT/'src/common/input_mapper.cpp'),str(ROOT/'src/common/screen_layout.cpp'),
                       str(ROOT/'src/common/framebuffer_scaler.cpp'),*flags,'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer','-g']
            result = subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
