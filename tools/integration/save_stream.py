"""One save transaction with an optional bounded native file sink."""
from sound_lifetime import replace_exact

SAVE_TRANSACTION = '''-- CORSIXTH_3DS_SAVE_OWNER_R68: diagnostic and cleanup facts belong to this request.
local function saveDiagnostic(owner, operation, site, callback, ...)
  if not callback then return true end
  if owner and operation then return owner:diagnostic(operation,site,callback,...) end
  return pcall(callback,...)
end
local function saveCleanup(owner, operation, site, value)
  if owner and operation then owner:cleanupFailure(operation,site,value)
  elseif TH3DS and TH3DS.operation_block then pcall(TH3DS.operation_block) end
end
local function saveError(value)
  if type(value)=="string" and debug and debug.traceback then return debug.traceback(value,2) end
  return value
end
-- CORSIXTH_3DS_SAVE_BUFFER_R75: call-local, never a persisted world/config flag.
local function saveBufferBytes(value)
  assert(value==nil or value==16384 or value==65536,"save buffer: 16384 or 65536 required")
  return value or 16384
end
function SaveGame(output_file, buffer_bytes)
  buffer_bytes = saveBufferBytes(buffer_bytes)
  -- CORSIXTH_3DS_SAVE_STREAM_R65: same graph/permanents for both writer modes.
  local state = {
    ui = TheApp.ui,
    world = TheApp.world,
    map = TheApp.map,
    random = math.randomdump(),
  }
  local prepared, phase = false, "prepare"
  local owner=TheApp._3ds and TheApp._3ds.operations
  local operation=owner and owner.current
  local function observe(phase,resource)
    if TH3DS then saveDiagnostic(owner,operation,phase,TH3DS.observe_memory,"save",phase,resource,"Operation") end
  end
  local dumped, result, err, obj, dump_us, write_us, write_max_us, flush_us = xpcall(function()
    observe("prepare-before","map")
    state.map:prepareForSave()
    prepared = true
    phase = "dump"
    observe("prepare-after","map")
    observe("dump-before","persist")
    -- CORSIXTH_3DS_SAVE_PHASES_R61
    observe("permanent-before","permanent")
    local permanent = MakePermanentObjectsTable(false)
    observe("permanent-after","permanent")
    observe("writer-before","persist")
    local result, err, obj, dump_us, write_us, write_max_us, flush_us
    if output_file then result, err, obj, dump_us, write_us, write_max_us, flush_us = persist.dump_file(state, permanent, output_file, buffer_bytes)
    else result, err, obj = persist.dump(state, permanent) end
    observe("writer-after","persist")
    return result, err, obj, dump_us, write_us, write_max_us, flush_us
  end,saveError)
  -- A diagnostic failure must never bypass the one matching afterSave call.
  observe("dump-after","persist")
  if prepared then observe("afterSave-before","map") end
  local cleaned, cleanup_error = true, nil
  if prepared then cleaned, cleanup_error = pcall(state.map.afterSave,state.map) end
  if not cleaned then saveCleanup(owner,operation,"map.afterSave",cleanup_error) end
  if prepared then observe("afterSave-after","map") end
  if not dumped then error(result,0) end
  if not result then error(err,0) end
  if not cleaned then error(cleanup_error,0) end
  if output_file then
    assert(result==true and type(err)=="number" and err>=0 and err<math.huge and err%1==0,
      "save dump_file: invalid success/byte count")
    assert(obj==nil or (type(obj)=="number" and obj>=0 and obj<math.huge and obj%1==0),
      "save dump_file: invalid flush count")
    return true, err, obj, dump_us, write_us, write_max_us, flush_us
  end
  return result
end
'''

