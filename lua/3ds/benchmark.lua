-- One-shot opt-in benchmark. It owns no user save file and changes no game rule.
-- The installer supplies a verified copy at Benchmark/input.sav. All automatic
-- recovery/periodic saves are redirected while this short session is active.
local Benchmark={}
Benchmark.__index=Benchmark
local root="sdmc:/3ds/corsixth/Benchmark/"
local speeds={"Normal","And then some more"}
local Health=require("3ds.state_health")
local Activity=require("3ds.recovery_activity")
local NEEDS_INPUT="TH3DS_NEEDS_INPUT"
local function failureText(value)
  if type(value)=="string" then return value:gsub("[\r\n]"," "):sub(1,1024) end
  return "non-string Lua error ("..type(value)..")"
end
local function loadBenchmark(self,path,required)
  local accepted,detail=self.app:load(path)
  local operations=self.app._3ds and self.app._3ds.operations
  if operations then operations:guard() end
  if required and accepted~=true then error(detail,0) end
  return accepted,detail
end

function Benchmark.new(app,native)
  local run=native.runner_context and native.runner_context()
  local root=run and run.root or root
  local self=setmetatable({app=app,native=native,phase="pending",index=1,
    root=root,run=run,results={},sample_elapsed=0,sample_ticks=0,sample_frames=0,
    original_dir=app.savegame_dir,original_autosave_frequency=app.config.autosave_frequency},Benchmark)
  self.profiles={{speed=speeds[1]},{speed=speeds[2]}}
  if app.config.unicode_font and app.config.audio_music and app.audio and app.strings
      and app.strings:checkLanguageExists("Chinese (simplified)") then
    self.media_profiles=true
    self.profiles={
      {speed="Normal",language="English",music=false,label="en-off"},
      {speed="Normal",language="Chinese (simplified)",music=false,label="zh-off"},
      {speed="Normal",language="Chinese (simplified)",music=true,label="zh-on"},
    }
  end
  local expanded=io.open(root.."expanded.sav","rb")
  if expanded then
    expanded:close();self.expanded=true
    self.profiles[#self.profiles+1]={speed="Normal",language="Chinese (simplified)",music=true,
      label="expanded-zh-on",file="expanded.sav"}
  end
  local recovery=io.open(root.."r62-recovery.sav","rb")
  if recovery then recovery:close();self.recovery_copy=true end
  if run then
    assert(self.media_profiles,"runner requires installed Chinese font, speech and music")
    if run.profile=="zh-on" then
      self.profiles={{speed="Normal",language="Chinese (simplified)",music=true,label="zh-on"}}
    elseif run.profile=="expanded-zh-on" then
      self.profiles={{speed="Normal",language="Chinese (simplified)",music=true,
        label="expanded-zh-on",file="expanded.sav"}}
    end
    self.stress_duration=tonumber(run.stress_ms)
    self.warmup_ms=tonumber(run.warmup_ms);self.sample_ms=tonumber(run.sample_ms)
    if run.capacity then
      assert((run.capacity=="r73-v1" or run.capacity=="r74-v1" or run.capacity=="r75-v1") and run.profile=="expanded-zh-on" and
        self.stress_duration>0 and self.stress_duration<=180000 and not run.recovery_sha256,
        "invalid capacity configuration")
      self.capacity_requested=true
      if run.capacity=="r75-v1" then
        assert(type(run.save_io_input_sha256)=="string" and #run.save_io_input_sha256==64
          and not run.save_io_input_sha256:find("[^0-9a-f]"),"invalid save IO input identity")
      end
    end
  end
  return self
end

-- Construction owns configuration only. Activation owns exactly one native
-- flag; a pre-existing session cannot be borrowed by a different App.
function Benchmark:activate()
  if self.activation_owned then return end
  local previous=self.native.benchmark_active()
  assert(type(previous)=="boolean" and not previous,"benchmark already active or state unavailable")
  self.activation_previous=previous
  self.activation_owned=true -- setter may change the flag and then throw
  self.native.benchmark_state(true)
  assert(self.native.benchmark_active()==true,"benchmark activation not applied")
  if not pcall(self.native.set_notice,"AUTO BENCHMARK - B CANCEL",false) then
    self.results.activation_diagnostics=math.min(65535,(self.results.activation_diagnostics or 0)+1)
  end
end

