-- CorsixTH 0.70.1 platform adapter for Nintendo 3DS.
-- Loaded only by the CORSIXTH_3DS integration patch.

local Platform = {}
Platform.__index = Platform
local Operations = require("3ds.operations")
-- The five ordinary entries in CorsixTH 0.70.1's Options / Game speed menu.
-- World:setSpeed owns their timing; this list contains no platform rates.
local game_speeds = {"Slowest", "Slower", "Normal", "Max speed", "And then some more"}

-- These pinned toolbar handlers take an explicit enable argument. The other
-- handlers (build/hire/furnish/edit/message) implement their own toggles.
local bottom_dialog_types = {
  dialogTownMap="UITownMap", dialogStaffManagement="UIStaffManagement",
  dialogStatus="UIProgressReport", dialogBankManager="UIBankManager",
  dialogDrugCasebook="UICasebook", dialogResearch="UIResearch",
  dialogPolicy="UIPolicy", dialogCharts="UIGraphs",
}

local function clamp(value, low, high)
  if value < low then return low end
  if value > high then return high end
  return value
end

local function finite(value)
  return type(value) == "number" and value == value and
    value > -math.huge and value < math.huge
end

local function pixel(value, maximum)
  assert(finite(value), "pointer coordinate must be finite")
  return math.floor(clamp(value, 0, maximum))
end

local function count_table(value)
  if type(value) ~= "table" then return 0 end
  local count = 0
  for _ in pairs(value) do count = count + 1 end
  return count
end

-- Optional legacy-panel observations only. Game actions use the protected
-- native boundary and must never discard a callback's exception here.
local function observed_call(target, method, ...)
  if target and type(target[method]) == "function" then
    local ok, result = pcall(target[method], target, ...)
    if ok then return result end
    print("CorsixTH 3DS: " .. method .. " failed: " .. tostring(result))
  end
end

local function required_method(target, method)
  local callback = target and target[method]
  if type(callback) ~= "function" then
    error("required action method missing: " .. method, 2)
  end
  return callback
end

local function safe_value(callback, fallback)
  local ok, result = pcall(callback)
  if ok and result ~= nil then return result end
  return fallback
end

local function traceback_message(message)
  if type(message)=="string" and debug and type(debug.traceback) == "function" then
    return debug.traceback(message, 2)
  end
  return message
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

-- R54: the input window owns focus and joystick context, independently of
-- whether a HUD has clickable controls. This does not remove windows from the
-- upstream hit-test/event list and does not change World pause semantics.
local function input_focused(owner)
  for _, box in ipairs(owner and owner.textboxes or {}) do
    if box.enabled and box.active and box.visible ~= false then return true end
  end
  return false
end

local function input_hud(ui, window)
  -- Even a normally passive window becomes an input owner for text entry.
  if input_focused(window) then return false end
  if window == ui.bottom_panel or window == ui.adviser or window == ui.subtitles then
    return true
  end
  -- UIWatch is the pinned engine's shared opening/emergency/epidemic HUD.
  -- Its modal_class groups windows; its own buttons still receive pen events.
  -- Unknown windows, modified modal behaviour, and missing class information
  -- remain blocking. Never infer pass-through from a string or size alone.
  local types, watch = rawget(_G, "class"), rawget(_G, "UIWatch")
  return type(types) == "table" and type(types.is) == "function" and watch and
    types.is(window, watch) and window.modal_class == "open_countdown" and
    window.esc_closes == false or false
end

local function top_window(ui)
  if not ui or type(ui.windows) ~= "table" then return nil end
  for index = 1, #ui.windows do
    local window = ui.windows[index]
    if window and window.visible ~= false and not input_hud(ui, window) then
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
    last_state = nil,
    world_seen = false,
    last_world = nil,
    menu_checkpointed = false,
    first_level_checkpointed = false,
    cursor_remainder_x = 0,
    cursor_remainder_y = 0,
    -- Observers must not retain a previous UI/world across a level load.
    pointer_owners = setmetatable({}, {__mode = "v"}),
    focus_owners = setmetatable({}, {__mode = "v"}),
  }, Platform)
  self.bindings=self:prepareOperations()
  self.bindings.errorHandler=self:prepareErrorTelemetry()
  return self
end

function Platform:resourceEvent(event, identity, success)
  if self.capabilities.resource_events == false then return end
  native_resource_event(self.native, event, identity, success)
end

