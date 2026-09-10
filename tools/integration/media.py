"""Pinned real font/audio entry points; private media stays outside source Git."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError
from .font_cache import transforms as font_transforms

NATIVE_FILE_MUSIC = r'''
#ifdef CORSIXTH_3DS
// R58: SDL_mixer's WAV decoder retains a file RWops and a bounded decode buffer.
// The userdata owns the decoder only, never a full Lua string containing a song.
int l_load_music_file(lua_State* L) {
  const char* path = luaL_checkstring(L, 1);
  music* owner = luaT_stdnew<music>(L, luaT_environindex, true);
  SDL_RWops* stream = SDL_RWFromFile(path, "rb");
  Mix_Music* value = stream ? Mix_LoadMUSType_RW(stream, MUS_WAV, 1) : nullptr;
  if (!value) {
    lua_pushnil(L); lua_pushstring(L, Mix_GetError()); return 2;
  }
  owner->pMusic = value;
  return 1;
}
int l_free_music(lua_State* L) {
  music* owner = luaT_testuserdata<music>(L, 1);
  if (owner->pMusic) { Mix_FreeMusic(owner->pMusic); owner->pMusic = nullptr; }
  return 0;
}
#endif
'''

def transforms(root):
    path = 'CorsixTH/Lua/app.lua'
    text = (root/path).read_text()
    marker = '-- CORSIXTH_3DS_MEDIA_R58'
    if marker not in text:
        text = replace_exact(text, '    self.config.language="English"',
            '''    -- CORSIXTH_3DS_MEDIA_R58
    require("3ds.media").configure(self.config, self:getFullPath())''', 'media config')
        text = replace_exact(text, '    self.config.play_music = false',
            '    -- play_music is preserved by 3ds.media after checking the directory.', 'music preference')
        text = replace_exact(text, '''    -- Sound effects stay on; music does not. The original music is
    -- XMI/MIDI and this build has no MIDI synthesiser, so every track
    -- would fail to load - after spawning a loader thread each. Off is
    -- both the honest state and a faster boot.''',
            '    -- Sound effects stay on; optional music uses preconverted file streams.', 'media comment')
    yield path, text

    yield from font_transforms(root)

    path = 'CorsixTH/Lua/config_finder.lua'
    text = (root/path).read_text()
    if 'speech_language = [[en]]' not in text:
        text=replace_exact(text,'    announcement_volume = 0.5,',
            '    announcement_volume = 0.5,\n    speech_language = [[en]],','persistent voice default')
        text=replace_exact(text,"param(config_values, 'announcement_volume') .. [=[",
            "param(config_values, 'announcement_volume') ..\nparam(config_values, 'speech_language') .. [=[",'voice config writer')
    yield path,text

    path = 'CorsixTH/Lua/graphics.lua'
    text = (root/path).read_text()
    marker = '-- CORSIXTH_3DS_FONT_METRICS_R59'
    if marker not in text:
        text=replace_exact(text,'function Graphics:_loadTrueTypeFont(name, sprite_table, font_options)',
            '''function Graphics:_loadTrueTypeFont(name, sprite_table, font_options)
  -- CORSIXTH_3DS_FONT_METRICS_R59
  if TH3DS then font_options=require("3ds.media").fontOptions(font_options) end''','handheld font metrics')
        text=replace_exact(text,'return string.format("%s,%d,%d,%s,%s,%s,%s",',
            'return string.format("%s,%d,%d,%s,%s,%s,%s,%s,%s",','font metric cache format')
        text=replace_exact(text,'    font_options.apply_ui_scale and "s" or "f")',
            '''    font_options.apply_ui_scale and "s" or "f",
    tostring(font_options.ttf_width), tostring(font_options.ttf_height))''','font metric cache identity')
    # Graphics already owns a checked local TH3DS. IS_3DS is local to other
    # modules and cannot be read here under upstream strict.lua. Upgrade the
    # retained R59 overlay as well as generating a clean upstream tree.
    old='  if IS_3DS then font_options=require("3ds.media").fontOptions(font_options) end'
    if old in text:
        text=replace_exact(text,old,old.replace('IS_3DS','TH3DS'),'local font platform scope')
    yield path,text

    path = 'CorsixTH/Src/th_gfx_font.cpp'
    text = (root/path).read_text()
    old='  if (is_monochrome() || iHeight <= 14 || iWidth <= 9) {'
    new='''#ifdef CORSIXTH_3DS
  // A zero width explicitly requests FreeType's natural aspect ratio. Avoid
  // the desktop minimum-width rule enlarging 14px CJK bodies beyond UI rows.
  if (iWidth == 0 && iHeight > 0) return FT_Set_Pixel_Sizes(font_face, 0, iHeight);
#endif
''' + old
    if new not in text:text=replace_exact(text,old,new,'natural aspect handheld font')
    yield path,text

    path = 'CorsixTH/Lua/audio.lua'
    text = (root/path).read_text()
    old='    speech_file=speech_file or "Sound-0.dat"'
    new='    speech_file=require("3ds.media").speechFile(self.app,speech_file) -- R59 independent voice'
    if new not in text:text=replace_exact(text,old,new,'independent speech selection')
    old='    assert(not self.not_loaded,"audio device unavailable")'
    new='    if self.not_loaded then return true end -- disabled audio retains the next voice choice'
    if new not in text:text=replace_exact(text,old,new,'audio-off language change')
    old='    local path,err=self.app.fs:_getFilePath("Sound"..pathsep.."Data"..pathsep..speech_file)'
    new='    local path,err=require("3ds.media").speechPath(self.app,speech_file)'
    if new not in text:text=replace_exact(text,old,new,'prepared voice path')
    if '-- CORSIXTH_3DS_MUSIC_R58' not in text:
        for old, new in (
            ('  local waveform = list_to_set(self.allowed_waveform_formats)',
             '''  -- CORSIXTH_3DS_MUSIC_R58: only the bounded WAV decoder on handheld.
  local waveform = list_to_set(IS_3DS and {"WAV"} or self.allowed_waveform_formats)'''),
            ('  local instructional = list_to_set(self.allowed_instructional_formats)',
             '  local instructional = list_to_set(IS_3DS and {} or self.allowed_instructional_formats)'),
            ('function Audio:playBackgroundTrack(index)', '''function Audio:playBackgroundTrack(index)
  if IS_3DS then return require("3ds.media").play(self, index, SDL.audio, TH3DS) end'''),
            ('function Audio:stopBackgroundTrack()', '''function Audio:stopBackgroundTrack()
  if IS_3DS then
    require("3ds.media").release(self, SDL.audio, TH3DS)
    self:notifyJukebox()
    return
  end'''),
            ('function Audio:destroy()', '''function Audio:destroy()
  if IS_3DS then require("3ds.media").release(self, SDL.audio, TH3DS) end'''),
        ):
            text = replace_exact(text, old, new, 'music real path')
    old = '  if music_dir then\n    _f, _s, _v = lfs.dir(music_dir)'
    if old in text:
        text = replace_exact(text, old, '''  if IS_3DS and not music_dir then
    _f, _s, _v = pairs({}) -- optional music absent; never scan original MIDI
  elseif music_dir then
    _f, _s, _v = lfs.dir(music_dir)''', 'optional music directory')
    yield path, text

    path = 'CorsixTH/Lua/dialogs/resizables/sound_setting.lua'
    text = (root/path).read_text()
    marker='  -- CORSIXTH_3DS_SPEECH_SETTINGS_R59'
    if marker not in text:
        begin=text.index('  local midi_api_label =')
        end=text.index('\n  -- jukebox',begin)
        desktop=text[begin:end]
        handheld='''  -- CORSIXTH_3DS_SPEECH_SETTINGS_R59
  if self.app.is_3ds then
    local media=require("3ds.media")
    self.default_api_panels={};self.midi_api_panels={}
    self:addBevelPanel(LBL_X,y,LBL_WIDTH,LBL_HEIGHT,col_shadow,col_bg,col_bg)
      :setLabel("Voice language").lowered=true
    local label=media.voiceLabel(app)
    local available=#media.voiceOptions(app)>1
    if not media.hasChineseSpeech(app) then label=label.." (Chinese data missing)" end
    self.voice_panel=self:addBevelPanel(BTN_X,y,BTN_WIDTH,BTN_HEIGHT,Colours.Setting,nil,nil,nil,Colours.SettingActive)
      :setLabel(label)
    self.voice_panel:makeButton(0,0,BTN_WIDTH,BTN_HEIGHT,nil,self.buttonVoiceLanguage):enable(available)
    self:addBevelPanel(LBL_X,y+25,BIG_BTN_WIDTH,LBL_HEIGHT,col_shadow,col_bg,col_bg)
      :setLabel("Music: PCM stream / one active voice bank").lowered=true
  else
'''+desktop+'''
  end
'''
        text=text[:begin]+handheld+text[end:]
        text+='''
function UISoundSettings:buttonVoiceLanguage()
  local media=require("3ds.media")
  local ok,err=media.cycleSpeech(self.app)
  if ok then self.voice_panel:setLabel(media.voiceLabel(self.app))
  else self.ui:addWindow(UIInformation(self.ui,{err})) end
end
'''
    old=marker+'\n  if IS_3DS then'
    if old in text:
        text=replace_exact(text,old,marker+'\n  if self.app.is_3ds then','sound window platform scope')
    for signature in ('function UISoundSettings:dropdownMidiApi(activate)',
                      'function UISoundSettings:dropdownMidiPort(activate)'):
        old=signature+'\n  if IS_3DS then return end'
        new=signature+'\n  if self.app.is_3ds then return end'
        if old in text:text=replace_exact(text,old,new,'MIDI callback platform scope')
        elif new not in text:text=replace_exact(text,signature,new,'inactive handheld MIDI controls')
    # Upgrade the retained in-progress R59 generated tree as well as a clean
    # upstream tree. No duplicate controls/functions on incremental builds.
    old='''    local label=app.config.speech_language=="zh" and "Chinese" or "English"
    local available=media.hasChineseSpeech(app)
    if not available then label=label.." (Chinese data missing)" end'''
    if old in text:
        text=replace_exact(text,old,'''    local label=media.voiceLabel(app)
    local available=#media.voiceOptions(app)>1
    if not media.hasChineseSpeech(app) then label=label.." (Chinese data missing)" end''','voice catalog upgrade')
    old='''  local choice=self.app.config.speech_language=="zh" and "en" or "zh"
  local ok,err=require("3ds.media").setSpeech(self.app,choice)
  if ok then self.voice_panel:setLabel(choice=="zh" and "Chinese" or "English")'''
    if old in text:
        text=replace_exact(text,old,'''  local media=require("3ds.media")
  local ok,err=media.cycleSpeech(self.app)
  if ok then self.voice_panel:setLabel(media.voiceLabel(self.app))''','voice cycling upgrade')
    for old, new in (
        (':setLabel("Voice language")', ':setLabel(media.uiText(app,"voice_language"))'),
        ('label=label.." (Chinese data missing)"', 'label=label..media.uiText(app,"missing_chinese")'),
        (':setLabel("Music: PCM stream / one active voice bank")', ':setLabel(media.uiText(app,"music_transport"))'),
    ):
        if old in text:
            text=replace_exact(text,old,new,'bilingual handheld media menu')
    yield path,text

    path = 'CorsixTH/Src/sdl_audio.cpp'
    text = (root/path).read_text()
    if NATIVE_FILE_MUSIC not in text:
        text = replace_exact(text, 'int l_music_volume(lua_State* L) {',
                             NATIVE_FILE_MUSIC + '\nint l_music_volume(lua_State* L) {', 'file music native')
        text = replace_exact(text, '  music* pLMusic = luaT_testuserdata<music>(L, -1);',
            '''  music* pLMusic = luaT_testuserdata<music>(L, 1);
  if (!pLMusic->pMusic) { lua_pushnil(L); lua_pushliteral(L, "Music is closed"); return 2; }''',
            'music ownership guard')
        text = replace_exact(text, '''int l_stop_music(lua_State* L) {
  Mix_HaltMusic();''', '''int l_stop_music(lua_State* L) {
#ifdef CORSIXTH_3DS
  Mix_HookMusicFinished(nullptr);
#endif
  Mix_HaltMusic();
#ifdef CORSIXTH_3DS
  SDL_FlushEvent(SDL_USEREVENT_MUSIC_OVER);
  Mix_HookMusicFinished(audio_music_over_callback);
#endif''', 'explicit stop is not EOF')
        text = replace_exact(text, 'constexpr std::array<struct luaL_Reg, 8> sdl_musiclib{',
            '''#ifdef CORSIXTH_3DS
constexpr std::array<struct luaL_Reg, 10> sdl_musiclib{
#else
constexpr std::array<struct luaL_Reg, 8> sdl_musiclib{
#endif''', 'file music registration size')
        text = replace_exact(text, '     {"loadMusicAsync", l_load_music_async},',
            '''     {"loadMusicAsync", l_load_music_async},
#ifdef CORSIXTH_3DS
     {"loadMusicFile", l_load_music_file},
     {"freeMusic", l_free_music},
#endif''', 'file music registration')
    yield path, text

def patch_media(root: Path):
    changed = []
    for name, text in transforms(root):
        path = root/name
        if path.read_text() != text:
            path.write_text(text)
            changed.append(name)
    return changed

def check_media(root: Path):
    try:
        return ['media integration differs: ' + name for name, text in transforms(root)
                if (root/name).read_text() != text]
    except (OSError, SoundPatchError) as e:
        return [str(e)]
