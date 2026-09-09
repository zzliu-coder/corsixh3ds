-- Appended inside the existing full native-persistence host fixture. The real
-- generated SaveGame/File/LoadGameFile and platform wrappers are executed;
-- both serialization and atomic_commit_existing are actual compiled C++.
package.loaded.native_probe = {Meta = NativeMeta}
local function inverse_permanents()
  for index = 1, 50 do
    local name, value = debug.getupvalue(SaveGame, index)
    if not name then break end
    if name == "MakePermanentObjectsTable" then return value(true) end
  end
  error("actual SaveGame permanents builder missing")
end

scenario("original-reader-loads-streamed-world", function()
  local app = fresh()
  app.world.payload = native_make(40000, 8) -- full GC during actual native writing
  assert(app:save(target))
  local encoded = read(target)
  assert(encoded == SaveGame(), "string/file output changed for same actual game state")
  local restored = assert(reference.load(encoded, inverse_permanents()))
  assert(restored.world.money == 777 and restored.map == restored.world.map)
  assert(restored.world.patients[1] == restored.world.last_cured)
  assert(native_length(restored.world.payload) == 40000)
  app.world.money = -1
  assert(app:load(target) and app.world.money == 777)
  assert(native_length(app.world.payload) == 40000)
end)

scenario("stream-native-faults-preserve-final-and-backup", function()
  local real_open = io.open
  local actual_commit = native.atomic_commit
  local commits = 0
  native.atomic_commit = function(...)
    commits = commits + 1
    return actual_commit(...)
  end
  local function seeded()
    local app = fresh()
    app.world.money = 444; assert(app:save(target))
    app.world.money = 555; assert(app:save(target))
    return app, read(target), read(target .. ".bak")
  end
  for _, mode in ipairs({1, 3, 5, 6, 7}) do
    local app, old, older = seeded()
    local before_cleanup, before_commit = cleaned, commits
    app.world.payload = native_make(45000, mode)
    assert(not pcall(app.save, app, target))
    assert(cleaned == before_cleanup + 1 and app.map.transient == "restored")
    assert(commits == before_commit and read(target) == old and read(target .. ".bak") == older)
    app.world.payload = nil; app.world.money = 888
    assert(app:save(target)); app.world.money = -1
    assert(app:load(target) and app.world.money == 888)
  end
  for _, fault in ipairs({{0, false}, {3, false}, {16391, false}, {40000, false}, {1000000, true}}) do
    local app, old, older = seeded()
    local before_cleanup, before_commit = cleaned, commits
    local _, _, _, _, _, opened, closed = stats()
    assert(opened == 0)
    app.world.payload = native_make(45000)
    io.open = function(path, mode)
      if path == target .. ".tmp" and mode == "wb" then return open_device(fault[1], fault[2]) end
      return real_open(path, mode)
    end
    local ok, err = pcall(app.save, app, target)
    io.open = real_open
    assert(not ok and tostring(err):find(fault[2] and "close" or "write", 1, true), tostring(err))
    local _, _, _, _, _, opened_after, closed_after = stats()
    assert(opened_after == 0 and closed_after == closed + 1)
    assert(cleaned == before_cleanup + 1 and app.map.transient == "restored")
    assert(commits == before_commit and read(target) == old and read(target .. ".bak") == older)
    app.world.payload = nil; app.world.money = 999
    assert(app:save(target)); app.world.money = -1
    assert(app:load(target) and app.world.money == 999)
  end
  native.atomic_commit = actual_commit
end)
