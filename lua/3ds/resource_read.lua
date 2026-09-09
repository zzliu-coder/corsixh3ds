-- Read ordinary game resources with one bounded eager buffer allocation.
-- The caller selects the platform path; ISO providers retain their own reader.
local M = {}
local eager_limit = 4 * 1024 * 1024

function M.read(fs, path)
  if fs.provider then return fs:readContents(path) end
  local physical, path_error = fs:_getFilePath(path)
  if not physical then return physical, path_error end
  local file, open_error = io.open(physical, "rb")
  if not file then return nil, open_error end

  local function close()
    local owned = file
    file = nil -- the handle is closed exactly once, including thrown errors
    return pcall(owned.close, owned)
  end
  local function reopen()
    local closed, close_error = close()
    if not closed then error(close_error, 0) end
    file, open_error = io.open(physical, "rb")
    return file, open_error
  end
  local function read()
    local size = file:seek("end")
    -- Always restore the current handle to offset zero before any fallback.
    -- A failed restore closes it and opens a fresh rb handle from the start.
    if not file:seek("set", 0) then
      if not reopen() then return nil, open_error end
      return file:read("*a")
    end
    -- This limit bounds eager preallocation only. Larger resources still use
    -- the original reader; empty files keep readall's empty-string contract.
    if type(size) ~= "number" or size <= 0 or size > eager_limit or size % 1 ~= 0 then
      return file:read("*a")
    end
    local data, read_error, code = file:read(size)
    if not data and read_error then return nil, read_error, code end
    data = data or "" -- EOF after concurrent truncation, distinct from I/O error
    local tail, tail_error, tail_code = file:read("*a")
    if not tail then return nil, tail_error, tail_code end
    if #tail > 0 then return data .. tail end -- growth only; stable data is reused
    return data
  end

  local ok, data, read_error, code = pcall(read)
  local closed, close_error = true
  if file then closed, close_error = close() end
  if not ok then error(data, 0) end
  if data == nil then return nil, read_error, code end
  if not closed then error(close_error, 0) end
  -- A returned close failure retains the original resource-reader policy.
  return data
end

return M
