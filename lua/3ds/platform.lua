-- CorsixTH 0.70.1 platform adapter for Nintendo 3DS.
-- Loaded only by the CORSIXTH_3DS integration patch.

local Platform = {}
Platform.__index = Platform

local function clamp(value, low, high)
  if value < low then return low end
  if value > high then return high end
  return value
end

local function count_table(value)
  if type(value) ~= "table" then return 0 end
  local count = 0
  for _ in pairs(value) do count = count + 1 end
  return count
end

local function safe_call(target, method, ...)
  if target and type(target[method]) == "function" then
    local ok, result = pcall(target[method], target, ...)
    if ok then return result end
    print("CorsixTH 3DS: " .. method .. " failed: " .. tostring(result))
  end
end

local function safe_value(callback, fallback)
  local ok, result = pcall(callback)
  if ok and result ~= nil then return result end
  return fallback
end

local function traceback_message(message)
  if debug and type(debug.traceback) == "function" then
    return debug.traceback(tostring(message), 2)
  end
  return tostring(message)
end

local function pack_values(...)
  return {n = select("#", ...), ...}
end

local function unpack_values(values)
  local unpack_function = table.unpack or unpack
  return unpack_function(values, 1, values.n)
end

local function native_notice(native, message, is_error)
  if native and type(native.set_notice) == "function" then
    pcall(native.set_notice, tostring(message or ""), is_error == true)
  end
end

local function native_checkpoint(native, name, phase, identity, bytes, requested)
  if native and type(native.checkpoint) == "function" then
    pcall(native.checkpoint, name, phase or "event", identity or "-",
          bytes or 0, requested or 0)
  end
end

local function native_resource_event(native, event, identity, success)
  if not native or type(native.resource_event) ~= "function" then return end
  local called, accepted, detail = pcall(native.resource_event, event,
                                          identity or "-", success ~= false)
  if not called then error(accepted, 0) end
  if accepted ~= true then
    error("Runtime Core " .. tostring(event) .. " failed: " ..
          tostring(detail or "unknown error"), 0)
  end
end

local function world_identity(world)
  if not world then return "main-menu" end
  return tostring(safe_value(function()
    return world.level_number or world.level_name or world.map_name or world.name
  end, tostring(world)))
end

local function top_window(ui)
  if not ui or type(ui.windows) ~= "table" then return nil end
  for index = #ui.windows, 1, -1 do
    local window = ui.windows[index]
    if window and window.visible ~= false and window ~= ui.bottom_panel then
      return window
    end
  end
  return nil
end

local function entity_name(entity)
  if not entity then return "" end
  local name = safe_value(function()
    if type(entity.getFullName) == "function" then return entity:getFullName() end
    if type(entity.name) == "string" then return entity.name end
    if entity.humanoid_class and entity.humanoid_class.name then
      return entity.humanoid_class.name
    end
  end, "")
  return tostring(name or "")
end

local function entity_status(entity)
  if not entity then return "" end
  return tostring(safe_value(function()
    if type(entity.getCurrentAction) == "function" then
      local action = entity:getCurrentAction()
      if action then return action.name or action.todo or "" end
    end
    return entity.status or entity.tooltip or ""
  end, ""))
end

function Platform.new(app, native)
  local self = setmetatable({
    app = app,
    native = native,
    cursor_x = 320,
    cursor_y = 240,
    saved_speed = nil,
    save_installed = false,
    load_installed = false,
    last_state = nil,
    world_seen = false,
    last_world = nil,
    menu_checkpointed = false,
    first_level_checkpointed = false,
  }, Platform)
  self:installAtomicSaves()
  self:installLoadTelemetry()
  local language = app.config and app.config.language or "unknown"
  native_checkpoint(native, "language_selected", "observed-at-adapter-attach",
                    tostring(language))
  return self
end

