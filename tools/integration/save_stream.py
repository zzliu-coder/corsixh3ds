"""One save transaction with an optional bounded native file sink."""
from sound_lifetime import replace_exact

SAVE_TRANSACTION = '''function SaveGame(output_file)
  -- CORSIXTH_3DS_SAVE_STREAM_R65: same graph/permanents for both writer modes.
  local state = {
    ui = TheApp.ui,
    world = TheApp.world,
    map = TheApp.map,
    random = math.randomdump(),
  }
  local prepared, phase = false, "prepare"
  local dumped, result, err, obj = pcall(function()
    if TH3DS then TH3DS.observe_memory("save", "prepare-before", "map", "Operation") end
    state.map:prepareForSave()
    prepared = true
    phase = "dump"
    if TH3DS then TH3DS.observe_memory("save", "prepare-after", "map", "Operation") end
    if TH3DS then TH3DS.observe_memory("save","dump-before","persist","Operation") end
    -- CORSIXTH_3DS_SAVE_PHASES_R61
    if TH3DS then TH3DS.observe_memory("save","permanent-before","permanent","Operation") end
    local permanent = MakePermanentObjectsTable(false)
    if TH3DS then TH3DS.observe_memory("save","permanent-after","permanent","Operation") end
    if TH3DS then TH3DS.observe_memory("save","writer-before","persist","Operation") end
    local result, err, obj
    if output_file then result, err, obj = persist.dump_file(state, permanent, output_file)
    else result, err, obj = persist.dump(state, permanent) end
    if TH3DS then TH3DS.observe_memory("save","writer-after","persist","Operation") end
    return result, err, obj
  end)
  -- A diagnostic failure must never bypass the one matching afterSave call.
  local noted, note_error = pcall(function()
    if TH3DS then TH3DS.observe_memory("save","dump-after","persist","Operation") end
    if prepared and TH3DS then TH3DS.observe_memory("save","afterSave-before","map","Operation") end
  end)
  local cleaned, cleanup_error = true, nil
  if prepared then cleaned, cleanup_error = pcall(state.map.afterSave,state.map) end
  local noted_after, note_after_error = pcall(function()
    if prepared and TH3DS then TH3DS.observe_memory("save","afterSave-after","map","Operation") end
  end)
  local detail = ""
  if not dumped then detail = "save "..phase..": "..tostring(result)
  elseif not result then detail = "save dump: "..tostring(err).." object="..tostring(obj) end
  if not cleaned then detail = detail.." save afterSave: "..tostring(cleanup_error) end
  if not noted then detail = detail.." save observation: "..tostring(note_error) end
  if not noted_after then detail = detail.." save observation: "..tostring(note_after_error) end
  if detail~="" then error(detail) end
  if output_file then
    assert(result==true and type(err)=="number" and err>=0 and err<math.huge and err%1==0,
      "save dump_file: invalid success/byte count")
    assert(obj==nil or (type(obj)=="number" and obj>=0 and obj<math.huge and obj%1==0),
      "save dump_file: invalid flush count")
    return true, err, obj
  end
  return result
end
'''

FILE_PREFIX = '''function SaveGameFile(filename)
  if IS_3DS then
    local started = TH3DS and TH3DS.clock_ms and TH3DS.clock_ms()
    local f, open_error = io.open(filename,"wb")
    assert(f,"save open: "..tostring(open_error))
    local saved, result, bytes, flushes = pcall(function()
      local buffered, buffer_error = f:setvbuf("no")
      assert(buffered,"save setvbuf: "..tostring(buffer_error))
      return SaveGame(f)
    end)
    local noted, note_error = pcall(function()
      if TH3DS then TH3DS.observe_memory("save","close-before","state-file","Operation") end
    end)
    -- Caller owns the FILE; even prepare, writer, cleanup and observation
    -- exceptions reach this explicit close attempt exactly once.
    local closed, close_result, close_error = pcall(f.close,f)
    local noted_after, note_after_error = pcall(function()
      if TH3DS then TH3DS.observe_memory("save","close-after","state-file","Operation") end
    end)
    local detail = ""
    if not saved or result~=true then detail = "save stream: "..tostring(result) end
    if not closed or not close_result then detail = detail.." save close: "..tostring(close_error or close_result) end
    if not noted then detail = detail.." save observation: "..tostring(note_error) end
    if not noted_after then detail = detail.." save observation: "..tostring(note_after_error) end
    if detail~="" then error(detail) end
    local elapsed = started and TH3DS.clock_ms()-started or "unknown"
    print("save-stream: mode=stream16k bytes="..tostring(bytes).." flush_count="..tostring(flushes or "unknown")
      .." elapsed_ms="..tostring(elapsed).." writer_includes_io=1 scope=save_file_including_close commit_included=0")
    return true
  end
'''


def transforms(root):
    path = 'CorsixTH/Lua/persistance.lua'
    text = (root / path).read_text()
    if 'CORSIXTH_3DS_SAVE_STREAM_R65' not in text:
        start = text.index('function SaveGame()\n')
        end = text.index('\n--! Save a game to disk.', start)
        old = text[start:end]
        # Phase transforms must already have run; reject unfamiliar source.
        assert old.count('state.map:prepareForSave()') == 1
        assert old.count('pcall(state.map.afterSave,state.map)') == 1
        assert 'CORSIXTH_3DS_SAVE_PHASES_R61' in old
        text = replace_exact(text, old, SAVE_TRANSACTION, 'shared stream save transaction')
        text = replace_exact(text, 'function SaveGameFile(filename)\n', FILE_PREFIX,
                             'early-open stream save with unconditional close')
    yield path, text