function Platform:showError(message)
  message = tostring(message)
  local function attempt(site,callback,...)
    if not callback then return false end
    if self.operations and self.operations.current then
      return self.operations:diagnostic(self.operations.current,site,callback,...)
    end
    return pcall(callback,...)
  end
  attempt("diagnostic_line",self.native.diagnostic_line,message)
  local summary=message:match("^[^\n]+") or message
  if message:match("^SAVE FAILED:") and message:find("not enough memory",1,true) then
    summary="SAVE FAILED: Not enough memory. Previous save kept."
  elseif #summary>150 then summary=summary:sub(1,147).."..." end
  local noticed=attempt("notice",self.native.set_notice,summary,true)
  local ui = self.app.ui
  local shown=false
  if ui and UIInformation then
    shown=attempt("error_ui",function()ui:addWindow(UIInformation(ui,{summary}))end)
  end
  attempt("print",print,"CorsixTH 3DS: " .. message)
  return noticed or shown
end

-- Optional naming; save slots remain usable when the system applet is absent.
function Platform:editText()
  local ui = self.app.ui
  local selected
  for _, box in ipairs(ui.textboxes or {}) do
    if box.enabled and box.visible and box.active and type(box.text) == "string" then selected = box; break end
  end
  if not selected then return true, "noop:no-text-focus" end
  if type(self.native.text_keyboard) ~= "function" then
    native_notice(self.native, "KEYBOARD UNAVAILABLE - USE SAVE SLOTS", false); return true, "unsupported:keyboard"
  end
  local limit = math.min(selected.char_limit or 40, 40)
  local ok, text = self.native.text_keyboard(selected.text, limit)
  if not ok then return true, "noop:keyboard-cancelled" end
  if self.app.ui ~= ui or not selected.active or not selected.visible then return true, "noop:text-owner-changed" end
  local registered = false
  for _, box in ipairs(ui.textboxes or {}) do if box == selected then registered = true end end
  if not registered then return true, "noop:text-owner-changed" end
  -- English input until the measured Chinese font/input work is enabled.
  if type(text) ~= "string" or #text > limit or text:find("[^A-Za-z0-9 _%-]") or not text:find("%S") then
    native_notice(self.native, "USE ENGLISH LETTERS NUMBERS SPACE - _", false); return true, "noop:text-rejected"
  end
  selected:setText(text)
  selected:setActive(true) -- refresh byte cursor after replacement
  -- Confirm only updates the field callback; saves still use overwrite checks.
  selected:confirm()
  return self:finishAction()
end

function Platform:prepareOperations()
  local app=self.app
  local operations=Operations.new(self,app.save,app.load)
  self.operations=operations
  local bindings={}
  bindings.save=function(instance,filename)return operations:save(instance,filename)end
  bindings.load=function(instance,filename)return operations:load(instance,filename)end
  bindings.quickSave = function(instance)
    operations:guard()
    if not instance.world then return false, "no world" end
    return instance:save(instance.savegame_dir .. (self.save_prefix or "") .. "quicksave.qs")
  end
  bindings.quickLoad = function(instance)
    operations:guard()
    return instance:load(instance.savegame_dir .. (self.save_prefix or "") .. "quicksave.qs")
  end
  return bindings
end

function Platform:afterLoadOperation(instance, filename, result)
    local native=self.native
    -- The installer creates this separate, hash-verified Slot1 copy. Ordinary
    -- saves are never migrated automatically, and original bytes stay intact.
    if filename=="sdmc:/3ds/corsixth/Saves/R62-Recovered.sav" or
       filename=="sdmc:/3ds/corsixth/Benchmark/r62-recovery.sav" or
       (self.native.runner_context and self.native.runner_context() and
        filename==self.native.runner_context().root.."r62-recovery.sav") then
      self.save_prefix="R63-Recovered-"
      self.recovery_cohort=nil
      local repaired,count=xpcall(function()
        local cohort=require("3ds.recovery_activity").capture(instance.world)
        local count=require("3ds.state_health").repairR62(instance.world)
        self.recovery_cohort=cohort -- scalar identities only; original bytes untouched
        return count
      end,function(value)
        if type(value)=="string" and debug and type(debug.traceback)=="function" then
          return debug.traceback(value,2)
        end
        return value
      end)
      if not repaired then
        self.recovery_cohort=nil
        if instance.world then
          self.operations:mandatory(result,"recovery_pause",instance.world.setSpeed,instance.world,"Pause")
        end
        -- Audit observes the refused copy only. It cannot relax recovery or
        -- replace its original error, even if diagnostic output itself fails.
        self.operations:diagnostic(result,"recovery_audit",function()
          require("3ds.state_health").auditR62(instance.world,self.native.diagnostic_line or print)
        end)
        return false,count
      end
      self.operations:diagnostic(result,"recovery_checkpoint",native.checkpoint,"save_load","r62-recovered",filename,count,0)
      self.recovery_count=count
    else
      self.recovery_cohort=nil
      local basename=filename:match("([^/]+)$") or ""
      self.save_prefix=basename:match("^R63%-Recovered%-") and "R63-Recovered-" or nil
    end
    return true
