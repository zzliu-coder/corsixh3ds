from __future__ import annotations

import ctypes
import os
import ctypes.util
import tempfile
import unittest
from pathlib import Path


class LuaRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        library_name = os.environ.get("CTH3DS_LUA_LIBRARY") or ctypes.util.find_library("lua5.4") or "/lib/x86_64-linux-gnu/liblua5.4.so.0"
        try:
            cls.lua = ctypes.CDLL(library_name)
        except OSError as exc:  # pragma: no cover - portable CI fallback
            raise unittest.SkipTest(f"Lua 5.4 runtime unavailable: {exc}") from exc
        cls.lua.luaL_newstate.restype = ctypes.c_void_p
        cls.lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        cls.lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        cls.lua.luaL_loadstring.restype = ctypes.c_int
        cls.lua.lua_pcallk.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_longlong,
            ctypes.c_void_p,
        ]
        cls.lua.lua_pcallk.restype = ctypes.c_int
        cls.lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)]
        cls.lua.lua_tolstring.restype = ctypes.c_char_p
        cls.lua.lua_close.argtypes = [ctypes.c_void_p]

    def run_lua(self, script: str) -> None:
        state = self.lua.luaL_newstate()
        self.assertTrue(state)
        try:
            self.lua.luaL_openlibs(state)
            status = self.lua.luaL_loadstring(state, script.encode("utf-8"))
            if status == 0:
                status = self.lua.lua_pcallk(state, 0, 0, 0, 0, None)
            if status != 0:
                size = ctypes.c_size_t()
                message = self.lua.lua_tolstring(state, -1, ctypes.byref(size))
                detail = message[: size.value].decode("utf-8", errors="replace") if message else "Lua error"
                self.fail(detail)
        finally:
            self.lua.lua_close(state)

    def test_empty_player_name_without_environment_uses_player(self) -> None:
        self.run_lua(
            '''
local function normalize_player_name(value, getenv)
  value = value:match('^%s*(.*%S)') or ""
  if value:len() == 0 then
    value = getenv("USER") or getenv("USERNAME")
  end
  value = (value or ""):match('^%s*(.*%S)') or ""
  if value:len() == 0 then value = "PLAYER" end
  return value
end
local function no_environment(_) return nil end
assert(normalize_player_name("", no_environment) == "PLAYER")
assert(normalize_player_name("  Alice  ", no_environment) == "Alice")
'''
        )

    def test_adapter_executes_save_state_and_action_flow(self) -> None:
        adapter = (Path(__file__).parents[1] / "lua/3ds/platform.lua").resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            script = f'''
local adapter_path = {str(adapter)!r}
local temp_root = {str(root)!r} .. "/"
local begin_count, end_count = 0, 0
local notices, states, dispatches = {{}}, {{}}, {{}}
local calls = {{build = 0, town = 0}}

local native = {{span_begin=function()return 1 end,span_end=function()end,observe_memory=function()end,flush_observations=function()end,
  is_platform = function() return true end,
  checkpoint = function() end,
  begin_critical_io = function() begin_count = begin_count + 1 end,
  end_critical_io = function() end_count = end_count + 1 end,
  atomic_commit = function(temporary, final)
    local ok, err = os.rename(temporary, final)
    return ok ~= nil, err
  end,
  recover_atomic = function() return true end,
  set_notice = function(message, is_error)
    notices[#notices + 1] = {{message = message, is_error = is_error}}
  end,
  set_state = function(state) states[#states + 1] = state end,
  request_redraw = function() end,
}}

local bottom = {{
  visible = true,
  message_queue = {{}}, message_windows = {{}},
  dialogBuildRoom = function() calls.build = calls.build + 1 end,
  dialogTownMap = function() calls.town = calls.town + 1 end,
}}
local world = {{
  game_speed = 1,
  setSpeed = function(self, value) self.game_speed = value end,
  pauseOrUnpause = function(self) self.game_speed = self.game_speed == 0 and 1 or 0 end,
}}
local hospital = {{balance = 12345, reputation = 678, patients = {{{{}}}}, staff = {{{{}}}}}}
local app = {{
  savegame_dir = temp_root,
  world = world,
  ui = {{windows = {{}}, bottom_panel = bottom, hospital = hospital, cursor_x=320, cursor_y=240, setMouseReleased=function() end}},
  dispatch = function(self, ...) dispatches[#dispatches + 1] = {{...}}; local e={{...}}; if e[1]=="motion" then self.ui.cursor_x,self.ui.cursor_y=e[2],e[3] end end,
  save = function(self, filename)
    local handle = assert(io.open(filename, "wb"))
    handle:write("SAVE")
    handle:close()
    return true
  end,
  load = function() return true end,
}}

local module = assert(loadfile(adapter_path))()
local platform = module.attach(app, native, {{asset_mode="loose",resource_events=false,epoch=1}})
platform:syncBottomState()
assert(app._3ds == platform)
assert(bottom.visible == true, "the game's own toolbar must stay visible")
assert(#states >= 1 and states[#states].cash == 12345)

local target = temp_root .. "slot.sav"
assert(app:save(target) == true)
local handle = assert(io.open(target, "rb"))
assert(handle:read("*a") == "SAVE")
handle:close()
assert(begin_count == 1 and end_count == 1)
assert(notices[#notices].message == "SAVE OK" and notices[#notices].is_error == false)

-- A repeated sync with nothing changed must not push a new state: on device
-- every push marks the lower screen dirty and forces a full repaint.
local before = #states
platform:syncBottomState()
platform:syncBottomState()
assert(#states == before, "unchanged state was pushed again")
hospital.balance = 999
platform:syncBottomState()
assert(#states == before + 1 and states[#states].cash == 999)

-- Zoom is pinned at 1.0 on 3DS; adjustZoom must not touch the UI.
local zoom_calls = 0
app.ui.setZoom = function() zoom_calls = zoom_calls + 1 end
app.ui.zoom_factor = 1
platform:adjustZoom(2)
assert(zoom_calls == 0, "adjustZoom must be a no-op on 3DS")
assert(app.ui.zoom_factor == 1)

platform:handleAction({{type = "open_build"}})
platform:handleAction({{type = "open_town_map"}})
assert(calls.build == 1 and calls.town == 1)
for _ = 1, 100 do platform:handleAction({{type = "cursor_step", dx = 1, dy = 1}}) end
assert(app.ui.cursor_x == 639 and app.ui.cursor_y == 479)
assert(#dispatches > 0)

local failing_native = {{span_begin=function()return 1 end,span_end=function()end,observe_memory=function()end,flush_observations=function()end,
  begin_critical_io = native.begin_critical_io,
  end_critical_io = native.end_critical_io,
  atomic_commit = native.atomic_commit,
  recover_atomic = native.recover_atomic,
  set_notice = native.set_notice,
  set_state = native.set_state,
  request_redraw = native.request_redraw,
  checkpoint = native.checkpoint,
}}
local failing_app = {{
  savegame_dir = temp_root,
  ui = {{windows = {{}}, bottom_panel = {{visible = true, message_queue = {{}}, message_windows = {{}}}}}},
  dispatch = function() end,
  save = function() error("intentional failure") end,
  load = function() return true end,
}}
local failing_platform = module.attach(failing_app, failing_native, {{asset_mode="loose",resource_events=false,epoch=1}})
local ok = pcall(failing_app.save, failing_app, temp_root .. "bad.sav")
assert(ok == false)
assert(notices[#notices].message:match("SAVE FAILED") and notices[#notices].is_error == true)
assert(begin_count == 2 and end_count == 2)
assert(failing_platform ~= nil)
'''
            self.run_lua(script)


    def test_mixed_input_frozen_upstream_ui_methods(self) -> None:
        # R21: exact 0.70.1 App/UI/Window method bodies; constructor, native,
        # engine and keyboard seams. Actual GameUI/SDL/HID remain unproven.
        adapter = (Path(__file__).parents[1] / "lua/3ds/platform.lua").resolve()
        self.run_lua("local adapter_path = " + repr(str(adapter)) + "\n" + r'''
App = {}; UI = {}; Window = {}; local done_no_handler_warning = {}

function App:dispatch(evt_type, ...)
  local handler = self.eventHandlers[evt_type]
  if handler then
    return handler(self, ...)
  else
    if not done_no_handler_warning[evt_type] then
      print("Warning: No event handler for " .. evt_type)
      done_no_handler_warning[evt_type] = true
    end
    return false
  end
end


function App:onMouseMove(...)
  return self.ui:onMouseMove(...)
end


function App:onMouseDown(...)
  return self.ui:onMouseDown(...)
end


function App:onMouseUp(...)
  return self.ui:onMouseUp(...)
end


function UI:setMouseReleased(released)
  if released == self.mouse_released then
    return
  end

  self.mouse_released = released

  -- If we are using a software cursor, show the hardware cursor on release
  -- and hide it again on capture.
  if self.cursor and not self.cursor.use then
    WM.showCursor(released)
  end

  self.app.video:setCaptureMouse(self.app.capturemouse and not self.app.mouse_released)
end


function UI:onMouseMove(x, y, dx, dy)
  if self.mouse_released then
    return false
  end

  local repaint = UpdateCursorPosition(self.app.video, x, y)

  self.cursor_x = x
  self.cursor_y = y

  if self.drag_mouse_move then
    self.drag_mouse_move(x, y)
    return true
  end

  if Window.onMouseMove(self, x, y, dx, dy) then
    repaint = true
  end

  self:updateTooltip()

  return repaint
end


function UI:onMouseDown(code, x, y)
  self:setMouseReleased(false)
  local repaint = false
  local button = self.button_codes[code] or code
  if self.app.moviePlayer.playing then
    if button == "left" then
      self.app.moviePlayer:stop()
    end
    return true
  end
  if self.cursor_entity == nil and self.down_count == 0 and
      self.cursor == self.default_cursor then
    self:setCursor(self.down_cursor)
    repaint = true
  end
  self.down_count = self.down_count + 1
  if x >= 3 and y >= 3 and x < self.app.config.width - 3 and y < self.app.config.height - 3 then
    self.buttons_down["mouse_"..button] = true
  end

  self:updateTooltip()
  return Window.onMouseDown(self, button, x, y) or repaint
end


function UI:onMouseUp(code, x, y)
  local repaint = false
  local button = self.button_codes[code] or code
  self.down_count = self.down_count - 1
  if self.down_count <= 0 then
    if self.cursor_entity == nil and self.cursor == self.down_cursor then
      self:setCursor(self.default_cursor)
      repaint = true
    end
    self.down_count = 0
  end
  self.buttons_down["mouse_"..button] = nil

  if Window.onMouseUp(self, button, x, y) then
    repaint = true
  else
    if self:ableToClickEntity(self.cursor_entity) then
      self.cursor_entity:onClick(self, button)
      repaint = true
    end
  end

  self:updateTooltip()
  return repaint
end


function Window:onMouseDown(button, x, y)
  local repaint = false
  if not self.visible then return false end
  if self.windows then
    for _, window in ipairs(self.windows) do
      local ws = window.apply_ui_scale and TheApp.config.ui_scale or 1
      if window:onMouseDown(button, x - window.x * ws, y - window.y * ws) then
        repaint = true
        break
      end
    end
  end
  if not repaint and (button == "left" or button == "right") then
    for _, btn in ipairs(self.buttons) do
      local bs = btn.panel_for_sprite.apply_ui_scale and TheApp.config.ui_scale or 1
      if btn.enabled and
          btn.x * bs <= x and x < btn.r * bs and btn.y * bs <= y and y < btn.b * bs and
          (button == "left" or btn.on_rightclick ~= nil) then
        btn.panel_for_sprite.sprite_index = btn.sprite_index_active
        self.active_button = btn
        btn.active = true
        btn.panel_for_sprite.lowered = btn.panel_lowered_active
        if btn.is_repeat then
          -- execute callback once, then wait some ticks before repeatedly executing
          btn:handleClick(button)
        end
        self.btn_repeat_delay = 10
        repaint = true
        break
      end
    end
    local s = self.apply_ui_scale and TheApp.config.ui_scale or 1
    for _, bar in ipairs(self.scrollbars) do
      if bar.enabled and self:hitTestPanel(x, y, bar.slider) then
        self.active_scrollbar = bar
        bar.active = true
        bar.down_x = x / s - bar.slider.x
        bar.down_y = y / s - bar.slider.y
        repaint = true
        break
      end
    end
  end
  if self:hitTest(x, y) then
    if button == "left" and not repaint then
      self:beginDrag(x, y)
    end
    repaint = true
  end

  if repaint then
    self:bringToTop()
  end
  return repaint
end


function Window:onMouseUp(button, x, y)
  local repaint = false

  if self.dragging then
    self.ui.drag_mouse_move = nil
    self.dragging = false
    local config = self.ui.app.runtime_config
    if not config.window_position then
      config.window_position = {}
    end
    config = config.window_position
    local name = self:getSavedWindowPositionName()
    if not config[name] then
      config[name] = {}
    end
    config = config[name]
    config.x = self.x_original
    config.y = self.y_original
    return false
  end

  if self.windows then
    for _, window in ipairs(self.windows) do
      local s = window.apply_ui_scale and TheApp.config.ui_scale or 1
      if window:onMouseUp(button, x - window.x * s, y - window.y * s) then
        repaint = true
        break -- Click has been handled. No need to look any further.
      end
    end
  end

  if button == "left" or button == "right" then
    local btn = self.active_button
    if btn then
      local bs = btn.panel_for_sprite.apply_ui_scale and TheApp.config.ui_scale or 1
      btn.panel_for_sprite.sprite_index = btn.sprite_index_normal
      btn.active = false
      btn.panel_for_sprite.lowered = btn.panel_lowered_normal
      self.active_button = false
      self.btn_repeat_delay = nil
      if btn.enabled and not btn.is_repeat and btn.x * bs <= x and x < btn.r * bs and btn.y * bs <= y and y < btn.b * bs then
        btn:handleClick(button)
      end
      repaint = true
    end
    local bar = self.active_scrollbar
    if bar then
      self.active_scrollbar = nil
      bar.active = false
      bar.down_x = nil
      bar.down_y = nil
    end
  end

  return repaint
end

-- Exact upstream App/UI/Window methods are loaded before this fixture.
-- Constructors, TH/WM, hit-test geometry, native callbacks and key dispatch are seams.
local module = assert(loadfile(adapter_path))()
local function fresh()
  local events, keys = {}, {}
  local app = setmetatable({config={width=640,height=480,ui_scale=1}, world={},
    moviePlayer={playing=false},runtime_config={},
    video={setCaptureMouse=function() end},save=function() return true end}, {__index=App})
  TheApp=app
  WM={showCursor=function() end}
  UpdateCursorPosition=function(_,x,y) events[#events+1]={'motion',x,y};return true end
  local ui=setmetatable({app=app,cursor_x=200,cursor_y=200,mouse_released=true,
    cursor={},default_cursor={},down_cursor={},cursor_entity=nil,down_count=0,
    button_codes={[1]='left',[3]='right'},buttons_down={},windows={},buttons={},
    scrollbars={},textboxes={},visible=true,
    updateTooltip=function() end,setCursor=function(self,c) self.cursor=c end,
    ableToClickEntity=function() return false end,
    hitTest=function() return false end,beginDrag=function() end,
    bringToTop=function() end,hitTestPanel=function() return false end}, {__index=UI})
  app.ui=ui
  app.eventHandlers={motion=App.onMouseMove,buttondown=App.onMouseDown,buttonup=App.onMouseUp,
    keydown=function(_,key) keys[#keys+1]=key end,keyup=function() end}
  Window.onMouseMove=function() return false end
  local native={span_begin=function()return 1 end,span_end=function()end,observe_memory=function()end,flush_observations=function()end,resource_event=function() return true end,
    set_state=function() end,request_redraw=function() end,recover_atomic=function() return true end}
  native.atomic_commit=function() return true end; native.begin_critical_io=function() end; native.end_critical_io=function() end; native.set_notice=function() end; native.checkpoint=function() end
  app.load=function() return true end
  local p=module.attach(app,native,{resource_events=false,epoch=1})
  -- Any attempt to enumerate hospital/message collections now fails.
  local poison=setmetatable({}, {__pairs=function() error('HEAVY ENUMERATION') end})
  ui.hospital={patients=poison,staff=poison}
  ui.bottom_panel={message_queue=poison,message_windows=poison}
  p.syncBottomState=function() error('HEAVY SYNC') end
  return p,app,ui,events,keys
end
local count=0
local function check(name,fn) fn();count=count+1;print('[PASS] '..name) end
check('real_ui_touch_step_click_capture_and_no_heavy_sync',function()
  local p,app,ui,events=fresh()
  assert(p:handlePointer{kind='down',x=200,y=200})
  assert(ui.cursor_x==200 and ui.cursor_y==200 and not ui.mouse_released)
  assert(ui.down_count==1)
  assert(p:handlePointer{kind='up'})
  assert(p:handleAction{type='cursor_step',dx=1,dy=0})
  assert(ui.cursor_x==216 and ui.cursor_y==200)
  assert(p:handleAction{type='confirm'})
  assert(p:handleAction{type='cancel'})
  assert(p:handleAction{type='show_details'})
  assert(ui.down_count==0 and ui.buttons_down.mouse_left==nil)
  for i=3,#events do assert(events[i][2]==216 and events[i][3]==200) end
  assert(rawget(p,'cursor_x')==nil and rawget(p,'cursor_y')==nil)
end)
check('real_ui_motion_before_press_and_release_at_current_point',function()
  local p,app,ui=fresh()
  assert(p:handlePointer{kind='down',x=0,y=479})
  assert(ui.cursor_x==0 and ui.cursor_y==479)
  assert(p:moveCursor(100,-100))
  assert(ui.cursor_x==639 and ui.cursor_y==0)
  assert(p:handlePointer{kind='up'})
  assert(ui.cursor_x==639 and ui.cursor_y==0 and ui.down_count==0)
end)
check('current_front_window_phase_and_boolean_edit_flag',function()
  local p,app,ui=fresh()
  ui.edit_room=true
  local build={phase='walls',visible=true}
  ui.windows={build}
  assert(p:inputState().input_context=='build_room')
  build.phase='objects';assert(p:inputState().input_context=='place_object')
  ui.windows={{visible=true},build}
  assert(p:inputState().input_context=='dialog')
  ui.windows[1].textboxes={{enabled=true,active=true}}
  assert(p:inputState().input_context=='text_input')
  ui.windows={};assert(p:inputState().input_context=='world')
  app.world=nil;assert(p:inputState().input_context=='menu')
end)
check('menu_dialog_dpad_and_cancel_routing',function()
  local p,app,ui,events,keys=fresh()
  app.world=nil
  assert(p:handleAction{type='cursor_step',dx=1,dy=0})
  assert(ui.cursor_x==216 and #keys==0)
  assert(p:handleAction{type='confirm'})
  assert(#keys==0)
  app.world={};ui.windows={{visible=true}}
  assert(p:handleAction{type='cancel'})
  assert(keys[1]=='Escape') -- key handler boundary is a supplied seam.
end)
check('ui_replacement_between_clicks_uses_new_current_point',function()
  local p,app,ui=fresh()
  local points={}
  local original=app.eventHandlers.buttonup
  app.eventHandlers.buttonup=function(self,...)
    original(self,...)
    self.ui.cursor_x,self.ui.cursor_y=300,301
  end
  app.eventHandlers.buttondown=function(self,button,x,y)
    points[#points+1]={x,y};return App.onMouseDown(self,button,x,y)
  end
  assert(p:handleAction{type='show_details'})
  assert(#points==2 and points[1][1]==200 and points[2][1]==300 and points[2][2]==301)
end)
check('cancel_drag_pressed_window_and_blueprint_without_activation',function()
  local p,app,ui=fresh()
  local clicks=0
  local panel={sprite_index=9,lowered=true}
  local btn={panel_for_sprite=panel,sprite_index_normal=1,panel_lowered_normal=false,
    active=true,enabled=true,x=0,y=0,r=640,b=480,handleClick=function() clicks=clicks+1 end}
  local child={active_button=btn,active_scrollbar={active=true,down_x=1},
    dragging=true,mouse_down_x=4,mouse_down_y=5,windows={}}
  ui.windows={child};ui.down_count=1;ui.buttons_down.mouse_left=true
  ui.drag_mouse_move=function() end
  assert(p:cancelPointer())
  assert(clicks==0 and ui.down_count==0 and not ui.buttons_down.mouse_left)
  assert(ui.drag_mouse_move==nil and not child.dragging and not child.mouse_down_x)
  assert(not child.active_button and not btn.active and not child.active_scrollbar)
  assert(panel.sprite_index==1 and panel.lowered==false)
end)
check('pointer_failures_are_explicit',function()
  local p,app,ui=fresh()
  ui.setMouseReleased=false
  local ok,err=p:handlePointer{kind='motion',x=200,y=200}
  assert(ok==false and err:find('capture unavailable'))
  local result,detail=p:handleAction{type='cursor_step',dx=1,dy=0}
  assert(result==false and detail:find('capture unavailable'))
end)
check('actual_window_button_receives_a_b_and_two_detail_clicks_at_ui_point',function()
  local p,app,ui=fresh()
  local hits={}
  local panel={}
  ui.buttons={{enabled=true,x=0,y=0,r=640,b=480,panel_for_sprite=panel,
    sprite_index_active=2,sprite_index_normal=1,on_rightclick=true,
    handleClick=function(_,button) hits[#hits+1]={button,ui.cursor_x,ui.cursor_y} end}}
  assert(p:handlePointer{kind='down',x=200,y=200})
  assert(p:handlePointer{kind='up'})
  assert(p:moveCursor(1,0))
  assert(p:handleAction{type='confirm'})
  assert(p:handleAction{type='cancel'})
  assert(p:handleAction{type='show_details'})
  assert(#hits==5 and hits[1][2]==200)
  for i=2,5 do assert(hits[i][2]==216 and hits[i][3]==200) end
  assert(hits[2][1]=='left' and hits[3][1]=='right')
end)
check('serialized_mapper_touch_is_scaled_once_then_ui_step_and_release',function()
  local p,app,ui=fresh()
  assert(p:handleAction{type='pointer_move',x=100,y=100})
  assert(p:handleAction{type='pointer_down',x=100,y=100})
  assert(p:handleAction{type='cursor_step',dx=1,dy=0})
  assert(ui.cursor_x==216 and ui.cursor_y==200)
  assert(p:handleAction{type='pointer_up',x=0,y=0,value=0})
  assert(ui.cursor_x==216 and ui.cursor_y==200 and ui.down_count==0)
end)

GameUI={};UIEditRoom={};UIConfirmDialog={};UIPlaceObjects={onMouseDown=Window.onMouseDown,onMouseUp=Window.onMouseUp};local highlight_x,highlight_y
function GameUI:onMouseMove(x, y, dx, dy)
  if self.mouse_released then
    return false
  end

  local repaint = UpdateCursorPosition(self.app.video, x, y)
  if self.app.moviePlayer.playing then
    return false
  end

  self.cursor_x = x
  self.cursor_y = y
  if self:onCursorWorldPositionChange() or self.simulated_cursor then
    repaint = true
  end

  if self:_isMouseScrollButtonDown() then
    local zoom = self.zoom_factor
    self.current_momentum.x = self.current_momentum.x - dx/zoom
    self.current_momentum.y = self.current_momentum.y - dy/zoom

    local momentum_x_int = math.round(self.current_momentum.x)
    local momentum_y_int = math.round(self.current_momentum.y)

    -- Stop zooming when the middle mouse button is pressed
    self.current_momentum.z = 0
    self:scrollMap(momentum_x_int, momentum_y_int)

    self.current_momentum.x = self.current_momentum.x - momentum_x_int
    self.current_momentum.y = self.current_momentum.y - momentum_y_int

    repaint = true
  end

  if self.drag_mouse_move then
    self.drag_mouse_move(x, y)
    return true
  end

  local scroll_region_size
  if self.app.config.fullscreen then
    -- As the mouse is locked within the window, a 1px region feels a lot
    -- larger than it actually is.
    scroll_region_size = 1
  else
    -- In windowed mode, a reasonable size is needed, though not too large.
    scroll_region_size = 8
  end
  if not self.app.config.prevent_edge_scrolling and
      (x < scroll_region_size or y < scroll_region_size or
       x >= self.app.config.width - scroll_region_size or
       y >= self.app.config.height - scroll_region_size) then
    local scroll_dx = 0
    local scroll_dy = 0
    local scroll_power = 7
    if x < scroll_region_size then
      scroll_dx = -scroll_power
    elseif x >= self.app.config.width - scroll_region_size then
      scroll_dx = scroll_power
    end
    if y < scroll_region_size then
      scroll_dy = -scroll_power
    elseif y >= self.app.config.height - scroll_region_size then
      scroll_dy = scroll_power
    end

    if not self.tick_scroll_amount_mouse then
      self.tick_scroll_amount_mouse = {x = scroll_dx, y = scroll_dy}
    else
      self.tick_scroll_amount_mouse.x = scroll_dx
      self.tick_scroll_amount_mouse.y = scroll_dy
    end
  else
    self.tick_scroll_amount_mouse = false
  end

  if Window.onMouseMove(self, x, y, dx, dy) then
    repaint = true
  end

  self:updateTooltip()

  local map = self.app.map
  local wx, wy = self:ScreenToWorld(x, y)
  wx = math.floor(wx)
  wy = math.floor(wy)
  if highlight_x then
    --map.th:setCell(highlight_x, highlight_y, 4, 0)
    highlight_x = nil
  end
  local map_width, map_height = map.th:size()
  if 1 <= wx and wx <= map_width and 1 <= wy and wy <= map_height then
    if map.th:getCellFlags(wx, wy).passable then
      --map.th:setCell(wx, wy, 4, 24 + 8 * 256)
      highlight_x = wx
      highlight_y = wy
    end
  end

  return repaint
end

function GameUI:onMouseUp(code, x, y)
  if self.app.moviePlayer.playing then
    return UI.onMouseUp(self, code, x, y)
  end

  -- Controlling debug patients movement with a cursor
  local button = self.button_codes[code]
  if button == "right" and not self.map_editor and highlight_x then
    local window = self:getWindow(UIPatient)
    local patient = (window and window.patient.is_debug and window.patient) or self.hospital:getDebugPatient()
    if patient then
      patient:walkTo(highlight_x, highlight_y)
      patient:queueAction(IdleAction())
    end
  end

  if self.edit_room then
    if class.is(self.edit_room, Room) then
      if button == "right" and self.cursor == self.waiting_cursor then
        -- Still waiting for people to leave the room, abort editing it.
        self:setEditRoom(false)
      end
    else -- No room chosen yet, but about to edit one.
      if button == "left" then -- Take the clicked one.
        local room = self.app.world:getRoom(self:ScreenToWorld(x, y))
        if room then
          if not room.crashed then
            self:setCursor(self.waiting_cursor)
            self.edit_room = room
            room:tryToEdit()
          else
            if self.app.config.remove_destroyed_rooms then
              local room_cost = room:calculateRemovalCost()
              self:setEditRoom(false)
              -- show confirmation dialog for removing the room
              self:addWindow(UIConfirmDialog(self, false, _S.confirmation.remove_destroyed_room:format(room_cost),
              --[[persistable:remove_destroyed_room_confirm_dialog]]function()
                local world = room.world
                UIEditRoom:removeRoom(false, room, world)
                world:resetSideObjects()
                world.rooms[room.id] = nil
                self.hospital:spendMoney(room_cost, _S.transactions.remove_room)
                end
              ))
            end
          end
        end
      else -- right click, we don't want to edit a room after all.
        self:setEditRoom(false)
      end
    end
  end

  -- During vaccination mode you can only interact with infected patients
  local epidemic = self.hospital.epidemic
  if epidemic and epidemic.vaccination_mode_active then
    if button == "left" then
      if self.cursor_entity then
        -- Allow click behaviour for infected patients
        if self.cursor_entity.infected then
          self.cursor_entity:onClick(self,button)
        end
      end
    elseif button == "right" then
      --Right click turns vaccination mode off
      local watch = TheApp.ui:getWindow(UIWatch)
      watch:toggleVaccinationMode()
    end
  end

  return UI.onMouseUp(self, code, x, y)
end

function UI:_determineKeyPressed(rawchar, modifiers, btn_maps)
  -- Apply key-remapping and normalisation
  rawchar = string.sub(rawchar,1,6) == "Keypad" and
            modifiers["numlockactive"] and string.sub(rawchar,8) or rawchar
  local key = rawchar:lower()
  if btn_maps and btn_maps[key] then
    -- Buttons remaps to mouse
    self:onMouseDown(btn_maps[key], self.cursor_x, self.cursor_y)
    return false
  end
  key = self.key_remaps[key] or key

  return rawchar, key
end

function UI:onKeyDown(rawchar, modifiers)
  local handled = false
  local rawchar_transformed, key = self:_determineKeyPressed(
      rawchar, modifiers, self.key_to_button_remaps)
  if not rawchar_transformed then return end

  -- Remove numlock modifier
  modifiers["numlockactive"] = nil
  -- If there is one, the current textbox gets the key.
  -- It will not process any text at this point though.
  for _, box in ipairs(self.textboxes) do
    if box.enabled and box.active and not handled then
      handled = box:keyInput(key, rawchar_transformed)
    end
  end

  -- If there is a hotkey box
  for _, hotkeybox in ipairs(self.hotkeyboxes) do
    if hotkeybox.enabled and hotkeybox.active and not handled then
      handled = hotkeybox:keyInput(key, rawchar_transformed, modifiers)
    end
  end

  -- Otherwise, if there is a key handler bound to the given key, then it gets
  -- the key.
  if not handled then
    local keyHandlers = self.key_handlers[key]
    if keyHandlers then
      -- Iterate over key handlers and call each one whose modifier(s) are pressed
      -- NB: Only if the exact correct modifiers are pressed will the shortcut get processed.
      for _, handler in ipairs(keyHandlers) do
        if compare_tables(handler.modifiers, modifiers) then
          handler.callback(handler.window, unpack(handler))
          handled = true
        end
      end
    end
  end

  -- Store information about the key
  self.buttons_down[key] = true
  self.modifiers_down = modifiers
  self.key_press_handled = handled
  return handled
end

function UI:onKeyUp(rawchar, modifiers)
  local _, key = self:_determineKeyPressed(rawchar, modifiers)
  self.buttons_down[key] = nil

  -- Go through all the hotkeyboxes.
  for _, hotkeybox in ipairs(self.hotkeyboxes) do
    -- If one is enabled and active...
    if hotkeybox.enabled and hotkeybox.active then
      -- If the key lifted is escape...
      if(key == "escape") then
        hotkeybox:abort()
        hotkeybox.noted_keys = {}
      else
        -- Check if the current key lifted has already been noted.
        self.key_noted = false
        for _, v in pairs(hotkeybox.noted_keys) do
          if v == key then
            self.key_noted = true
          end
        end

        -- If the current key hasn't been noted...
        if self.key_noted == false then
          hotkeybox.noted_keys[#hotkeybox.noted_keys + 1] = key
        end

        -- Says if there is still a button being pressed.
        self.temp_button_down = false

        -- Go through and check if there are still any buttons pressed. If so...
        for _, _ in pairs(self.buttons_down) do
          -- Then toggle the corresponding bool.
          self.temp_button_down = true
        end

        --If there ISN'T still a button down when a button was released...
        if self.temp_button_down == false then
          -- Activate the confirm function on the hotkey box.
          hotkeybox:confirm()
          hotkeybox.noted_keys = {}
        end
      end
    end
  end

  -- Clean up
  self.modifiers_down = nil
  self.key_press_handled = nil
end

function Window:close()
  if self.dragging then
    self.dragging = false
    self.ui.drag_mouse_move = nil
  end
  if self.parent then
    self.parent:removeWindow(self)
  end
  for key in pairs(self.key_handlers) do
    self.ui:removeKeyHandler(key, self)
  end
  for _, box in pairs(self.textboxes) do
    self.ui:unregisterTextBox(box)
  end
  for _, box in pairs(self.hotkeyboxes) do
    self.ui:unregisterHotkeyBox(box)
  end
  self.closed = true
end

function Window:removeWindow(window)
  if self.windows then
    for n = 1, #self.windows do
      if self.windows[n] == window then
        if #self.windows == 1 then
          self.windows = false
        else
          table.remove(self.windows, n)
        end
        return true
      end
    end
  end
  return false
end

function UIEditRoom:onMouseDown(button, x, y)
  if self.world.user_actions_allowed and not self.confirm_dialog_open then
    if button == "left" then
      self:onLeftButtonDown(x, y)
    elseif button == "right" then
      if self.phase == "windows" then
        self:tryRemoveWindowFromWall(x, y)
      end
    end
  end
  return UIPlaceObjects.onMouseDown(self, button, x, y) or true
end

function UIEditRoom:onMouseUp(button, x, y)
  if self.mouse_down_x then
    self.mouse_down_x = false
    self.mouse_down_y = false
  end

  if self.move_rect_x then
    self.move_rect_x = false
    self.move_rect_y = false
  end

  return UIPlaceObjects.onMouseUp(self, button, x, y)
end

function UIConfirmDialog:cancel()
  self:close(false)
end

function UIConfirmDialog:close(confirmed)
  -- NB: Window is closed before executing the callback in order to not save the confirmation dialog in a savegame
  Window.close(self)
  if confirmed then
    if self.callback_ok then
      self.callback_ok()
    end
  else
    if self.callback_cancel then
      self.callback_cancel()
    end
  end
end
unpack=table.unpack
compare_tables=function(a,b) return next(a)==nil and next(b)==nil end
check('actual_game_edit_dialog_handlers_ten_rounds',function()
 for round=1,10 do
  local p,app,ui=fresh()
  ui.onMouseMove=GameUI.onMouseMove;ui.onMouseUp=GameUI.onMouseUp
  ui.onCursorWorldPositionChange=function()return false end
  ui._isMouseScrollButtonDown=function()return false end
  ui.ScreenToWorld=function()return 0,0 end
  app.map={th={size=function()return 128,128 end}}
  assert(p:handleAction{type='pointer_down',x=100,y=100})
  assert(p:handleAction{type='cursor_step',dx=1,dy=0})
  assert(p:handleAction{type='pointer_up'})
  assert(ui.cursor_x==216 and ui.cursor_y==200 and ui.down_count==0)
  for _,point in ipairs({{0,0},{639,0},{0,479},{639,479}})do
   assert(p:handlePointer{kind='motion',x=point[1],y=point[2]})
   assert(ui.cursor_x==point[1] and ui.cursor_y==point[2])
  end
  local edit=setmetatable({visible=true,world={user_actions_allowed=true},phase='walls',
   confirm_dialog_open=false,windows={},buttons={},scrollbars={},ui=ui,
   hitTest=function()return false end,bringToTop=function()end,
   onLeftButtonDown=function(self,x,y) self.mouse_down_x,self.mouse_down_y=x,y end}, {__index=UIEditRoom})
  assert(edit:onMouseDown('left',200,200));assert(edit.mouse_down_x==200)
  edit:onMouseUp('left',216,200);assert(edit.mouse_down_x==false)
  ui.windows={edit};edit.mouse_down_x=200;edit.move_rect_x=10
  assert(p:cancelPointer());assert(edit.mouse_down_x==false and edit.move_rect_x==false)
  ui._determineKeyPressed=UI._determineKeyPressed;ui.key_remaps={};ui.key_to_button_remaps={}
  ui.hotkeyboxes={};ui.removeWindow=Window.removeWindow
  ui.onKeyDown=UI.onKeyDown;ui.onKeyUp=UI.onKeyUp
  local dialog=setmetatable({ui=ui,parent=ui,key_handlers={},textboxes={},hotkeyboxes={},visible=true}, {__index=UIConfirmDialog})
  ui.windows={dialog};ui.key_handlers={escape={{window=dialog,callback=UIConfirmDialog.cancel,modifiers={}}}}
  app.eventHandlers.keydown=function(self,...)return self.ui:onKeyDown(...)end
  app.eventHandlers.keyup=function(self,...)return self.ui:onKeyUp(...)end
  assert(p:handleAction{type='cancel'});assert(dialog.closed and (ui.windows==false or #ui.windows==0))
 end
end)

print('Ran '..count..' Lua observations; 0 failed; engine constructors, native HID/SDL and device NOT_PROVEN')
''')


if __name__ == "__main__":
    unittest.main()
