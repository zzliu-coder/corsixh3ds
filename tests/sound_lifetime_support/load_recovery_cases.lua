-- Real Lua + real files. Game loading/writing is narrowed to a text-state seam.
local Module = assert(loadfile(MODULE_FILE))()
local function write(path, text)
  local file = assert(io.open(path, "wb")); assert(file:write(text)); assert(file:close())
end
local function read(path)
  local file = assert(io.open(path, "rb")); local value = assert(file:read("*a")); assert(file:close()); return value
end
local function exists(path)
  local file = io.open(path, "rb"); if not file then return false end; file:close(); return true
end
local function resolve(path)
  return path:gsub("\\", "/"):gsub("/[^/]+$", function(tail) return tail:lower() end)
end
local primary = TESTDIR .. "/recovery-before-load.sav"
local alternate = TESTDIR .. "/recovery-before-load-alt.sav"
local function setup(requested, failure, menu)
  for _, path in ipairs({primary, alternate, TESTDIR.."/quicksave.qs", TESTDIR.."/normal.sav"}) do
    write(path, "TARGET:"..path); write(path..".bak", "BACKUP:"..path)
  end
  local app = {savegame_dir = TESTDIR.."/", world = not menu and {}, saved = 0, loaded = 0}
  function app:save(path)
    self.saved = self.saved + 1; self.last_save = path
    if failure == "false" then return false end
    if failure == "throw" then error("injected writer failure") end
    write(path, "CURRENT-HOSPITAL"); return true
  end
  function app:load(path)
    self.loaded = self.loaded + 1; self.loaded_path = resolve(path); self.loaded_text = read(self.loaded_path)
    if failure == "load" then return false, "injected load failure" end
    return true
  end
  local native = {open_spans={},next_span=0}
  function native.span_begin()
    native.next_span=native.next_span+1; native.open_spans[native.next_span]=true
    return native.next_span
  end
  function native.span_end(token)
    assert(native.open_spans[token]); native.open_spans[token]=nil
  end
  for _, name in ipairs({"observe_memory","flush_observations","begin_critical_io",
                         "end_critical_io","set_notice","checkpoint","request_redraw"}) do
    native[name]=function() end
  end
  function native.atomic_commit(temporary, final_path)
    if exists(final_path..".bak") then assert(os.remove(final_path..".bak")) end
    if exists(final_path) then assert(os.rename(final_path,final_path..".bak")) end
    assert(os.rename(temporary,final_path)); app.last_save=final_path; return true
  end
  local adapter = Module.attach(app,native,{resource_events=false,epoch=1})
  app.native=native
  return app,adapter
end
local function check(path, expected_save)
  local app = setup(path)
  local target = resolve(path); local expected = read(target)
  assert(app:load(path)==true)
  assert(app.loaded_text == expected, "requested save was overwritten: "..path)
  assert(read(target) == expected, "requested file changed")
  assert(app.last_save == expected_save)
  assert(read(expected_save)=="CURRENT-HOSPITAL")
  assert(app._3ds_preload_recovery == expected_save)
  assert(next(app.native.open_spans)==nil,"unclosed operation span")
end
local cases = {
  ["primary-target"] = function() check(primary,alternate) end,
  ["backup-target"] = function() check(primary..".bak",alternate) end,
  ["alternate-target"] = function() check(alternate,primary) end,
  ["normal-target"] = function() check(TESTDIR.."/normal.sav",primary) end,
  ["uppercase-fat-name"] = function() check(TESTDIR.."/RECOVERY-BEFORE-LOAD.SAV",alternate) end,
  ["windows-separator"] = function() check((TESTDIR.."/RECOVERY-BEFORE-LOAD.SAV"):gsub("/","\\"),alternate) end,
  ["save-false"] = function()
    local app = setup(primary,"false"); local before=read(primary)
    assert(app:load(primary)==false); assert(app.loaded==0); assert(read(primary)==before)
    assert(app._3ds_preload_recovery==nil)
  end,
  ["save-throws"] = function()
    local app = setup(primary,"throw"); local before=read(primary)
    assert(app:load(primary)==false); assert(app.loaded==0); assert(read(primary)==before)
  end,
  ["menu-load"] = function()
    local app = setup(primary,nil,true); local before=read(primary)
    assert(app:load(primary)==true); assert(app.saved==0); assert(app.loaded_text==before)
    assert(app._3ds_preload_recovery==nil)
  end,
  ["failed-publication-recovery"] = function()
    local app = setup(primary,"load"); local before=read(primary)
    assert(app:load(primary)==false); assert(read(primary)==before)
    assert(app._3ds_preload_recovery==alternate); assert(read(alternate)=="CURRENT-HOSPITAL")
  end,
  ["quicksave-target"] = function()
    local app=setup(TESTDIR.."/quicksave.qs"); local before=read(TESTDIR.."/quicksave.qs")
    assert(app:quickLoad()==true); assert(app.loaded_text==before); assert(app.last_save==primary)
  end,
}
assert(cases[CASE],"unknown case")()
print("PASS load-recovery "..CASE)
