-- Private recovery observation. No world/entity is stored in a save graph.
-- Weak keys cannot keep departed staff or desks alive. Rows contain scalars only.
local A={active=false}
local targets,desks,rows
local function action(e)
  local a=e.action_queue and e.action_queue[1]
  return a and tostring(a.name):sub(1,48) or "none",a and a.path_index
end
function A.capture(world)
  local cohort={}
  for index,e in ipairs(world.entities) do
    if e.ticks==false and class.is(e,Staff) then
      assert(#cohort<64,"recovery cohort exceeds observation bound")
      cohort[#cohort+1]={index=index,source_index=index,kind=tostring(e.humanoid_class):sub(1,48)}
    end
  end
  return cohort
end
function A.stop()
  A.active=false;targets=nil;desks=nil;rows=nil
end
function A.start(world,cohort)
  A.stop()
  assert(type(cohort)=="table" and #cohort>0 and #cohort<=64,"recovery cohort unavailable")
  targets=setmetatable({},{__mode="k"});desks=setmetatable({},{__mode="k"});rows={}
  for i,c in ipairs(cohort) do
    local e=assert(world.entities[c.index],"recovered entity missing after reload")
    assert(class.is(e,Staff) and e.humanoid_class==c.kind,"recovered entity identity changed")
    local r={index=c.index,source_index=c.source_index or c.index,kind=c.kind,ticks=0,failures=0,timers=0,callbacks=0,
      actions=0,desk_ticks=0,services=0,partial_timer=0,timerless=0,unscheduled=0}
    rows[i]=r;targets[e]=r
  end
  A.active=true
end
function A.before(e)
  if not A.active then return end
  local r=targets[e]
  if r then
    r.before_timer=e.timer_time;r.before_name,r.before_path=action(e)
    r.before_x=e.tile_x;r.before_y=e.tile_y
  end
  r=targets[e.receptionist]
  if r and (not class.is(e,ReceptionDesk) or e.tick~=ReceptionDesk.tick) then r=nil end
  desks[e]=r -- only retained until the matching synchronous after call
  if r then
    r.before_service_owner=targets[e.receptionist]==r
    r.before_visitors=e.queue and e.queue.visitor_count
  end
end
function A.after(e,ok)
  if not A.active then return end
  local r=targets[e]
  if r then
    if not ok then r.failures=r.failures+1
    else
      r.ticks=r.ticks+1
      local name,path=action(e)
      if r.before_timer and (e.timer_time~=r.before_timer or r.before_timer==1) then r.timers=r.timers+1 end
      if r.before_timer==1 then r.callbacks=r.callbacks+1 end
      if name~=r.before_name or path~=r.before_path or e.tile_x~=r.before_x or e.tile_y~=r.before_y then r.actions=r.actions+1 end
      if (e.timer_time==nil)~=(e.timer_function==nil) then r.partial_timer=r.partial_timer+1 end
      if e.timer_time==nil then r.timerless=r.timerless+1 end
      if e.timer_time==nil and r.kind=="Receptionist" and not
          (name=="staff_reception" and e.associated_desk and e.associated_desk.receptionist==e
          and e.associated_desk.ticks==true) then r.unscheduled=r.unscheduled+1 end
    end
    r.before_timer=nil;r.before_name=nil;r.before_path=nil;r.before_x=nil;r.before_y=nil
  end
  r=desks[e]
  desks[e]=nil
  if r then
    if not ok then r.failures=r.failures+1
    else
      local owner=r.before_service_owner and targets[e.receptionist]==r
      if owner then r.desk_ticks=r.desk_ticks+1 end
      local n=e.queue and e.queue.visitor_count
      if owner and type(n)=="number" and type(r.before_visitors)=="number" and n>r.before_visitors then
        r.services=r.services+n-r.before_visitors
      end
    end
    r.before_visitors=nil
    r.before_service_owner=nil
  end
end
function A.report()
  assert(A.active,"recovery observer stopped")
  local result={outcome="PASS",count=#rows,updated=0,action_covered=0,service_uncovered=0,rows={}}
  for i,r in ipairs(rows) do
    local copy={};for k,v in pairs(r) do copy[k]=v end;result.rows[i]=copy
    if r.ticks>0 then result.updated=result.updated+1 end
    if r.actions>0 then result.action_covered=result.action_covered+1 end
    local covered=r.ticks>0 and r.timers>0 and r.actions>0 and r.timerless==0
    if r.kind=="Receptionist" then
      covered=r.ticks>0 and r.desk_ticks>0 and r.services>0 and r.unscheduled==0
      if r.services==0 then result.service_uncovered=result.service_uncovered+1 end
    end
    if r.failures>0 or r.partial_timer>0 then result.outcome="FAIL"
    elseif not covered and result.outcome~="FAIL" then result.outcome="NOT_PROVEN" end
  end
  return result
end
function A.rebindCohort(world)
  assert(A.active,"recovery observer stopped")
  local positions={}
  for index,e in ipairs(world.entities) do
    local r=targets[e]
    if r then assert(not positions[r],"recovery duplicate membership");positions[r]=index end
  end
  local cohort={}
  for i,r in ipairs(rows) do
    if not positions[r] then return nil,"recovered staff departed observation world" end
    cohort[i]={index=positions[r],source_index=r.source_index,kind=r.kind}
  end
  return cohort
end
return A