end

function Platform:prepareErrorTelemetry()
  local original=self.app.errorHandler
  self.simulation_errors=0
  if type(original)~="function" then return end
  self.error_diagnostics=0
  local function observe(callback,...)
    if not pcall(callback,...) then self.error_diagnostics=math.min(65535,self.error_diagnostics+1) end
  end
  local function describe(value)
    if type(value)=="string" then return value:sub(1,1024) end
    return "<"..type(value)..">"
  end
  return function(app,...)
    local event,detail=...
    self.simulation_errors=self.simulation_errors+1
    self.staff_sampler=nil
    -- The engine's existing protected boundary owns the original exception.
    -- Observe a failed entity without wrapping every successful entity update.
    observe(function()
      local activity=package.loaded["3ds.recovery_activity"]
      if activity and activity.active and app.world and app.world.current_tick_entity then
        activity.after(app.world.current_tick_entity,false)
      end
    end)
    observe(function()
      print("engine-error: sequence="..self.simulation_errors.." event="..describe(event)
        .." detail="..describe(detail))
    end)
    observe(function()self.native.checkpoint("simulation","error",describe(event))end)
    return original(app,...)
  end
end

function Platform:saveAndExit()
  self.operations:guard()
  if self.app.world then
    local ok, result = pcall(self.app.save, self.app,
      self.app.savegame_dir .. (self.save_prefix or "") .. "save-and-exit.sav")
    if not ok or result ~= true then return false, result end
  end
  self.app:exit()
  return true
end

-- Shared bridge contract for the subsequent InputMapper integration.
function Platform:inputState()
  self.operations:guard()
  local ui = assert(self.app.ui, "input UI unavailable")
  assert(finite(ui.cursor_x) and finite(ui.cursor_y),
         "input UI cursor unavailable")
  local context, window = self:inputContext(), top_window(ui)
  local owners = self.pointer_owners
  if owners.ui ~= ui or owners.window ~= window or owners.world ~= self.app.world or
     self.pointer_context ~= context then
    self:resetCursorResidual()
    owners.ui, owners.window, owners.world = ui, window, self.app.world
    self.pointer_context = context
    self.input_epoch = (self.input_epoch or 0) + 1
    native_checkpoint(self.native, "input_policy", "transition",
      context .. ":" .. tostring(window and window.modal_class or "world"))
  end
  -- Recompute the actual UI/owner on every call. Only the transport table is
  -- reused, never a context cached across callbacks which can open a window.
  local state = self.input_snapshot
  if not state then state = {}; self.input_snapshot = state end
  state.cursor_x, state.cursor_y = ui.cursor_x, ui.cursor_y
  state.input_context, state.input_epoch = context, self.input_epoch or 0
  return state
end

function Platform:resetCursorResidual()
  self.cursor_remainder_x, self.cursor_remainder_y = 0, 0
end

-- Called before a new HID sample, never between touch-down and touch-up.
-- Keep existing geometry and pen coordinates. A new dialog may move the
-- viewing rectangle, never the authoritative mouse position.
function Platform:prepareInput()
  self.operations:guard()
  self:syncScene()
  local state = self:inputState()
  local ui, owners = self.app.ui, self.focus_owners
  local window = top_window(ui)
  if owners.ui == ui and owners.window == window then return true end
  self:resetCursorResidual()
  if (ui.down_count or 0) ~= 0 then return true end
  owners.ui, owners.window = ui, window
  if self.native.window_identity then
    local types = rawget(_G, "class")
    self.native.window_identity(window and types and types.type and types.type(window) or
      (self.app.world and "world" or "menu"))
  end
  if not window or state.input_context == "build_room" or
     state.input_context == "place_object" then return true end
  local x, y = state.cursor_x, state.cursor_y
  local s = window.apply_ui_scale and (self.app.config.ui_scale or 1) or 1
  if window == ui.menu_bar then
    local first = window.menus and window.menus[1]
    x = first and ((first.x or 0) + (first.width or 32) / 2) * s or 16
    y = 8 * s
  elseif finite(window.x) and finite(window.y) and finite(window.width) and
         finite(window.height) then
    local left, top = window.x * s, window.y * s
    local width, height = window.width * s, window.height * s
    if x < left or x >= left + width or y < top or y >= top + height then
      x, y = left + width / 2, top + math.min(height / 2, 40)
    end
  end
  if type(self.native.focus_view) == "function" then
    -- Odd-sized dialogs have half-pixel centres; native view coordinates are
    -- integers. Focusing the view must leave the authoritative pen untouched.
    self.native.focus_view(pixel(x,639), pixel(y,479))
  end
  return true
