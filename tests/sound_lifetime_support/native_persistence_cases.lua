-- Exercise the real C++ serializer, generated persistance.lua, and platform.lua.
-- This table-world seam does not emulate native maps, graphics, audio, or FAT.
local directory = assert(os.getenv("CTH3DS_PERSIST_TESTDIR"))
local source = assert(os.getenv("CTH3DS_PERSIST_SOURCE"))
local platform = assert(os.getenv("CTH3DS_PLATFORM_SOURCE"))
function Noop() end
function strict_declare_global() end
function pause_gc_and_use_weak_keys(fn, value) fn(value) end
unpack = table.unpack
math.randomdump = function() return 12345 end
local native = {observations = 0, spans = {}, serial = 0, critical = 0}
function native.is_platform() return true end
function native.observe_memory() native.observations = native.observations + 1 end
function native.span_begin()
  native.serial = native.serial + 1
  native.spans[native.serial] = true
  return native.serial
end
function native.span_end(id) assert(native.spans[id]); native.spans[id] = nil end
function native.begin_critical_io() native.critical = native.critical + 1 end
function native.end_critical_io() native.critical = native.critical - 1; assert(native.critical >= 0) end
for _, name in ipairs({"flush_observations", "set_notice", "checkpoint", "request_redraw"}) do native[name] = Noop end
function native.shutdown() error("unexpected shutdown") end
package.loaded.th3ds = native
assert(loadfile(source))()
local Module = assert(loadfile(platform))()
local function exists(path)
  local f = io.open(path, "rb"); if not f then return false end
  assert(f:close()); return true
end
local function read(path)
  local f = assert(io.open(path, "rb")); local data = assert(f:read("*a")); assert(f:close()); return data
end
local function write(path, data)
  local f = assert(io.open(path, "wb")); assert(f:write(data)); assert(f:close())
end
function native.atomic_commit(temporary, final)
  if exists(final .. ".bak") then assert(os.remove(final .. ".bak")) end
  if exists(final) then assert(os.rename(final, final .. ".bak")) end
  assert(os.rename(temporary, final)); return true
end
local prepared, cleaned = 0, 0
function Prepare(map) prepared = prepared + 1; map.transient = nil end
function AfterSave(map) cleaned = cleaned + 1; map.transient = "restored" end
function SetCursor(ui, cursor) ui.cursor = cursor end
function UIMenuBar(ui) return {ui = ui, onChangeLanguage = Noop} end
function WorldExited(app) app.exited = (app.exited or 0) + 1 end
function AfterLoad(app) if app.fail_after_load then error("injected publication failure") end end
function MainMenu(app) app.world = nil; app.map = nil; app.ui = {menu_bar = UIMenuBar({app = app})} end
function Compatible() return true end
function ActualSave(app, path) return SaveGameFile(path) end
function ActualLoad(app, path) return LoadGameFile(path) end
local function fresh()
  local app = {config = {play_sounds = false}, modes = {}, video = {}, strings = {},
    audio = {playSoundEffects = Noop}, gfx = {load_info = {}}, fs = {}, moviePlayer = {},
    walls = {}, objects = {}, rooms = {}, humanoid_actions = {}, diseases = {},
    savegame_dir = directory .. "/", save = ActualSave, load = ActualLoad,
    worldExited = WorldExited, afterLoad = AfterLoad, loadMainMenu = MainMenu,
    checkCompatibility = Compatible}
  local map = {cells = {1, 4, 9}, transient = "restored", prepareForSave = Prepare,
    afterSave = AfterSave, registerTemperatureDisplayMethod = Noop}
  local patient = {name = "patient-one", cured = true}
  local world = {map = map, gfx_set = "full", savegame_version = 200,
    money = 777, patients = {patient}, receptionist = {name = "worker-one"},
    last_cured = patient, resetAnimations = Noop, updateUserActionsAllowed = Noop,
    updateScreenBlueFilter = Noop}
  world.self = world
  local ui = {world = world, cursor = "normal", resync = Noop, setCursor = SetCursor,
    onChangeResolution = Noop}
  ui.menu_bar = UIMenuBar(ui)
  app.world, app.map, app.ui = world, map, ui
  TheApp = app
  Module.attach(app, native, {resource_events = false, epoch = 1})
  return app
