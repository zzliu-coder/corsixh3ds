"""Actual generated World and native presentation success paths, no device claims."""
import os
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest

from support.pinned_upstream import generated_sources
import test_lua_runtime
from test_playable_path import function_body

ROOT = Path(__file__).resolve().parents[1]


class R74PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='cth-r74-presentation-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = generated_sources(Path(cls.temporary.name))
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def test_generated_world_pause_permissions_and_snapshot_use_real_owner(self):
        world = self.generated / 'CorsixTH/Lua/world.lua'
        script = r'''
package.preload.TH=function()return {} end
corsixth={require=function()end}
World={}
function class(name) _G[name]={} end
Date=function()return {} end
unpack=table.unpack
tracy={Message=function()end}
local resumes=0
local blue, mandatory=false,false
TheApp={config={allow_user_actions_while_paused=false},is_3ds=true,
 audio={onEndPause=function()resumes=resumes+1 end},
 video={setBlueFilterActive=function(_,v)blue=v end}}
'''+f'assert(loadfile({str(ROOT/"tests/fixtures/strict.lua.pinned")!r}))()\nassert(loadfile({str(world)!r}))()\n'+r'''
local ui={anyMustPauseWindowOpen=function()return mandatory end,hospital={tickEarthquake=function()end}}
local date={dayOfMonth=function()return 1 end,monthOfYear=function()return 1 end,year=function()return 1 end}
date.clone=function()return date end
local w=setmetatable({ui=ui,hours_per_tick=1,tick_rate=3,tick_timer=3,game_date=date},{__index=World})
TheApp.world=w;TheApp.ui=ui;TheApp.savegame_dir='Saves/'
TheApp.save=function()return true end;TheApp.load=function()return true end
local native, states={},{}
for _,name in ipairs({'span_begin','span_end','span_abandon','observe_memory','operation_boundary',
 'operation_block','flush_observations','atomic_commit','begin_critical_io','end_critical_io',
 'set_notice','checkpoint','request_redraw'}) do native[name]=function()return true end end
native.set_state=function(state)states[#states+1]=state end
local p=require('3ds.platform').attach(TheApp,native,{resource_events=false,asset_mode='loose',epoch=1})
for _,speed in ipairs({'Normal','Max speed','And then some more'}) do
 for _,allow in ipairs({false,true}) do
  TheApp.config.allow_user_actions_while_paused=allow
  w:setSpeed(speed)
  w:pauseOrUnpause()
  assert(w:isCurrentSpeed('Pause') and blue==false)
  assert(w.user_actions_allowed==allow and w:isUserActionProhibited()==not allow)
  p:syncBottomState()
  assert(states[#states].paused and not states[#states].must_pause and states[#states].user_actions_allowed==allow)
  w:pauseOrUnpause()
  assert(w:isCurrentSpeed(speed) and w.user_actions_allowed and not blue)
  p:syncBottomState();assert(not states[#states].paused)
 end
end
w:pauseOrUnpause();mandatory=true
w:pauseOrUnpause();assert(w:isCurrentSpeed('Pause'))
w:updateUserActionsAllowed();assert(not w.user_actions_allowed)
p:syncBottomState();assert(states[#states].paused and states[#states].must_pause and not states[#states].user_actions_allowed)
mandatory=false;w:pauseOrUnpause()
TheApp.is_3ds=false;TheApp.config.allow_user_actions_while_paused=false
w:pauseOrUnpause();assert(blue==true) -- desktop keeps its original presentation
TheApp.is_3ds=true;w:updateScreenBlueFilter();assert(not blue)
assert(resumes==7)
-- Real generated World rates, not independently invented multipliers.
w:pauseOrUnpause();mandatory=false
local hints, notices={},{}
native.notice_hint=function(id)hints[#hints+1]=id;return true end
native.set_notice=function(text)notices[#notices+1]=text end
for _,language in ipairs({'chinese (simplified)','Chinese (simplified)','English'})do
 TheApp.config.language=language;p:syncBottomState()
 assert(states[#states].chinese_ui==(language~='English'))
end
w:setSpeed('Normal')
for _,entry in ipairs({{'Max speed','speed_4'},{'And then some more','speed_5'},
 {'Slowest','speed_1'},{'Slower','speed_2'},{'Normal','speed_3'}})do
 p:cycleSpeed();assert(w:getCurrentSpeed()==entry[1] and hints[#hints]==entry[2])
end
w:pauseOrUnpause();p:cycleSpeed();assert(hints[#hints]=='resume_speed')
assert(w:isCurrentSpeed('Pause'))
p:adjustZoom(1);assert(hints[#hints]=='zoom_locked')
native.notice_hint=nil;p:adjustZoom(1);assert(notices[#notices]=='ZOOM LOCKED ON 3DS')
native.notice_hint=function()return false end
p:adjustZoom(1);assert(notices[#notices]=='ZOOM LOCKED ON 3DS')
native.notice_hint=function()error('old backend')end
p:adjustZoom(1);assert(notices[#notices]=='ZOOM LOCKED ON 3DS')
assert(#notices==3)
'''
        # Load the whole generated module. Only unrelated constructors/services
        # above are seams; every speed, permission and filter method is real.
        test_lua_runtime.LuaRuntimeTests().run_lua(script)
        platform = (ROOT/'lua/3ds/platform.lua').read_text()
        self.assertNotIn('world.game_speed', platform)
        self.assertIn('world:isCurrentSpeed("Pause")', platform)
        self.assertIn('world:mustPause()', platform)

    def test_generated_startup_transitions_are_explicit_and_licenses_remain(self):
        text = (self.generated/'CorsixTH/Lua/app.lua').read_text()
        enter = text.index('TH3DS.presentation("boot-artwork")')
        first = text.index('self.gfx:loadRaw("Load01V"')
        copyright_frame = text.index('TH.freetype_font.getCopyrightNotice()')
        leave = text.index('TH3DS.presentation("game")')
        ui = text.index('  -- Load UI\n')
        self.assertLess(enter, first)
        self.assertLess(first, copyright_frame)
        self.assertLess(copyright_frame, leave)
        self.assertLess(leave, ui)
        self.assertEqual(text.count('TH3DS.presentation("boot-artwork")'), 1)
        self.assertEqual(text.count('TH3DS.presentation("game")'), 1)

    def test_native_state_fixed_masks_and_cpu_projection(self):
        source = ROOT/'tests/runtime_support/r74_presentation_probe.cpp'
        with tempfile.TemporaryDirectory(prefix='cth-r74-display-') as temp:
            binary = Path(temp)/'probe'
            command = [os.environ.get('CXX','c++'),'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                       '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(ROOT/'include'),
                       str(source), str(ROOT/'src/common/framebuffer_scaler.cpp'), '-o',str(binary)]
            compiled = subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result = subprocess.run([str(binary),temp],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout,end='')

    def test_actual_overlay_priority_cache_and_mandatory_pause(self):
        runtime = (ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        method = function_body(runtime, '  const std::uint32_t* overlay_pixels()')
        code = r'''
#include "cth3ds/boot_presentation.hpp"
#include "cth3ds/notice_hints.hpp"
#include "cth3ds/software_canvas.hpp"
#include <cassert>
#include <cstring>
using namespace cth3ds;
constexpr int kOverlayHeight=13;
static std::uint64_t now_us(){return 1000;}
struct UI {BottomUiState value;const BottomUiState& state()const{return value;}};
struct Harness {
 UI bottom_ui_;SoftwareCanvas overlay_canvas_{320,kOverlayHeight};
 std::uint64_t last_tick_us_{1000},overlay_until_us_{0},notice_until_us_{0};
 std::string overlay_text_;bool overlay_error_{false};
 const presentation_masks::Mask* overlay_mask_{nullptr};
'''+method+r'''
};
int main(){
 Harness h;auto& s=h.bottom_ui_.value;
 assert(!h.overlay_pixels());
 s.paused=true;s.notice="temporary controls";h.notice_until_us_=2000;
 auto* pixels=h.overlay_pixels();assert(pixels);assert(h.overlay_text_=="pause");
 auto original=h.overlay_canvas_.rgba_bytes();
 assert(h.overlay_pixels()==pixels&&original==h.overlay_canvas_.rgba_bytes());
 s.user_actions_allowed=true;assert(h.overlay_pixels()==pixels);
 assert(h.overlay_text_=="pause-build"&&original!=h.overlay_canvas_.rgba_bytes());
 s.notice="SAVE FAILED";s.notice_is_error=true;
 assert(h.overlay_pixels()&&h.overlay_text_=="SAVE FAILED"&&h.overlay_error_);
 const auto& bytes=h.overlay_canvas_.rgba_bytes();assert(bytes[0]==176&&bytes[1]==46&&bytes[2]==40);
 s.notice.clear();s.notice_is_error=false;s.must_pause=true;
 assert(!h.overlay_pixels()); // a forced dialog cannot advertise Start to resume
 s.must_pause=false;assert(h.overlay_pixels()&&h.overlay_text_=="pause-build");
 s.paused=false;assert(!h.overlay_pixels());
 // One shared cached strip feeds CPU copying and GPU submission. Language
 // changes invalidate it even while an ordinary hint or pause stays visible.
 s.notice="SPEED: NORMAL";s.notice_hint="speed_3";h.notice_until_us_=2000;
 assert(h.overlay_pixels());auto english=h.overlay_canvas_.rgba_bytes();
 s.chinese_ui=true;assert(h.overlay_pixels());
 assert(english!=h.overlay_canvas_.rgba_bytes());
 auto chinese=h.overlay_canvas_.rgba_bytes();assert(h.overlay_pixels());
 assert(chinese==h.overlay_canvas_.rgba_bytes());
 s.chinese_ui=false;assert(h.overlay_pixels());assert(english==h.overlay_canvas_.rgba_bytes());
 s.chinese_ui=true;s.notice_is_error=true;assert(h.overlay_pixels());
 assert(h.overlay_text_=="SPEED: NORMAL"); // diagnostic original wins over mask
 s.notice_is_error=false;s.paused=true;assert(h.overlay_pixels());
 assert(h.overlay_text_=="pause-build"&&h.overlay_mask_==&presentation_masks::paused_build);
 s.paused=false;h.notice_until_us_=0;assert(!h.overlay_pixels());
 assert(!notice_hint("unknown")&&!notice_hint("SPEED: NORMAL"));
 unsigned mask_bytes=0;
 for(const auto& hint:kNoticeHints){
  assert(hint.chinese->width<=320&&hint.chinese->height<=13);
  assert(notice_hint(hint.id)==&hint);
  mask_bytes+=(hint.chinese->width*hint.chinese->height+1)/2;
 }
 assert(mask_bytes<24000); // fixed read-only bytes, no font/texture/cache owner
}
'''
        with tempfile.TemporaryDirectory(prefix='cth-r74-strip-') as temp:
            source, binary = Path(temp)/'probe.cpp', Path(temp)/'probe'
            source.write_text(code)
            compiled = subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O1',
                '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                '-I'+str(ROOT/'include'),str(source),str(ROOT/'src/common/software_canvas.cpp'),
                str(ROOT/'src/common/screen_layout.cpp'),str(ROOT/'src/common/build_gesture.cpp'),
                '-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result = subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_cpu_end_frame_publishes_startup_pair_once(self):
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        methods='\n'.join(function_body(runtime,name) for name in (
            '  bool present_game(', '  bool mirror_game_to_bottom()',
            '  bool copy_artwork(', '  void after_frame('))
        code=(ROOT/'tests/runtime_support/r74_cpu_presentation_call_probe.cpp.in').read_text()
        code=code.replace('// INSERT_ACTUAL_METHODS',methods)
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl2'],text=True))
        with tempfile.TemporaryDirectory(prefix='cth-r74-cpu-call-') as directory:
            source=Path(directory)/'probe.cpp';source.write_text(code)
            binary=Path(directory)/'probe'
            compiled=subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O1',
                '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
                '-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),str(source),
                str(ROOT/'src/common/framebuffer_scaler.cpp'),str(ROOT/'src/3ds/runtime/game_view.cpp'),
                *flags,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout,end='')


if __name__ == '__main__':
    unittest.main()
