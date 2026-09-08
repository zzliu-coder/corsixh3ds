"""Execute the optional benchmark state machine, including private save routing."""
from pathlib import Path
import unittest
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):test_lua_runtime.LuaRuntimeTests.setUpClass()

    def test_completed_and_cancelled_runs_restore_user_directory(self):
        script='local B=assert(loadfile('+repr(str(ROOT/'lua/3ds/benchmark.lua'))+'))()\n'+r'''
local now,active=0,false
local rows,loads={},{}
local app={savegame_dir='USER/',config={autosave_frequency=2}}
local native={clock_ms=function()return now end,
  benchmark_state=function(v)active=v end,set_notice=function()end,flush_observations=function()end,
  benchmark_mark=function(e,s,d)rows[#rows+1]={e,s,d} end}
function app:load(path)
 assert(self.savegame_dir=='sdmc:/3ds/corsixth/Benchmark/Saves/')
 assert(self.config.autosave_frequency==0)
 assert(path=='sdmc:/3ds/corsixth/Benchmark/input.sav')
 loads[#loads+1]=path
 self.world={autosave_next_tick=true,setSpeed=function(self,s)self.speed=s end,getCurrentSpeed=function(self)return self.speed end,
   game_date={tostring=function()return '1/1/1-1' end}}
 return true
end
local b=B.new(app,native);assert(active)
b:tick();assert(b.phase=='warmup' and app.world.speed=='Normal')
assert(app.world.autosave_next_tick==false and app.config.autosave_frequency==0)
now=29999;b:tick();assert(b.phase=='warmup')
now=30000;b:tick();assert(b.phase=='sample')
now=90000;b:tick();assert(b.phase=='warmup' and app.world.speed=='And then some more')
now=120000;b:tick();assert(b.phase=='sample')
now=180000;b:tick();assert(b.phase=='done' and not active)
assert(app.savegame_dir=='USER/' and app.config.autosave_frequency==2 and app.world.speed=='Normal')
assert(#loads==3 and rows[#rows][1]=='COMPLETE')
local count=#rows;b:tick();b:cancel('late');assert(#rows==count)
b=B.new(app,native);b:tick();b:cancel('B')
assert(not active and app.savegame_dir=='USER/' and app.config.autosave_frequency==2)
assert(rows[#rows][1]=='ABORT-B')
b=B.new(app,native);b:tick();app.world.speed='Pause';b:tick()
assert(b.phase=='done' and not active and rows[#rows][1]=='FAILED')
assert(app.savegame_dir=='USER/' and app.config.autosave_frequency==2)
for _,failure in ipairs({'rejected','exception'}) do
 app.load=function()if failure=='exception' then error('injected') end;return false,'injected' end
 b=B.new(app,native);b:tick()
 assert(not active and b.phase=='done' and app.savegame_dir=='USER/' and app.config.autosave_frequency==2)
 assert(rows[#rows][1]=='FAILED')
end
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_media_triplet_and_cancel_restore_user_settings(self):
        script='local B=dofile('+repr(str(ROOT/'lua/3ds/benchmark.lua'))+')\n'+r'''
local now,active=0,false
local app={savegame_dir='USER/',config={language='Chinese (simplified)',play_music=true,
 unicode_font='font',audio_music='Music',autosave_frequency=2},
 strings={checkLanguageExists=function()return true end}}
local native={clock_ms=function()return now end,benchmark_state=function(v)active=v end,
 set_notice=function()end,flush_observations=function()end,benchmark_mark=function()end}
app.audio={background_playlist={{filename_music='Music/CANDY.wav'}},
 stopBackgroundTrack=function(self)self.playing=false end,
 playBackgroundTrack=function(self,index)assert(index==1);self.playing=true;return true end}
function app:initLanguage()return true end
function app:load(path)
 assert(self.savegame_dir=='sdmc:/3ds/corsixth/Benchmark/Saves/')
 self.world={setSpeed=function(self,s)self.speed=s end,getCurrentSpeed=function(self)return self.speed end}
 return true
end
local b=B.new(app,native);assert(b.media_profiles and #b.profiles==3)
b:tick();assert(app.config.language=='English' and not app.config.play_music)
now=30000;b:tick();now=90000;b:tick()
assert(b.index==2 and app.config.language=='Chinese (simplified)' and not app.config.play_music)
now=120000;b:tick();now=180000;b:tick()
assert(b.index==3 and app.config.play_music and app.audio.playing)
now=210000;b:tick();now=270000;b:tick()
assert(b.phase=='done' and not active and app.savegame_dir=='USER/')
assert(app.config.language=='Chinese (simplified)' and app.config.play_music and app.config.autosave_frequency==2)
b=B.new(app,native);b:tick();b:cancel('B')
assert(not active and app.config.language=='Chinese (simplified)' and app.config.play_music)
assert(app.savegame_dir=='USER/')
local writes=0
app.saveConfig=function()writes=writes+1 end
local original_save=app.saveConfig
app.audio.background_music={}
app.audio.background_playlist[1].music=app.audio.background_music
app.audio.background_paused=true
app.audio.pauseBackgroundTrack=function(self)self.background_paused=true;return true end
b=B.new(app,native);b:tick();app:saveConfig();b:cancel('B')
assert(writes==0 and app.saveConfig==original_save and app.audio.background_paused)
app:initLanguage()
function app:initLanguage()self:saveConfig();return false,'injected language failure' end
b=B.new(app,native);b:tick()
assert(b.phase=='done' and not active and writes==0 and app.saveConfig==original_save)
assert(app.savegame_dir=='USER/' and app.config.autosave_frequency==2)
app:saveConfig();assert(writes==1)
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

if __name__=='__main__':unittest.main()