function Benchmark:releaseActivation()
  if not self.activation_owned then return end
  self.native.benchmark_state(self.activation_previous)
  assert(self.native.benchmark_active()==self.activation_previous,"benchmark activation restore failed")
  self.activation_owned=false
end

-- App attaches us before it starts the normal menu song. Snapshot immediately
-- before the first mutation, after startup has finished. Pending cancellation
-- owns no media state and must leave the user's playback untouched.
function Benchmark:captureMedia()
  if not self.media_profiles or self.media_captured then return end
  local app=self.app
  self.original_language=app.config.language
  self.original_music=app.config.play_music
  self.original_voice=app.config.speech_language or "en"
  self.original_music_playing=app.audio.background_music~=nil
  self.original_music_paused=app.audio.background_paused==true
  for i,info in ipairs(app.audio.background_playlist or {}) do
    if info.music and info.music==app.audio.background_music then self.original_track=i;break end
  end
  self.original_save_config=rawget(app,"saveConfig")
  app.saveConfig=function()end
  self.media_captured=true
end

function Benchmark:mark(event,progress)
  local world=self.app.world
  local date=world and world.game_date and world.game_date:tostring() or "unknown"
  local speed=world and world:getCurrentSpeed() or "No world"
  -- Synchronous opening output precedes the window; closing output follows it.
  -- flush_observations only requests a later main-loop flush. Its actual cost
  -- can fall inside this sample and is retained in native phase residency.
  -- Native returns the exact timestamp used by its frame window.
  local function boundary()
    local at_us,frames=self.native.benchmark_mark(event,speed,date)
    if progress and self.run then
      assert(type(at_us)=="number" and at_us>=0 and at_us<math.huge and
        type(frames)=="number" and frames>=0 and frames<math.huge,
        "native benchmark boundary missing or invalid")
    end
    if progress and at_us then
      -- Millisecond completion reports retain their integer wire format;
      -- truncation at each end differs from native by less than one ms.
      progress.at=math.floor(at_us/1000)
      progress.at_us=math.floor(at_us)
      if frames then progress.frames=frames end
    end
  end
  if event~="SAMPLE-BEGIN" then boundary() end
  if self.media_profiles then
    local p=self.profiles[self.index]
    print("benchmark-media: event="..event.." variant="..p.label
      .." language="..tostring(self.app.config.language).." music="..tostring(self.app.config.play_music)
      .." voice="..tostring(self.app.config.speech_language or "en"))
  end
  local playing,paused
  if self.native.music_state then playing,paused=self.native.music_state() end
  print("benchmark-media-actual: music_playing="..tostring(playing)
    .." music_paused="..tostring(paused).." voice_bank="
    ..tostring(self.app.audio and self.app.audio.speech_file_name)
    .." voice_playback=NOT_PROVEN")
  self.native.flush_observations()
  if event=="SAMPLE-BEGIN" then boundary() end
end

function Benchmark:applyMedia(language, music, selected, stopped)
  local app=self.app
  app.audio:stopBackgroundTrack()
  app.config.play_music=false
  if app.config.language~=language then
    app.config.language=language
    local ok,err=app:initLanguage()
    assert(ok==true,"benchmark language failed: "..tostring(err))
  end
  app.config.play_music=music==true
  if music and not stopped then
    if not selected then
      for i,info in ipairs(app.audio.background_playlist) do
        if (info.filename_music or ""):upper():match("/CANDY%.WAV$") then selected=i;break end
      end
    end
    assert(selected,"benchmark needs prepared CANDY.wav for repeatable music")
    local ok,err=app.audio:playBackgroundTrack(selected)
    assert(ok==true,"benchmark music failed: "..tostring(err))
  end
end

function Benchmark:progress()
  local p=self.app._3ds and self.app._3ds.simulation_progress or {}
  return {world=p.world_completed or 0,hours=p.hours_completed or 0,
    entities=p.entity_completed or 0,at=self.native.clock_ms(),
    frames=self.native.runner_frames and self.native.runner_frames() or 0}
end

