"""Per-recovered-object continuity using pinned real Entity and reception ticks."""
import os
import subprocess
import tempfile
from pathlib import Path
import unittest
import test_lua_runtime
from test_r65_reception_recovery import reception_script, ROOT


def script():
    return reception_script() + '\nlocal A=dofile(' + repr(str(ROOT / 'lua/3ds/recovery_activity.lua')) + ')\n' + r'''
local function observed(e)
 A.before(e);local ok,err=pcall(e.tick,e);A.after(e,ok);return ok,err
end
local function recovered()
 local w=new_world();w.entities[1].ticks=false
 local cohort=A.capture(w);assert(#cohort==1 and cohort[1].index==1)
 assert(H.repairR62(w)==1);return w,cohort
end
local function serve(w)
 local patient=Patient();patient.action_queue={{name='idle'}}
 local desk=w.entities[2];desk.queue[#desk.queue+1]=patient
 for i=1,4 do assert(observed(w.entities[1]));assert(observed(desk)) end
 assert(patient.has_passed_reception and patient.action_queue[2].room=='gp')
end
'''


class R66RecoveryActivity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def test_real_ticks_wait_service_failure_timer_and_weak_lifetime(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(script() + r'''
local w,c=recovered();local frozen_check=frozen(w,false)
A.start(w,c);A.before(w.entities[1]);A.after(w.entities[1],true);frozen_check()
A.stop();A.start(w,c)
for i=1,10 do assert(observed(w.entities[1]));assert(observed(w.entities[2])) end
local r=A.report();assert(r.outcome=='NOT_PROVEN' and r.updated==1 and r.service_uncovered==1)
assert(r.rows[1].ticks==10 and r.rows[1].timerless==10 and r.rows[1].failures==0)
serve(w);r=A.report();assert(r.outcome=='PASS' and r.rows[1].services==1)
w.entities[1].action_queue[1].name='idle';assert(observed(w.entities[1]))
assert(A.report().outcome=='NOT_PROVEN' and A.report().rows[1].unscheduled==1)
w.entities[1].action_queue[1].name='staff_reception'
A.stop();A.start(w,c)
local original=w.entities[1];local replacement=Receptionist()
replacement.profile={skill=1};replacement.action_queue=original.action_queue
w.entities[2].receptionist=replacement
serve(w);assert(A.report().rows[1].services==0,'replacement employee service attributed to recovered employee')
w.entities[2].receptionist=original
A.stop();A.start(w,c)
w.entities[1].timer_time=1;w.entities[1].timer_function=function()error('injected callback failure')end
assert(not observed(w.entities[1]));r=A.report();assert(r.outcome=='FAIL' and r.updated==0 and r.rows[1].callbacks==0)
A.stop()
w,c=recovered();local e=w.entities[1];e.humanoid_class='Doctor';c[1].kind='Doctor'
local function advance(e)e.tile_x=e.tile_x+1;e:setTimer(2,advance)end
e:setTimer(2,advance);A.start(w,c)
for i=1,8 do assert(observed(e)) end
r=A.report();assert(r.outcome=='PASS' and r.rows[1].ticks==8 and r.rows[1].callbacks==4 and r.rows[1].actions==4)
e.timer_time=nil;e.timer_function=nil;assert(observed(e));assert(A.report().outcome=='NOT_PROVEN')
A.stop();e.timer_time=nil;e.timer_function=nil;A.start(w,c)
for i=1,4 do assert(observed(e)) end
r=A.report();assert(r.outcome=='NOT_PROVEN' and r.rows[1].timers==0 and r.rows[1].failures==0)
e.timer_time=5;assert(observed(e));assert(A.report().outcome=='FAIL')
A.stop()
w,c=recovered();A.start(w,c)
local weak=setmetatable({w,w.entities[1],w.entities[2]},{__mode='v'})
w=nil;c=nil;e=nil;collectgarbage('collect');collectgarbage('collect')
assert(weak[1]==nil and weak[2]==nil and weak[3]==nil,'observer retained world')
A.stop();assert(not A.active);assert(not pcall(A.report))
print('PASS recovered ticks, genuine service, legal waiting, callback failure, lost timer and bounded weak lifetime')
''')

    def test_native_save_reload_rebind_and_no_graph_pollution(self):
        from test_save_stream_native import build_stream_probe
        with tempfile.TemporaryDirectory(prefix='cth-r66-activity-') as name:
            directory = Path(name)
            binary, closure, _ = build_stream_probe(directory)
            source = directory / 'activity.lua'
            source.write_text(script() + r'''
local w,c=recovered();local permanents,inverse=permanence(w)
local before=assert(candidate.dump(w,permanents))
local unchanged=frozen(w,false);A.start(w,c,true);unchanged()
assert(candidate.dump(w,permanents)==before,'observer entered serialized graph')
serve(w);assert(A.report().outcome=='PASS')
-- Simulate real world array compaction before the pause/save boundary.
w.entities={w.entities[2],w.entities[1]}
c=assert(A.rebindCohort(w));assert(c[1].index==2)
A.stop();assert(not A.active)
permanents,inverse=permanence(w)
local file=assert(io.open(directory..'/activity.save','wb'))
assert(candidate.dump_file(w,permanents,file));assert(file:close())
file=assert(io.open(directory..'/activity.save','rb'));local bytes=file:read('*a');file:close()
for _,reader in ipairs{reference,candidate}do
 local restored=assert(reader.load(bytes,inverse));A.start(restored,c,true)
 assert(A.report().updated==0,'pre-reload updates leaked into second window')
 local staff,desk=restored.entities[2],restored.entities[1]
 local patient=Patient();patient.action_queue={{name='idle'}};desk.queue[1]=patient
 for i=1,4 do assert(observed(staff));assert(observed(desk))end
 assert(patient.has_passed_reception and A.report().outcome=='PASS')
 assert(A.patientReport().rows[1].patient_services==1)
 assert(A.patientReport().events[1].tail_after=='seek_room');A.stop()
end
print('PASS actual native private file roundtrip, both readers, cohort compaction/rebind and graph isolation')
''')
            result = subprocess.run([str(binary), str(closure), str(directory), str(source)],
                                    capture_output=True, text=True, timeout=120,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                                             UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_seventeen_original_staff_require_their_own_work(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(script() + r'''
local w=new_world();local hospital=w.entities[1].hospital
w.entities[1].ticks=false
local function move(e)e.tile_x=e.tile_x+1;e:setTimer(2,move)end
for i=2,17 do
 local e=Staff();e.world=w;e.hospital=hospital;e.humanoid_class='Doctor';e.ticks=false
 e.tile_x=1;e.tile_y=i;e.action_queue={{name='walk'}};e:setTimer(2,move)
 hospital.staff[#hospital.staff+1]=e;w.entities[#w.entities+1]=e
 w.game_log[#w.game_log+1]='Error in timer handler: '
 w.game_log[#w.game_log+1]="/entities/humanoids/staff.lua:127: use of undeclared variable 'TH3DS'"
 w.game_log[#w.game_log+1]='Recovering from error in timer handler...'
end
local c=A.capture(w);assert(#c==17 and H.repairR62(w)==17);A.start(w,c)
serve(w)
for i=3,17 do for n=1,4 do assert(observed(w.entities[i]))end end
local r=A.report();assert(r.count==17 and r.updated==16 and r.outcome=='NOT_PROVEN')
for n=1,4 do assert(observed(w.entities[18]))end
r=A.report();assert(r.count==17 and r.updated==17 and r.outcome=='PASS')
for n=1,100 do assert(observed(w.entities[3]))end
assert(A.report().updated==17,'total entity work used in place of original cohort')
A.stop()
print('PASS 17 qualified original employees each require actual successful work; 16 plus unrelated work cannot pass')
''')

    def test_benchmark_two_windows_save_boundaries_and_forced_input(self):
        test_lua_runtime.LuaRuntimeTests().run_lua(script() +
            '\npackage.loaded["3ds.recovery_activity"]=A\nlocal B=dofile(' +
            repr(str(ROOT / 'lua/3ds/benchmark.lua')) + ')\n' + r'''
package.loaded['3ds.benchmark_stress']={fingerprint=function(app)return H.fingerprint(app.world)end}
package.loaded['3ds.media']={setSpeech=function(app,code)
 app.config.speech_language=code;app.audio.speech_file_name=code;return true
end,speechFile=function(app)return app.config.speech_language end}
local original_open=io.open
io.open=function(path)if path:match('r62%-recovery.sav$')then return{close=function()end}end end
for _,mode in ipairs{'service','waiting','input','save_failure','media','music_failure'}do
 local now,loads,saves=0,{},0
 local app={savegame_dir='USER/',config={autosave_frequency=2},_3ds={simulation_errors=0},
  eventHandlers={timer=function()end},ui={anyMustPauseWindowOpen=function()return false end}}
 local saved
 function app:load(path)
  assert(not A.active,'observer active across load');loads[#loads+1]=path
  if path:match('r62%-recovery.sav$')then
   self.world,self._3ds.recovery_cohort=recovered();self._3ds.recovery_count=1
  elseif path:match('input.sav$')then self.world=new_world()
  else self.world=assert(saved)end
  function self.world:setSpeed(speed)self.speed=speed end
  function self.world:getCurrentSpeed()return self.speed end
  return true
 end
 function app:save(path)
  assert(not A.active,'observer active across save');assert(self.world:getCurrentSpeed()=='Pause')
  assert(path:find('Benchmark/Saves/',1,true));saves=saves+1;saved=self.world
  if mode=='save_failure' and saves==2 then return false end
  return true
 end
 local diagnostics={}
 local playing,plays=false,0
 local native={clock_ms=function()return now end,benchmark_active=function()return benchmark_active_flag==true end,benchmark_state=function(v)benchmark_active_flag=v end,
  diagnostic_line=function(line)assert(#line<=230);diagnostics[#diagnostics+1]=line end,
  set_notice=function()end,benchmark_mark=function()end,flush_observations=function()end}
 local b=B.new(app,native);b:activate()
 if mode=='media' or mode=='music_failure'then
  app.audio={background_playlist={{filename_music='Music/CANDY.wav'}},
   stopBackgroundTrack=function()playing=false end,
   playBackgroundTrack=function()playing=true;plays=plays+1;return true end}
  function app:initLanguage()return true end
  native.music_state=function()return playing,false end
  b.media_profiles=true;b.profiles={{speed='Normal',language='Chinese (simplified)',music=true,label='zh-on'}}
 end
 b:tick()
 assert(b.phase=='recovery' and b.recovery_window==1 and #loads==2 and saves==1 and A.active)
 assert(app.world:getCurrentSpeed()=='Normal' and b.results.recovery_qualification_outcome=='PASS')
 local terminal
 if mode=='input' or mode=='music_failure' or mode=='save_failure'then
  b.run={};function app:exit()assert(not A.active)end
  native.runner_finish=function(outcome,reason,fields)terminal={outcome=outcome,reason=reason,fields=fields}end
 end
 if mode=='music_failure'then
  playing=false;now=5000;b:tick()
  assert(b.phase=='done' and not A.active and b.results.failure_phase=='observation_1')
  assert(b.results.recovery_behavior_outcome=='FAIL' and b.results.failure_detail:find('music is not actually playing',1,true))
 elseif mode=='input'then
  app.ui.anyMustPauseWindowOpen=function()return true end;b:tick()
  assert(b.phase=='done' and not A.active and saves==1 and #loads==2)
  assert(b.results.recovery_behavior_outcome=='NOT_PROVEN' and b.results.failure_detail:find('TH3DS_NEEDS_INPUT',1,true))
 else
  if mode=='service' or mode=='media'then serve(app.world)else assert(observed(app.world.entities[1]))end
  now=25000;b:tick()
  if mode=='save_failure'then assert(b.phase=='done' and not A.active and #loads==2)
  else
   assert(b.phase=='recovery' and b.recovery_window==2 and #loads==3 and saves==2 and A.active)
   if mode=='media'then assert(plays==1 and app.config.play_music and app.config.speech_language=='zh')end
   if mode=='service' or mode=='media'then serve(app.world)else assert(observed(app.world.entities[1]))end
   now=50000;b:tick()
   assert(b.phase=='warmup' and #loads==4 and loads[4]:match('input.sav$') and not A.active)
   assert(b.results.recovery_continuity_roundtrip_outcome=='PASS')
   assert(b.results.recovery_behavior_outcome==((mode=='service' or mode=='media') and 'PASS' or 'NOT_PROVEN'))
   if mode=='media'then
    assert(plays==2 and b.results.recovery_music=='true' and b.results.recovery_voice=='zh')
    assert(table.concat(diagnostics,'\n'):find('playing=true',1,true))
   end
   assert(table.concat(diagnostics,'\n'):find('source_index=1',1,true))
   assert(table.concat(diagnostics,'\n'):find('services=',1,true))
   b:cancel('test')
  end
 end
 if terminal then
  assert(terminal.fields.healthy_baseline_outcome=='NOT_PROVEN')
  assert(terminal.fields.recovery_roundtrip_outcome=='PASS' and terminal.fields.recovery_qualification_outcome=='PASS')
  assert(terminal.fields.failure_phase==(mode=='save_failure' and 'continuity_roundtrip' or 'observation_1'))
  assert(terminal.reason==(mode=='input' and 'NEEDS_INPUT' or 'FAILED'))
 end
end
io.open=original_open
print('PASS two real-observer windows precede healthy benchmark, private paused save boundaries, absent service, NEEDS_INPUT and save failure')
''')


if __name__ == '__main__':
    unittest.main()
