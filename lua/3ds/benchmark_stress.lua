-- Private-copy acceptance sequence. It calls real window constructors and the
-- normal save/load path. It never changes rules, hires fake staff, or buys land
-- with invented money. Non-deterministic emergencies remain manual acceptance.
local Stress={};Stress.__index=Stress
local root="sdmc:/3ds/corsixth/Benchmark/"
local windows={"UIPolicy","UIProgressReport","UIResearch","UIStaffManagement"}

local function fingerprint(app)
  local w,h=assert(app.world),assert(app.ui.hospital)
  local rows={"date:"..w.game_date:tostring(),"balance:"..tostring(h.balance)}
  for key,s in pairs(h.staff)do
    rows[#rows+1]="staff:"..tostring(key)..":"..tostring(s.humanoid_class)..":"..tostring(s.profile.wage)
  end
  for key,r in pairs(w.rooms)do if r.hospital==h then
    rows[#rows+1]="room:"..tostring(key)..":"..r.room_info.id..":"..tostring(r.x)..":"..tostring(r.y)
      ..":"..tostring(r.width)..":"..tostring(r.height)
  end end
  for i=1,w.map.th:getPlotCount()do rows[#rows+1]="plot:"..i..":"..w.map.th:getPlotOwner(i) end
  table.sort(rows);return table.concat(rows,"|")
end

function Stress.new(app,native,duration)
  assert(app.savegame_dir==root.."Saves/" and app.config.autosave_frequency==0,
    "stress must own the private save route")
  local self=setmetatable({app=app,native=native,cycle=0,phase="open",deadline=0,
    finish_at=native.clock_ms()+(duration or 22*60000)},Stress)
  print("benchmark-stress: event=BEGIN duration_ms="..(duration or 22*60000).." saves=Benchmark/Saves user_saves_writable=0")
  return self
end

function Stress:close()
  local window=self.window;self.window=nil
  if window and not window.closed then window:close() end
end

function Stress:saveReload()
  local app=self.app
  assert(app.savegame_dir==root.."Saves/" and app.config.autosave_frequency==0)
  app.world:setSpeed("Pause")
  local before=fingerprint(app)
  assert(app:save(root.."Saves/r62-roundtrip.sav")==true,"private save failed")
  assert(app:load(root.."Saves/r62-roundtrip.sav")==true,"private reload failed")
  app.config.autosave_frequency=0;app.world.autosave_next_tick=false
  assert(fingerprint(app)==before,"private reload hospital fingerprint changed")
  app.world:setSpeed("Normal")
  print("benchmark-stress: event=SAVE-RELOAD status=PASS cycle="..self.cycle.." checks=date,staff,wages,rooms,balance,plots")
end

function Stress:tick()
  local now=self.native.clock_ms()
  if now<self.deadline then return false end
  if self.phase=="close" then
    self:close();self.phase="open"
    if self.cycle%8==0 then self:saveReload() end
    if now>=self.finish_at then
      self:saveReload()
      print("benchmark-stress: event=COMPLETE cycles="..self.cycle.." sequence=PASS completed_only=1")
      return true
    end
    self.deadline=self.native.clock_ms()+12000
  else
    local app=self.app;local ui=app.ui
    if ui:anyMustPauseWindowOpen() then
      error("mandatory event requires user decision; stress stopped without auto-answer")
    end
    self.cycle=self.cycle+1
    local name=windows[(self.cycle-1)%#windows+1]
    local panel=assert(ui:getWindow(UIBottomPanel),"bottom panel missing")
    local result=panel:addDialog(name)
    assert(result~=false,"window preflight rejected "..name)
    self.window=assert(ui:getWindow(_G[name]),"window did not open: "..name)
    print("benchmark-stress: event=OPEN status=PASS cycle="..self.cycle.." class="..name)
    self.deadline=self.native.clock_ms()+5000;self.phase="close"
  end
  local remaining=math.max(0,math.ceil((self.finish_at-self.native.clock_ms())/60000))
  self.native.set_notice("AUTO WINDOWS/SAVE "..remaining.." MIN - B CANCEL",false)
  return false
end
return Stress