function Platform:installAtomicSaves()
  if self.save_installed then return end
  self.save_installed = true
  local app = self.app
  local native = self.native
  local original_save = app.save

  app.save = function(instance, filename)
    native_checkpoint(native, "save_load", "save-begin", filename)
    local temporary = filename .. ".tmp"
    os.remove(temporary)
    local transaction_started = false
    local ok, result = xpcall(function()
      native_resource_event(native, "save-begin", filename, true)
      transaction_started = true
      if type(native.begin_critical_io) == "function" then
        native.begin_critical_io()
      end
      local save_result = original_save(instance, temporary)
      local committed, commit_error = native.atomic_commit(temporary, filename, true)
      if not committed then
        error("Atomic save commit failed: " .. tostring(commit_error))
      end
      return save_result
    end, traceback_message)

    if type(native.end_critical_io) == "function" then
      native.end_critical_io()
    end
    if not ok then
      os.remove(temporary)
      if transaction_started then
        native_resource_event(native, "save-end", filename, false)
      end
      native_notice(native, "SAVE FAILED", true)
      native_checkpoint(native, "save_load", "save-failed", filename)
      error(result, 0)
    end
    native_resource_event(native, "save-end", filename, true)
    native_notice(native, "SAVE OK", false)
    native_checkpoint(native, "save_load", "save-complete", filename)
    return result
  end

  app.quickSave = function(instance)
    if not instance.world then return false end
    return instance:save(instance.savegame_dir .. "quicksave.qs")
  end

  if app.savegame_dir then
    -- A missing quicksave is normal on first launch; recovery errors are ignored.
    native.recover_atomic(app.savegame_dir .. "quicksave.qs")
  end
end

function Platform:installLoadTelemetry()
  if self.load_installed then return end
  self.load_installed = true
  local app = self.app
  local native = self.native
  local method_name = type(app.load) == "function" and "load" or "quickLoad"
  local original_load = app[method_name]
  if type(original_load) ~= "function" then return end

  app[method_name] = function(instance, identity, ...)
    local resource = method_name == "load" and identity or "quicksave"
    local arguments = pack_values(...)
    local results
    native_checkpoint(native, "save_load", "load-begin", resource)
    local transaction_started = false
    local ok, result = xpcall(function()
      native_resource_event(native, "load-begin", resource, true)
      transaction_started = true
      results = pack_values(original_load(instance, identity,
                                          unpack_values(arguments)))
    end, traceback_message)
    if not ok then
      if transaction_started then
        native_resource_event(native, "load-end", resource, false)
      end
      native_checkpoint(native, "save_load", "load-failed", resource)
      error(result, 0)
    end
    native_resource_event(native, "load-end", resource, true)
    native_checkpoint(native, "save_load", "load-complete", resource)
    return unpack_values(results)
  end
end

--! CorsixTH's own toolbar stays visible.
--
-- The lower screen now shows the whole 640x480 frame at half size, so the
-- game's real toolbar and dialogs are what the player touches. An earlier
-- version hid the toolbar because a hand-drawn panel stood in for it; hiding it
-- now would remove the very thing the lower screen exists to show.
function Platform:showLegacyBottomPanel()
  local ui = self.app.ui
  if ui and ui.bottom_panel and ui.bottom_panel.visible == false then
    ui.bottom_panel.visible = true
  end
end

function Platform:inputContext()
  local app = self.app
  local ui = app.ui
  if not app.world then return "menu" end
  if ui and ui.focused_textbox then return "text_input" end

  local edit = ui and ui.edit_room
  if edit then
    if edit.phase == "walls" then return "build_room" end
    if edit.phase == "door" or edit.phase == "windows" or
       edit.phase == "objects" or edit.phase == "clear_area" then
      return "place_object"
    end
  end

  local window = top_window(ui)
  if window and window ~= ui and window ~= ui.menu_bar and
     window ~= ui.adviser and window ~= ui.subtitles then
    return "dialog"
  end
  return "world"
end

function Platform:dateParts(world)
  if not world or type(world.date) ~= "function" then return 1, 1, 1 end
  local date = safe_call(world, "date")
  if not date then return 1, 1, 1 end
  local day = safe_call(date, "dayOfMonth") or 1
  local month = safe_call(date, "monthOfYear") or 1
  local year = safe_call(date, "year") or safe_value(function() return date.year end, 1)
  return day, month, year
end

