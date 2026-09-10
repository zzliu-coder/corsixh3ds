-- Normal media uses the upstream language/playlist UI. Only the file transport
-- and lifetime are platform-specific. No game/music/font payload lives here.
local M = {}

-- Menu text only. Audio-bank names, event keys and diagnostic protocols stay
-- language-independent. Resolve on opening/clicking a menu, never per sample.
local labels = {
  voice_language={"播报语音", "Voice language"},
  missing_chinese={"（未安装中文语音）", " (Chinese data missing)"},
  music_transport={"流式音乐；仅驻留当前语音", "Music: PCM stream / one active voice bank"},
  missing_voice={"未安装此语音，已保留当前设置。", "Voice data is not installed; current voice kept."},
  no_voice={"未安装语音素材", "Voice data is not installed"},
  save_name_rule={"名称须为 1—40 个英文字母、数字、空格、- 或 _。", "Use 1-40 English letters, numbers, spaces, - or _."},
  zh={"中文", "Chinese"}, en={"英语", "English"}, fr={"法语", "French"},
  de={"德语", "German"}, it={"意大利语", "Italian"}, es={"西班牙语", "Spanish"},
  sv={"瑞典语", "Swedish"}, unknown={"未知", "Unknown"},
}
function M.isChinese(app)
  local language = app.config and app.config.language
  if type(language) ~= "string" then return false end
  language = language:lower()
  -- Strings resolves language declarations case-insensitively. Config files
  -- may retain the lowercase spelling returned by the actual language menu.
  return language == "chinese (simplified)" or language == "简体中文" or
    language == "zh(s)" or language == "chi(s)" or language == "zho(s)"
end
function M.uiText(app, key)
  local values = assert(labels[key], "unknown media UI label")
  return values[M.isChinese(app) and 1 or 2]
end

function M.fontOptions(options)
  local result={}
  for key,value in pairs(options)do result[key]=value end
  -- Natural outline aspect ratio, integer body height inside 19-pixel rows.
  -- Explicit per-window sizes remain available; no final-screen stretching.
  if result.ttf_height==nil then result.ttf_height=14 end
  if result.ttf_width==nil then result.ttf_width=0 end
  return result
end

function M.speechFile(app, requested)
  local choice=app.config.speech_language or "en"
  for _,voice in ipairs(M.voices)do if voice.code==choice then return voice.file end end
  return requested or "Sound-0.dat"
end

M.voices={
  {code="zh",label="Chinese",file="Sound-CN.dat"},
  {code="en",label="English",file="Sound-EN.dat",original="Sound-0.dat"},
  {code="fr",label="French",file="Sound-FR.dat"},
  {code="de",label="German",file="Sound-DE.dat"},
  {code="it",label="Italian",file="Sound-IT.dat"},
  {code="es",label="Spanish",file="Sound-ES.dat"},
  {code="sv",label="Swedish",file="Sound-SV.dat"},
}
function M.speechPath(app,file)
  for _,voice in ipairs(M.voices)do
    if file==voice.file then
      if app.getFullPath then
        local path=app:getFullPath().."Voices/"..file
        if require("lfs").attributes(path,"mode")=="file" then return path end
      end
      if voice.original then return app.fs:_getFilePath("Sound/Data/"..voice.original) end
      return nil,"Voice data missing: "..voice.label
    end
  end
  return app.fs:_getFilePath("Sound/Data/"..file)
end
function M.voiceOptions(app)
  local result={}
  for _,voice in ipairs(M.voices)do
    if M.speechPath(app,voice.file) then result[#result+1]=voice end
  end
  return result
end
function M.voiceLabel(app)
  for _,voice in ipairs(M.voices)do
    if voice.code==(app.config.speech_language or "en") then return M.uiText(app, voice.code) end
  end
  return M.uiText(app, "unknown")
end
function M.hasChineseSpeech(app)
  return M.speechPath(app,"Sound-CN.dat")~=nil
end

function M.setSpeech(app,choice)
  local available=false
  for _,voice in ipairs(M.voiceOptions(app))do if voice.code==choice then available=true;break end end
  if not available then return false,M.uiText(app,"missing_voice") end
  local previous=app.config.speech_language
  app.config.speech_language=choice
  local ok,result=pcall(app.audio.initSpeech,app.audio)
  if not ok or result~=true then app.config.speech_language=previous;return false,tostring(result) end
  app:saveConfig()
  return true
end
function M.cycleSpeech(app)
  local choices=M.voiceOptions(app);local index=0
  for i,voice in ipairs(choices)do if voice.code==(app.config.speech_language or "en") then index=i;break end end
  if #choices==0 then return false,M.uiText(app,"no_voice") end
  return M.setSpeech(app,choices[index%#choices+1].code)
end

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

-- Playback observations live outside the persisted Audio object. Revisions
-- distinguish an actual finished-event handoff from manual Next/Stop/reload.
local music_states=setmetatable({}, {__mode="k"})
local function musicState(audio)
  local state=music_states[audio]
  if not state then state={revision=0};music_states[audio]=state end
  return state
end
function M.musicStatus(audio)
  local s=musicState(audio)
  return s.revision,s.finished_from,s.finished_to,s.failed==true
end

local function observe(native, phase, path)
  if native and native.diagnostic_line then
    native.diagnostic_line("music-state: "..phase.." file="..tostring(path or "none"))
  end
  if native and native.observe_memory then
    -- A file/decoder failure is not evidence of an allocation failure.
    native.observe_memory("sound_read", phase, path or "music", "Operation")
  end
end

function M.release(audio, api, native)
  local state=musicState(audio)
  state.revision=state.revision+1
  state.finished_from=nil;state.finished_to=nil;state.failed=false
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
      musicState(audio).revision=musicState(audio).revision+1
      observe(native, "music-playing", path)
      audio:notifyJukebox()
      return true
    end
    api.freeMusic(music)
  end
  info.enabled = false
  musicState(audio).failed=true
  observe(native, "music-file-failed", path)
  print("3DS music: " .. tostring(err))
  audio:notifyJukebox()
  return false, err
end

-- Called only by the original Audio:onMusicOver dispatch, after its original
-- loaded/playlist/current-track guards. The playlist policy remains upstream's.
-- SDL_mixer reports both completion and decoder termination via this callback;
-- these counters prove successful continuation, not error-free decoding.
function M.onMusicOver(audio)
  local state=musicState(audio)
  local before=state.revision
  local result=audio:playNextBackgroundTrack()
  if not state.failed and audio.background_music and state.revision>before then
    state.finished_from=before;state.finished_to=state.revision
  end
  return result
end

return M