end
local passed = 0
local function scenario(name, test)
  test(); assert(native.critical == 0); assert(next(native.spans) == nil)
  passed = passed + 1; print("PASS native-persistence " .. name)
end
local target = directory .. "/roundtrip.sav"
scenario("actual-byte-roundtrip-and-aliases", function()
  local app = fresh()
  assert(app:save(target)); assert(#read(target) > 100)
  app.world.money = 5
  assert(app:load(target)); assert(app.world.money == 777)
  assert(app.map == app.world.map and app.ui.world == app.world and app.world.self == app.world)
  assert(app.world.patients[1] == app.world.last_cured and app.world.last_cured.cured)
  assert(app.world.receptionist.name == "worker-one")
  assert(app._3ds_preload_recovery and exists(app._3ds_preload_recovery))
end)
scenario("corrupt-primary-uses-committed-backup", function()
  local app = fresh(); assert(app:save(target))
  app.world.money = 999; assert(app:save(target))
  write(target, "invalid committed save")
  assert(app:load(target)); assert(app.world.money == 777)
end)
scenario("both-invalid-leave-live-world-and-ignore-tmp", function()
  local app = fresh(); local old = app.world
  assert(SaveGameFile(target .. ".tmp"))
  write(target, "invalid"); write(target .. ".bak", "invalid backup")
  assert(app:load(target) == false); assert(app.world == old)
end)
scenario("serializer-failure-cleans-map-and-preserves-save", function()
  local app = fresh(); assert(app:save(target)); local before = read(target)
  BadThread = coroutine.create(Noop); app.world.bad = BadThread
  local previous = cleaned
  assert(pcall(app.save, app, target) == false); assert(cleaned == previous + 1)
  assert(app.map.transient == "restored" and read(target) == before)
  app.world.bad = nil; BadThread = nil
end)
scenario("publication-failure-retains-reloadable-prior-progress", function()
  local app = fresh(); assert(app:save(target)); app.world.money = 321
  app.fail_after_load = true
  local ok, detail = app:load(target)
  assert(ok == false and tostring(detail):find("publication", 1, true))
  assert(app.world == nil and app._3ds_preload_recovery)
  local recovery = app._3ds_preload_recovery
  assert(exists(recovery)); app.fail_after_load = nil
  assert(app:load(recovery)); assert(app.world.money == 321)
end)
scenario("requested-recovery-is-not-overwritten", function()
  local app = fresh(); local recovery = directory .. "/recovery-before-load.sav"
  assert(app:save(recovery)); local before = read(recovery)
  app.world.money = 12
  assert(app:load(recovery)); assert(read(recovery) == before and app.world.money == 777)
  assert(app._3ds_preload_recovery == directory .. "/recovery-before-load-alt.sav")
end)
scenario("thirty-real-serialization-cycles", function()
  local app = fresh(); assert(app:save(target)); assert(app:load(target))
  collectgarbage("collect"); local initial = collectgarbage("count")
  for index = 1, 30 do
    app.world.money = index; assert(app:save(target)); app.world.money = -1
    assert(app:load(target)); assert(app.world.money == index)
  end
  collectgarbage("collect"); local final = collectgarbage("count")
  assert(final - initial < 64, "controlled Lua table-world retains excessive memory")
  print(string.format("model_lua_kib_initial=%.2f final=%.2f", initial, final))
end)
assert(prepared == cleaned)
print("native_persistence_cases=" .. passed .. " memory_observations=" .. native.observations)
print("device_and_native_map=NOT_PROVEN")
