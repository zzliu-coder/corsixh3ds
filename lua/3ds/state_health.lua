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

return Health
