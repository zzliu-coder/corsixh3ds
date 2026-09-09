-- One-shot opt-in benchmark. It owns no user save file and changes no game rule.
-- The installer supplies a verified copy at Benchmark/input.sav. All automatic
-- recovery/periodic saves are redirected while this short session is active.
local Benchmark={}
Benchmark.__index=Benchmark
local root="sdmc:/3ds/corsixth/Benchmark/"
local speeds={"Normal","And then some more"}
local Health=require("3ds.state_health")
local NEEDS_INPUT="TH3DS_NEEDS_INPUT"

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
  end
  native.benchmark_state(true)
  native.set_notice("AUTO BENCHMARK - B CANCEL",false)
  return self
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

function Benchmark:mark(event)
  local world=self.app.world
  local date=world and world.game_date and world.game_date:tostring() or "unknown"
  local speed=world and world:getCurrentSpeed() or "No world"
  self.native.benchmark_mark(event,speed,date)
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
  local fields={simulation_ticks=tostring(self.sample_ticks),frames=tostring(self.sample_frames),
    elapsed_us=tostring(self.sample_elapsed*1000),recovery_outcome="NOT_PROVEN",
    recovery_roundtrip_outcome=self.recovery_verified and "PASS" or "NOT_PROVEN",
    recovery_behavior_outcome="NOT_PROVEN",
    healthy_baseline_outcome=outcome,errors=tostring(self.app._3ds.simulation_errors or 0),
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
    local now=self:progress()
    for _,key in ipairs{"world","hours","entities","frames","at"}do
      fields["stress_"..key]=tostring(now[key]-self.stress_progress[key])
    end
  end
  local exited,exit_err=pcall(self.app.exit,self.app)
  if not exited then
    outcome="FAIL";reason="EXIT_FAILED"
    fields.exit_error=tostring(exit_err):gsub("[\r\n]"," "):sub(1,1024)
    if self.app.abandon then pcall(self.app.abandon,self.app)end
  end
  local written,err=pcall(self.native.runner_finish,outcome,reason,fields)
  assert(written,err)
end

function Benchmark:cleanup()
  local ok,result=pcall(self.restore,self)
  if not ok then self.results.cleanup_error=tostring(result):gsub("[\r\n]"," "):sub(1,1024) end
  return ok and result==true
end

function Benchmark:restore()
  local closed=true
  if self.stress then
    local detail;closed,detail=pcall(self.stress.close,self.stress)
    if not closed then print("benchmark window cleanup failed: "..tostring(detail)) end
  end
  self.app.savegame_dir=self.run and self.root.."save/" or self.original_dir
  self.app.config.autosave_frequency=self.original_autosave_frequency
  if self.app.world then self.app.world:setSpeed(self.failed and "Pause" or "Normal") end
  self.native.benchmark_state(false)
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
    if not ok then print("benchmark media restore failed: "..tostring(err));return false end
  end
  return closed
end

function Benchmark:cancel(reason)
  if self.phase=="done" then return end
  self:mark("ABORT-"..tostring(reason))
  local restored=self:cleanup()
  self:terminal(restored and "NOT_PROVEN" or "FAIL",restored and "CANCEL" or "CLEANUP_FAILED")
  self.phase="done"
  self.native.set_notice(restored and "BENCHMARK STOPPED - LOG RETAINED"
    or "BENCHMARK RESTORE FAILED - SEE LOG",not restored)
end

function Benchmark:load()
  local root=self.root
  self:captureMedia()
  self.app.savegame_dir=root..(self.run and "save/" or "Saves/")
  self.app.config.autosave_frequency=0
  if self.media_profiles then self.app.audio:stopBackgroundTrack();self.app.config.play_music=false end
  if self.recovery_copy and not self.recovery_verified then
    -- The installer supplies a byte-identical copy of the affected Slot1.
    -- Platform only repairs that explicit name; these writes stay private.
    local recovered,reason=self.app:load(root.."r62-recovery.sav")
    self.recovery_copy=false -- one independent qualification attempt
    if recovered~=true then
      self.recovery_refused=true
      self.results.recovery_reason=tostring(reason):gsub("[\r\n]"," "):sub(1,1024)
      print("benchmark-recovery: status=REFUSED original_slot1=untouched reason="..tostring(reason))
    else
    local health=Health.assertActive(self.app)
    self.app.world:setSpeed("Pause")
    local fingerprint=require("3ds.benchmark_stress").fingerprint
    local before=fingerprint(self.app)
    local output=self.app.savegame_dir.."r63-recovery-roundtrip.sav"
    assert(self.app:save(output)==true,"R62 recovery copy save failed")
    assert(self.app:load(output)==true,"R62 recovery copy reload failed")
    Health.assertActive(self.app)
    assert(fingerprint(self.app)==before,"R62 recovery copy roundtrip state changed")
    self.recovery_verified=true
    self.results.recovery_staff=health.staff;self.results.recovery_patients=health.patients
    self.results.recovery_repaired_count=self.app._3ds.recovery_count or "NOT_PROVEN"
    print("benchmark-recovery: status=PASS staff="..health.staff.." patients="..health.patients
      .." ticks=active action_timer_state=preserved original_slot1=untouched")
    end
  end
  local profile=self.profiles[self.index]
  local ok,detail=self.app:load(root..(profile.file or "input.sav"))
  assert(ok==true,"benchmark copy load failed: "..tostring(detail))
  assert(self.app.world,"benchmark copy has no world")
  local health=Health.assertActive(self.app)
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
  self.phase="warmup";self.deadline=self.native.clock_ms()+(self.warmup_ms or 30000)
  self.native.set_notice("AUTO BENCHMARK - WARMUP",false)
end

function Benchmark:advance()
  if self.phase=="pending" then self:load();return end
  assert((self.app._3ds and self.app._3ds.simulation_errors or 0)==self.expected_errors,
    "engine error occurred; performance sample invalid")
  assert(self.app.eventHandlers and self.app.eventHandlers.timer,
    "simulation timer disconnected; performance sample invalid")
  if self.native.clock_ms()-self.last_health_check>=5000 then
    Health.assertActive(self.app);self.last_health_check=self.native.clock_ms()
    if self.phase=="sample" and self.native.music_state and self.expected_music then
      local playing,paused=self.native.music_state()
      assert(playing and not paused,"benchmark music is not actually playing")
    end
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
    self:mark("SAMPLE-BEGIN");self.phase="sample"
    self.deadline=self.native.clock_ms()+(self.sample_ms or 60000)
    self.native.set_notice("AUTO BENCHMARK - SAMPLING",false)
  elseif self.phase=="sample" then
    Health.assertActive(self.app)
    local start=self.sample_progress;local finish=self:progress()
    assert(finish.world>start.world and finish.hours>start.hours and finish.entities>start.entities,
      "no completed simulation work; performance sample invalid")
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
      if self.native.runner_checkpoint then
        local checkpoint={phase="sample_complete",outcome="NOT_PROVEN"}
        for k,v in pairs(self.results)do checkpoint[k]=tostring(v)end
        self.native.runner_checkpoint(checkpoint)
      end
    end
    self:mark("SAMPLE-END")
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
  if self.run then
    Health.assertActive(self.app)
    if self.stress then
      local now=self:progress()
      assert(now.world>self.stress_progress.world and now.hours>self.stress_progress.hours and
        now.entities>self.stress_progress.entities,"stress completed no simulation work")
    end
    assert(self.app:save(self.app.savegame_dir.."completed.sav")==true,"runner final private save failed")
    self:mark("WORKLOAD-END");assert(self:cleanup(),"runner cleanup failed")
    self:terminal("PASS","COMPLETE");self.phase="done";return
  end
  -- Return a fresh private copy for play; all automated writes have ended.
  local ok,detail=self.app:load(root..(self.expanded and "expanded.sav" or "input.sav"))
  assert(ok==true,"benchmark final reload failed: "..tostring(detail))
  Health.assertActive(self.app)
  self.phase="done";assert(self:restore(),"benchmark media restore failed");self:mark("COMPLETE")
  self.native.set_notice(self.recovery_refused and "BENCH DONE - OLD SAVE NEEDS AUDIT"
    or "BENCHMARK DONE - YOU CAN PLAY",false)
end

function Benchmark:tick()
  if self.phase=="done" then return end
  local ok,err=pcall(self.advance,self)
  if not ok then
    self:mark("FAILED")
    self.failed=true;local restored=self:cleanup()
    self.native.set_notice("BENCHMARK FAILED - SEE LOG",true)
    print("benchmark failure: "..tostring(err))
    if self.native.runner_error then self.native.runner_error(tostring(err))end
    self.results.failure_detail=tostring(err):gsub("[\r\n]"," "):sub(1,1024)
    local needs_input=tostring(err):match(NEEDS_INPUT.."$")~=nil
    self:terminal(needs_input and restored and "NOT_PROVEN" or "FAIL",
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
