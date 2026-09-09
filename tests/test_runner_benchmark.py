"""Runner completion and cancellation exercise the existing Lua state machine."""
from pathlib import Path
import unittest
import test_benchmark

class RunnerBenchmarkTests(unittest.TestCase):
    setUpClass=classmethod(lambda cls: test_benchmark.BenchmarkTests.setUpClass())
    run_benchmark_lua=test_benchmark.BenchmarkTests.run_benchmark_lua
    def test_context_is_bounded_relative_work_and_does_not_open_sample(self):
        self.run_benchmark_lua('local B=dofile('+repr(str(Path(__file__).resolve().parents[1]/'lua/3ds/benchmark.lua'))+')\n'+r'''
local now=1000
local app={world={entities={},game_date={tostring=function()return string.rep('x',140)..'\n' end}}}
local b=setmetatable({run={},app=app,index=2,results={},
 warmup_progress={world=90,hours=30,entities=60,frames=10,at=100},
 sample_progress={world=105,hours=35,entities=70,frames=15,at=1000},
 expected_camera_x=-160,expected_camera_y=240,
 native={benchmark_mark=function()error('context must precede sample')end}},B)
b:captureSampleContext()
assert(b.results.sample_2_warmup_work=='world=15;hours=5;entities=10;frames=5;observed_ms=900')
assert(b.results.sample_2_scene_begin=='date='..string.rep('x',128)..';camera_x=-160;camera_y=240;staff=0;patients=0')
assert(#b.results.sample_2_scene_begin<240)
b.sample_progress.world=89
assert(not pcall(b.captureSampleContext,b))
b.sample_progress.world=105;b.sample_progress.at=99
assert(not pcall(b.captureSampleContext,b))
b.run=nil;assert(pcall(b.captureSampleContext,b))
''')

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
local native={clock_ms=function()return now end,benchmark_active=function()return benchmark_active_flag==true end,benchmark_state=function(v)benchmark_active_flag=v end,
 set_notice=function()end,flush_observations=function()end,benchmark_mark=function(event)marks[#marks+1]=event;return now*1000,math.floor(now/50) end,
 runner_context=function()return {root=root,profile='zh-on',stress_ms='0',warmup_ms='1000',sample_ms='1000'}end,
 runner_frames=function()return math.floor(now/50)end,
 runner_finish=function(outcome,reason,fields)results[#results+1]={outcome=outcome,reason=reason,fields=fields}end}
local b=B.new(app,native);b:activate();assert(#b.profiles==1);b:tick()
local Stress=require('3ds.benchmark_stress')
b.stress=setmetatable({cycle=3,annual_attempt_count=2,annual_count=2},Stress)
b.stress_progress={world=0,hours=0,entities=0,frames=0,at=0}
now=1000;b:tick();now=2000;b:tick()
assert(exits==1 and results[1].outcome=='PASS' and #loads==1 and #saves==1)
assert(tonumber(results[1].fields.sample_1_world)>0 and tonumber(results[1].fields.frames)==20)
assert(results[1].fields.sample_1_warmup_work=='world=55;hours=55;entities=55;frames=20;observed_ms=1000')
assert(results[1].fields.sample_1_scene_begin=='date=unknown;camera_x=nil;camera_y=nil;staff=0;patients=0')
assert(results[1].fields.exact_state_ab=='NOT_PROVEN')
assert(results[1].fields.recovery_outcome=='NOT_PROVEN')
assert(results[1].fields.stress_annual_attempts=='2' and results[1].fields.stress_annual_passes=='2')
assert(results[1].fields.stress_annual_outcome=='PASS')
assert(marks[#marks]=='WORKLOAD-END')
for _,mark in ipairs(marks)do assert(mark~='COMPLETE')end
root='sdmc:/3ds/ftpd-runner/runs/new-run-02/';app.savegame_dir=root..'save/'
b=B.new(app,native);b:activate();b:tick();now=3000;b:tick();now=3500;b:cancel('user')
assert(exits==2 and results[2].outcome=='NOT_PROVEN' and results[2].reason=='CANCEL')
assert(tonumber(results[2].fields.partial_world)>0)
b=B.new(app,native);b:activate();b:tick();app.world:setSpeed('Pause');b:tick()
assert(exits==3 and results[3].outcome=='FAIL' and results[3].reason=='FAILED')
b=B.new(app,native);b:activate();b:tick()
function app.world:setSpeed()error('cleanup failed')end
b:cancel('user')
assert(exits==4 and results[4].outcome=='FAIL' and results[4].reason=='CLEANUP_FAILED')
b=B.new(app,native);b:activate();b:tick()
function app:exit()error('hotkeys write failed')end
local abandoned=0
function app:abandon()abandoned=abandoned+1 end
b:cancel('user')
assert(abandoned==1 and results[5].outcome=='FAIL' and results[5].reason=='EXIT_FAILED')
function app:exit()exits=exits+1 end
-- A snapshot write failure occurs after SAMPLE-END, and still fails the run.
native.runner_checkpoint=function()error('injected snapshot write failure')end
b=B.new(app,native);b:activate();b:tick();now=now+1000;b:tick();now=now+1000;b:tick()
assert(results[6].outcome=='FAIL' and results[6].reason=='FAILED')
assert(results[6].fields.failure_detail:find('injected snapshot write failure',1,true))
assert(marks[#marks]=='FAILED' and marks[#marks-1]=='SAMPLE-END')
native.runner_checkpoint=nil
-- Runner boundaries require the new native return contract.
native.benchmark_mark=function(event)marks[#marks+1]=event end
b=B.new(app,native);b:activate();b:tick();now=now+1000;b:tick()
assert(results[7].outcome=='FAIL' and results[7].reason=='FAILED')
assert(results[7].fields.failure_detail:find('native benchmark boundary missing or invalid',1,true))
io.open=original_open
''')
