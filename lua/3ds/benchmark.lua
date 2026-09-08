-- One-shot opt-in benchmark. It owns no user save file and changes no game rule.
-- The installer supplies a verified copy at Benchmark/input.sav. All automatic
-- recovery/periodic saves are redirected while this short session is active.
local Benchmark={}
Benchmark.__index=Benchmark
local root="sdmc:/3ds/corsixth/Benchmark/"
local speeds={"Normal","And then some more"}

function Benchmark.new(app,native)
  local self=setmetatable({app=app,native=native,phase="pending",index=1,
    original_dir=app.savegame_dir,original_autosave_frequency=app.config.autosave_frequency},Benchmark)
  self.profiles={{speed=speeds[1]},{speed=speeds[2]}}
  if app.config.unicode_font and app.config.audio_music and app.audio and app.strings
      and app.strings:checkLanguageExists("Chinese (simplified)") then
    self.media_profiles=true
    self.original_language=app.config.language
    self.original_music=app.config.play_music
    self.original_music_playing=app.audio.background_music~=nil
    self.original_music_paused=app.audio.background_paused==true
    if self.original_music_playing then
      for i,info in ipairs(app.audio.background_playlist) do
        if info.music==app.audio.background_music then self.original_track=i;break end
      end
    end
    -- Even the upstream language-error fallback must not persist temporary
    -- benchmark settings. Restore the exact instance method on every exit.
    self.original_save_config=rawget(app,"saveConfig")
    app.saveConfig=function()end
    self.profiles={
      {speed="Normal",language="English",music=false,label="en-off"},
      {speed="Normal",language="Chinese (simplified)",music=false,label="zh-off"},
      {speed="Normal",language="Chinese (simplified)",music=true,label="zh-on"},
    }
  end
  native.benchmark_state(true)
  native.set_notice("AUTO BENCHMARK - B CANCEL",false)
  return self
end

function Benchmark:mark(event)
  local world=self.app.world
  local date=world and world.game_date and world.game_date:tostring() or "unknown"
  local speed=world and world:getCurrentSpeed() or "No world"
  self.native.benchmark_mark(event,speed,date)
  if self.media_profiles then
    local p=self.profiles[self.index]
    print("benchmark-media: event="..event.." variant="..p.label
      .." language="..tostring(self.app.config.language).." music="..tostring(self.app.config.play_music))
  end
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

function Benchmark:restore()
  self.app.savegame_dir=self.original_dir
  self.app.config.autosave_frequency=self.original_autosave_frequency
  if self.app.world then self.app.world:setSpeed("Normal") end
  self.native.benchmark_state(false)
  if self.media_profiles then
    local ok,err=pcall(function()
      self:applyMedia(self.original_language,self.original_music,self.original_track,
        not self.original_music_playing)
      if self.original_music_playing and self.original_music_paused then
        assert(self.app.audio:pauseBackgroundTrack()==true,"music pause restore failed")
      end
    end)
    self.app.saveConfig=self.original_save_config
    if not ok then print("benchmark media restore failed: "..tostring(err));return false end
  end
  return true
end

function Benchmark:cancel(reason)
  if self.phase=="done" then return end
  self:mark("ABORT-"..tostring(reason))
  self.phase="done"
  local restored=self:restore()
  self.native.set_notice(restored and "BENCHMARK STOPPED - LOG RETAINED"
    or "BENCHMARK RESTORE FAILED - SEE LOG",not restored)
end

function Benchmark:load()
  self.app.savegame_dir=root.."Saves/"
  self.app.config.autosave_frequency=0
  if self.media_profiles then self.app.audio:stopBackgroundTrack();self.app.config.play_music=false end
  local ok,detail=self.app:load(root.."input.sav")
  assert(ok==true,"benchmark copy load failed: "..tostring(detail))
  assert(self.app.world,"benchmark copy has no world")
  -- World:onEndDay reads autosave_frequency. A saved pending request also
  -- needs clearing in this private benchmark world, before the first tick.
  self.app.config.autosave_frequency=0
  self.app.world.autosave_next_tick=false
  local profile=self.profiles[self.index]
  if self.media_profiles then self:applyMedia(profile.language,profile.music) end
  self.app.world:setSpeed(profile.speed)
  assert(self.app.world:getCurrentSpeed()==profile.speed,
    "benchmark blocked by a mandatory pause window")
  self:mark("WARMUP")
  self.phase="warmup";self.deadline=self.native.clock_ms()+30000
  self.native.set_notice("AUTO BENCHMARK - WARMUP",false)
end

function Benchmark:advance()
  if self.phase=="pending" then self:load();return end
  assert(self.app.world and self.app.world:getCurrentSpeed()==self.profiles[self.index].speed,
    "benchmark speed changed or a mandatory pause window opened")
  if self.native.clock_ms()<self.deadline then return end
  if self.phase=="warmup" then
    self:mark("SAMPLE-BEGIN");self.phase="sample"
    self.deadline=self.native.clock_ms()+60000
    self.native.set_notice("AUTO BENCHMARK - SAMPLING",false)
  elseif self.phase=="sample" then
    self:mark("SAMPLE-END")
    if self.index<#self.profiles then self.index=self.index+1;self:load()
    else
      -- Return a fresh copy of the original hospital for the user's checks.
      local ok,detail=self.app:load(root.."input.sav")
      assert(ok==true,"benchmark final reload failed: "..tostring(detail))
      self.phase="done";assert(self:restore(),"benchmark media restore failed");self:mark("COMPLETE")
      self.native.set_notice("BENCHMARK DONE - YOU CAN PLAY",false)
    end
  end
end

function Benchmark:tick()
  if self.phase=="done" then return end
  local ok,err=pcall(self.advance,self)
  if not ok then
    self:mark("FAILED")
    self.phase="done";self:restore()
    self.native.set_notice("BENCHMARK FAILED - SEE LOG",true)
    print("benchmark failure: "..tostring(err))
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
