"""Pinned original source excerpts, real generated path and operation regressions.

Fixture bytes are MIT-licensed upstream files at commit
56bd5d00f76331c7f76d7b696726a7926303ca0c (copyright notices retained).
Regenerate with git show COMMIT:PATH; SHA256 per file is checked before use.
Fixture storage and assembly helpers live in tests/fixtures and tests/support.
No game payload, save or generated production source is part of this fixture.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from integrate_corsixth import main as integrate

from support.pinned_upstream import SOURCE_HASHES, original_sources, generated_sources


class PlayablePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.generated=generated_sources(Path(cls.temp.name))
        from test_lua_runtime import LuaRuntimeTests
        LuaRuntimeTests.setUpClass()
        cls.lua_runner=LuaRuntimeTests()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def lua(self,script):
        self.lua_runner.run_lua(script)

    def test_actual_generated_startup_order_and_loose_consumers(self):
        app=(self.generated/'CorsixTH/Lua/app.lua').read_text()
        self.assertLess(app.index('TH3DS.initialize('),app.index('self.audio:init()'))
        self.assertLess(app.index('TH3DS.initialize('),app.index('self.gfx = Graphics'))
        start=app.index('local function callback_after_movie()')
        menu=app.index('self:loadMainMenu()',start)
        attach=app.index('module.attach(',menu)
        ready=app.index('TH3DS.mark_ready()',attach)
        command=app.index('if self.command_line.continue',ready)
        self.assertLess(menu,attach);self.assertLess(ready,command)
        self.assertNotIn('runtime_initialize(L)',(self.generated/'CorsixTH/Src/sdl_core.cpp').read_text())
        self.assertIn('loadFromFile(path)',(self.generated/'CorsixTH/Lua/audio.lua').read_text())

    def test_attach_identity_failure_rollback_and_no_loose_events(self):
        self.lua(f'''
local module=dofile({str(ROOT/'lua/3ds/platform.lua')!r})
local events,commits=0,0
local native={{span_begin=function()return 1 end,span_end=function()end,observe_memory=function()end,flush_observations=function()end,checkpoint=function() end,set_notice=function() end,request_redraw=function() end,
 begin_critical_io=function() end,end_critical_io=function() end,
 atomic_commit=function() commits=commits+1;return true end,
 resource_event=function() events=events+1;error('loose event') end}}
local caps={{epoch=1,asset_mode='loose',resource_events=false}}
local app={{save=function() return true end,load=function() return true end,savegame_dir='Saves/'}}
local original=app.save
local bad={{epoch=1,asset_mode='th3ds',resource_events=true}}
assert(not pcall(module.attach,app,native,bad))
assert(app.save==original and app._3ds==nil)
events=0
local a=module.attach(app,native,caps)
local wrapper=app.save
assert(module.attach(app,native,caps)==a and app.save==wrapper)
assert(not pcall(module.attach,app,native,{{epoch=2,resource_events=false}}))
assert(app:save('slot')==true and commits==1 and events==0)
local missing={{}}
assert(not pcall(module.attach,{{}},missing,caps))
''')

    def test_save_exit_and_preload_failures_are_truthful(self):
        self.lua(f'''
UIInformation=function(ui,text) return text end
local module=dofile({str(ROOT/'lua/3ds/platform.lua')!r})
local fail_save,fail_commit,load_result=false,false,true
local exited,loaded,notices,recovery=0,0,0,0
local native={{span_begin=function()return 1 end,span_end=function()end,observe_memory=function()end,flush_observations=function()end,checkpoint=function() end,set_notice=function() notices=notices+1 end,
 request_redraw=function() end,begin_critical_io=function() end,end_critical_io=function() end,
 atomic_commit=function() return not fail_commit,'injected rename failure' end}}
local app={{world={{}},savegame_dir='Saves/',ui={{addWindow=function() end}},
 save=function(self,path) if path:find('recovery%-before%-load') then recovery=recovery+1 end
   if fail_save then error('injected writer failure') end return true end,
 load=function() loaded=loaded+1;return load_result,'compatibility refusal' end,
 exit=function() exited=exited+1 end}}
local a=module.attach(app,native,{{epoch=1,asset_mode='loose',resource_events=false}})
fail_save=true;assert(a:saveAndExit()==false and exited==0)
assert(app:load('old')==false and loaded==0)
fail_save=false;fail_commit=true;assert(a:saveAndExit()==false and exited==0)
fail_commit=false;load_result=false;assert(app:load('old')==false and loaded==1)
load_result=true;assert(app:load('old')==true and loaded==2 and recovery==3)
assert(a:saveAndExit()==true and exited==1 and notices>0)
''')

    def persistence_script(self):
        source=(self.generated/'CorsixTH/Lua/persistance.lua').read_text()
        # Engine object graph seam only: execute the generated production
        # serialization/publication functions with injected persist and map.
        source=source[source.index('strict_declare_global "SaveGame"'):]
        return '''
local IS_3DS=true
local persist={}
local MakePermanentObjectsTable=function() return {} end
local NameOf=function() return 'fixture' end
strict_declare_global=function() end
local after_save=0
local failure=''
local map={prepareForSave=function() end,afterSave=function() after_save=after_save+1 end}
math.randomdump=function() return 'random-state' end
TheApp={map=map,world={},ui={}}
persist.dump=function() if failure=='dump' then error('injected dump') end return 'SERIALIZED' end
''' + source

    def test_generated_dump_write_close_failure_matrix(self):
        self.lua(self.persistence_script()+'''
local real_open=io.open
for _,stage in ipairs({'dump','open','write','close'}) do
  failure=stage
  io.open=function()
    if failure=='open' then return nil,'injected open' end
    return {write=function() if failure=='write' then return nil,'injected write' end return true end,
            close=function() if failure=='close' then return nil,'injected close' end return true end}
  end
  local before=after_save
  local ok,err=pcall(SaveGameFile,'exact.tmp')
  assert(not ok and tostring(err):find(stage),tostring(err))
  assert(after_save==before+1,'afterSave must run after failed dump')
end
failure='';io.open=function(path) assert(path=='exact.tmp');return {write=function() return true end,close=function() return true end} end
assert(SaveGameFile('exact.tmp')==true)
io.open=real_open
''')

    def test_generated_load_selects_valid_final_backup_and_handles_afterload(self):
        self.lua(self.persistence_script()+'''
local selected,menu=0,0
local valid=true
local function state()
 local ui={cursor='c',setCursor=function() end,resync=function() end,onChangeResolution=function() end,
 menu_bar={onChangeLanguage=function() end}}
 local world={gfx_set='full',savegame_version=254,map={registerTemperatureDisplayMethod=function() end},
 resetAnimations=function() end,updateUserActionsAllowed=function() end,updateScreenBlueFilter=function() end}
 return {ui=ui,world=world,map=world.map,random=1}
end
TheApp.checkCompatibility=function() return valid end
TheApp.worldExited=function() end
TheApp.audio={playSoundEffects=function() end};TheApp.config={}
TheApp.afterLoad=function() if failure=='afterLoad' then error('injected afterLoad') end end
TheApp.loadMainMenu=function(self) menu=menu+1;self.world=nil;self.ui={} end
persist.load=function(data) if data=='BAD' then error('truncated') end selected=selected+1;return state() end
local files={slot='BAD',['slot.bak']='GOOD',['slot.tmp']='UNCOMMITTED'}
io.open=function(path) local data=files[path];if not data then return nil,'missing' end
 assert(not path:find('%.tmp'),'must not read orphan tmp')
 return {read=function() return data end,close=function() return true end} end
assert(LoadGameFile('slot')==true and selected==1)
valid=false;local old=TheApp.world;assert(LoadGameFile('slot')==false and TheApp.world==old)
valid=true;failure='afterLoad';assert(LoadGameFile('slot')==false and menu==1 and TheApp.world==nil)
files.slot='GOOD';failure='';selected=0;assert(LoadGameFile('slot')==true and selected==1)
''')


"""U3 tests generate the pinned upstream using a private exact overlay export.
SDL/Lua dispatch is a controlled host seam; generated mainloop/top/after_frame
bodies execute unchanged. No ambient generated checkout is required.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function_body(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


class U3GeneratedClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        cls.upstream = generated_sources(directory)
        cls.binary = directory / 'loop'
        loop = function_body((cls.upstream/'CorsixTH/Src/sdl_core.cpp').read_text(), 'void mainloop(lua_State* L)')
        top = function_body((cls.upstream/'CorsixTH/Src/th_gfx_sdl.cpp').read_text(), 'bool render_target::end_frame()')
        runtime = (ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        bottom = function_body(runtime, '  void after_frame(bool draw_success)')
        present = function_body(runtime, 'bool runtime_present_game(int cursor_x, int cursor_y) noexcept')
        code = HARNESS.replace('// INSERT_TOP', top).replace('// INSERT_BOTTOM', bottom).replace('// INSERT_LOOP', loop).replace('// INSERT_PRESENT', present)
        code = code.replace('// INSERT_CLOCK_COUNTERS',
            function_body(runtime, 'void runtime_simulation_begin() noexcept') + '\n' +
            function_body(runtime, 'bool runtime_simulation_step() noexcept') + '\n' +
            function_body(runtime, 'void runtime_note_timer_event() noexcept') + '\n' +
            function_body(runtime, 'void runtime_note_logic_callback(bool success) noexcept'))
        source = directory/'loop.cpp'
        source.write_text(code)
        compiler = shutil.which('clang++') or shutil.which('g++')
        built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
            '-I'+str(ROOT/'include'), str(source), str(ROOT/'src/common/telemetry.cpp'),
            '-o', str(cls.binary)], capture_output=True, text=True)
        if built.returncode: raise RuntimeError(built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, stage, failure=0, extra_timers=0):
        result = subprocess.run([str(self.binary), str(stage), str(failure), str(extra_timers)],
            check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_actual_loop_logic_top_bottom_save_delays(self):
        baseline = self.run_case(-1)
        self.assertGreater(baseline['success'], 0)
        self.assertEqual(baseline['count'], baseline['success']-1)
        self.assertEqual(baseline['timers'], 301)
        self.assertEqual(baseline['callbacks'], baseline['steps'])
        coalesced = self.run_case(-1, extra_timers=2)
        self.assertEqual(coalesced['timers'], 903)
        self.assertLess(coalesced['callbacks'], coalesced['timers'])
        self.assertEqual(coalesced['callbacks'], coalesced['steps'])
        self.assertEqual(coalesced['dropped'], 0)
        for delayed in (2, 3, 4, 5, 7):
            with self.subTest(delayed=delayed):
                value = self.run_case(delayed)
                self.assertEqual(value['count'], value['success']-1)
                self.assertEqual(value['callbacks'], value['steps'])
                self.assertLessEqual(value['callbacks'], 301*4)
                # Actual clock changes callback/frame counts under load. Check
                # each exclusive stage against its instrumented work count,
                # including the SDL flush charged to render, not presentation.
                for stage in (0, 1, 2, 3, 4, 5, 6, 7):
                    expected=value['work'][stage]*(8000 if stage==delayed else 1000)
                    if stage==3: expected+=value['flushes']*500
                    self.assertEqual(value['exclusive'][stage], expected)

    def test_actual_loop_top_draw_and_bottom_failures_are_not_successes(self):
        for failure in (1, 2, 3, 5):
            with self.subTest(failure=failure):
                value = self.run_case(-1, failure)
                self.assertEqual(value['success'], 0)
                self.assertEqual(value['count'], 0)
                self.assertGreater(value['failed'], 0)
                self.assertEqual(value['failed'], value['work'][3])

    def test_actual_loop_missing_top_is_skipped(self):
        value = self.run_case(-1, 4)
        self.assertEqual(value['success'], 0)
        self.assertGreater(value['skipped'], 0)
        # Includes iterations with no due simulation/frame and missing-top draws.
        self.assertEqual(value['skipped'], 301)
        self.assertLess(value['work'][3], value['skipped'])

    def test_actual_memory_entrypoints_and_checked_bottom_present(self):
        runtime = (ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        mirror = function_body(runtime, '  bool mirror_game_to_bottom()')
        self.assertIn('SDL_UpdateWindowSurface(bottom_window_) == 0', mirror)
        self.assertIn('scaled &&', mirror)
        sources = {
          'strings.lua': ('compile-before','compile-after'),
          'graphics.lua': ('read-before','read-after'),
          'app.lua': ('"world"','"LevelStable"'),
          'persistance.lua': ('dump-before','parse-before','afterLoad-after'),
          'audio.lua': ('"sound_index"',),
        }
        for file, tokens in sources.items():
            text = (self.upstream/'CorsixTH/Lua'/file).read_text()
            for token in tokens: self.assertIn(token, text)
        for file, tokens in {
          'th_map.cpp': ('"cells"','"original_cells"'),
          'th_gfx_sdl.cpp': ('"textures"','"vspr_decode"','"release"'),
          'th_sound.cpp': ('"sound_decode"','"sound_play"','"sound_release"'),
        }.items():
            text = (self.upstream/'CorsixTH/Src'/file).read_text()
            for token in tokens: self.assertIn(token, text)

    def test_actual_lua_save_wrapper_closes_failed_and_successful_spans(self):
        text = (ROOT/'lua/3ds/platform.lua').read_text()
        block = text.split('-- CORSIXTH_3DS_BEGIN: U3-checked-operation-spans',1)[1].split('-- CORSIXTH_3DS_END:',1)[0]
        script = '''
local current, ended, kinds = 0, {}, {}
local commit_called=false
local pack_values=table.pack
Platform={}
TH3DS = {
  span_begin=function(stage) current=current+1; kinds[current]=stage; return current end,
  span_end=function(token, success) if kinds[token]~="gc" then if success then assert(commit_called) end; ended[#ended+1]=success end end,
  observe_memory=function() end,
  flush_observations=function() end,
}
App = {_loadLevel=function() end,loadMainMenu=function() end,
       save=function(_, mode) if mode=='throw' then error('write failure') end; commit_called=true; if mode=='commit-fail' then error('commit failed') end; return mode=='ok' end,
       load=function() return false,'incompatible' end}
'''+block+'''
Platform.installOperationSpans({app=App,native=TH3DS})
assert(App:save('ok') == true and ended[#ended] == true)
assert(App:save('no') == false and ended[#ended] == false)
assert(not pcall(App.save, App, 'throw') and ended[#ended] == false)
assert(not pcall(App.save, App, 'commit-fail') and ended[#ended] == false)
local ok, err=App:load(); assert(ok==false and err=='incompatible' and ended[#ended]==false)
'''
        from test_lua_runtime import LuaRuntimeTests
        LuaRuntimeTests.setUpClass()
        LuaRuntimeTests().run_lua(script)


HARNESS = r'''
#include "cth3ds/telemetry.hpp"
#include "cth3ds/simulation_clock.hpp"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#define CORSIXTH_3DS 1
#define TRACY_ENABLE 1
#define FrameMark
using namespace std::literals;
using Uint32=unsigned;
using SDL_TimerID=int;
struct lua_State {};
constexpr int LUA_OK=0,LUA_GCSTEP=5,usertick_period_ms=18;
enum {SDL_QUIT=1, SDL_KEYDOWN,SDL_KEYUP,SDL_TEXTINPUT,SDL_TEXTEDITING,SDL_MOUSEBUTTONDOWN,
 SDL_MOUSEBUTTONUP,SDL_MOUSEWHEEL,SDL_MOUSEMOTION,SDL_MULTIGESTURE,SDL_WINDOWEVENT,
 SDL_WINDOWEVENT_FOCUS_GAINED,SDL_WINDOWEVENT_FOCUS_LOST,SDL_WINDOWEVENT_SIZE_CHANGED,
 SDL_USEREVENT_MUSIC_OVER,SDL_USEREVENT_MUSIC_LOADED,SDL_USEREVENT_TICK,
 SDL_USEREVENT_MOVIE_OVER,SDL_USEREVENT_SOUND_OVER};
struct SDL_Event {int type=0;
 struct {struct {int sym=0,mod=0;} keysym; int repeat=0;} key;
 struct {char text[32]{};} text;
 struct {char text[32]{}; int start=0,length=0;} edit;
 struct {int button=0,x=0,y=0;} button;
 struct {int x=0,y=0;} wheel;
 struct {int x=0,y=0,xrel=0,yrel=0;} motion;
 struct {int numFingers=0;double dTheta=0,dDist=0,x=0,y=0;} mgesture;
 struct {int event=0,data1=0,data2=0;} window;
 struct {int code=0;void* data1=nullptr;} user;
};
cth3ds::Telemetry g_timing;
std::uint64_t clock_us=0;
// This timing seam generates no sound-over events. Real SDL event ownership,
// queue behavior and completion deadlines are covered by test_sound_lifetime.
Uint32 SDL_GetTicks(){return static_cast<Uint32>(clock_us/1000);}
void cth3ds_poll_sound_callbacks(Uint32){}
bool cth3ds_consume_sound_callback(const SDL_Event&){return true;}
void cth3ds_clear_sound_callbacks(){}
int delayed=-1,failure=0,iterations=0,infinite_loop_counter=0;
bool g_top_present_seen=false,g_top_present_ok=false;
std::string_view dispatch;
std::uint64_t work[10]{},flushes=0;
void spend(int stage,std::uint64_t base=1000) {++work[stage];clock_us+=base+(stage==delayed?7000:0);}
namespace cth3ds {
std::uint64_t g_timer_events=0,g_logic_callbacks=0,g_logic_failures=0;
SimulationClock g_simulation_clock;
std::uint64_t now_us();
struct RuntimeTimingScope {
 std::uint64_t token;
 explicit RuntimeTimingScope(TimingStage stage):token(g_timing.begin_span(stage,clock_us)){}
 ~RuntimeTimingScope(){if(token)g_timing.end_span(token,clock_us);}
 void finish(bool ok=true){g_timing.end_span(token,clock_us,ok);token=0;}
};
bool runtime_initialize(lua_State*){return true;}
bool runtime_assert_ready(lua_State*){return true;}
void report_fatal(const char*){}
void runtime_shutdown(lua_State*){}
void runtime_tick(lua_State*){RuntimeTimingScope span(TimingStage::Runtime);spend(1);}
bool runtime_consume_sdl_event(const SDL_Event&){spend(0);return false;}
void runtime_begin_frame(){g_top_present_seen=g_top_present_ok=false;}
void runtime_top_present_complete(bool ok){g_top_present_seen=true;g_top_present_ok=ok;}
void runtime_frame_skipped(){g_timing.present_complete(clock_us,PresentResult::Skipped);}
// INSERT_CLOCK_COUNTERS
void runtime_flush_observations(bool=false){}
enum class MemoryGate{Operation};
void runtime_observe_memory(const char*,const char*,const char*,MemoryGate){}
std::uint64_t now_us(){return clock_us;}
enum class BottomScreenMode{Game,Panel};
struct Runtime {
 bool initialized_=true;BottomScreenMode bottom_mode_=BottomScreenMode::Game;
 bool mirror_game_to_bottom(){spend(5);return failure!=3;}
 bool present_game(int,int){spend(4);return failure!=1;}
 // INSERT_BOTTOM
};
Runtime& runtime(){static Runtime value;return value;}
void boot_log(const char*){}
// INSERT_PRESENT
void runtime_after_frame(bool ok){runtime().after_frame(ok);}
}
using cth3ds::now_us;
constexpr int SDL_BLENDMODE_BLEND=1;
void SDL_ClearError(){}
const char* SDL_GetError(){return failure==1?"present-failed":"";}
// Real pixel/ownership operations run in test_dual_screen_canvas. Here the
// flush belongs to the generated game's render span; LCD submission is Top.
int SDL_RenderFlush(void*){++flushes;clock_us+=500;return failure==5?-1:0;}
void SDL_SetRenderDrawBlendMode(void*,int){}
void SDL_SetRenderDrawColor(void*,int,int,int,int){}
void SDL_RenderFillRect(void*,void*){}
struct render_target {
 std::unique_ptr<int> zoom_buffer;
 struct Cursor{void draw(render_target*,int,int){}};
 Cursor* game_cursor=nullptr;int cursor_x=0,cursor_y=0;
 bool blue_filter_active=false;void* renderer=nullptr;
 bool end_frame();
};
// INSERT_TOP
struct Fps{bool limit_fps=true,track_fps=false;void count_frame(){}} fps;
int timer_frame_callback=0;
int SDL_AddTimer(int,int,void*){return 1;}
void SDL_RemoveTimer(int){}
int extra_timers=0,remaining_timers=0;
int SDL_WaitEvent(SDL_Event* e){clock_us+=1000;remaining_timers=extra_timers;e->type=iterations++<301?SDL_USEREVENT_TICK:SDL_QUIT;return 1;}
int SDL_PollEvent(SDL_Event* e){if(remaining_timers>0){--remaining_timers;e->type=SDL_USEREVENT_TICK;return 1;}return 0;}
const char* SDL_GetKeyName(int){return "key";}
void l_push_modifiers_table(lua_State*,int){}
void push_app_dispatch(lua_State*,std::string_view kind){dispatch=kind;}
void lua_pushstring(lua_State*,const char*){}
void lua_pushinteger(lua_State*,int){}
void lua_pushboolean(lua_State*,int){}
void lua_pushnumber(lua_State*,double){}
void lua_pushlstring(lua_State*,const char*,std::size_t){}
void lua_pushcclosure(lua_State*,int(*)(lua_State*),int){}
void lua_pushcfunction(lua_State*,int(*)(lua_State*)){}
void lua_pushlightuserdata(lua_State*,void*){}
int l_error_handler(lua_State*){return 0;}
int l_load_music_async_callback(lua_State*){return 0;}
const char* lua_tostring(lua_State*,int){return "draw error";}
int lua_toboolean(lua_State*,int){return 1;}
void lua_pop(lua_State*,int){}
void lua_gc(lua_State*,int,int){spend(6);}
int lua_pcall(lua_State*,int,int,int){
 if(dispatch=="timer") {
   spend(2);
   cth3ds::RuntimeTimingScope save(cth3ds::TimingStage::Save);spend(7);
 } else if(dispatch=="frame") {
   spend(3); if(failure!=4) {render_target target;target.end_frame();}
   if(failure==2)return 1;
 }
 return 0;
}
constexpr auto dispatch_keydown="keydown"sv,dispatch_keyup="keyup"sv,dispatch_textinput="textinput"sv,
 dispatch_textediting="textediting"sv,dispatch_buttondown="buttondown"sv,dispatch_buttonup="buttonup"sv,
 dispatch_mousewheel="wheel"sv,dispatch_motion="motion"sv,dispatch_multigesture="gesture"sv,
 dispatch_active="active"sv,dispatch_window_resize="resize"sv,dispatch_music_over="music"sv,
 dispatch_callback="callback"sv,dispatch_movie_over="movie"sv,dispatch_sound_over="sound"sv,
 dispatch_timer="timer"sv,dispatch_frame="frame"sv;
// INSERT_LOOP
int main(int argc,char** argv){
 delayed=argc>1?std::atoi(argv[1]):-1;failure=argc>2?std::atoi(argv[2]):0;
 extra_timers=argc>3?std::atoi(argv[3]):0;
 lua_State state;mainloop(&state);const auto s=g_timing.snapshot(clock_us);
 std::cout<<"{\"success\":"<<s.successful_presents<<",\"failed\":"<<s.failed_presents
 <<",\"skipped\":"<<s.skipped_presents<<",\"count\":"<<s.intervals.count
 <<",\"sum\":"<<s.intervals.total_us<<",\"exclusive\":[";
 for(std::size_t i=0;i<10;++i){if(i)std::cout<<",";std::cout<<s.stages[i].exclusive_us;}
 const auto clock=cth3ds::g_simulation_clock.statistics();
 std::cout<<"],\"timers\":"<<cth3ds::g_timer_events<<",\"callbacks\":"<<cth3ds::g_logic_callbacks
 <<",\"steps\":"<<clock.steps<<",\"dropped\":"<<clock.dropped_us<<",\"flushes\":"<<flushes<<",\"work\":[";
 for(int i=0;i<10;++i){if(i)std::cout<<",";std::cout<<work[i];}std::cout<<"]}";
}
'''
