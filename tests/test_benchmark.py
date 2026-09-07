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
local app={savegame_dir='USER/',config={autosave=true}}
local native={clock_ms=function()return now end,
  benchmark_state=function(v)active=v end,set_notice=function()end,flush_observations=function()end,
  benchmark_mark=function(e,s,d)rows[#rows+1]={e,s,d} end}
function app:load(path)
 assert(self.savegame_dir=='sdmc:/3ds/corsixth/Benchmark/Saves/')
 assert(self.config.autosave==false)
 assert(path=='sdmc:/3ds/corsixth/Benchmark/input.sav')
 loads[#loads+1]=path
 self.world={setSpeed=function(self,s)self.speed=s end,getCurrentSpeed=function(self)return self.speed end,
   game_date={tostring=function()return '1/1/1-1' end}}
 return true
end
local b=B.new(app,native);assert(active)
b:tick();assert(b.phase=='warmup' and app.world.speed=='Normal')
now=29999;b:tick();assert(b.phase=='warmup')
now=30000;b:tick();assert(b.phase=='sample')
now=90000;b:tick();assert(b.phase=='warmup' and app.world.speed=='And then some more')
now=120000;b:tick();assert(b.phase=='sample')
now=180000;b:tick();assert(b.phase=='done' and not active)
assert(app.savegame_dir=='USER/' and app.config.autosave==true and app.world.speed=='Normal')
assert(#loads==3 and rows[#rows][1]=='COMPLETE')
local count=#rows;b:tick();b:cancel('late');assert(#rows==count)
b=B.new(app,native);b:tick();b:cancel('B')
assert(not active and app.savegame_dir=='USER/' and app.config.autosave)
assert(rows[#rows][1]=='ABORT-B')
b=B.new(app,native);b:tick();app.world.speed='Pause';b:tick()
assert(b.phase=='done' and not active and rows[#rows][1]=='FAILED')
assert(app.savegame_dir=='USER/' and app.config.autosave)
for _,failure in ipairs({'rejected','exception'}) do
 app.load=function()if failure=='exception' then error('injected') end;return false,'injected' end
 b=B.new(app,native);b:tick()
 assert(not active and b.phase=='done' and app.savegame_dir=='USER/' and app.config.autosave)
 assert(rows[#rows][1]=='FAILED')
end
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

if __name__=='__main__':unittest.main()