function Benchmark:terminal(outcome,reason)
  if not self.run then return end
  if self.terminal_started then return end
  self:cleanup()
  if not self.cleanup_finished then return end -- callback reentry waits for the owner
  self.terminal_started=true
  if self.cleanup_started and not self.cleanup_ok then outcome="FAIL";reason="CLEANUP_FAILED" end
  local fields={simulation_ticks=tostring(self.sample_ticks),frames=tostring(self.sample_frames),
    elapsed_us=tostring(math.floor(self.sample_elapsed_us or self.sample_elapsed*1000)),recovery_outcome="NOT_PROVEN",
    recovery_roundtrip_outcome=self.recovery_verified and "PASS" or "NOT_PROVEN",
    recovery_qualification_outcome="NOT_PROVEN",
    recovery_behavior_outcome="NOT_PROVEN",
    healthy_baseline_outcome=self.healthy_started and outcome or "NOT_PROVEN",errors=tostring(self.app._3ds.simulation_errors or 0),
    voice_playback="NOT_PROVEN",exact_state_ab="NOT_PROVEN"}
  for k,v in pairs(self.results)do fields[k]=tostring(v) end
  if self.phase=="sample" and self.sample_progress then
    local now=self:progress()
    for _,key in ipairs{"world","hours","entities","frames","at"}do
      fields["partial_"..key]=tostring(now[key]-self.sample_progress[key])
    end
  end
  if self.stress then
    fields.stress_cycles=tostring(self.stress.cycle)
    fields.stress_save_reload_count=tostring(self.stress.save_reload_count or 0)
    if self.stress.annualFields then
      for key,value in pairs(self.stress:annualFields())do fields[key]=value end
      if (self.stress.annual_observation_errors or 0)>0 and outcome~="FAIL" then
        outcome="FAIL";reason="ANNUAL_OBSERVATION_FAILED"
      end
    end
    local now=self.stress_end_progress or self:progress()
    for _,key in ipairs{"world","hours","entities","frames","at"}do
      fields["stress_"..key]=tostring(now[key]-self.stress_progress[key])
    end
  end
  local exited,exit_err=pcall(self.app.exit,self.app)
  if not exited then
    outcome="FAIL";if reason~="CLEANUP_FAILED" then reason="EXIT_FAILED" end
    fields.exit_error=failureText(exit_err)
    if self.app.abandon then pcall(self.app.abandon,self.app)end
  end
  local written,err=pcall(self.native.runner_finish,outcome,reason,fields)
  assert(written,err)
end

function Benchmark:cleanup()
  -- Cleanup consumes its ownership once. A window may clear its reference and
  -- then throw; retrying restore would erase that first necessary failure.
  if self.cleanup_started then return self.cleanup_ok==true end
  self.cleanup_started=true;self.cleanup_ok=false
  local ok,result=pcall(self.restore,self)
  if not ok or result~=true then
    if not self.results.cleanup_error then
      self.results.cleanup_error=ok and "mandatory restore rejected" or failureText(result)
    end
    -- A failed mandatory restore cannot leave a live unattended session. The
    -- normal path releases at its original point below, after world cleanup.
    local platform=rawget(self.app,"_3ds")
    if platform and platform.app==self.app and platform.native==self.native and platform.operations then
      platform.operations.blocked="BENCHMARK RESTORE FAILED; UNSAFE TO CONTINUE"
    end
    if self.native.operation_block then pcall(self.native.operation_block) end
    if self.native.shutdown then pcall(self.native.shutdown) end
    pcall(self.releaseActivation,self)
  else
    self.cleanup_ok=true
  end
  self.cleanup_finished=true
  return self.cleanup_ok
end

function Benchmark:restore()
  self.music_pending=nil
  Activity.stop()
  if self.capacity then self.capacity:close() end
  local closed=true
  if self.stress then
    local detail;closed,detail=pcall(self.stress.close,self.stress)
    if not closed then
      self.results.cleanup_error=self.results.cleanup_error or failureText(detail)
      pcall(print,"benchmark window cleanup failed: "..self.results.cleanup_error)
    end
  end
  self.app.savegame_dir=self.run and self.root.."save/" or self.original_dir
  self.app.config.autosave_frequency=self.original_autosave_frequency
  if self.app.world then self.app.world:setSpeed(self.failed and "Pause" or "Normal") end
  self:releaseActivation()
  if self.media_captured then
    local ok,err=pcall(function()
      self:applyMedia(self.original_language,self.original_music,self.original_track,
        not self.original_music_playing)
      assert(require("3ds.media").setSpeech(self.app,self.original_voice)==true,
        "voice restore failed")
      if self.original_music_playing and self.original_music_paused then
        assert(self.app.audio:pauseBackgroundTrack()==true,"music pause restore failed")
      end
    end)
    self.app.saveConfig=self.original_save_config
    if not ok then
      self.results.cleanup_error=self.results.cleanup_error or failureText(err)
      pcall(print,"benchmark media restore failed: "..failureText(err));return false
    end
  end
  return closed
