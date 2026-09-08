-- Normal media uses the upstream language/playlist UI. Only the file transport
-- and lifetime are platform-specific. No game/music/font payload lives here.
local M = {}

function M.configure(config, root, attributes)
  attributes = attributes or require("lfs").attributes
  root = root:gsub("[/\\]+$", "") .. "/"
  -- Keep the user's selected language, and use the existing private subset.
  config.language = config.language or "English"
  local font = root .. "CorsixTH-SC-subset.ttf"
  if (not config.unicode_font or attributes(config.unicode_font, "mode") ~= "file")
      and attributes(font, "mode") == "file" then
    config.unicode_font = font
  end
  local directory = config.audio_music or root .. "Music"
  if attributes(directory, "mode") == "directory" then
    config.audio_music = directory
  else
    -- An optional missing directory must not make Audio:init's lfs.dir fatal.
    config.audio_music = nil
    config.play_music = false
  end
  -- Enabling remains an explicit config / original jukebox choice.
  config.play_music = config.play_music == true
end

local function observe(native, phase, path)
  if native and native.observe_memory then
    -- A file/decoder failure is not evidence of an allocation failure.
    native.observe_memory("sound_read", phase, path or "music", "Operation")
  end
end

function M.release(audio, api, native)
  -- Native stop suppresses the synthetic EOF callback and clears queued EOF
  -- events before another track starts. Otherwise a manual Next can skip twice.
  audio.load_music = false
  api.stopMusic()
  for _, info in ipairs(audio.background_playlist or {}) do
    if info.music then api.freeMusic(info.music); info.music = nil end
  end
  audio.background_music = nil
  audio.background_paused = nil
  if audio.old_bg_music_volume ~= nil then
    audio.app.config.music_volume = audio.old_bg_music_volume
    audio.old_bg_music_volume = nil
  end
  observe(native, "music-released")
end

function M.play(audio, index, api, native)
  local info = assert(audio.background_playlist[index], "Index not valid")
  if not audio.app.config.play_music then return end
  M.release(audio, api, native)
  local path = info.filename_music
  local music, err
  if type(path) ~= "string" or not path:lower():match("%.wav$") then
    err = "3DS music requires a preconverted WAV file"
  else
    observe(native, "music-file-before", path)
    -- Only the header and decoder buffers are read here. No Lua song string,
    -- no per-song worker, and no archive of inactive decoder objects.
    music, err = api.loadMusicFile(path)
  end
  if music then
    api.setMusicVolume(audio.app.config.music_volume)
    local ok
    ok, err = api.playMusic(music)
    if ok then
      info.music = music
      audio.background_music = music
      observe(native, "music-playing", path)
      audio:notifyJukebox()
      return true
    end
    api.freeMusic(music)
  end
  info.enabled = false
  observe(native, "music-file-failed", path)
  print("3DS music: " .. tostring(err))
  audio:notifyJukebox()
  return false, err
end

return M
