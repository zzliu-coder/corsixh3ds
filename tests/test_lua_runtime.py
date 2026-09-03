from __future__ import annotations

import ctypes
import ctypes.util
import tempfile
import unittest
from pathlib import Path


class LuaRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        library_name = ctypes.util.find_library("lua5.4") or "/lib/x86_64-linux-gnu/liblua5.4.so.0"
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

local native = {{
  is_platform = function() return true end,
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
  ui = {{windows = {{}}, bottom_panel = bottom, hospital = hospital}},
  dispatch = function(self, ...) dispatches[#dispatches + 1] = {{...}} end,
  save = function(self, filename)
    local handle = assert(io.open(filename, "wb"))
    handle:write("SAVE")
    handle:close()
    return "saved"
  end,
  quickLoad = function() return true end,
}}

local module = assert(loadfile(adapter_path))()
local platform = module.attach(app, native)
assert(app._3ds == platform)
assert(bottom.visible == true, "the game's own toolbar must stay visible")
assert(#states >= 1 and states[#states].cash == 12345)

local target = temp_root .. "slot.sav"
assert(app:save(target) == "saved")
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

local failing_native = {{
  begin_critical_io = native.begin_critical_io,
  end_critical_io = native.end_critical_io,
  atomic_commit = native.atomic_commit,
  recover_atomic = native.recover_atomic,
  set_notice = native.set_notice,
  set_state = native.set_state,
  request_redraw = native.request_redraw,
}}
local failing_app = {{
  savegame_dir = temp_root,
  ui = {{windows = {{}}, bottom_panel = {{visible = true, message_queue = {{}}, message_windows = {{}}}}}},
  dispatch = function() end,
  save = function() error("intentional failure") end,
}}
local failing_platform = module.attach(failing_app, failing_native)
local ok = pcall(failing_app.save, failing_app, temp_root .. "bad.sav")
assert(ok == false)
assert(notices[#notices].message == "SAVE FAILED" and notices[#notices].is_error == true)
assert(begin_count == 2 and end_count == 2)
assert(failing_platform ~= nil)
'''
            self.run_lua(script)


if __name__ == "__main__":
    unittest.main()
