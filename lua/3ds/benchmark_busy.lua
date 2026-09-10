-- Optional R74 acceptance workload. Only ordinary UI hire/place/save methods
-- mutate the private hospital. No generated people, cash, rules or action ticks.
local Busy={};Busy.__index=Busy
local Health=require("3ds.state_health")
local Activity=require("3ds.recovery_activity")
local Stress=require("3ds.benchmark_stress")
local categories={"Doctor","Nurse","Handyman","Receptionist"}

function Busy.new(capacity)
  local self=setmetatable({c=capacity,app=capacity.app,next_hire=0,hires=0},Busy)
  -- The accepted busy range is 40..45. R75 already loads the user's 41-person
  -- hospital; observe it directly instead of requiring funds to hire to 43.
  -- R74's historical recruitment workload remains reproducible.
  self.target=capacity.b.run and capacity.b.run.capacity=="r75-v1" and 40 or 43
  capacity:normal("busy_recruit",120000)
  capacity:snapshot("busy_before")
  return self
end

function Busy:hire()
  local app=self.app;local ui,w=app.ui,app.world
  local profile,category
  for _,kind in ipairs(categories)do
    for _,candidate in ipairs(w.available_staff[kind])do
      if candidate.wage<=ui.hospital.balance and (not profile or candidate.wage<profile.wage)then
        profile,category=candidate,kind
      end
    end
  end
  if not profile then return false,"available_pool_or_balance" end
  -- Pick a real owned passable corridor tile; the placement window rechecks it.
  local flags={};local tx,ty
  local map=app.map
  assert(map.width<=256 and map.height<=256,"capacity placement search bound")
  for y=1,map.height do
    for x=1,map.width do
      map.th:getCellFlags(x,y,flags)
      if flags.owner==ui.hospital:getPlayerIndex() and flags.hospital and flags.passable
        and flags.roomId==0 then tx,ty=x,y;break end
    end
    if tx then break end
  end
  if not tx then return false,"no_owned_corridor" end
  local before=Health.assertActive(app).staff
  local panel=assert(ui:getWindow(UIBottomPanel),"capacity bottom panel missing")
  panel:dialogHireStaff()
  local hire=assert(ui:getWindow(UIHireStaff),"capacity hire window did not open")
  assert(getmetatable(hire)==UIHireStaff._metatable and hire.ui==ui and hire.world==w,
    "capacity hire owner changed")
  hire:setCategory(category)
  local index
  for i,candidate in ipairs(w.available_staff[category])do if candidate==profile then index=i end end
  assert(index,"capacity profile vanished")
  for _=2,index do assert(hire:moveBy(1),"capacity profile navigation refused") end
  local sx,sy=ui:WorldToScreen(tx+0.5,ty+0.5)
  hire.mouse_up_x=sx;hire.mouse_up_y=sy-14
  hire:hire()
  local place=assert(ui:getWindow(UIPlaceStaff),"capacity hiring refused")
  assert(getmetatable(place)==UIPlaceStaff._metatable and place.profile==profile,
    "capacity placement owner changed")
  place:onCursorWorldPositionChange(sx,sy-14)
  assert(place:_isValidStaffPlacement(),"capacity real placement rejected")
  assert(place:onMouseUp("left",sx,sy-14)==true and place.closed,
    "capacity staff placement did not finish")
  assert(app.world==w and app.ui==ui and Health.assertActive(app).staff==before+1,
    "capacity real hiring did not add one active employee")
  self.hires=self.hires+1
  self.c.b.results.capacity_busy_hires=self.hires
  return true
end

function Busy:observe(window,cohort)
  cohort=cohort or {}
  if #cohort==0 then
    for index,e in ipairs(self.app.world.entities)do
      if class.is(e,Staff)then
        cohort[#cohort+1]={index=index,source_index=index,kind=e.humanoid_class}
      end
    end
  end
  assert(#cohort>=40 and #cohort<=45,"capacity busy population outside 40..45")
  self.window=window;self.count=#cohort
  Activity.start(self.app.world,cohort)
  self.c:normal("busy_"..window,60000)
end

function Busy:report(partial)
  local report=Activity.report()
  local cohort=Activity.rebindCohort(self.app.world)
  Activity.stop()
  local complete=cohort~=nil and report.updated==self.count and report.outcome~="FAIL"
  self.c.b.results["capacity_busy_"..self.window.."_activity"]=
    "count="..report.count..";updated="..report.updated..";action_covered="..report.action_covered
      ..";identity="..(cohort and "PASS" or "NOT_PROVEN")..";partial="..tostring(partial==true)
      ..";outcome="..report.outcome
  for _,row in ipairs(report.rows)do
    self.c.b:recoveryLine("capacity-busy: window="..self.window.." source="..row.source_index
      .." ticks="..row.ticks.." actions="..row.actions.." timers="..row.timers
      .." failures="..row.failures.." partial_timer="..row.partial_timer)
  end
  assert(report.outcome~="FAIL","capacity busy entity failure")
  self.cohort=cohort
  return complete
end

function Busy:saveUI()
  local app=self.app;local ui=app.ui;local operations=assert(app._3ds.operations)
  self.c:check();app.world:setSpeed("Pause")
  local before=Stress.fingerprint(app);local previous=operations.last
  local name="r74-busy";local file=app.savegame_dir..name..".sav"
  assert(lfs.attributes(file,"size")==nil,"capacity private save already exists")
  local window=UISaveGame(ui);ui:addWindow(window)
  window.new_savegame_textbox:setText(name)
  window:confirmName() -- real validation -> trySave -> doSave -> same operations
  local result=operations.last
  assert(window.closed and result~=previous and result.method=="save" and result.committed
    and result.completed and result.ready,"capacity private save UI did not commit and finish")
  self.c:guardOperation()
  self.c.b.results.capacity_busy_save_entry="UISaveGame.confirmName/trySave/doSave"
  self.c.b.results.capacity_busy_save_ui="PASS"
  self.c:load(file)
  Stress.assertFingerprint(app,before,"capacity busy reload changed hospital state",self.c.native)
  self.c.b.results.capacity_busy_roundtrip="PASS"
end

function Busy:tick()
  local c=self.c;local now=c.native.clock_ms()
  assert(self.app.world:getCurrentSpeed()=="Normal","capacity busy speed changed")
  if c.phase=="busy_recruit"then
    if Health.assertActive(self.app).staff>=self.target then
      c:advanced();c:snapshot("busy_loaded");self:observe(1);return false
    end
    if now>=c.b.deadline then
      c.b.results.capacity_busy_reason=self.reason or "recruitment_timeout"
      c:advanced();return true -- size not reached: explicitly NOT_PROVEN
    end
    if now>=self.next_hire then
      local hired,reason=self:hire();self.reason=reason
      self.next_hire=c.native.clock_ms()+(hired and 250 or 5000)
    end
    return false
  end
  if now<c.b.deadline then return false end
  c:advanced()
  local complete=self:report(false)
  if self.window==1 then
    self.first_complete=complete
    if not self.cohort then c.b.results.capacity_busy_reason="staff_departed";return true end
    self:saveUI();c:snapshot("busy_reloaded");self:observe(2,self.cohort)
    self.cohort=nil;return false
  end
  assert(self.window==2,"unknown busy window")
  c.b.results.capacity_busy_hospital=complete and self.first_complete and "PASS" or "NOT_PROVEN"
  c:snapshot("busy_complete");return true
end

function Busy:close()
  Activity.stop();self.cohort=nil
end
return Busy