end

function Platform:closeMenuBar()
  local ui = self.app.ui
  local menu = ui and ui.menu_bar
  if not menu or not menu.visible then return false end
  -- Upstream's delayed menu closure saves changed checkbox/volume options.
  -- Preserve that side effect when B/leaf selection closes it immediately.
  if type(self.app.saveConfig) == "function" then self.app:saveConfig() end
  -- Match the actual UIMenuBar:onTick terminal hide state immediately.
  menu.open_menus, menu.active_menu = {}, false
  menu.visible, menu.disappear_counter, menu.menu_disappear_counter = false, nil, nil
  if menu.on_top then ui:sendToBottom(menu); menu.on_top = false end
  self:resetCursorResidual()
  self.native.request_redraw()
  return true
end

-- Logical pixels only. The native bridge converts bottom pixels exactly once.
function Platform:handlePointer(event)
    local state = self:inputState()
    local kind = event.kind
    assert(kind == "motion" or kind == "down" or kind == "up" or kind == "click",
           "invalid pointer kind")
    local x = pixel(event.x or state.cursor_x, 639)
    local y = pixel(event.y or state.cursor_y, 479)
    if not event.relative then self:resetCursorResidual() end
    local ui = self.app.ui
    local menu = ui.menu_bar
    local menu_was_active = menu and menu.active_menu
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
    if menu_was_active and ui == self.app.ui and not menu.active_menu and
       menu.disappear_counter ~= nil and self:closeMenuBar() then return true, "applied" end
    return self:finishAction()
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
  if input_focused(ui) or input_focused(window) then return "text_input" end
  if window and window == ui.menu_bar then return "menu" end
  -- Window order is front-to-back. A dialog above a blueprint wins.
  if window then
    local phase = window.phase
    if phase == "walls" then return "build_room" end
    if phase == "door" or phase == "windows" or phase == "objects" or
       phase == "clear_area" then return "place_object" end
    local types, place = rawget(_G, "class"), rawget(_G, "UIPlaceObjects")
    if type(types) == "table" and type(types.is) == "function" and place and types.is(window, place) then return "place_object" end
    if app.world then return "dialog" end
  end
  if not app.world then return "menu" end
  return "world"
end

function Platform:dateParts(world)
  if not world or type(world.date) ~= "function" then return 1, 1, 1 end
  local date = observed_call(world, "date")
  if not date then return 1, 1, 1 end
  local day = observed_call(date, "dayOfMonth") or 1
  local month = observed_call(date, "monthOfYear") or 1
  local year = observed_call(date, "year") or safe_value(function() return date.year end, 1)
  return day, month, year
end

-- A ten-second diagnostic sample, separate from the per-input lightweight
-- context. No resource loading, simulation mutation or cached UI collection.
function Platform:syncScene()
  local world=self.app.world
  self.scene_owner=self.scene_owner or setmetatable({}, {__mode="v"})
  if self.scene_synced and self.scene_owner.world==world then return end
  if type(self.native.scene)=="function" then
    self.native.scene(world and ("level:"..tostring(world.map and world.map.level_number or "unknown")) or "menu")
  end
  self.scene_owner.world=world;self.scene_synced=true
end
function Platform:benchmarkTick()
  self.operations:guard()
  if self.benchmark then self.benchmark:tick() end
  self.operations:guard()
  return true
end
function Platform:benchmarkCancel()
  if self.benchmark then self.benchmark:cancel("user-or-lifecycle") end
  return true
