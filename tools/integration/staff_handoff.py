"""Room calls complete at Room:onHumanoidEnter, not an exhausted walk action."""
from sound_lifetime import replace_exact, SoundPatchError


DISPATCH = "CorsixTH/Lua/calls_dispatcher.lua"
CHECKPOINT = "CorsixTH/Lua/humanoid_actions/call_checkpoint.lua"

HELPER = '''-- CORSIXTH_3DS_STAFF_HANDOFF_R75: successful room entry completes the
-- call and replaces this checkpoint with the room's service actions. A still
-- owned checkpoint means that transfer never happened (e.g. a vanished path).
-- Preserve the room's request, release only this assignment, and resume the
-- ordinary dispatcher. Other call types and existing queue tails are untouched.
function CallsDispatcher.finishStaffRoomCheckpoint(action, staff)
  if action.on_remove ~= CallsDispatcher.staffActionInterruptHandler then
    return false
  end
  local call = action.call
  if call and call.assigned == staff and staff.on_call == call then
    -- Failure-only, bounded observation; normal room entry has no log cost.
    -- Diagnostics cannot interrupt the mandatory ownership transition.
    pcall(function()
      local native = rawget(_G, "TH3DS")
      if native and native.diagnostic_line then
        native.diagnostic_line(("staff-room-handoff: unaccepted room="..
          tostring(call.object.id).." staff="..tostring(staff.humanoid_class)..
          " x="..tostring(staff.tile_x).." y="..tostring(staff.tile_y)):sub(1,230))
      end
    end)
    call.assigned = nil
    staff.on_call = nil
    staff:unexpectFromRoom(call.object)
    call.dispatcher:onChange()
  end
  if not staff.on_call and #staff.action_queue == 1 then
    staff:queueAction(AnswerCallAction())
  end
  staff:finishAction(action)
  return true
end

'''

DISPATCH_SITES = [
    ('  if not staff:isIdle() or not staff:fulfillsCriterion(attribute) then',
     '  if not room.is_active or not staff:isIdle() or not staff:fulfillsCriterion(attribute) then'),
    ('''function CallsDispatcher.getPriorityForRoom(room, attribute, staff)
  local score = 0
  local x, y = room:getEntranceXY()''',
     '''function CallsDispatcher.getPriorityForRoom(room, attribute, staff)
  local score = 0
  -- Use the same destination as createEnterAction, including the door crossing.
  local x, y = room:getEntranceXY(true)'''),
    ('''  if distance then
    score = score + distance
  end

  -- More people on the queue''',
     '''  -- CORSIXTH_3DS_STAFF_HANDOFF_R75: unreachable is unavailable, not
  -- zero distance. Reuse the existing priority search; do not add another one.
  if not distance then
    return nil
  end
  score = score + distance

  -- More people on the queue'''),
    ('          if another_score <= score then',
     '          if another_score ~= nil and another_score <= score then'),
    ('function CallsDispatcher.sendStaffToRoom(room, staff)',
     HELPER + 'function CallsDispatcher.sendStaffToRoom(room, staff)'),
]
CHECKPOINT_SITES = [
    ('''  action.must_happen = true
  CallsDispatcher.onCheckpointCompleted(action.call)''',
     '''  action.must_happen = true
  if CallsDispatcher.finishStaffRoomCheckpoint(action, humanoid) then
    return
  end
  CallsDispatcher.onCheckpointCompleted(action.call)'''),
]


def patch(text, sites):
    for old, new in sites:
        if new not in text:
            text = replace_exact(text, old, new, "staff room handoff")
    return text


def transforms(root):
    paths = [root / DISPATCH, root / CHECKPOINT]
    # Older reduced fixtures contain neither; a partially present pair is drift.
    present = [p.is_file() for p in paths]
    if not any(present):
        return
    if not all(present):
        raise SoundPatchError("staff room handoff source pair is incomplete")
    yield DISPATCH, patch(paths[0].read_text(), DISPATCH_SITES)
    yield CHECKPOINT, patch(paths[1].read_text(), CHECKPOINT_SITES)
