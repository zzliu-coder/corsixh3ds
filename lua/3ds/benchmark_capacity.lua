-- Optional bounded phases owned by Benchmark. All saves use its private route.
local C={};C.__index=C
local Health=require("3ds.state_health")
local Activity=require("3ds.recovery_activity")
local Stress=require("3ds.benchmark_stress")
C.sha="17b74375444d153599873bf25255b0d6a817343382eed1ebab6d3d89dce3a808"
local kinds={"Doctor","Doctor","Doctor","Nurse","Nurse","Handyman","Receptionist",
  "Handyman","Handyman","Nurse","Doctor","Receptionist","Nurse","Nurse","Doctor","Doctor","Nurse"}
local function scalar(v)return tostring(v):gsub("[\r\n]"," "):sub(1,80)end
local function packed(t)
  local rows={};for k,v in pairs(t)do rows[#rows+1]=k.."="..scalar(v) end
  table.sort(rows);local value=table.concat(rows,";")
  assert(#value<=1024,"capacity snapshot exceeds field bound");return value
end
function C.new(benchmark)
  local run=assert(benchmark.run)
  assert(run.capacity=="r73-v1" and run.continuity_sha256==C.sha,"unbound capacity input")
  assert(run.profile=="expanded-zh-on" and not run.recovery_sha256,"capacity profile conflict")
  assert(run.expanded_sha256=="f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7",
    "unbound capacity expanded input")
  local self=setmetatable({b=benchmark,app=benchmark.app,native=benchmark.native,
    guard=assert(benchmark.stress),phase="begin",services={[15]=0,[20]=0},patient_evidence={}},C)
  local r=benchmark.results
  r.capacity_stage="pending";r.capacity_reception_outcome="NOT_PROVEN"
  r.capacity_level_outcome="NOT_PROVEN";r.capacity_return_outcome="NOT_PROVEN"
  r.capacity_release_outcome="NOT_PROVEN";r.capacity_busy_hospital="NOT_PROVEN"
  r.capacity_lua_release_outcome="NOT_PROVEN"
  r.capacity_natural_promotion="NOT_PROVEN"
  r.capacity_input_sha256=C.sha
  r.capacity_annual_scope="original stress and capacity phases; stress work counters exclude capacity"
  return self
end
function C:check()
  self:guardOperation()
  self.guard:checkMandatory()
  assert(self.app.savegame_dir==self.b.root.."save/" and self.app.config.autosave_frequency==0,
    "capacity private route lost")
  assert(self.app.config.language==self.b.expected_language and
    self.app.config.play_music==self.b.expected_music and
    self.app.config.speech_language==self.b.expected_voice,"capacity media changed")
  assert((self.app._3ds.simulation_errors or 0)==self.b.expected_errors,"capacity simulation error")
end
function C:guardOperation()
  local operations=self.app._3ds.operations
  if operations then operations:guard() end
end
function C:loaded()
  self:guardOperation()
  self.app.config.autosave_frequency=0;self.app.world.autosave_next_tick=false
  Health.assertActive(self.app)
  self:check()
end
function C:load(file)
  self:check()
  assert(self.app:load(file)==true,"capacity private load failed")
  self:loaded()
end
function C:snapshot(stage)
  local app=self.app;local w=assert(app.world);local map=assert(app.map)
  local h=Health.assertActive(app);local rooms=0
  for _,room in pairs(w.rooms or {})do if room.hospital==app.ui.hospital then rooms=rooms+1 end end
  local p=self.b:progress()
  self.b.results["capacity_"..stage]=packed{level=map.level_number,difficulty=map.difficulty,
    world=tostring(w),map=tostring(map),staff=h.staff,patients=h.patients,rooms=rooms,
    date=w.game_date:tostring(),world_completed=p.world,hours=p.hours,entities=p.entities,
    frames=p.frames,at=p.at,errors=app._3ds.simulation_errors or 0}
  local m=assert(self.native.memory())
  local values={heap=m.heap_available_estimate,linear=m.linear_free,lua=m.lua_current,
    stage=m.stage,heap_low=m.heap_available_low_water,linear_low=m.linear_low_water}
  -- Keep the terminal payload bounded; complete native resources remain in
  -- the existing load/LevelStable diagnostics, outside this compact snapshot.
  for _,key in ipairs{"texture","map","world","sound_decoded"}do
    values["resource_"..key]=(m.diagnostic_resources or {})[key] or "NOT_PROVEN"
  end
  self.b.results["capacity_"..stage.."_memory"]=packed(values)
  self.b.results.capacity_stage=stage
  local fields={phase="capacity",outcome="NOT_PROVEN"}
  for k,v in pairs(self.b.results)do fields[k]=tostring(v)end
  for k,v in pairs(self.guard:annualFields())do fields[k]=v end
  self.native.runner_checkpoint(fields)
end
function C:normal(phase,duration)
  self.app.world:setSpeed("Normal")
  assert(self.app.world:getCurrentSpeed()=="Normal","capacity speed changed")
  self.phase=phase;self.b.results.capacity_stage=phase
  self.start_progress=self.b:progress()
  self.b.deadline=self.native.clock_ms()+duration
end
function C:advanced()
  local p=self.b:progress();local before=self.start_progress
  assert(p.world>before.world and p.hours>before.hours and p.frames>before.frames,
    "capacity has no completed simulation or presentation")
  -- A freshly initialized level can have zero people; record actual entities.
  self.b.results["capacity_"..self.phase.."_work"]=packed{world=p.world-before.world,
    hours=p.hours-before.hours,entities=p.entities-before.entities,frames=p.frames-before.frames,
    elapsed_ms=p.at-before.at}
end
function C:roundtrip(name)
  self:check();self.app.world:setSpeed("Pause")
  Health.assertActive(self.app)
  local before=Stress.fingerprint(self.app)
  local file=self.app.savegame_dir..name..".sav"
  self.b.results.capacity_stage=name.."_save"
  assert(self.app:save(file)==true,"capacity private save failed")
  self:guardOperation()
  self:load(file)
  assert(Stress.fingerprint(self.app)==before,"capacity private roundtrip changed state")
end
function C:observation(window)
  Activity.start(self.app.world,self.cohort,true)
  self.window=window
  self:normal("reception_"..window,180000)
end
function C:report(partial)
  local report=Activity.patientReport()
  local updated=report.updated
  local prefix="capacity_reception_"..self.window
  local identity=Activity.rebindCohort(self.app.world)
  Activity.stop() -- detach before diagnostics; a write failure cannot replay events
  self.cohort=identity
  self.b.results[prefix]=packed{outcome=report.outcome,updated=updated,count=report.count,
    identity=identity and "PASS" or "NOT_PROVEN",partial=partial==true,event_drops=report.event_drops}
  for _,r in ipairs(report.rows)do
    self.b:recoveryLine("capacity-activity: window="..self.window.." source="..r.source_index
      .." ticks="..r.ticks.." actions="..r.actions.." timers="..r.timers.." failures="..r.failures
      .." desk_ticks="..r.desk_ticks.." services="..r.services.." patients="..r.patient_services)
    if self.services[r.source_index] then self.services[r.source_index]=self.services[r.source_index]+r.patient_services end
  end
  for i,e in ipairs(report.events)do
    if e.head_kind=="Patient" then self.patient_evidence[e.source_index]=true end
    local tag="capacity-service: window="..self.window.." event="..i.." source="..e.source_index
    self.b:recoveryLine(tag.." head="..e.head_kind.." id="..e.head_id.." owner="..e.owner_index
      .." same="..tostring(e.owner_same).." before="..e.before.." after="..e.after)
    self.b:recoveryLine(tag.." action="..e.action_before.." next="..e.action_after)
    self.b:recoveryLine(tag.." tail="..e.tail_after.." passed_before="..tostring(e.passed_before).." passed_after=true")
  end
  self.b.results.capacity_patient_services="15="..self.services[15]..";20="..self.services[20]
  assert(report.outcome~="FAIL","capacity observed entity failure")
  return identity~=nil and updated==17
end
function C:level()
  Activity.stop();self.cohort=nil
  self:check();self:snapshot("level_before")
  self.old=setmetatable({self.app.world,self.app.map,self.app.ui},{__mode="v"})
  assert(self.app:loadLevel(12,"full",nil,nil,nil,nil,_S.errors.load_level_prefix,nil)==true,
    "capacity level load failed")
  self:loaded()
  assert(self.app.world~=self.old[1] and self.app.map~=self.old[2],"capacity level identity unchanged")
  assert(self.app.world.map==self.app.map and self.app.map.level_number==12
    and self.app.map.difficulty=="full","capacity actual level mismatch")
  self:snapshot("level_loaded")
  self.level_initial=setmetatable({self.app.world,self.app.map,self.app.ui},{__mode="v"})
  self:normal("level_run",60000)
end
function C:tick()
  self:check()
  if self.phase=="begin" then
    self:snapshot("continuity_before")
    self:load(self.b.root.."continuity.sav")
    assert(Health.assertActive(self.app).staff==17,"capacity healthy cohort count changed")
    self.cohort={}
    for i,kind in ipairs(kinds)do
      local index=i==17 and 45 or i+8
      self.cohort[i]={index=index,source_index=index,kind=kind}
    end
    self:snapshot("continuity_loaded")
    self:observation(1);return false
  end
  assert(self.app.world:getCurrentSpeed()=="Normal","capacity speed changed")
  if self.native.clock_ms()<self.b.deadline then return false end
  self:advanced()
  if self.phase=="reception_1" then
    self.first_complete=self:report(false)
    self:snapshot("reception_before_save")
    if self.cohort then
      self:roundtrip("r73-continuity")
      self.b.results.capacity_continuity_roundtrip="PASS"
      self:snapshot("reception_reloaded")
      self:observation(2)
    else self:level() end
  elseif self.phase=="reception_2" then
    local complete=self:report(false)
    self.b.results.capacity_reception_outcome=complete and self.first_complete
      and self.services[15]>0 and self.services[20]>0 and self.patient_evidence[15]
      and self.patient_evidence[20] and "PASS" or "NOT_PROVEN"
    self:level()
  elseif self.phase=="level_run" then
    self:snapshot("level_ran")
    self:roundtrip("r73-level12")
    assert(self.app.map.level_number==12 and self.app.map.difficulty=="full","capacity reloaded level mismatch")
    self.b.results.capacity_level_outcome="PASS"
    self:snapshot("level_reloaded")
    self.level_old=setmetatable({self.app.world,self.app.map,self.app.ui},{__mode="v"})
    self:load(self.b.root.."expanded.sav")
    self:snapshot("expanded_returned")
    self:normal("return_run",5000)
  else
    assert(self.phase=="return_run","unknown capacity phase")
    local released=true
    for _,list in ipairs{self.old,self.level_initial,self.level_old}do
      for _,key in ipairs{1,2,3}do if list[key]~=nil then released=false end end
    end
    self.b.results.capacity_lua_release_outcome=released and "PASS" or "NOT_PROVEN"
    self.b.results.capacity_return_outcome="PASS"
    self:snapshot("complete");self:close();return true
  end
  return false
end
function C:close()
  Activity.stop();self.cohort=nil;self.old=nil;self.level_old=nil;self.level_initial=nil
end
return C
