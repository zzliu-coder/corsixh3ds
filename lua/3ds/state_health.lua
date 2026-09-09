-- R63: read simulation health independently of rendered FPS. Recovery is
-- explicit and limited to a copied R62 save whose own log proves this defect.
local Health={}

local function kind(entity)
  local classes=rawget(_G,"class")
  local staff,patient=rawget(_G,"Staff"),rawget(_G,"Patient")
  assert(classes and staff and patient,"simulation classes unavailable")
  if classes.is(entity,staff) then return "staff" end
  if classes.is(entity,patient) then return "patients" end
end

function Health.snapshot(world)
  assert(world and type(world.entities)=="table","simulation entities unavailable")
  local result={staff=0,patients=0,disabled_staff=0,disabled_patients=0}
  for _,entity in ipairs(world.entities)do
    local name=kind(entity)
    if name then
      result[name]=result[name]+1
      if entity.ticks==false then result["disabled_"..name]=result["disabled_"..name]+1 end
    end
  end
  return result
end

function Health.assertActive(app)
  assert(app.eventHandlers and type(app.eventHandlers.timer)=="function",
    "simulation timer disconnected; performance sample invalid")
  local state=Health.snapshot(app.world)
  assert(state.disabled_staff==0 and state.disabled_patients==0,
    "disabled humanoids; performance sample invalid: staff="..state.disabled_staff
      .." patients="..state.disabled_patients)
  return state
end

