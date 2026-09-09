-- R63: read simulation health independently of rendered FPS. Recovery is
-- explicit and limited to a copied R62 save whose own log proves this defect.
local Health={}
local reception_interrupt
local reception_binding_conflict=false

-- Called by the fixed StaffReceptionAction module immediately after declaring
-- its formal permanent callback. Retains code only, never a World or entity.
function Health.bindReceptionInterrupt(callback)
  assert(type(callback)=="function","reception binding requires a function")
  if reception_interrupt~=nil and reception_interrupt~=callback then reception_binding_conflict=true end
  assert(not reception_binding_conflict,"reception binding conflict")
  reception_interrupt=callback
end

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

-- R65: a seated receptionist is driven by ReceptionDesk:tick. The fixed
-- StaffReceptionAction idle phase consumes its timer before publishing the
-- bidirectional desk relationship. No other timerless action is eligible.
local function seatedReceptionist(world,entity)
  local classes=rawget(_G,"class")
  local receptionist=rawget(_G,"Receptionist")
  local desk_class=rawget(_G,"ReceptionDesk")
  local action_class=rawget(_G,"StaffReceptionAction")
  if not (classes and receptionist and desk_class and action_class and
      classes.is(entity,receptionist)) then return false,"not-receptionist" end
  if entity.timer_time~=nil or entity.timer_function~=nil then return false,"partial-timer" end
  -- ReceptionDesk:tick directly subtracts this value to determine service time.
  -- StaffProfile documents skill in [0,1]; NaN also fails these comparisons.
  if type(entity.profile)~="table" or type(entity.profile.skill)~="number" or
      not (entity.profile.skill>=0 and entity.profile.skill<=1) then return false,"reception-skill" end
  local queue=entity.action_queue
  if type(queue)~="table" or #queue~=1 then return false,"queue-not-single" end
  for key in pairs(queue)do if key~=1 then return false,"queue-extra-entry" end end
  local action=queue[1]
  if type(action)~="table" or not classes.is(action,action_class) or
      action.name~="staff_reception" then return false,"action-class" end
  if action.must_happen~=true or action.uninterruptible~=false or action.todo_interrupt or
      action.count~=nil or action.loop_callback~=nil or action.after_use~=nil or
      action.is_leaving~=false or action.no_truncate~=false or action.on_restart~=nil then
    return false,"action-flags"
  end
  -- Source names/line numbers are diagnostic only. Eligibility requires the
  -- exact formal callback published by this runtime's fixed action module.
  if reception_binding_conflict then return false,"interrupt-binding-conflict" end
  if reception_interrupt==nil then return false,"interrupt-unbound" end
  if action.on_interrupt~=reception_interrupt then return false,"interrupt-not-seated" end
  local desk=entity.associated_desk
  if type(desk)~="table" or not classes.is(desk,desk_class) or action.object~=desk or
      desk.receptionist~=entity or desk.reserved_for~=nil then return false,"desk-links" end
  if desk.world~=world or desk.hospital~=entity.hospital or desk.ticks~=true or
      desk.destroyed or desk.being_destroyed or desk.picked_up or desk.pickup or desk.dead then
    return false,"desk-lifecycle"
  end
  if type(desk.object_type)~="table" or desk.object_type.id~="reception_desk" or
      desk.tick~=desk_class.tick or type(desk.tick)~="function" or
      type(desk.queue)~="table" or type(desk.queue.front)~="function" or
      type(desk.queue.pop)~="function" or type(desk.queue.visitor_count)~="number" or
      desk.queue.visitor_count<0 or desk.queue.visitor_count%1~=0 or type(desk.queue_advance_timer)~="number" or
      desk.queue_advance_timer<0 or desk.queue_advance_timer%1~=0 then return false,"desk-scheduler" end
  local x,y=entity.tile_x,entity.tile_y
  if type(x)~="number" or type(y)~="number" or x<1 or y<1 or x%1~=0 or y%1~=0 or
      desk.tile_x~=x or desk.tile_y~=y then return false,"desk-tile" end
  local count=0
  for _,member in pairs(world.entities)do if member==desk then count=count+1 end end
  if count~=1 then return false,"desk-entity-membership" end
  count=0
  for _,member in ipairs(world.entities)do if member==desk then count=count+1 end end
  if count~=1 then return false,"desk-not-ticked" end
  local width=world.map and world.map.width
  if type(width)~="number" or width<1 or width%1~=0 or x>width or
      type(world.objects)~="table" then return false,"desk-object-map" end
  local tile=(y-1)*width+x
  count=0
  for location,list in pairs(world.objects)do
    if type(list)~="table" then return false,"desk-object-list" end
    for slot,member in pairs(list)do
      if member==desk then
        if location~=tile then return false,"desk-object-tile" end
        if type(slot)~="number" or slot<1 or slot%1~=0 or slot>#list then
          return false,"desk-object-slot"
        end
        count=count+1
      end
    end
  end
  if count~=1 then return false,"desk-object-membership" end
  count=0
  for _,member in ipairs(world.objects[tile])do if member==desk then count=count+1 end end
  if count~=1 then return false,"desk-object-hole" end
  return true,"seated-desk-scheduler"
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
      local timer_ok=type(entity.timer_time)=="number" and entity.timer_time>=1 and
        entity.timer_time%1==0 and type(entity.timer_function)=="function"
      if not timer_ok then
        local seated,reason=seatedReceptionist(world,entity)
        assert(seated,"staff has no resumable timer: "..index.." reception="..reason)
      end
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
    if rawget(entity,"humanoid_class")=="Receptionist" then
      local desk=rawget(entity,"associated_desk")
      local action=type(queue)=="table" and rawget(queue,1)
      line(prefix.." reception desk="..type(desk).." action_object_eq="..tostring(field(action,"object")==desk)
        .." receptionist_eq="..tostring(field(desk,"receptionist")==entity)
        .." reserved="..type(field(desk,"reserved_for")).." desk_ticks="..scalar(field(desk,"ticks")))
      line(prefix.." reception interrupt_bound="..tostring(reception_interrupt~=nil)
        .." interrupt_eq="..tostring(reception_interrupt~=nil and field(action,"on_interrupt")==reception_interrupt))
      line(prefix.." reception desk_world_ok="..tostring(field(desk,"world")==world)
        .." desk_hospital_eq="..tostring(field(desk,"hospital")==hospital)
        .." desk_members="..(memberships[desk] or 0)
        .." same_tile="..tostring(field(desk,"tile_x")==rawget(entity,"tile_x") and
          field(desk,"tile_y")==rawget(entity,"tile_y"))
        .." destroyed="..scalar(field(desk,"destroyed")).." picked_up="..scalar(field(desk,"picked_up")))
    end
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
