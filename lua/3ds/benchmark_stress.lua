-- Private-copy acceptance sequence. It calls real window constructors and the
-- normal save/load path. It never changes rules, hires fake staff, or buys land
-- with invented money. Non-deterministic emergencies remain manual acceptance.
local Stress={};Stress.__index=Stress
local root="sdmc:/3ds/corsixth/Benchmark/"
local windows={"UIPolicy","UIProgressReport","UIResearch","UIStaffManagement"}
local Health=require("3ds.state_health")

-- Native load can reconstruct instance metatables; the direct methods table is
-- permanent. Require this exact class, never an inherited class.is match.
local function exactClass(instance,expected)
  local mt=type(instance)=="table" and getmetatable(instance)
  return type(expected)=="table" and type(mt)=="table" and rawget(mt,"__index")==expected
end

local function className(instance)
  local mt=type(instance)=="table" and getmetatable(instance)
  local methods=type(mt)=="table" and rawget(mt,"__index")
  local class_mt=type(methods)=="table" and getmetatable(methods)
  local name=type(class_mt)=="table" and rawget(class_mt,"__class_name")
  return type(name)=="string" and name:gsub("[^%w_]","_"):sub(1,32) or "unknown"
end

function Stress:needsInput(window,reason)
  -- One bounded record for this run, even if a caller catches and retries.
  -- The terminal consumer matches the error suffix, so keep it unchanged.
  if not self.input_diagnostic_written then
    self.input_diagnostic_written=true
    local ui=self.app.ui
    local modal=window and window.modal_class
    local line="benchmark-stress: event=NEEDS_INPUT reason="..reason
      .." class="..className(window)
      .." modal="..(type(modal)=="string" and modal:gsub("[^%w_]","_"):sub(1,32) or "none")
      .." parent="..tostring(window~=nil and window.parent==ui)
      .." ui="..tostring(window~=nil and window.ui==ui)
      .." registered="..tostring(window~=nil and ui.modal_windows~=nil and ui.modal_windows[modal]==window)
      .." closed="..tostring(window~=nil and not not window.closed)
    print(line:sub(1,230))
  end
  error("TH3DS_NEEDS_INPUT")
end

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
  table.sort(rows);return table.concat(rows,"|").."\n"..Health.fingerprint(w)
end
Stress.fingerprint=fingerprint

function Stress.new(app,native,duration,save_dir)
  save_dir=save_dir or root.."Saves/"
  assert(app.savegame_dir==save_dir and app.config.autosave_frequency==0,
    "stress must own the private save route")
  local self=setmetatable({app=app,native=native,cycle=0,phase="open",deadline=0,save_dir=save_dir,
    finish_at=native.clock_ms()+(duration or 22*60000)},Stress)
  local annual,button=rawget(_G,"UIAnnualReport"),rawget(_G,"Button")
  self.annual_class=annual;self.annual_close=annual and annual.close
  self.annual_awards=annual and annual.updateAwards
  self.button_class=button;self.button_click=button and button.handleClick
  self.watch_class=rawget(_G,"UIWatch")
  self.annual_attempts=setmetatable({},{__mode="k"});self.annual_count=0
  print("benchmark-stress: event=BEGIN duration_ms="..(duration or 22*60000).." saves=Benchmark/Saves user_saves_writable=0")
  return self
end

function Stress:annualFields()
  return {stress_annual_attempts=tostring(self.annual_attempt_count or 0),
    stress_annual_passes=tostring(self.annual_count or 0),
    stress_annual_failures=tostring(self.annual_failure_count or 0),
    stress_annual_incomplete=self.annual_failed and "1" or "0",
    stress_annual_observation_errors=tostring(self.annual_observation_errors or 0),
    stress_annual_outcome=(self.annual_failure_count or 0)>0 and "FAIL"
      or (not self.annual_failed and (self.annual_count or 0)>0 and "PASS" or "NOT_PROVEN")}
end

function Stress:annualCheckpoint(event)
  -- At most two extra immutable checkpoints: the first attempt and its result.
  -- Later totals ride the existing save/reload and terminal records.
  if not self.native.runner_checkpoint or self.annual_attempt_count~=1
    or (self.annual_checkpoint_attempts or 0)>=2 then return end
  self.annual_checkpoint_attempts=(self.annual_checkpoint_attempts or 0)+1
  local fields=self:annualFields();fields.phase="stress_annual";fields.outcome="NOT_PROVEN"
  fields.annual_event=event
  local ok,err=pcall(self.native.runner_checkpoint,fields)
  if not ok then
    self.annual_observation_errors=(self.annual_observation_errors or 0)+1
    error(err,0)
  end
end