-- Used only around paused private save/reload, never in the per-frame path.
-- Stable scalar state catches a lost timer/action that an entity count misses.
function Health.fingerprint(world)
  local rows={}
  for index,entity in ipairs(world.entities)do
    local name=kind(entity)
    if name then
      local row={tostring(index),name,tostring(entity.humanoid_class),tostring(entity.ticks),
        tostring(entity.tile_x),tostring(entity.tile_y),tostring(entity.timer_time),
        type(entity.timer_function)}
      for _,action in ipairs(entity.action_queue or {})do
        row[#row+1]=table.concat({tostring(action.name),tostring(action.must_happen),
          tostring(action.uninterruptible),tostring(action.todo_interrupt)},":")
      end
      rows[#rows+1]=table.concat(row,"|")
    end
  end
  return table.concat(rows,"\n")
end

function Health.repairR62(world)
  local log=assert(world.game_log,"R62 recovery requires saved game log")
  local verified,recoveries,pending=0,0,false
  for i,message in ipairs(log)do
    if type(message)=="string" then
      local lowered=message:lower()
      assert(not (lowered:find("warning:",1,true) and
        (lowered:find("action queue",1,true) or lowered:find("callback",1,true))),
        "save has action/callback warnings; needs separate object audit")
    end
    if type(message)=="string" and message:match("^Error in .+ handler:") then
      local detail=log[i+1]
      assert(message:match("^Error in timer handler:") and type(detail)=="string"
        and detail:find("/entities/humanoids/staff.lua:127:",1,true)
        and detail:find("use of undeclared variable 'TH3DS'",1,true),
        "save contains another engine error; automatic R62 recovery refused")
      assert(not pending,"overlapping errors; R62 recovery refused")
      verified=verified+1;pending=true
    elseif message=="Recovering from error in timer handler..." then
      assert(pending,"unmatched recovery entry; R62 recovery refused")
      recoveries=recoveries+1;pending=false
    end
  end
  assert(verified>0 and verified==recoveries and not pending,
    "save lacks matched R62 error/recovery evidence")
  local before=Health.snapshot(world)
  assert(before.disabled_patients==0,"disabled patient has no R62 staff evidence")
  assert(before.disabled_staff<=recoveries,"disabled staff exceed verified recoveries")
  local seen,eligible={},{}
  for index,entity in ipairs(world.entities)do
    assert(not seen[entity],"duplicate entity membership; recovery refused")
    seen[entity]=true
    if entity.ticks==false and kind(entity)=="staff" then
      -- In the R62 Staff inheritance path, ticks=false is written by
      -- App:errorHandler; Object tick policies have a separate class path.
      -- Require a live, uniquely owned employee with a
      -- resumable timer; picked-up/fired/dead/ambiguous objects stay untouched.
      assert(entity.world==world and not entity.fired and not entity.dead and
        not entity.pickup and not entity.destroyed,"staff lifecycle ineligible: "..index)
      local hospital=entity.hospital
      assert(hospital and hospital.world==world and type(hospital.staff)=="table",
        "staff hospital ownership missing: "..index)
      local memberships=0
      for _,member in ipairs(hospital.staff)do if member==entity then memberships=memberships+1 end end
      assert(memberships==1,"staff hospital membership ambiguous: "..index)
      assert(type(entity.timer_time)=="number" and entity.timer_time>=1 and
        entity.timer_time%1==0 and type(entity.timer_function)=="function",
        "staff has no resumable timer: "..index)
      assert(type(entity.action_queue)=="table" and #entity.action_queue>0,
        "staff has no active action queue: "..index)
      for _,action in ipairs(entity.action_queue)do
        assert(type(action)=="table" and type(action.name)=="string" and #action.name>0,
          "staff action invalid: "..index)
      end
      eligible[#eligible+1]=entity
    end
  end
  -- Validate every precondition before changing any entity. Do not recreate
  -- entities, change action queues/timers, reset attributes or enable objects.
  local repaired=0
  for _,entity in ipairs(eligible)do
    entity.ticks=true;repaired=repaired+1
  end
  local after=Health.snapshot(world)
  assert(after.disabled_staff==0 and after.staff==before.staff and after.patients==before.patients)
  print("r63-recovery: source=verified-r62-copy staff="..before.staff
    .." restored="..repaired.." verified_errors="..verified.." confirmed_recoveries="..recoveries
    .." action_queues=preserved objects=unchanged")
  return repaired
end

-- R64 rejection diagnostics. No entity/action methods, callbacks, timer changes
-- or retained World references. Limits bound both output and collection scans.
function Health.auditR62(world,emit)
  assert(type(world)=="table" and type(rawget(world,"entities"))=="table",
    "simulation entities unavailable")
  assert(type(emit)=="function","recovery audit emitter unavailable")
  local limit,scan_limit=24,8192
  local result={shown=0,disabled=0,scanned=0,lines=0,truncated=false,
    scan_truncated=false,objects_truncated=false,actions_truncated=false,
    membership_truncated=false,line_truncated=false}
  local function scalar(value,width)
    local t=type(value)
    if t=="string" then
      -- Printable ASCII keeps corrupt strings/newlines from creating log rows.
      width=width or 40
      local clean=value:sub(1,width):gsub("[^ -~]","?")
      return clean..(#value>width and "..." or "")
    end
    if t=="number" or t=="boolean" or t=="nil" then return tostring(value) end
    return "<"..t..">"
  end
  local function line(message)
    if #message>230 then
      result.line_truncated=true
      message=message:sub(1,217).." [line-cut]"
    end
    emit(message) -- Let the caller retain the original repair refusal on error.
    result.lines=result.lines+1
  end
  local function field(object,key)
    if type(object)=="table" then return rawget(object,key) end
    return nil
  end
  local function length(value)
    return type(value)=="table" and tostring(rawlen(value)) or "<"..type(value)..">"
  end
  local entities=rawget(world,"entities")
  local indices,memberships={},{}
  local key,entity=next(entities)
  while key~=nil and result.scanned<scan_limit do
    result.scanned=result.scanned+1
    if type(entity)=="table" then memberships[entity]=(memberships[entity] or 0)+1 end
    if type(key)=="number" and key>=1 and key%1==0 and type(entity)=="table" and
        rawget(entity,"ticks")==false and kind(entity) then
      indices[#indices+1]=key
    end
    key,entity=next(entities,key)
  end
  result.scan_truncated=key~=nil
  table.sort(indices)
  result.disabled=#indices
  result.objects_truncated=#indices>limit
  for n=1,math.min(#indices,limit) do
    local index=indices[n]
    entity=rawget(entities,index)
    local prefix="r64-audit idx="..index
    local profile=rawget(entity,"profile")
    line(prefix.." kind="..kind(entity).." class="..scalar(rawget(entity,"humanoid_class"))
      .." profession="..scalar(field(profile,"profession")).." ticks="..scalar(rawget(entity,"ticks")))
    local timer=rawget(entity,"timer_function")
    local source="unavailable"
    local dbg=rawget(_G,"debug")
    local getinfo=type(dbg)=="table" and rawget(dbg,"getinfo")
    if type(timer)=="function" and type(getinfo)=="function" then
      local ok,info=pcall(getinfo,timer,"S")
      if ok and type(info)=="table" then
        local filename=rawget(info,"source")
        -- Report a basename and definition line, never closure data or a path.
        if type(filename)=="string" then
          if filename:sub(1,1)=="@" then
            filename=filename:match("([^/\\]+)$") or filename
          elseif filename:sub(1,1)~="=" then filename="[string]" end
          source=scalar(filename)..":"..scalar(rawget(info,"linedefined"))
        end
      end
    end
    line(prefix.." timer_time="..scalar(rawget(entity,"timer_time"))
      .." timer_type="..type(timer).." source="..source)
    line(prefix.." fired="..scalar(rawget(entity,"fired")).." dead="..scalar(rawget(entity,"dead"))
      .." pickup="..scalar(rawget(entity,"pickup")).." destroyed="..scalar(rawget(entity,"destroyed")))
    local hospital=rawget(entity,"hospital")
    local staff=field(hospital,"staff")
    local count,scanned=0,0
    local member_key,member
    if type(staff)=="table" then member_key,member=next(staff) end
    while member_key~=nil and scanned<scan_limit do
      scanned=scanned+1
      if member==entity then count=count+1 end
      member_key,member=next(staff,member_key)
    end
    local partial=member_key~=nil
    result.membership_truncated=result.membership_truncated or partial
    line(prefix.." world_ok="..tostring(rawget(entity,"world")==world)
      .." world_members="..(memberships[entity] or 0)..(result.scan_truncated and "+?" or "")
      .." hospital="..type(hospital).." hospital_world_ok="..tostring(field(hospital,"world")==world)
      .." staff_type="..type(staff).." staff_members="..count..(partial and "+?" or ""))
    local queue=rawget(entity,"action_queue")
    local qlength=type(queue)=="table" and rawlen(queue) or 0
    line(prefix.." queue_type="..type(queue).." queue_len="..qlength
      .." actions_truncated="..tostring(qlength>4))
    result.actions_truncated=result.actions_truncated or qlength>4
    for a=1,math.min(qlength,4) do
      local action=rawget(queue,a)
      -- must/uintr/intr are must_happen/uninterruptible/todo_interrupt;
      -- cb_i/cb_r report on_interrupt/on_restart types, never call them.
      line(prefix.." action="..a.." type="..type(action).." name="..scalar(field(action,"name"),24)
        .." must="..scalar(field(action,"must_happen"),6).." uintr="..scalar(field(action,"uninterruptible"),6)
        .." intr="..scalar(field(action,"todo_interrupt"),6).." path_index="..scalar(field(action,"path_index"),12)
        .." path_x="..length(field(action,"path_x")).." path_y="..length(field(action,"path_y"))
        .." cb_i="..type(field(action,"on_interrupt")).." cb_r="..type(field(action,"on_restart")))
    end
    result.shown=result.shown+1
  end
  result.truncated=result.scan_truncated or result.objects_truncated or
    result.actions_truncated or result.membership_truncated or result.line_truncated
  line("r64-audit summary scanned="..result.scanned.." disabled="..result.disabled.." shown="..result.shown
    .." truncated="..tostring(result.truncated).." scan="..tostring(result.scan_truncated)
    .." objects="..tostring(result.objects_truncated).." actions="..tostring(result.actions_truncated)
    .." membership="..tostring(result.membership_truncated).." line="..tostring(result.line_truncated))
  return result
end

return Health
