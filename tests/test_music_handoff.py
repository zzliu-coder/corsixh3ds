"""Real assembled Audio playlist path; native mixer is an explicit host seam."""
from pathlib import Path
import tempfile
import unittest
from test_playable_path import generated_sources
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

class MusicHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-music-handoff-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.upstream=generated_sources(Path(cls.temp.name))

    def run_lua(self,tail):
        test_lua_runtime.LuaRuntimeTests().run_lua(r'''
local now,playing,paused,fail=0,false,false,nil
local token,phase=0,0
local logs={}
local api={stopMusic=function()playing=false end,freeMusic=function(m)m.closed=true end,
 setMusicVolume=function()end,
 loadMusicFile=function(path)if fail=='load' then return nil,'load failed' end;return{path=path}end,
 playMusic=function(m)if fail=='play'then return nil,'play failed'end;playing=true;token=token+1;phase=1;return true end}
package.preload.th3ds=function()return{is_platform=function()return true end}end
package.preload.sdl=function()return{audio=api}end
for _,name in ipairs{'rnc','lfs','TH'}do package.preload[name]=function()return{}end end
function class(name)_G[name]={};return function()end end
function permanent()return function(value)return value end end
''' + 'dofile('+repr(str(self.upstream/'CorsixTH/Lua/audio.lua'))+')\n' + r'''
local Media=require('3ds.media')
local Guard=require('3ds.benchmark_music')
local native={clock_ms=function()return now end,music_state=function()return playing,paused,token,phase end,
 diagnostic_line=function(line)logs[#logs+1]=line end}
local function audio()
 return setmetatable({app={config={play_music=true,music_volume=.5}},
 background_playlist={{enabled=true,filename_music='first.wav'},{enabled=true,filename_music='next.wav'}},
 notifyJukebox=function()end},{__index=Audio})
end
local a=audio();assert(a:playBackgroundTrack(1))
local first=a.background_music
assert(Guard.check(native,a,nil)==nil)
local function stopped()
 playing=false;phase=2;local pending=Guard.check(native,a,nil)
 assert(pending.audio==a and pending.at==now)
 return pending
end
''' + tail)

    def test_original_finished_dispatch_resolves_gap_once(self):
        self.run_lua(r'''
local pending=stopped();now=17
-- As in sdl_core, runtime_tick ran before dispatch of the already-read event.
a:onMusicOver()
assert(a.background_music.path=='next.wav' and first.closed)
assert(Guard.check(native,a,pending)==nil)
assert(logs[#logs]:match('HANDOFF_COMPLETE gap_ms=17'))
local rev,from,to=Media.musicStatus(a);assert(from and to==rev)
-- Persisted audio state contains no observation counters/closures.
assert(rawget(a,'revision')==nil and rawget(a,'finished_from')==nil)
''')

    def test_pause_stall_and_next_load_play_failures(self):
        for failure in ('pause','stall','load','play'):
            with self.subTest(failure=failure):
                self.run_lua('local mode='+repr(failure)+'\n'+r'''
local pending=stopped()
if mode=='pause' then paused=true
elseif mode=='stall'then now=1001
else fail=mode;a:onMusicOver()end
assert(not pcall(Guard.check,native,a,pending))
''')

    def test_manual_next_stop_new_owner_and_late_completion_rejected(self):
        for mode in ('next','stop','owner','late','after_finish_next'):
            with self.subTest(mode=mode):
                self.run_lua('local mode='+repr(mode)+'\n'+r'''
local pending=stopped();now=10
if mode=='next'then a:playNextBackgroundTrack()
elseif mode=='stop'then a:stopBackgroundTrack()
elseif mode=='owner'then a=audio();a:playBackgroundTrack(1)
elseif mode=='late'then a:onMusicOver();now=1001
else a:onMusicOver();a:playNextBackgroundTrack()end
assert(not pcall(Guard.check,native,a,pending))
''')

    def test_empty_playlist_or_stopped_audio_does_not_forge_finished_handoff(self):
        self.run_lua(r'''
local pending=stopped()
a.not_loaded=true;a:onMusicOver();assert(Guard.check(native,a,pending)==pending)
a.not_loaded=false;a.background_playlist={};a:onMusicOver()
assert(Guard.check(native,a,pending)==pending)
now=1001;assert(not pcall(Guard.check,native,a,pending))
''')

    def test_stop_without_native_completion_or_failed_delivery_is_rejected(self):
        self.run_lua(r'''
playing=false
for _,value in ipairs{0,1,3}do
 phase=value;assert(not pcall(Guard.check,native,a,nil))
end
phase=2;token=0;assert(not pcall(Guard.check,native,a,nil))
''')

    def test_pending_blocks_capacity_sample_and_recovery_boundaries(self):
        self.run_lua(r'''
package.loaded['3ds.state_health']={assertActive=function()return{}end}
local B=require('3ds.benchmark')
local advanced=0
local b=setmetatable({app={audio=a,eventHandlers={timer=function()end},_3ds={simulation_errors=0}},
 native=native,expected_errors=0,expected_music=true,recovery_music=true,last_health_check=-5000,
 capacity={tick=function()advanced=advanced+1;return false end},
 advanceRecovery=function()advanced=advanced+1 end},B)
for _,phase in ipairs{'capacity','sample','recovery'}do
 b.phase=phase;b.music_pending=nil;b.last_health_check=-5000;stopped()
 b:advance();assert(b.music_pending and advanced==0)
 now=now+8;b:advance();assert(b.music_pending and advanced==0)
 a:onMusicOver();assert(playing)
 -- Do not execute sample/recovery fixtures outside the pending branch.
 if phase=='capacity'then b:advance();assert(not b.music_pending and advanced==1);advanced=0 end
end
''')