end

function Benchmark:cancel(reason)
  if self.phase=="done" or self.cleanup_started then return end
  local capacity_ok=true
  if self.capacity and Activity.active then
    local detail;capacity_ok,detail=pcall(self.capacity.report,self.capacity,true)
    if not capacity_ok then
      self.results.failure_detail=self.results.failure_detail or failureText(detail)
      self.results.capacity_failure_outcome="FAIL"
    end
  end
  local marked,err=pcall(self.mark,self,"ABORT-"..failureText(reason))
  if not marked then self.results.failure_detail=self.results.failure_detail or failureText(err) end
  local restored=self:cleanup()
  local reported,report_error=pcall(self.terminal,self,restored and marked and capacity_ok and "NOT_PROVEN" or "FAIL",
    not restored and "CLEANUP_FAILED" or (marked and capacity_ok and "CANCEL" or "FAILED"))
  self.phase="done"
  if not reported then error(report_error,0) end
  if not pcall(self.native.set_notice,restored and "BENCHMARK STOPPED - LOG RETAINED"
    or "BENCHMARK RESTORE FAILED - SEE LOG",not restored) then
    self.results.failure_diagnostics=math.min(65535,(self.results.failure_diagnostics or 0)+1)
  end
end

function Benchmark:load()
  local root=self.root
  self:captureMedia()
  self.app.savegame_dir=root..(self.run and "save/" or "Saves/")
  self.app.config.autosave_frequency=0
  if self.media_profiles then self.app.audio:stopBackgroundTrack();self.app.config.play_music=false end
  if self.recovery_copy and not self.recovery_verified then
    self.results.recovery_stage="qualification"
    -- The installer supplies a byte-identical copy of the affected Slot1.
    -- Platform only repairs that explicit name; these writes stay private.
    local recovered,reason=loadBenchmark(self,root.."r62-recovery.sav",false)
    self.recovery_copy=false -- one independent qualification attempt
    if recovered~=true then
      self.recovery_refused=true
      self.results.recovery_qualification_outcome="REFUSED"
      self.results.recovery_reason=failureText(reason)
      pcall(print,"benchmark-recovery: status=REFUSED original_slot1=untouched reason="..failureText(reason))
    else
    local health=Health.assertActive(self.app)
    self.results.recovery_qualification_outcome="PASS"
    self.results.recovery_stage="paused_roundtrip"
    local cohort=self.app._3ds.recovery_cohort
    self.app.world:setSpeed("Pause")
    local fingerprint=require("3ds.benchmark_stress").fingerprint
    local before=fingerprint(self.app)
    local output=self.app.savegame_dir.."r63-recovery-roundtrip.sav"
    assert(self.app:save(output)==true,"R62 recovery copy save failed")
    loadBenchmark(self,output,true)
    Health.assertActive(self.app)
    assert(fingerprint(self.app)==before,"R62 recovery copy roundtrip state changed")
    self.recovery_verified=true
    self.results.recovery_staff=health.staff;self.results.recovery_patients=health.patients
    self.results.recovery_repaired_count=self.app._3ds.recovery_count or "NOT_PROVEN"
    print("benchmark-recovery: status=PASS staff="..health.staff.." patients="..health.patients
      .." ticks=active action_timer_state=preserved original_slot1=untouched")
    self.recovery_cohort=cohort
    self:beginRecoveryObservation(1)
    return
    end
  end
  local profile=self.profiles[self.index]
  loadBenchmark(self,root..(profile.file or "input.sav"),true)
  assert(self.app.world,"benchmark copy has no world")
  local health=Health.assertActive(self.app)
  self.healthy_started=true
  self.expected_errors=self.app._3ds and self.app._3ds.simulation_errors or 0
  self.last_health_check=self.native.clock_ms()
  print("benchmark-health: event=LOAD staff="..health.staff.." patients="..health.patients
    .." disabled_staff=0 disabled_patients=0 timer=active")
  -- World:onEndDay reads autosave_frequency. A saved pending request also
  -- needs clearing in this private benchmark world, before the first tick.
  self.app.config.autosave_frequency=0
  self.app.world.autosave_next_tick=false
  if self.media_profiles then
    self:applyMedia(profile.language,profile.music)
    local choice=profile.language=="English" and "en" or "zh"
    assert(require("3ds.media").setSpeech(self.app,choice)==true,"benchmark voice bank failed")
    assert(self.app.audio.speech_file_name==require("3ds.media").speechFile(self.app) and
      not self.app.audio.not_loaded,"benchmark voice bank not loaded")
  end
  self.app.world:setSpeed(profile.speed)
  self.expected_language=self.app.config.language
  self.expected_music=self.app.config.play_music
  self.expected_voice=self.app.config.speech_language
  self.expected_camera_x=self.app.ui and self.app.ui.screen_offset_x
  self.expected_camera_y=self.app.ui and self.app.ui.screen_offset_y
  if self.app.ui and self.app.ui.anyMustPauseWindowOpen and self.app.ui:anyMustPauseWindowOpen() then error(NEEDS_INPUT) end
  assert(self.app.world:getCurrentSpeed()==profile.speed,"benchmark speed could not be selected")
  self:mark("WARMUP")
  self.warmup_progress=self:progress()
  self.phase="warmup";self.deadline=self.native.clock_ms()+(self.warmup_ms or 30000)
  self.native.set_notice("AUTO BENCHMARK - WARMUP",false)