end
function Platform:samplePerformanceContext()
  self:syncScene()
  if type(self.native.workload) ~= "function" then return true end
  local app, ui = self.app, self.app.ui
  local hospital, world = ui and ui.hospital, app.world
  local date = world and world.game_date
  local date_text = date and type(date.tostring) == "function" and date:tostring() or "unknown"
  local rooms = 0
  for _, room in pairs(world and world.rooms or {}) do
    if room.hospital == hospital then rooms = rooms + 1 end
  end
  self.native.workload{
    patients = hospital and count_table(hospital.patients) or 0,
    staff = hospital and count_table(hospital.staff) or 0,
    rooms = rooms,
    speed = world and type(world.getCurrentSpeed) == "function" and world:getCurrentSpeed() or "unknown",
    hours_per_tick = world and world.hours_per_tick or -1,
    tick_rate = world and world.tick_rate or -1, game_date = date_text,
    camera_x = ui and ui.screen_offset_x or 0, camera_y = ui and ui.screen_offset_y or 0,
    language = app.config.language or "unknown", music = app.config.play_music == true,
    voice = app.config.speech_language or "en",
  }
  return true
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
  self:resetCursorResidual()
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
  return self:finishAction()
end

function Platform:moveCursor(dx, dy, precise)
  local state = self:inputState()
  assert(finite(dx) and finite(dy), "cursor delta must be finite")
  if precise then self:resetCursorResidual() end
  local function advance(position, delta, remainder, maximum)
    local movement = delta * 16 + remainder
    if not finite(movement) then return nil end
    local whole = movement < 0 and math.ceil(movement) or math.floor(movement)
    local next_position = clamp(position + whole, 0, maximum)
    -- Discard outward movement at an edge; no delayed jump when reversing.
    if next_position == 0 and movement < 0 or next_position == maximum and movement > 0 then
      return next_position, 0
    end
    return next_position, movement - whole
  end
  local x, rx = advance(state.cursor_x, dx, self.cursor_remainder_x, 639)
  local y, ry = advance(state.cursor_y, dy, self.cursor_remainder_y, 479)
  assert(x and y, "cursor delta overflow")
  if x == state.cursor_x and y == state.cursor_y then
    self.cursor_remainder_x, self.cursor_remainder_y = rx, ry
    return true, "noop:subpixel-or-edge"
  end
  local ok, outcome = self:handlePointer{kind = "motion", x = x, y = y, relative = true}
  if ok then self.cursor_remainder_x, self.cursor_remainder_y = rx, ry end
  return ok, outcome
end

function Platform:click(button, double_click)
  return self:handlePointer{kind = "click", button = button,
    clicks = double_click and 2 or 1}
end

function Platform:invokeBottom(method)
  local ui = self.app.ui
  local bottom = ui and ui.bottom_panel
  if not bottom then return true, "noop:no-bottom-panel" end
  local callback = required_method(bottom, method)
  if method == "openFirstMessage" and #bottom.message_windows == 0 then
    return true, "noop:no-messages"
  end
  local dialog_name = bottom_dialog_types[method]
  local enable
  if dialog_name then
    local dialog_type = assert(rawget(_G, dialog_name), "required toolbar dialog type missing")
    enable = not required_method(ui, "getWindow")(ui, dialog_type)
  end
  -- Always run the upstream policy: a refused action may reset toggle states,
  -- play a sound or show research advice. editRoom owns editing_allowed itself.
  callback(bottom, enable) -- Upstream callbacks legitimately return nil/false.
  if method == "editRoom" then
    if not ui.editing_allowed then return self:finishAction("noop:editing-prohibited") end
  elseif method ~= "openFirstMessage" and self.app.world and
         self.app.world.user_actions_allowed == false then
    return self:finishAction("noop:actions-prohibited")
  elseif method == "dialogResearch" and not ui.hospital.research_dep_built then
    return self:finishAction("noop:research-unavailable")
  end
  return self:finishAction()
end

