"""Keep an already running, ordinary handyman wander as its own continuation."""
from sound_lifetime import replace_exact


SOURCE = "CorsixTH/Lua/entities/humanoids/staff/handyman.lua"
OLD = '''function Handyman:doMeandering()
  -- Make sure that the handyman isn't meandering already.
  if self:isMeandering() then
    return
  end
  if self:getRoom() then
    self:queueAction(self:getRoom():createLeaveAction())
  end
  self:queueAction(MeanderAction())
end'''
NEW = OLD[:OLD.index('  if self:getRoom() then')] + '''  -- CORSIXTH_3DS_HANDYMAN_QUEUE_R74: meander_start searches for work
  -- before inserting its temporary idle/walk action. At that instant the
  -- repeating action is first, which Staff:isMeandering intentionally excludes.
  -- Keep that ordinary infinite continuation; never prune a saved queue or
  -- absorb a finite, callback-driven, interrupted or room-leaving action.
  local current = self.action_queue[1]
  local mt = type(current) == "table" and getmetatable(current)
  local room = self:getRoom()
  if type(mt) == "table" and rawget(mt, "__index") == _G["MeanderAction"]
      and current.name == "meander" and current.count == nil
      and current.loop_callback == nil and current.after_use == nil
      and current.on_interrupt == nil and current.on_remove == nil
      and not current.todo_interrupt and not current.must_happen
      and not current.uninterruptible and not current.is_leaving
      and not current.no_truncate and not room then
    return
  end
  if room then
    self:queueAction(self:getRoom():createLeaveAction())
  end
  self:queueAction(MeanderAction())
end
'''


def patch(text):
    if NEW in text:
        return text
    return replace_exact(text, OLD, NEW, "handyman ordinary wander continuation")


def transforms(root):
    path = root / SOURCE
    # Historical reduced source fixtures omit this upstream file. Complete
    # production assembly includes it, and the dedicated test exercises it.
    if path.is_file():
        yield SOURCE, patch(path.read_text())