end

function Benchmark:beginRecoveryObservation(window)
  self.results.recovery_stage="observation_"..window
  self.recovery_window=window
  self.app.config.autosave_frequency=0;self.app.world.autosave_next_tick=false
  self.expected_errors=self.app._3ds.simulation_errors or 0
  self.last_health_check=self.native.clock_ms()
  self.phase="recovery"
  self.results.recovery_behavior_outcome="NOT_PROVEN"
  if window==1 and self.media_profiles and self.profiles and self.profiles[self.index] then
    local profile=self.profiles[self.index]
    self:applyMedia(profile.language,profile.music)
    local media=require("3ds.media")
    assert(media.setSpeech(self.app,profile.language=="English" and "en" or "zh")==true,
      "recovery voice bank failed")
    assert(self.app.audio.speech_file_name==media.speechFile(self.app) and not self.app.audio.not_loaded,
      "recovery voice bank not loaded")
  end
  self.recovery_language=self.app.config.language
  self.recovery_music=self.app.config.play_music
  self.recovery_voice=self.app.config.speech_language
  self.results.recovery_language=tostring(self.recovery_language)
  self.results.recovery_music=tostring(self.recovery_music)
  self.results.recovery_voice=tostring(self.recovery_voice)
  local playing,paused
  if self.native.music_state then playing,paused=self.native.music_state() end
  if self.recovery_music and self.native.music_state then assert(playing and not paused,"recovery music is not actually playing") end
  self:recoveryLine("recovery-media: window="..window.." language="..tostring(self.recovery_language)
    .." music="..tostring(self.recovery_music).." voice="..tostring(self.recovery_voice)
    .." playing="..tostring(playing).." paused="..tostring(paused).." voice_playback=NOT_PROVEN")
  if self.app.ui and self.app.ui:anyMustPauseWindowOpen() then error(NEEDS_INPUT) end
  Activity.start(self.app.world,self.recovery_cohort)
  self.app.world:setSpeed("Normal")
  assert(self.app.world:getCurrentSpeed()=="Normal","recovery speed changed")
  self.deadline=self.native.clock_ms()+25000
  self:recoveryLine("recovery-activity: event=BEGIN window="..window.." duration_ms=25000 speed=Normal")
end