-- Only the original annual settlement confirmation is automatic. Scan before
-- every due action, including closing our window and either private save.
function Stress:checkMandatory()
  assert(not self.annual_failed,"annual confirmation previously failed")
  local app=self.app;local ui,world=app.ui,app.world
  local paused=ui:anyMustPauseWindowOpen()
  local annual,n=nil,0
  local class,button_class=self.annual_class,self.button_class
  local function owned(window)
    return not window.closed and window.parent==ui and window.ui==ui
      and ui.modal_windows and ui.modal_windows[window.modal_class]==window
      and ((window==self.window and self.window_class
        and exactClass(window,self.window_class))
        or (self.watch_class and exactClass(window,self.watch_class)
          and window.modal_class=="open_countdown"))
  end
  for _,window in pairs(ui.windows or {})do
    if window:mustPause() then annual=window;n=n+1 end
    if window.modal_class and not owned(window)
      and not exactClass(window,class) then
      self:needsInput(window,"modal_contract")
    end
  end
  if not paused and n==0 then return end
  local button=annual and annual.second_close
  local panel=button and button.panel_for_sprite
  local attached_button,attached_panel=0,0
  for _,item in pairs(annual and annual.buttons or {})do if item==button then attached_button=attached_button+1 end end
  for _,item in pairs(annual and annual.panels or {})do if item==panel then attached_panel=attached_panel+1 end end
  local valid=n==1 and class and button_class and rawget(_G,"TheApp")==app
    and type(self.annual_close)=="function" and type(self.annual_awards)=="function"
    and type(self.button_click)=="function"
    and app.savegame_dir==self.save_dir and app.config.autosave_frequency==0
    and ui.app==app and annual.parent==ui and annual.ui==ui and not annual.closed and annual.visible==true
    and exactClass(annual,class) and rawget(_G,"UIAnnualReport")==class
    and annual.modal_class=="fullscreen" and ui.modal_windows and ui.modal_windows.fullscreen==annual
    and annual.close==self.annual_close and class.close==self.annual_close
    and annual.updateAwards==self.annual_awards and class.updateAwards==self.annual_awards
    and button and exactClass(button,button_class)
    and rawget(_G,"Button")==button_class and button.handleClick==self.button_click
    and button_class.handleClick==self.button_click and button.ui==ui
    and button.on_click_self==annual and button.on_click==self.annual_close
    and button.enabled==true and button.visible==true and not button.is_toggle and not button.is_repeat
    and panel and panel.window==annual and panel.visible==true and attached_button==1 and attached_panel==1
    and (annual.state==2 or annual.state==3)
    and not self.annual_attempts[annual] and self.annual_count<32
  if not valid then self:needsInput(annual,"annual_contract") end
  self.annual_attempts[annual]=true;self.annual_failed=true
  self.annual_attempt_count=(self.annual_attempt_count or 0)+1
  self:annualCheckpoint("ATTEMPT")
  print("benchmark-stress: event=ANNUAL-CONFIRM status=ATTEMPT cycle="..self.cycle)
  local ok,err=pcall(function()
    self.button_click(button,"left")
    assert(app.ui==ui and app.world==world and rawget(_G,"TheApp")==app,
      "annual confirmation replaced world or ui")
    assert(annual.closed,"annual confirmation did not close")
    for _,window in pairs(ui.windows or {})do assert(window~=annual,"annual confirmation still attached") end
  end)
  if not ok then
    self.annual_failure_count=(self.annual_failure_count or 0)+1
    -- Preserve the raw settlement error; checkpoint failure has its own count.
    pcall(self.annualCheckpoint,self,"FAIL")
    error(err,0)
  end
  self.annual_count=self.annual_count+1;self.annual_failed=false
  self:annualCheckpoint("PASS")
  print("benchmark-stress: event=ANNUAL-CONFIRM status=PASS count="..self.annual_count.." cycle="..self.cycle)
  for _,window in pairs(ui.windows or {})do
    if window:mustPause() or (window.modal_class and not owned(window)) then
      self:needsInput(window,"after_annual")
    end
  end
end

function Stress:close()
  local window=self.window;self.window=nil
  if window and not window.closed then window:close() end
  assert(not self.annual_failed,"annual confirmation incomplete; cleanup blocked")
end

function Stress:saveReload()
  self:checkMandatory()
  local app=self.app
  assert(app.savegame_dir==self.save_dir and app.config.autosave_frequency==0)
  app.world:setSpeed("Pause")
  Health.assertActive(app)
  local before=fingerprint(app)
  assert(app:save(self.save_dir.."r62-roundtrip.sav")==true,"private save failed")
  assert(app:load(self.save_dir.."r62-roundtrip.sav")==true,"private reload failed")
  app.config.autosave_frequency=0;app.world.autosave_next_tick=false
  Health.assertActive(app)
  assert(fingerprint(app)==before,"private reload hospital fingerprint changed")
  self.save_reload_count=(self.save_reload_count or 0)+1
  if self.native.runner_checkpoint then
    local fields=self:annualFields()
    fields.phase="stress_save_reload";fields.outcome="NOT_PROVEN"
    fields.cycles=tostring(self.cycle);fields.save_reload_count=tostring(self.save_reload_count)
    fields.save_reload_outcome="PASS"
    local ok,err=pcall(self.native.runner_checkpoint,fields)
    if not ok then
      self.annual_observation_errors=(self.annual_observation_errors or 0)+1
      error(err,0)
    end
  end
  app.world:setSpeed("Normal")
  print("benchmark-stress: event=SAVE-RELOAD status=PASS cycle="..self.cycle.." checks=date,staff,wages,rooms,balance,plots,humanoids,ticks,timers,actions")
end

function Stress:tick()
  local now=self.native.clock_ms()
  self:checkMandatory()
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
      self:needsInput(nil,"before_open")
    end
    self.cycle=self.cycle+1
    local name=windows[(self.cycle-1)%#windows+1]
    local panel=assert(ui:getWindow(UIBottomPanel),"bottom panel missing")
    local result=panel:addDialog(name)
    assert(result~=false,"window preflight rejected "..name)
    self.window=assert(ui:getWindow(_G[name]),"window did not open: "..name)
    self.window_class=_G[name]
    print("benchmark-stress: event=OPEN status=PASS cycle="..self.cycle.." class="..name)
    self.deadline=self.native.clock_ms()+5000;self.phase="close"
  end
  local remaining=math.max(0,math.ceil((self.finish_at-self.native.clock_ms())/60000))
  self.native.set_notice("AUTO WINDOWS/SAVE "..remaining.." MIN - B CANCEL",false)
  return false
end
return Stress
