"""Exercise generated World dispatch and the actual adapter recovery boundary."""
import tempfile
from pathlib import Path
import unittest
import test_lua_runtime
import test_r64_runtime_hooks as hooks
from support.pinned_upstream import generated_sources


class R66IntegrationBoundaries(unittest.TestCase):
    setUpClass = classmethod(lambda cls: test_lua_runtime.LuaRuntimeTests.setUpClass())

    def test_actual_platform_capture_qualification_and_error_identity(self):
        hooks.R64RuntimeHooks().lua(r'''
local calls,primary={},{}
local A={active=true,capture=function(world)
 assert(world.disabled==true);calls[#calls+1]='capture';return{{index=1,kind='Doctor'}}
end,after=function(entity,ok)
 assert(entity==app.world.current_tick_entity and not ok);calls[#calls+1]='failed'
 error('observer failure must preserve primary')
end}
package.loaded['3ds.recovery_activity']=A
package.loaded['3ds.state_health']={repairR62=function(w)
 assert(w.disabled);calls[#calls+1]='qualify';w.disabled=false;return 1
end,auditR62=function()end}
app.errorHandler=function(_,event,detail)
 assert(event=='timer' and detail==primary);calls[#calls+1]='original';return 'handled'
end
app.load=function(self)
 self.world={disabled=true,current_tick_entity={},setSpeed=function()end};return true
end
app.save=function()return true end
local p=P.attach(app,native,{epoch=1,resource_events=false})
p.syncScene=function()end
assert(app:load('sdmc:/3ds/corsixth/Benchmark/r62-recovery.sav'))
assert(table.concat(calls,',')=='capture,qualify' and p.recovery_cohort[1].index==1)
assert(app:errorHandler('timer',primary)=='handled')
assert(table.concat(calls,',')=='capture,qualify,failed,original')
assert(p.simulation_errors==1)
assert(app:load('PRIVATE/normal.sav') and p.recovery_cohort==nil)
package.loaded['3ds.state_health'].repairR62=function()error('qualification refused')end
local ok,reason=app:load('sdmc:/3ds/corsixth/Benchmark/r62-recovery.sav')
assert(ok==false and reason:find('qualification refused',1,true) and p.recovery_cohort==nil)
''')

    def test_generated_world_success_order_failure_and_inactive_fast_path(self):
        with tempfile.TemporaryDirectory(prefix='cth-r66-world-') as temp:
            root=generated_sources(Path(temp))
            text=(root/'CorsixTH/Lua/world.lua').read_text()
            start=text.index('function World:onTick()')
            method=text[start:text.index('\nend',start)+4]
            self.assertNotIn('pcall(',method)
            test_lua_runtime.LuaRuntimeTests().run_lua(r'''
World={};TheApp={_3ds={native={profiling_enabled=false}}}
local entity_profile_iteration=0
local outside_temperatures={0.5}
local calls={}
local A={active=false,before=function(e)calls[#calls+1]='before'..e.id end,
 after=function(e,ok)assert(ok);calls[#calls+1]='after'..e.id end}
package.loaded['3ds.recovery_activity']=A
''' + method + r'''
local date={plusHours=function(self)return self end,dayOfMonth=function()return 1 end,
 hourOfDay=function()return 0 end,monthOfYear=function()return 1 end}
local function nop()end
local w=setmetatable({map={level_number=1,onTick=nop,th={updateTemperatures=nop}},
 tick_timer=0,tick_rate=3,hours_per_tick=1,game_date=date,spawn_hours={},
 earthquake={tick=nop},anims={tick=nop},dispatcher={onTick=nop},
 hospitals={{tick=nop,heating={radiator_heat=0.5}}},
 isCurrentSpeed=function()return false end,entities={}}, {__index=World})
for i=1,3 do
 w.entities[i]={id=i,ticks=i<3,tick=function(e)calls[#calls+1]='tick'..e.id end}
end
w:onTick();assert(table.concat(calls,',')=='tick1,tick2')
assert(TheApp._3ds.simulation_progress.entity_completed==2)
A.active=true;calls={};w.tick_timer=0;w:onTick()
assert(table.concat(calls,',')=='before1,tick1,after1,before2,tick2,after2')
assert(TheApp._3ds.simulation_progress.entity_completed==4)
local primary={};w.entities[2].tick=function()error(primary)end
calls={};w.tick_timer=0
local ok,err=pcall(w.onTick,w);assert(not ok and err==primary)
assert(table.concat(calls,',')=='before1,tick1,after1,before2')
assert(w.current_tick_entity==w.entities[2] and TheApp._3ds.simulation_progress.entity_completed==5)
''')


if __name__=='__main__':unittest.main()