function Benchmark:recoveryLine(line)
  assert(#line<=230,"recovery diagnostic exceeds line bound")
  if self.native.diagnostic_line then self.native.diagnostic_line(line) else print(line) end
end

function Benchmark:recoveryRows(rows,partial)
  for _,r in ipairs(rows) do
    local prefix="recovery-entity: window="..self.recovery_window.." source_index="..r.source_index
      .." index="..r.index.." partial="..tostring(partial==true)
    self:recoveryLine(prefix.." kind="..r.kind.." ticks="..r.ticks.." timers="..r.timers
      .." callbacks="..r.callbacks.." actions="..r.actions)
    self:recoveryLine(prefix.." desk_ticks="..r.desk_ticks.." services="..r.services
      .." failures="..r.failures.." timerless="..r.timerless.." partial_timer="..r.partial_timer.." unscheduled="..r.unscheduled)
  end
end

function Benchmark:advanceRecovery()
  if self.app.ui and self.app.ui:anyMustPauseWindowOpen() then error(NEEDS_INPUT) end
  assert(self.app.world:getCurrentSpeed()=="Normal","recovery speed changed")
  assert(self.app.config.language==self.recovery_language and self.app.config.play_music==self.recovery_music
    and self.app.config.speech_language==self.recovery_voice,"recovery media changed")
  if self.native.clock_ms()<self.deadline then return end
  local report=Activity.report()
  local prefix="recovery_window_"..self.recovery_window.."_"
  for k,v in pairs(report) do if k~="rows" then self.results[prefix..k]=v end end
  self:recoveryRows(report.rows,false)
  self:recoveryLine("recovery-activity: event=END window="..self.recovery_window.." outcome="..report.outcome
    .." cohort="..report.count.." updated="..report.updated.." action_covered="..report.action_covered
    .." service_uncovered="..report.service_uncovered)
  local cohort,reason=Activity.rebindCohort(self.app.world)
  Activity.stop() -- MUST precede every save/load; no observer references persist.
  self.results[prefix.."identity_outcome"]=cohort and "PASS" or "NOT_PROVEN"
  assert(report.outcome~="FAIL","recovered entity execution failed")
  if self.native.runner_checkpoint then
    local fields={phase="recovery_observation",outcome="NOT_PROVEN"}
    for k,v in pairs(self.results) do fields[k]=tostring(v) end
    self.native.runner_checkpoint(fields)
  end
  if self.recovery_window==1 and cohort then
    self.results.recovery_stage="continuity_roundtrip"
    self.recovery_cohort=cohort
    self.app.world:setSpeed("Pause")
    local fingerprint=require("3ds.benchmark_stress").fingerprint
    local before=fingerprint(self.app)
    local file=self.app.savegame_dir.."r66-recovery-continuity.sav"
    assert(self.app:save(file)==true,"recovery continuity save failed")
    loadBenchmark(self,file,true)
    Health.assertActive(self.app)
    assert(fingerprint(self.app)==before,"recovery continuity roundtrip changed")
    self.results.recovery_continuity_roundtrip_outcome="PASS"
    self:beginRecoveryObservation(2)
  else
    self.results.recovery_behavior_outcome=(cohort and report.outcome=="PASS" and
      self.results.recovery_window_1_outcome=="PASS") and "PASS" or "NOT_PROVEN"
    self.results.recovery_behavior_reason=reason or "bounded natural observation; absent actions or service remain uncovered"
    self.recovery_cohort=nil
    self.results.recovery_stage="complete"
    self:load()
  end
end

-- Fixed wall-time warmup can complete different amounts of simulation on two
-- builds. Record that difference and the scene before opening the timed window.
-- These bounded scalars describe comparability; they do not claim exact-state A/B.
function Benchmark:captureSampleContext()
  if not self.run then return end
  local before=assert(self.warmup_progress)
  local now=self.sample_progress
  local work={}
  for _,key in ipairs{"world","hours","entities","frames"} do
    assert(now[key]>=before[key],"warmup progress moved backwards")
    work[#work+1]=key.."="..(now[key]-before[key])
  end
  assert(now.at>=before.at,"warmup clock moved backwards")
  work[#work+1]="observed_ms="..(now.at-before.at)
  local health=Health.assertActive(self.app)
  local world=self.app.world
  local date=world.game_date and world.game_date:tostring() or "unknown"
  date=date:gsub("[\r\n]"," "):sub(1,128)
  local prefix="sample_"..self.index.."_"
  self.results[prefix.."warmup_work"]=table.concat(work,";")
  self.results[prefix.."scene_begin"]="date="..date
    ..";camera_x="..tostring(self.expected_camera_x)..";camera_y="..tostring(self.expected_camera_y)
    ..";staff="..health.staff..";patients="..health.patients
end

function Benchmark:advance()
  if self.phase=="pending" then self:load();return end
  assert((self.app._3ds and self.app._3ds.simulation_errors or 0)==self.expected_errors,
    "engine error occurred; performance sample invalid")
  assert(self.app.eventHandlers and self.app.eventHandlers.timer,
    "simulation timer disconnected; performance sample invalid")
  if self.music_pending or self.native.clock_ms()-self.last_health_check>=5000 then
    Health.assertActive(self.app);self.last_health_check=self.native.clock_ms()
    if (self.phase=="sample" and self.expected_music or self.phase=="recovery" and self.recovery_music
        or self.phase=="capacity" and self.expected_music)
        and self.native.music_state then
      self.music_pending=require("3ds.benchmark_music").check(
        self.native,self.app.audio,self.music_pending)
      -- Let the normal SDL event dispatch run first. Pending never advances a
      -- capacity/save/sample boundary and is checked on every subsequent loop.
      if self.music_pending then return end
    end
  end
  if self.phase=="recovery" then self:advanceRecovery();return end
  if self.phase=="capacity" then
    if self.capacity:tick() then self.capacity_complete=true;self:finish() end
    return
  end
  if self.phase=="stress" then
    if self.stress:tick() then self:finish() end
    return
  end
  if self.app.ui and self.app.ui.anyMustPauseWindowOpen and self.app.ui:anyMustPauseWindowOpen() then error(NEEDS_INPUT) end
  assert(self.app.world and self.app.world:getCurrentSpeed()==self.profiles[self.index].speed,"benchmark speed changed")
  assert(self.app.config.language==self.expected_language and
    self.app.config.play_music==self.expected_music and
    self.app.config.speech_language==self.expected_voice,
    "benchmark language, music or voice changed")
  assert((self.app.ui and self.app.ui.screen_offset_x)==self.expected_camera_x and
    (self.app.ui and self.app.ui.screen_offset_y)==self.expected_camera_y,
    "benchmark camera changed")
  if self.native.clock_ms()<self.deadline then return end
  if self.phase=="warmup" then
    self.sample_progress=self:progress()
    self:captureSampleContext()
    self:mark("SAMPLE-BEGIN",self.sample_progress);self.phase="sample"
    local duration=self.sample_ms or 60000
    self.deadline=self.sample_progress.at_us and
      math.ceil((self.sample_progress.at_us+duration*1000)/1000) or
      self.sample_progress.at+duration
    self.native.set_notice("AUTO BENCHMARK - SAMPLING",false)
  elseif self.phase=="sample" then
    Health.assertActive(self.app)
    local start=self.sample_progress;local finish=self:progress()
    assert(finish.world>start.world and finish.hours>start.hours and finish.entities>start.entities,
      "no completed simulation work; performance sample invalid")
    if self.run then assert(finish.frames>start.frames,"no valid rendered frames") end
    self:mark("SAMPLE-END",finish)
    assert(finish.at>start.at,"benchmark sample boundary did not advance")
    local elapsed_us=(finish.at_us or finish.at*1000)-(start.at_us or start.at*1000)
    print("benchmark-simulation: mode=fixed-wall-time elapsed_ms="..(finish.at-start.at)
      .." completed_world="..(finish.world-start.world).." completed_hours="..(finish.hours-start.hours)
      .." completed_entities="..(finish.entities-start.entities)
      .." exact_state_ab=NOT_PROVEN")
    if self.run then
      local prefix="sample_"..self.index.."_"
      for _,key in ipairs{"world","hours","entities","frames","at"} do
        self.results[prefix..key]=finish[key]-start[key]
      end
      assert(finish.frames>start.frames,"no valid rendered frames")
      self.sample_ticks=self.sample_ticks+finish.world-start.world
      self.sample_frames=self.sample_frames+finish.frames-start.frames
      self.sample_elapsed=self.sample_elapsed+finish.at-start.at
      self.sample_elapsed_us=(self.sample_elapsed_us or 0)+elapsed_us
      self.results[prefix.."elapsed_us"]=elapsed_us
      if self.native.runner_checkpoint then
        local checkpoint={phase="sample_complete",outcome="NOT_PROVEN"}
        for k,v in pairs(self.results)do checkpoint[k]=tostring(v)end
        self.native.runner_checkpoint(checkpoint)
      end
    end
    if self.index<#self.profiles then self.index=self.index+1;self:load()
    else
      if (self.run and self.stress_duration>0) or (not self.run and self.expanded) then
        self.phase="stress";self.deadline=nil
        self.stress_progress=self:progress()
        self.stress=require("3ds.benchmark_stress").new(self.app,self.native,self.stress_duration,
          self.run and self.app.savegame_dir or nil)
      else self:finish() end
    end
  end
end

function Benchmark:finish()
  if self.phase=="done" or self.cleanup_started then return end
  if self.capacity_requested and not self.capacity_complete then
    assert(not self.capacity,"capacity reentered before completion")
    self.stress_end_progress=self:progress()
    self.stress:close()
    self.capacity=require("3ds.benchmark_capacity").new(self)
    self.phase="capacity";self.deadline=nil
    return
  end
  if self.run then
    Health.assertActive(self.app)
    if self.stress then
      local now=self.stress_end_progress or self:progress()
      assert(now.world>self.stress_progress.world and now.hours>self.stress_progress.hours and
        now.entities>self.stress_progress.entities,"stress completed no simulation work")
    end
    assert(self.app:save(self.app.savegame_dir.."completed.sav")==true,"runner final private save failed")
    self:mark("WORKLOAD-END");assert(self:cleanup(),"runner cleanup failed")
    self:terminal("PASS","COMPLETE");self.phase="done";return
  end
  -- Return a fresh private copy for play; all automated writes have ended.
  loadBenchmark(self,root..(self.expanded and "expanded.sav" or "input.sav"),true)
  Health.assertActive(self.app)
  assert(self:cleanup(),"benchmark cleanup failed");self:mark("COMPLETE")
  self.phase="done"
  self.native.set_notice(self.recovery_refused and "BENCH DONE - OLD SAVE NEEDS AUDIT"
    or "BENCHMARK DONE - YOU CAN PLAY",false)
end

function Benchmark:tick()
  if self.phase=="done" or self.cleanup_started then return end
  local ok,err=pcall(self.advance,self)
  if not ok then
    -- Keep the original failure's safe summary before attempting observers.
    -- Even a broken mark/report must reach the existing cleanup exactly once.
    local detail=failureText(err)
    self.results.failure_detail=self.results.failure_detail or detail
    local function observe(callback,...)
      local observed=pcall(callback,...)
      if not observed then self.results.failure_diagnostics=math.min(65535,(self.results.failure_diagnostics or 0)+1)end
      return observed
    end
    self.results.failure_phase=self.results.failure_phase or
      (not self.healthy_started and self.results.recovery_stage or self.phase)
    if self.phase=="capacity" then
      local needs=type(err)=="string" and err:match(NEEDS_INPUT.."$")~=nil
      self.results.capacity_failure_outcome=needs and "NOT_PROVEN" or "FAIL"
      if self.capacity.save_io then
        self.capacity.save_io.failed=not needs
        self.results.save_io_outcome=needs and "NOT_PROVEN" or "FAIL"
      end
      if Activity.active then observe(self.capacity.report,self.capacity,true) end
    end
    if self.phase=="recovery" then
      local needs=type(err)=="string" and err:match(NEEDS_INPUT.."$")~=nil
      self.results.recovery_behavior_outcome=needs and "NOT_PROVEN" or "FAIL"
      self.results.recovery_interrupted_window=self.recovery_window
      if Activity.active then
        observe(function()
        local partial=Activity.report()
        self.results.recovery_partial_updated=partial.updated
        self.results.recovery_partial_service_uncovered=partial.service_uncovered
        self:recoveryRows(partial.rows,true)
        end)
      end
    end
    observe(self.mark,self,"FAILED")
    self.failed=true;local restored=self:cleanup()
    observe(self.native.set_notice,"BENCHMARK FAILED - SEE LOG",true)
    observe(print,"benchmark failure: "..detail)
    if self.native.runner_error then observe(self.native.runner_error,detail)end
    local needs_input=type(err)=="string" and err:match(NEEDS_INPUT.."$")~=nil
    observe(self.terminal,self,needs_input and restored and "NOT_PROVEN" or "FAIL",
      not restored and "CLEANUP_FAILED" or (needs_input and "NEEDS_INPUT" or "FAILED"))
    self.phase="done"
  elseif self.phase~="done" and self.deadline then
    local second=math.floor(self.native.clock_ms()/1000)
    if second~=self.last_second then
      self.last_second=second
      local remaining=math.max(0,math.ceil((self.deadline-self.native.clock_ms())/1000))
      self.native.set_notice("AUTO "..self.index.."/"..#self.profiles.." "..self.phase:upper().." "..remaining.."S - B CANCEL",false)
    end
  end
end
return Benchmark