function Platform:syncBottomState()
  self:showLegacyBottomPanel()
  local app = self.app
  local world = app.world
  local ui = app.ui
  local hospital = ui and ui.hospital

  if not self.world_seen then
    self.world_seen = true
    self.last_world = world
    if world then
      self.first_level_checkpointed = true
      native_resource_event(self.native, "level", world_identity(world), true)
      native_checkpoint(self.native, "first_level", "ready", "initial-world")
    else
      self.menu_checkpointed = true
      native_resource_event(self.native, "menu", "main-menu", true)
      native_checkpoint(self.native, "menu", "ready", "main-menu")
    end
  elseif world ~= self.last_world then
    native_checkpoint(self.native, "transition", "world-changed",
                      world and "enter-world" or "leave-world")
    self.last_world = world
    if world and not self.first_level_checkpointed then
      self.first_level_checkpointed = true
      native_resource_event(self.native, "level", world_identity(world), true)
      native_checkpoint(self.native, "first_level", "ready", "first-world")
    elseif not world then
      if not self.menu_checkpointed then self.menu_checkpointed = true end
      native_resource_event(self.native, "menu", "main-menu", true)
      native_checkpoint(self.native, "menu", "ready", "main-menu")
    elseif world then
      native_resource_event(self.native, "level", world_identity(world), true)
    end
  end

  local day, month, year = self:dateParts(world)
  local bottom = ui and ui.bottom_panel
  local selected = ui and (ui.last_hovered_entity or ui.last_clicked_entity)

  local state = {
    cash = hospital and math.floor(hospital.balance or 0) or 0,
    reputation = hospital and math.floor(hospital.reputation or 0) or 0,
    day = day,
    month = month,
    year = year,
    patient_count = hospital and count_table(hospital.patients) or 0,
    staff_count = hospital and count_table(hospital.staff) or 0,
    queue_count = hospital and safe_value(function()
      if type(hospital.getTotalQueueSize) == "function" then
        return hospital:getTotalQueueSize()
      end
      return 0
    end, 0) or 0,
    message_count = bottom and
      (count_table(bottom.message_queue) + count_table(bottom.message_windows)) or 0,
    game_speed = world and math.floor(world.game_speed or 0) or 0,
    paused = world and world.game_speed == 0 or false,
    selected_name = entity_name(selected),
    selected_status = entity_status(selected),
    input_context = self:inputContext(),
  }

  -- Pushing an unchanged table still marks the lower screen dirty on the
  -- native side, so compare here first. syncBottomState runs on a timer.
  local previous = self.last_state
  if previous then
    local same = true
    for key, value in pairs(state) do
      if previous[key] ~= value then same = false break end
    end
    if same then return end
  end
  self.last_state = state
  self.native.set_state(state)
end

function Platform:dispatchKey(name)
  self.app:dispatch("keydown", name, {}, false)
  self.app:dispatch("keyup", name, {})
end

function Platform:moveCursor(dx, dy)
  local ui = self.app.ui
  if not ui then return end
  local step = 16
  local old_x, old_y = self.cursor_x, self.cursor_y
  self.cursor_x = clamp(self.cursor_x + dx * step, 0, 639)
  self.cursor_y = clamp(self.cursor_y + dy * step, 0, 479)
  ui.cursor_x, ui.cursor_y = self.cursor_x, self.cursor_y
  self.app:dispatch("motion", self.cursor_x, self.cursor_y,
                    self.cursor_x - old_x, self.cursor_y - old_y)
end

function Platform:click(button, double_click)
  local count = double_click and 2 or 1
  for _ = 1, count do
    self.app:dispatch("buttondown", button, self.cursor_x, self.cursor_y)
    self.app:dispatch("buttonup", button, self.cursor_x, self.cursor_y)
  end
end

function Platform:invokeBottom(method)
  local ui = self.app.ui
  local bottom = ui and ui.bottom_panel
  if bottom and type(bottom[method]) == "function" then
    return safe_call(bottom, method)
  end
end

function Platform:cycleSpeed()
  local world = self.app.world
  if not world then return end
  local current = tonumber(world.game_speed) or 0
  local next_speed = current == 0 and 1 or (current >= 3 and 1 or current + 1)
  safe_call(world, "setSpeed", next_speed)
end

--! Zoom is deliberately disabled on Old 3DS.
--
-- CorsixTH applies a non-integer zoom by giving every sprite a fractional
-- destination rectangle. With the software renderer that turns each blit into
-- a scaled blit, which an Old 3DS cannot afford. Keeping the factor pinned at
-- 1.0 also keeps direct_zoom on the fast path where no intermediate
-- full-screen render target is allocated per frame.
function Platform:adjustZoom(_)
  native_notice(self.native, "ZOOM LOCKED ON 3DS", false)
end

function Platform:placeRoomRectangle(action)
  local ui = self.app.ui
  local edit = ui and ui.edit_room
  if not edit or edit.phase ~= "walls" or type(edit.setBlueprintRect) ~= "function" then
    return
  end
  local width = math.max(1, tonumber(action.rect_w) or 1)
  local height = math.max(1, tonumber(action.rect_h) or 1)
  local cursor_x = tonumber(edit.mouse_cell_x) or 1
  local cursor_y = tonumber(edit.mouse_cell_y) or 1
  -- The lower grid is 19x8. Its centre follows the current world cursor.
  local x = cursor_x + (tonumber(action.rect_x) or 0) - 9
  local y = cursor_y + (tonumber(action.rect_y) or 0) - 3
  safe_call(edit, "setBlueprintRect", x, y, width, height)