function Platform:cycleSpeed()
  local world = self.app.world
  if not world then return true, "noop:no-world" end
  -- World uses named rates, and setSpeed returns false even on success.
  -- Read back the authoritative rate; mandatory pauses take precedence.
  local current = world:getCurrentSpeed()
  if current == "Pause" or world:mustPause() then
    native_notice(self.native, "PAUSED - RESUME BEFORE CHANGING SPEED", false)
    return true, "noop:paused"
  end
  local next_speed = "Normal"
  for index, name in ipairs(game_speeds) do
    if current == name then next_speed = game_speeds[index % #game_speeds + 1]; break end
  end
  world:setSpeed(next_speed)
  local actual = world:getCurrentSpeed()
  if actual ~= next_speed then
    native_notice(self.native, "SPEED UNCHANGED: " .. tostring(actual), false)
    return true, "noop:speed-unchanged"
  end
  native_notice(self.native, "SPEED: " .. actual:upper(), false)
  native_checkpoint(self.native, "game_speed", "selected", actual)
  return self:finishAction()
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
  return true, "unsupported:engine-zoom"
end

function Platform:placeRoomRectangle(action)
  local ui = self.app.ui
  local edit = ui and ui.edit_room
  if type(edit) ~= "table" or edit.phase ~= "walls" then
    return true, "noop:no-blueprint"
  end
  local set_rectangle = required_method(edit, "setBlueprintRect")
  local width = math.max(1, tonumber(action.rect_w) or 1)
  local height = math.max(1, tonumber(action.rect_h) or 1)
  local cursor_x = tonumber(edit.mouse_cell_x) or 1
  local cursor_y = tonumber(edit.mouse_cell_y) or 1
  -- The lower grid is 19x8. Its centre follows the current world cursor.
  local x = cursor_x + (tonumber(action.rect_x) or 0) - 9
  local y = cursor_y + (tonumber(action.rect_y) or 0) - 3
  set_rectangle(edit, x, y, width, height)
  return self:finishAction()
end

-- A true first result means the input was handled, including a legitimate
-- no-op. The second result is mandatory at the native action boundary. These
-- interned strings add no per-HID result table or per-action log allocation.
function Platform:finishAction(outcome)
  self.native.request_redraw()
  return true, outcome or "applied"
end

function Platform:handleAction(action)
  self.operations:guard()
  assert(type(action) == "table" and type(action.type) == "string", "invalid action envelope")
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
    if context ~= "world" and context ~= "build_room" and context ~= "place_object" then
      return true, "noop:pan-context"
    end
    if (ui.down_count or 0) ~= 0 then return true, "noop:pointer-held" end
    local dx, dy = action.dx or 0, action.dy or 0
    assert(finite(dx) and finite(dy), "camera delta must be finite")
    if dx == 0 and dy == 0 then return true, "noop:zero-pan" end
    local scroll = required_method(ui, "scrollMap")
    local x, y = ui.screen_offset_x, ui.screen_offset_y
    scroll(ui, dx, dy)
    if ui.onCursorWorldPositionChange then ui:onCursorWorldPositionChange() end
    if x ~= nil and y ~= nil and x == ui.screen_offset_x and y == ui.screen_offset_y then
      return true, "noop:map-edge"
    end
  elseif kind == "cursor_step" then
    return self:moveCursor(action.dx or 0, action.dy or 0, action.value == 1)
  elseif kind == "confirm" then
    return self:click(1, false)
  elseif kind == "cancel" or kind == "close_top_window" then
    self:resetCursorResidual()
    if top_window(ui) == ui.menu_bar and self:closeMenuBar() then
      -- The menu owns cancellation; do not send Escape into the world.
      return true, "applied"
    elseif kind == "close_top_window" or context == "dialog" or
       context == "menu" or context == "text_input" or
       context == "place_object" or context == "build_room" then
      self:dispatchKey("Escape")
    else
      return self:click(3, false)
    end
  elseif kind == "open_quick_menu" then
    if not world then return true, "noop:no-world-menu" end
    required_method(ui, "showMenuBar")(ui)
    -- Explicit X also refocuses a menu already visible after a hover.
    self.focus_owners.window = nil
    self:prepareInput()
  elseif kind == "rotate_object" then
    return self:click(3, false)
  elseif kind == "toggle_walls" then
    if not world then return true, "noop:no-world" end
    required_method(ui, "toggleTransparent")(ui)
  elseif kind == "show_details" then
    return self:click(1, true)
  elseif kind == "zoom_in" then
    return self:adjustZoom(1.125)
  elseif kind == "zoom_out" then
    return self:adjustZoom(1 / 1.125)
  elseif kind == "pause_toggle" then
    if not world then return true, "noop:no-world" end
    local pause = required_method(world, "pauseOrUnpause")
    if world.mustPause and world:mustPause() then return true, "noop:mandatory-pause" end
    pause(world)
  elseif kind == "speed_cycle" then
    return self:cycleSpeed()
  elseif kind == "overview" or kind == "open_town_map" then
    return self:invokeBottom("dialogTownMap")
  elseif kind == "open_build" then
    return self:invokeBottom("dialogBuildRoom")
  elseif kind == "open_staff" then
    return self:invokeBottom("dialogStaffManagement")
  elseif kind == "open_patients" then
    return self:invokeBottom("dialogStatus")
  elseif kind == "open_finance" or kind == "open_bank" then
    return self:invokeBottom("dialogBankManager")
  elseif kind == "open_messages" then
    return self:invokeBottom("openFirstMessage")
  elseif kind == "open_casebook" then
    return self:invokeBottom("dialogDrugCasebook")
  elseif kind == "open_research" then
    return self:invokeBottom("dialogResearch")
  elseif kind == "open_policy" then
    return self:invokeBottom("dialogPolicy")
  elseif kind == "open_charts" then
    return self:invokeBottom("dialogCharts")
  elseif kind == "hire_staff" then
    return self:invokeBottom("dialogHireStaff")
  elseif kind == "furnish_corridor" then
    return self:invokeBottom("dialogFurnishCorridor")
  elseif kind == "edit_room" then
    return self:invokeBottom("editRoom")
  elseif kind == "quick_save" then
    if not world then return true, "noop:no-world" end
    local previous=self.operations.last
    local called,accepted=pcall(self.app.quickSave,self.app)
    if not called and (self.operations.last==previous or not self.operations.last.rejected) then error(accepted,0) end
    self.operations:guard()
    if not called or accepted~=true then return true,"noop:save-refused" end
  elseif kind == "open_save_slots" then
    if world then
      ui:addWindow(UISaveGame(ui))
      self.focus_owners.window = nil
      self:prepareInput()
      return self:finishAction()
    end
    native_notice(self.native, "START OR LOAD A HOSPITAL TO SAVE", false)
    return true, "noop:no-world"
  elseif kind == "show_help" then
    ui:addWindow(UIInformation(ui, {
      "CIRCLE: VIEW / EDGE: SCROLL MAP", "PEN: POINT / CLICK / DRAG",
      "PEN: CLICK / DRAG    A: CONFIRM", "B: BACK    X: MENU / ROTATE",
      "Y: WALLS    L: CLEAR / WIDE", "D-PAD: UNUSED; PEN OWNS CURSOR",
      "START: PAUSE    SELECT: SPEED", "R + START: SAVE SLOTS",
      "TEXT FIELD + A: KEYBOARD", "R + SELECT: THIS HELP",
    }))
    self:prepareInput()
  elseif kind == "text_keyboard" then
    return self:editText()
  elseif kind == "quick_load" then
    if not world then return true, "noop:no-world" end
    local previous=self.operations.last
    local accepted,detail = self.app:quickLoad()
    if accepted~=true and self.operations.last~=previous and self.operations.last.raised then error(detail,0) end
    self.operations:guard()
    if accepted ~= true then return true,"noop:load-refused" end
  elseif kind == "build_room_rectangle" then
    return self:placeRoomRectangle(action)
  elseif kind == "place_item" then
    return self:click(1, false)
  elseif kind == "previous_category" then
    self:dispatchKey("Left")
  elseif kind == "next_category" then
    self:dispatchKey("Right")
  elseif kind == "lifecycle_suspend" then
    self:resetCursorResidual()
    if not world or self.suspended_world then return true, "noop:not-suspendable" end
    self.saved_speed = world:getCurrentSpeed()
    self.suspended_world = world
    world:setSpeed("Pause")
  elseif kind == "lifecycle_resume" then
    self:resetCursorResidual()
    local resumable = world and world == self.suspended_world and self.saved_speed
    if resumable then world:setSpeed(self.saved_speed) end
    self.saved_speed, self.suspended_world = nil, nil
    if not resumable then return true, "noop:not-resumable" end
  elseif kind == "lifecycle_exit" then
    -- The native layer queues SDL_QUIT after the atomic quicksave request.
    return true, "noop:native-exit"
  elseif kind == "none" then
    return true, "noop:none"
  elseif kind == "move_viewport" or kind == "toggle_view" or kind == "open_dashboard" then
    -- Native view/panel owners consume these before the Lua game adapter.
    return true, "unsupported:native-owned"
  elseif kind == "tap" or kind == "double_tap" or kind == "long_press" then
    -- Legacy panel gestures must be translated by BottomUi, not clicked twice.
    return true, "unsupported:untranslated-gesture"
  else
    error("unknown action: " .. kind, 0)
  end

  return self:finishAction()
end

local module = {}

function module.attach(app, native, capabilities)
  assert(type(app)=="table" and type(native)=="table", "adapter owner missing")
  assert(type(capabilities)=="table" and type(capabilities.resource_events)=="boolean"
    and math.type(capabilities.epoch)=="integer" and capabilities.epoch>0, "native capabilities missing")
  local existing=rawget(app,"_3ds")
  if existing~=nil then
    assert(type(existing)=="table" and existing.completed and existing.app==app
      and existing.native==native and existing.capabilities.epoch==capabilities.epoch,
      "adapter identity/epoch mismatch")
    return existing
  end
  assert(app._3ds==nil,"inherited adapter belongs to another owner")
  local failed=rawget(app,"_3ds_binding_failed")
  assert(not failed or failed.native~=native or failed.epoch~=capabilities.epoch,
    "adapter binding unsafe; restart runtime before retry")
  for _,name in ipairs({"span_begin","span_end","span_abandon","observe_memory","operation_boundary","operation_block","flush_observations","atomic_commit","begin_critical_io","end_critical_io","set_notice","checkpoint","request_redraw"}) do
    assert(type(native[name])=="function", "mandatory native API missing: "..name)
  end
  if capabilities.resource_events then
    assert(type(native.resource_event)=="function" and type(native.shutdown)=="function", "resource safety API missing")
  end
  -- All preparation is private. No App field, native activation or one-shot
  -- marker is changed by these constructors.
  local prepared,platform=xpcall(function()
    local candidate=Platform.new(app,native,{epoch=capabilities.epoch,
      resource_events=capabilities.resource_events,asset_mode=capabilities.asset_mode})
    if native.benchmark_enabled and native.benchmark_enabled(false) then
      for _,name in ipairs({"benchmark_active","benchmark_state","shutdown"}) do
        assert(type(native[name])=="function", "benchmark safety API missing: "..name)
      end
      candidate.benchmark=require("3ds.benchmark").new(app,native)
    end
    return candidate
  end,traceback_message)
  if not prepared then error(platform,0) end
  local names={"save","load","quickSave","quickLoad","errorHandler"}
  local original={}
  for _,name in ipairs(names) do original[name]=rawget(app,name) end
  local ui=app.ui
  local raw_ui=rawget(app,"ui")
  local bottom=ui and ui.bottom_panel
  local raw_bottom=ui and rawget(ui,"bottom_panel")
  local visible=bottom and rawget(bottom,"visible")
  local resource_entered,claimed,claim_pending=false,false,false
  local ok, primary=xpcall(function()
    for _,name in ipairs(names) do
      if platform.bindings[name]~=nil then rawset(app,name,platform.bindings[name]) end
    end
    platform:showLegacyBottomPanel()
    if platform.benchmark then platform.benchmark:activate() end
    if capabilities.resource_events then
      resource_entered=true -- The native call may mutate before it reports failure.
      platform:resourceEvent("menu","main-menu",true)
    end
    assert(app.ui==ui and (not ui or ui.bottom_panel==bottom),"binding UI owner changed")
    if platform.benchmark then
      claim_pending=true
      local accepted=native.benchmark_enabled(true)
      claim_pending=false
      assert(accepted==true,"benchmark request claim rejected")
      claimed=true
    end
    platform.bindings=nil
    platform.completed=true
    rawset(app,"_3ds",platform) -- sole publication, after every necessary effect
  end,traceback_message)
  if not ok then
    rawset(app,"_3ds",nil)
    for _,name in ipairs(names) do rawset(app,name,original[name]) end
    rawset(app,"ui",raw_ui)
    if ui then rawset(ui,"bottom_panel",raw_bottom) end
    if bottom then rawset(bottom,"visible",visible) end
    local restored=true
    if platform.benchmark then restored=pcall(platform.benchmark.releaseActivation,platform.benchmark) end
    if not restored or resource_entered or claimed or claim_pending then
      rawset(app,"_3ds_binding_failed",{native=native,epoch=capabilities.epoch})
      pcall(native.operation_block)
      if native.shutdown then pcall(native.shutdown) end
    end
    error(primary,0)
  end
  rawset(app,"_3ds_binding_failed",nil)
  pcall(function()
    local language=app.config and app.config.language
    native.checkpoint("language_selected", "observed-at-adapter-attach",
      type(language)=="string" and language or "unknown")
  end)
  return platform
end

return module