FILE_PREFIX = '''function SaveGameFile(filename, buffer_bytes)
  if IS_3DS then
    buffer_bytes = saveBufferBytes(buffer_bytes) -- reject before open/truncate/prepare
    -- CORSIXTH_3DS_SAVE_IO_R74: bounded native IO and caller-owned close timings.
    -- CORSIXTH_3DS_SAVE_FILE_OWNER_R68
    local owner=TheApp._3ds and TheApp._3ds.operations
    local operation=owner and owner.current
    local timed,started=saveDiagnostic(owner,operation,"save_clock",TH3DS and TH3DS.clock_ms)
    local f, open_error = io.open(filename,"wb")
    assert(f,"save open: "..tostring(open_error))
    local saved, result, bytes, flushes, dump_us, write_us, write_max_us, flush_us = xpcall(function()
      local buffered, buffer_error = f:setvbuf("no")
      assert(buffered,"save setvbuf: "..tostring(buffer_error))
      return SaveGame(f, buffer_bytes)
    end,saveError)
    if TH3DS then saveDiagnostic(owner,operation,"close-before",TH3DS.observe_memory,"save","close-before","state-file","Operation") end
    local close_timed,close_started=saveDiagnostic(owner,operation,"save_clock",TH3DS and TH3DS.clock_ms)
    -- Caller owns the FILE; even prepare, writer, cleanup and observation
    -- exceptions reach this explicit close attempt exactly once.
    local closed, close_result, close_error = pcall(f.close,f)
    local close_ended,close_finished=saveDiagnostic(owner,operation,"save_clock",TH3DS and TH3DS.clock_ms)
    local close_ms=close_timed and close_ended and type(close_started)=="number" and type(close_finished)=="number"
      and close_finished>=close_started and close_finished-close_started or "unknown"
    local close_failure
    if not closed then close_failure=close_result else close_failure=close_error end
    if not closed or not close_result then saveCleanup(owner,operation,"file.close",close_failure) end
    if TH3DS then saveDiagnostic(owner,operation,"close-after",TH3DS.observe_memory,"save","close-after","state-file","Operation") end
    if not saved or result~=true then error(result,0) end
    if not closed or not close_result then
      if type(close_failure)=="string" then error("save close: "..close_failure,0) end
      error(close_failure,0)
    end
    local ended,finished=saveDiagnostic(owner,operation,"save_clock",TH3DS and TH3DS.clock_ms)
    local elapsed = timed and ended and type(started)=="number" and type(finished)=="number" and finished-started or "unknown"
    print("save-stream: mode=stream16k bytes="..tostring(bytes).." flush_count="..tostring(flushes or "unknown")
      .." elapsed_ms="..tostring(elapsed).." writer_includes_io=1 scope=save_file_including_close commit_included=0")
    return true
  end
'''


OLD_REPORT = '''    print("save-stream: mode=stream16k bytes="..tostring(bytes).." flush_count="..tostring(flushes or "unknown")
      .." elapsed_ms="..tostring(elapsed).." writer_includes_io=1 scope=save_file_including_close commit_included=0")'''

NEW_REPORT = '''    -- CORSIXTH_3DS_SAVE_REPORT_R66: one bounded native boot.log record.
    -- Emitted only after writer, map cleanup and close succeed. The caller's
    -- atomic commit has not run; this is a closed temporary file observation.
    local report = "save-stream: mode=stream"..tostring(math.floor(buffer_bytes/1024)).."k bytes="..tostring(bytes).." flush_count="..tostring(flushes or "unknown")
      .." elapsed_ms="..tostring(elapsed).." writer_includes_io=1 scope=save_file_including_close close_ok=1 commit_included=0"
    saveDiagnostic(owner,operation,"file_timing_report",TH3DS and TH3DS.save_io_timing,
      dump_us,write_us,write_max_us,flush_us,type(close_ms)=="number" and close_ms or nil)
    saveDiagnostic(owner,operation,"closed_file_report",TH3DS and TH3DS.diagnostic_line or print,report)'''


def transforms(root):
    path = 'CorsixTH/Lua/persistance.lua'
    text = (root / path).read_text()
    if 'CORSIXTH_3DS_SAVE_OWNER_R68' in text and 'CORSIXTH_3DS_SAVE_IO_R74' not in text:
        raise ValueError('save Lua view predates R74; regenerate from pinned source')
    if 'CORSIXTH_3DS_SAVE_IO_R74' in text and 'CORSIXTH_3DS_SAVE_BUFFER_R75' not in text:
        raise ValueError('save Lua view predates R75; regenerate from pinned source')
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
    if 'CORSIXTH_3DS_SAVE_REPORT_R66' not in text:
        text = replace_exact(text, OLD_REPORT, NEW_REPORT, 'collectable closed-file save counters')
    if 'CORSIXTH_3DS_SAVE_OWNER_R68' not in text:
        start=text.index('function SaveGame(output_file)\n')
        end=text.index('\n--! Save a game to disk.',start)
        text=text[:start]+SAVE_TRANSACTION+text[end:]
        start=text.index('function SaveGameFile(filename)\n')
        end=text.index('  local data = SaveGame()',start)
        prefix=FILE_PREFIX.replace(OLD_REPORT,NEW_REPORT)
        text=text[:start]+prefix+text[end:]
    yield path, text
    # The ordinary caller passes no option. Only Operations' guarded private
    # route forwards a bounded size through this original writer reference.
    path = 'CorsixTH/Lua/app.lua'
    text = (root/path).read_text()
    marker = '-- CORSIXTH_3DS_SAVE_BUFFER_FORWARD_R75'
    if marker not in text:
        text = replace_exact(text,
            'function App:save(filename)\n  return SaveGameFile(filename)\nend',
            marker+'\nfunction App:save(filename, buffer_bytes)\n  return SaveGameFile(filename, buffer_bytes)\nend',
            'call-local bounded save writer capacity')
    yield path, text
