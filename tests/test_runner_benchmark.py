"""Runner completion and cancellation exercise the existing Lua state machine."""
from pathlib import Path
import unittest
import test_benchmark

class RunnerBenchmarkTests(unittest.TestCase):
    setUpClass=classmethod(lambda cls: test_benchmark.BenchmarkTests.setUpClass())
    run_benchmark_lua=test_benchmark.BenchmarkTests.run_benchmark_lua
    def test_runner_private_complete_cancel_failure_and_repeat(self):
        self.run_benchmark_lua('local B=dofile('+repr(str(Path(__file__).resolve().parents[1]/'lua/3ds/benchmark.lua'))+')\n'+r'''
local now,root=0,'sdmc:/3ds/ftpd-runner/runs/new-run-01/'
local original_open=io.open
io.open=function()return nil end
local app={savegame_dir=root..'save/',config={language='Chinese (simplified)',play_music=true,
 unicode_font='font',audio_music='Music',autosave_frequency=2},
 strings={checkLanguageExists=function()return true end}}
app.audio={background_playlist={{filename_music='Music/CANDY.wav'}},
 stopBackgroundTrack=function()end,playBackgroundTrack=function()return true end}
function app:initLanguage()return true end
local loads,saves,exits,results={},{},0,{}
function app:load(name)
 assert(self.savegame_dir==root..'save/')
 loads[#loads+1]=name
 self.world={setSpeed=function(self,s)self.speed=s end,getCurrentSpeed=function(self)return self.speed end}
 return true
end
function app:save(name)assert(name:sub(1,#root)==root);saves[#saves+1]=name;return true end
function app:exit()assert(self.savegame_dir==root..'save/');exits=exits+1 end
local marks={}
local native={clock_ms=function()return now end,benchmark_state=function()end,
 set_notice=function()end,flush_observations=function()end,benchmark_mark=function(event)marks[#marks+1]=event end,
 runner_context=function()return {root=root,profile='zh-on',stress_ms='0',warmup_ms='1000',sample_ms='1000'}end,
 runner_frames=function()return math.floor(now/50)end,
 runner_finish=function(outcome,reason,fields)results[#results+1]={outcome=outcome,reason=reason,fields=fields}end}
local b=B.new(app,native);assert(#b.profiles==1);b:tick()
now=1000;b:tick();now=2000;b:tick()
assert(exits==1 and results[1].outcome=='PASS' and #loads==1 and #saves==1)
assert(tonumber(results[1].fields.sample_1_world)>0 and tonumber(results[1].fields.frames)==20)
assert(results[1].fields.recovery_outcome=='NOT_PROVEN')
assert(marks[#marks]=='WORKLOAD-END')
for _,mark in ipairs(marks)do assert(mark~='COMPLETE')end
root='sdmc:/3ds/ftpd-runner/runs/new-run-02/';app.savegame_dir=root..'save/'
b=B.new(app,native);b:tick();now=3000;b:tick();now=3500;b:cancel('user')
assert(exits==2 and results[2].outcome=='NOT_PROVEN' and results[2].reason=='CANCEL')
assert(tonumber(results[2].fields.partial_world)>0)
b=B.new(app,native);b:tick();app.world:setSpeed('Pause');b:tick()
assert(exits==3 and results[3].outcome=='FAIL' and results[3].reason=='FAILED')
b=B.new(app,native);b:tick()
function app.world:setSpeed()error('cleanup failed')end
b:cancel('user')
assert(exits==4 and results[4].outcome=='FAIL' and results[4].reason=='CLEANUP_FAILED')
b=B.new(app,native);b:tick()
function app:exit()error('hotkeys write failed')end
local abandoned=0
function app:abandon()abandoned=abandoned+1 end
b:cancel('user')
assert(abandoned==1 and results[5].outcome=='FAIL' and results[5].reason=='EXIT_FAILED')
io.open=original_open
''')
