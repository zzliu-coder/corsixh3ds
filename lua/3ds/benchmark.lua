-- One-shot opt-in benchmark. It owns no user save file and changes no game rule.
-- The installer supplies a verified copy at Benchmark/input.sav. All automatic
-- recovery/periodic saves are redirected while this short session is active.
local Benchmark={}
Benchmark.__index=Benchmark
local root="sdmc:/3ds/corsixth/Benchmark/"
local speeds={"Normal","And then some more"}

function Benchmark.new(app,native)
  local self=setmetatable({app=app,native=native,phase="pending",index=1,
    original_dir=app.savegame_dir,original_autosave=app.config.autosave},Benchmark)
  native.benchmark_state(true)
  native.set_notice("AUTO BENCHMARK - B CANCEL",false)
  return self
end

function Benchmark:mark(event)
  local world=self.app.world
  local date=world and world.game_date and world.game_date:tostring() or "unknown"
  local speed=world and world:getCurrentSpeed() or "No world"
  self.native.benchmark_mark(event,speed,date)
  self.native.flush_observations()
end

function Benchmark:restore()
  self.app.savegame_dir=self.original_dir
  self.app.config.autosave=self.original_autosave
  if self.app.world then self.app.world:setSpeed("Normal") end
  self.native.benchmark_state(false)
end

function Benchmark:cancel(reason)
  if self.phase=="done" then return end
  self:mark("ABORT-"..tostring(reason))
  self.phase="done";self:restore()
  self.native.set_notice("BENCHMARK STOPPED - LOG RETAINED",false)
end

function Benchmark:load()
  self.app.savegame_dir=root.."Saves/"
  self.app.config.autosave=false
  local ok,detail=self.app:load(root.."input.sav")
  assert(ok==true,"benchmark copy load failed: "..tostring(detail))
  assert(self.app.world,"benchmark copy has no world")
  self.app.world:setSpeed(speeds[self.index])
  assert(self.app.world:getCurrentSpeed()==speeds[self.index],
    "benchmark blocked by a mandatory pause window")
  self:mark("WARMUP")
  self.phase="warmup";self.deadline=self.native.clock_ms()+30000
  self.native.set_notice("AUTO BENCHMARK - WARMUP",false)
end

function Benchmark:advance()
  if self.phase=="pending" then self:load();return end
  assert(self.app.world and self.app.world:getCurrentSpeed()==speeds[self.index],
    "benchmark speed changed or a mandatory pause window opened")
  if self.native.clock_ms()<self.deadline then return end
  if self.phase=="warmup" then
    self:mark("SAMPLE-BEGIN");self.phase="sample"
    self.deadline=self.native.clock_ms()+60000
    self.native.set_notice("AUTO BENCHMARK - SAMPLING",false)
  elseif self.phase=="sample" then
    self:mark("SAMPLE-END")
    if self.index<#speeds then self.index=self.index+1;self:load()
    else
      -- Return a fresh copy of the original hospital for the user's checks.
      local ok,detail=self.app:load(root.."input.sav")
      assert(ok==true,"benchmark final reload failed: "..tostring(detail))
      self.phase="done";self:restore();self:mark("COMPLETE")
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
      self.native.set_notice("AUTO "..self.index.."/2 "..self.phase:upper().." "..remaining.."S - B CANCEL",false)
    end
  end
end
return Benchmark
