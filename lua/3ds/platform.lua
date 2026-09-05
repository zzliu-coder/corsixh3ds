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
  assert(native and type(native.resource_event) == "function", "mandatory resource_event missing")
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
  for index = 1, #ui.windows do
    local window = ui.windows[index]
    if window and window.visible ~= false and window ~= ui.bottom_panel and
       window ~= ui.menu_bar and window ~= ui.adviser and window ~= ui.subtitles then
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

function Platform.new(app, native, capabilities)
  local self = setmetatable({
    app = app,
    native = native,
    capabilities = capabilities,
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

function Platform:resourceEvent(event, identity, success)
  if self.capabilities.resource_events == false then return end
  native_resource_event(self.native, event, identity, success)
end

function Platform:showError(message)
  message = tostring(message)
  native_notice(self.native, message, true)
  local ui = self.app.ui
  if ui and UIInformation then ui:addWindow(UIInformation(ui, {message})) end
  print("CorsixTH 3DS: " .. message)
end

function Platform:installAtomicSaves()
  local app, native = self.app, self.native
  local original_save = assert(app.save, "App.save missing")
  app.save = function(instance, filename)
    assert(type(filename) == "string" and filename ~= "", "invalid save path")
    local temporary = filename .. ".tmp"
    native_checkpoint(native, "save_load", "save-begin", filename)
    local critical, transaction = false, false
    local ok, err = xpcall(function()
      self:resourceEvent("save-begin", filename, true); transaction = true
      native.begin_critical_io(); critical = true
      assert(original_save(instance, temporary) == true, "save writer did not confirm success")
      local committed, detail = native.atomic_commit(temporary, filename, true)
      assert(committed == true, "save commit: " .. tostring(detail))
    end, traceback_message)
    if critical then native.end_critical_io() end
    if transaction then self:resourceEvent("save-end", filename, ok) end
    if not ok then
      self:showError("SAVE FAILED: " .. tostring(err))
      native_checkpoint(native, "save_load", "save-failed", filename)
      error(err, 0)
    end
    native_notice(native, "SAVE OK", false)
    native_checkpoint(native, "save_load", "save-complete", filename)
    return true
  end
  app.quickSave = function(instance)
    if not instance.world then return false, "no world" end
    return instance:save(instance.savegame_dir .. "quicksave.qs")
  end
end

function Platform:installLoadTelemetry()
  local app, native = self.app, self.native
  local original_load = assert(app.load, "App.load missing")
  app.load = function(instance, filename)
    local recovery = instance.savegame_dir .. "recovery-before-load.sav"
    if instance.world then
      local saved, result = pcall(instance.save, instance, recovery)
      if not saved or result ~= true then return false, "preload recovery save failed: " .. tostring(result) end
    end
    native_checkpoint(native, "save_load", "load-begin", filename)
    local transaction = false
    local ok, accepted, detail = xpcall(function()
      self:resourceEvent("load-begin", filename, true); transaction = true
      return original_load(instance, filename)
    end, traceback_message)
    local success = ok and accepted == true
    if transaction then self:resourceEvent("load-end", filename, success) end
    if not success then
      local message = tostring(ok and (detail or "load rejected") or accepted)
      self:showError("LOAD FAILED: " .. message)
      native_checkpoint(native, "save_load", "load-failed", filename)
      return false, message
    end
    native_checkpoint(native, "save_load", "load-complete", filename)
    native_notice(native, "LOAD COMPLETE", false)
    return true
  end
  app.quickLoad = function(instance)
    return instance:load(instance.savegame_dir .. "quicksave.qs")
  end
end

function Platform:saveAndExit()
  if self.app.world then
    local ok, result = pcall(self.app.save, self.app, self.app.savegame_dir .. "save-and-exit.sav")
    if not ok or result ~= true then return false, result end
  end
  self.app:exit()
  return true
end

-- Shared bridge contract for the subsequent InputMapper integration.
function Platform:inputState()
  local ui = assert(self.app.ui, "input UI unavailable")
  assert(type(ui.cursor_x) == "number" and type(ui.cursor_y) == "number",
         "input UI cursor unavailable")
  return {cursor_x = ui.cursor_x, cursor_y = ui.cursor_y,
          input_context = self:inputContext()}
end

-- Logical pixels only. The native bridge converts bottom pixels exactly once.
function Platform:handlePointer(event)
  local ok, err = pcall(function()
    local state = self:inputState()
    local kind = event.kind
    assert(kind == "motion" or kind == "down" or kind == "up" or kind == "click",
           "invalid pointer kind")
    local x = clamp(event.x or state.cursor_x, 0, 639)
    local y = clamp(event.y or state.cursor_y, 0, 479)
    local ui = self.app.ui
    assert(type(ui.setMouseReleased) == "function", "UI mouse capture unavailable")
    ui:setMouseReleased(false)
    self.app:dispatch("motion", x, y, x - state.cursor_x, y - state.cursor_y)
    local button = event.button or 1
    assert(button == 1 or button == 3, "invalid pointer button")
    if kind == "down" then
      self.app:dispatch("buttondown", button, x, y)
    elseif kind == "up" then
      self.app:dispatch("buttonup", button, x, y)
    elseif kind == "click" then
      local clicks = event.clicks or 1
      assert(clicks == 1 or clicks == 2, "invalid click count")
      for _ = 1, clicks do
        -- A first click can replace App.ui; use its current visible point.
        local current = self:inputState()
        self.app:dispatch("buttondown", button, current.cursor_x, current.cursor_y)
        current = self:inputState()
        self.app:dispatch("buttonup", button, current.cursor_x, current.cursor_y)
      end
    end
    self.native.request_redraw()
  end)
  if not ok then return false, tostring(err) end
  return true
end

-- Lifecycle cancellation must not call onMouseUp: upstream uses release to
-- activate buttons/entities. Clear only UI input ownership, including children.
function Platform:showLegacyBottomPanel()
  local ui = self.app.ui
  if ui and ui.bottom_panel and ui.bottom_panel.visible == false then
    ui.bottom_panel.visible = true
  end
end

function Platform:inputContext()
  local app, ui = self.app, self.app.ui
  if not ui then error("input UI unavailable") end
  local window = top_window(ui)
  local function focused(owner)
    for _, box in ipairs(owner and owner.textboxes or {}) do
      if box.enabled and box.active then return true end
    end
    return false
  end
  if focused(ui) or focused(window) then return "text_input" end
  -- Window order is front-to-back. A dialog above a blueprint wins.
  if window then
    local phase = window.phase
    if phase == "walls" then return "build_room" end
    if phase == "door" or phase == "windows" or phase == "objects" or
       phase == "clear_area" then return "place_object" end
    local types, place = rawget(_G, "class"), rawget(_G, "UIPlaceObjects")
    if types and place and types.is(window, place) then return "place_object" end
    if app.world then return "dialog" end
  end
  if not app.world then return "menu" end
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
      self:resourceEvent( "level", world_identity(world), true)
      native_checkpoint(self.native, "first_level", "ready", "initial-world")
    else
      self.menu_checkpointed = true
      self:resourceEvent( "menu", "main-menu", true)
      native_checkpoint(self.native, "menu", "ready", "main-menu")
    end
  elseif world ~= self.last_world then
    native_checkpoint(self.native, "transition", "world-changed",
                      world and "enter-world" or "leave-world")
    self.last_world = world
    if world and not self.first_level_checkpointed then
      self.first_level_checkpointed = true
      self:resourceEvent( "level", world_identity(world), true)
      native_checkpoint(self.native, "first_level", "ready", "first-world")
    elseif not world then
      if not self.menu_checkpointed then self.menu_checkpointed = true end
      self:resourceEvent( "menu", "main-menu", true)
      native_checkpoint(self.native, "menu", "ready", "main-menu")
    elseif world then
      self:resourceEvent( "level", world_identity(world), true)
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

function Platform:cancelPointer()
  local ui = assert(self.app.ui, "input UI unavailable")
  local function clear(window)
    local button = window.active_button
    if button then
      button.panel_for_sprite.sprite_index = button.sprite_index_normal
      button.panel_for_sprite.lowered = button.panel_lowered_normal
      button.active = false
    end
    window.active_button = false
    window.btn_repeat_delay = nil
    local bar = window.active_scrollbar
    if bar then bar.active, bar.down_x, bar.down_y = false, nil, nil end
    window.active_scrollbar = nil
    window.dragging = false
    if window.mouse_down_x ~= nil then window.mouse_down_x = false end
    if window.mouse_down_y ~= nil then window.mouse_down_y = false end
    if window.move_rect_x ~= nil then window.move_rect_x = false end
    if window.move_rect_y ~= nil then window.move_rect_y = false end
    for _, child in ipairs(window.windows or {}) do clear(child) end
  end
  clear(ui)
  ui.drag_mouse_move = nil
  ui.down_count = 0
  ui.buttons_down.mouse_left = nil
  ui.buttons_down.mouse_right = nil
  ui.buttons_down.mouse_middle = nil
  ui.tick_scroll_amount_mouse = false
  if ui.cursor == ui.down_cursor then ui:setCursor(ui.default_cursor) end
  self.native.request_redraw()
  return true
end

function Platform:moveCursor(dx, dy)
  local state = self:inputState()
  return self:handlePointer{kind = "motion",
    x = state.cursor_x + dx * 16, y = state.cursor_y + dy * 16}
end

function Platform:click(button, double_click)
  return self:handlePointer{kind = "click", button = button,
    clicks = double_click and 2 or 1}
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

  if kind == "pointer_move" or kind == "pointer_down" then
    return self:handlePointer{kind = kind == "pointer_move" and "motion" or "down",
      x = clamp(assert(action.x), 0, 319) * 2,
      y = clamp(assert(action.y), 0, 239) * 2}
  elseif kind == "pointer_up" then
    if action.value == 1 then return self:cancelPointer() end
    return self:handlePointer{kind = "up"}
  elseif kind == "pan_camera" then
    if ui and type(ui.scrollMap) == "function" then
      safe_call(ui, "scrollMap", -(action.dx or 0), -(action.dy or 0))
    end
  elseif kind == "cursor_step" then
    local ok, err = self:moveCursor(action.dx or 0, action.dy or 0)
    if not ok then return false, err end
  elseif kind == "confirm" then
    local ok, err = self:click(1, false)
    if not ok then return false, err end
  elseif kind == "cancel" or kind == "close_top_window" then
    if kind == "close_top_window" or context == "dialog" or
       context == "menu" or context == "text_input" then
      self:dispatchKey("Escape")
    else
      local ok, err = self:click(3, false)
      if not ok then return false, err end
    end
  elseif kind == "open_quick_menu" then
    if ui and type(ui.showMenuBar) == "function" then safe_call(ui, "showMenuBar") end
  elseif kind == "rotate_object" then
    local ok, err = self:click(3, false)
    if not ok then return false, err end
  elseif kind == "toggle_walls" then
    if ui and type(ui.toggleTransparent) == "function" then safe_call(ui, "toggleTransparent") end
  elseif kind == "show_details" then
    local ok, err = self:click(1, true)
    if not ok then return false, err end
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
    if world then return self.app:quickSave() end
  elseif kind == "quick_load" then
    if world then return self.app:quickLoad() end
  elseif kind == "build_room_rectangle" then
    self:placeRoomRectangle(action)
  elseif kind == "place_item" then
    local ok, err = self:click(1, false)
    if not ok then return false, err end
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

  self.native.request_redraw()
  return true
end

-- CORSIXTH_3DS_BEGIN: U3-checked-operation-spans
function Platform:installOperationSpans()
  if self.operation_spans_installed then return end
  local app, native = self.app, self.native
  -- Wrap after U1 installs checked save/load including commit and recovery.
  for _, spec in ipairs({{"save", "save", "save"}, {"load", "load", "reload"}}) do
    local method, stage, site = spec[1], spec[2], spec[3]
    local original = assert(app[method], "missing checked operation " .. method)
    app[method] = function(...)
      local token = native.span_begin(stage)
      native.observe_memory(site, "before", method, "Operation")
      local function baseline(phase)
        local gc_token=native.span_begin("gc")
        collectgarbage("collect")
        native.observe_memory(site,phase,method,"Operation")
        native.span_end(gc_token,true)
      end
      baseline("gc-before")
      local result = pack_values(pcall(original, ...))
      local success = result[1] and result[2] == true
      native.observe_memory(site, success and "committed" or "failed", method, "Operation")
      baseline("gc-after")
      native.span_end(token, success)
      native.flush_observations()
      if not result[1] then error(result[2], 0) end
      return (table.unpack or unpack)(result, 2, result.n)
    end
  end
  self.operation_spans_installed = true
end
-- CORSIXTH_3DS_END: U3-checked-operation-spans

local module = {}

function module.attach(app, native, capabilities)
  assert(type(capabilities)=="table" and type(capabilities.resource_events)=="boolean" and capabilities.epoch, "native capabilities missing")
  if app._3ds then
    local existing=app._3ds
    assert(existing.completed and existing.native==native and existing.capabilities.epoch==capabilities.epoch, "adapter identity/epoch mismatch")
    return existing
  end
  for _,name in ipairs({"span_begin","span_end","observe_memory","flush_observations","atomic_commit","begin_critical_io","end_critical_io","set_notice","checkpoint","request_redraw"}) do
    assert(type(native[name])=="function", "mandatory native API missing: "..name)
  end
  if capabilities.resource_events then assert(type(native.resource_event)=="function", "resource_event missing") end
  local names={"save","load","quickSave","quickLoad"}
  local original={}
  for _,name in ipairs(names) do original[name]=rawget(app,name) end
  local ok, platform=xpcall(function()
    local result=Platform.new(app,native,capabilities)
    result:showLegacyBottomPanel()
    result:resourceEvent("menu","main-menu",true)
    result:installOperationSpans()
    result.completed=true
    return result
  end,traceback_message)
  if not ok then
    for _,name in ipairs(names) do rawset(app,name,original[name]) end
    error(platform,0)
  end
  app._3ds=platform
  return platform
end

return module
