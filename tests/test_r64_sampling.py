"""Run the actual Lua state machine with slow synchronous output and snapshots."""
from pathlib import Path
import unittest
import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]


class SamplingTests(unittest.TestCase):
    setUpClass = classmethod(lambda cls: test_lua_runtime.LuaRuntimeTests.setUpClass())

    def test_submillisecond_start_reaches_full_native_duration(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(
            "package.path=" + repr(str(ROOT / 'lua/?.lua') + ';') + "..package.path\n" + r'''
package.loaded['3ds.state_health']={assertActive=function()return {staff=0,patients=0} end}
local B=require('3ds.benchmark')
local now_us,frames=1000137,0
local started,ended
local p={world_completed=0,hours_completed=0,entity_completed=0}
local app={_3ds={simulation_progress=p},config={},eventHandlers={timer=function()end},
 world={getCurrentSpeed=function()return 'Normal' end}}
local native={clock_ms=function()return math.floor(now_us/1000)end,
 runner_frames=function()return frames end,flush_observations=function()end,
 benchmark_mark=function(event)
   if event=='SAMPLE-BEGIN' then started=now_us
   elseif event=='SAMPLE-END' then ended=now_us end
   return now_us,frames
 end}
local b=setmetatable({app=app,native=native,phase='warmup',index=1,deadline=0,
 profiles={{speed='Normal'}},expected_errors=0,last_health_check=1000,
 run={},stress_duration=0,sample_ms=60000,results={},
 sample_ticks=0,sample_frames=0,sample_elapsed=0},B)
native.set_notice=function()end
b.finish=function(self)self.phase='done' end
b.warmup_progress=b:progress() -- Direct warmup seam supplies the state normally captured by load().
b:advance()
assert(started==1000137 and b.deadline==61001)
now_us=61000000;frames=1200
p.world_completed=3000;p.hours_completed=30;p.entity_completed=9000
b:advance()
assert(b.phase=='sample' and not ended)
now_us=b.deadline*1000
b:advance()
assert(b.phase=='done' and ended-started==60000863)
assert(b.sample_elapsed_us==60000863 and ended-started>=60000000)
''')

    def test_shared_boundaries_exclude_500ms_output_and_checkpoint(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(
            "package.path=" + repr(str(ROOT / 'lua/?.lua') + ';') + "..package.path\n" + r'''
package.loaded['3ds.state_health']={assertActive=function()return {staff=0,patients=0} end}
local B=require('3ds.benchmark')
for _,runner in ipairs{false,true} do
 local now,frames=0,0
 local opened,closed,checkpoint=nil,nil,false
 local p={world_completed=0,hours_completed=0,entity_completed=0}
 local app={_3ds={simulation_progress=p},config={},eventHandlers={timer=function()end},
   world={getCurrentSpeed=function()return 'Normal' end}}
 local original_print=print
 print=function()now=now+500 end
 local native={clock_ms=function()return now end,runner_frames=function()return frames end,
   flush_observations=function()now=now+500 end,set_notice=function()end,
   benchmark_mark=function(event)
     if event=='SAMPLE-BEGIN' then assert(not opened);opened=now
     elseif event=='SAMPLE-END' then
       assert(opened and not closed);closed=now
       -- Native report itself can block after freezing its boundary.
       now=now+500
     else error(event) end
     return (closed or opened)*1000,frames
   end,
   runner_checkpoint=function(fields)
     assert(closed and tonumber(fields.sample_1_at)==60000)
     now=now+500;checkpoint=true
   end}
 local b=setmetatable({app=app,native=native,phase='warmup',index=1,deadline=0,
   profiles={{speed='Normal'}},expected_errors=0,last_health_check=0,
   run=runner and {} or nil,stress_duration=0,sample_ms=60000,
   results={},sample_ticks=0,sample_frames=0,sample_elapsed=0},B)
 b.finish=function(self)self.phase='done' end
 b.warmup_progress=b:progress()
 b:advance()
 assert(opened==1000 and b.sample_progress.at==opened)
 now=opened+60000;frames=1200
 p.world_completed=3000;p.hours_completed=30;p.entity_completed=9000
 b:advance()
 assert(closed-opened==60000 and now>closed+500)
 assert(b.phase=='done')
 if runner then
   assert(checkpoint and b.results.sample_1_at==60000 and b.sample_elapsed==60000)
   assert(b.results.sample_1_elapsed_us==60000000 and b.sample_elapsed_us==60000000)
   assert(b.sample_frames==1200 and b.sample_ticks==3000)
 else assert(not checkpoint) end
 print=original_print
end
''')


if __name__ == '__main__':
    unittest.main()