end

function Platform:handleAction(action)
  local kind = action.type
  local ui = self.app.ui
  local world = self.app.world
  local context = self:inputContext()

  if kind == "pan_camera" then
    if ui and type(ui.scrollMap) == "function" then
      safe_call(ui, "scrollMap", -(action.dx or 0), -(action.dy or 0))
    end
  elseif kind == "cursor_step" then
    local dx, dy = action.dx or 0, action.dy or 0
    if context == "dialog" or context == "menu" or context == "text_input" then
      if math.abs(dx) > math.abs(dy) then
        self:dispatchKey(dx < 0 and "Left" or "Right")
      elseif dy ~= 0 then
        self:dispatchKey(dy < 0 and "Up" or "Down")
      end
    else
      self:moveCursor(dx, dy)
    end
  elseif kind == "confirm" then
    if context == "dialog" or context == "menu" or context == "text_input" then
      self:dispatchKey("Return")
    else
      self:click(1, false)
    end
  elseif kind == "cancel" or kind == "close_top_window" then
    self:dispatchKey("Escape")
  elseif kind == "open_quick_menu" then
    if ui and type(ui.showMenuBar) == "function" then safe_call(ui, "showMenuBar") end
  elseif kind == "rotate_object" then
    self:click(3, false)
  elseif kind == "toggle_walls" then
    if ui and type(ui.toggleTransparent) == "function" then safe_call(ui, "toggleTransparent") end
  elseif kind == "show_details" then
    self:click(1, true)
  elseif kind == "zoom_in" then
    self:adjustZoom(1.125)
  elseif kind == "zoom_out" then
    self:adjustZoom(1 / 1.125)
  elseif kind == "pause_toggle" then
    if world then safe_call(world, "pauseOrUnpause") end
  elseif kind == "speed_cycle" then
    self:cycleSpeed()
  elseif kind == "overview" or kind == "open_town_map" then
    self:invokeBottom("dialogTownMap")
  elseif kind == "open_build" then
    self:invokeBottom("dialogBuildRoom")
  elseif kind == "open_staff" then
    self:invokeBottom("dialogStaffManagement")
  elseif kind == "open_patients" then
    self:invokeBottom("dialogStatus")
  elseif kind == "open_finance" or kind == "open_bank" then
    self:invokeBottom("dialogBankManager")
  elseif kind == "open_messages" then
    self:invokeBottom("openFirstMessage")
  elseif kind == "open_casebook" then
    self:invokeBottom("dialogDrugCasebook")
  elseif kind == "open_research" then
    self:invokeBottom("dialogResearch")
  elseif kind == "open_policy" then
    self:invokeBottom("dialogPolicy")
  elseif kind == "open_charts" then
    self:invokeBottom("dialogCharts")
  elseif kind == "hire_staff" then
    self:invokeBottom("dialogHireStaff")
  elseif kind == "furnish_corridor" then
    self:invokeBottom("dialogFurnishCorridor")
  elseif kind == "edit_room" then
    self:invokeBottom("editRoom")
  elseif kind == "quick_save" then
    if world then safe_call(self.app, "quickSave") end
  elseif kind == "quick_load" then
    if world then safe_call(self.app, "quickLoad") end
  elseif kind == "build_room_rectangle" then
    self:placeRoomRectangle(action)
  elseif kind == "place_item" then
    self:click(1, false)
  elseif kind == "previous_category" then
    self:dispatchKey("Left")
  elseif kind == "next_category" then
    self:dispatchKey("Right")
  elseif kind == "lifecycle_suspend" then
    if world and world.game_speed ~= 0 then
      self.saved_speed = world.game_speed
      safe_call(world, "setSpeed", 0)
    end
  elseif kind == "lifecycle_resume" then
    if world and self.saved_speed then
      safe_call(world, "setSpeed", self.saved_speed)
      self.saved_speed = nil
    end
  elseif kind == "lifecycle_exit" then
    -- The native layer queues SDL_QUIT after the atomic quicksave request.
  end

  -- The player just acted, so bypass the change filter for this one sync.
  self.last_state = nil
  self:syncBottomState()
  self.native.request_redraw()
end

local module = {}

function module.attach(app, native)
  local platform = Platform.new(app, native)
  app._3ds = platform
  platform:syncBottomState()
  return platform
end

return module
