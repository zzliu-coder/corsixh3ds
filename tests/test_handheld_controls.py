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
for _,name in ipairs({'Max speed','And then some more','Slowest','Slower','Normal'}) do
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
        harness = (ROOT/'tests/runtime_support/game_view_probe.cpp').read_text()
        with tempfile.TemporaryDirectory(prefix='cth3ds-r49-view-') as temp:
            source, binary = Path(temp)/'view.cpp', Path(temp)/'view'
            source.write_text(harness)
            flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
            command = [os.environ.get('CXX','c++'),'-std=c++17','-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),str(source),
                       str(ROOT/'src/3ds/runtime/game_view.cpp'),
                       str(ROOT/'src/common/input_mapper.cpp'),str(ROOT/'src/common/screen_layout.cpp'),
                       str(ROOT/'src/common/framebuffer_scaler.cpp'),*flags,'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer','-g']
            result = subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
