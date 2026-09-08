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

    path = 'CorsixTH/Lua/audio.lua'
    text = (root/path).read_text()
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
