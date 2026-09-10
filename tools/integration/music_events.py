"""Bind real mixer completions to one playback generation across SDL dispatch."""
from sound_lifetime import replace_exact, SoundPatchError

AUDIO = 'CorsixTH/Src/sdl_audio.cpp'
CORE = 'CorsixTH/Src/sdl_core.cpp'
MARKER = '// CORSIXTH_3DS_MUSIC_EVENTS_R75'
HEADER = '''#include "config.h"
// CORSIXTH_3DS_MUSIC_EVENTS_R75
#ifdef CORSIXTH_3DS
#include "cth3ds/music_event_owner.hpp"
#endif'''

CALLBACK = '''void audio_music_over_callback() {
  SDL_Event e{};
  e.type = SDL_USEREVENT_MUSIC_OVER;
#ifdef CORSIXTH_3DS
  const auto token = cth3ds::music_event_owner.completed();
  if (!token) return;
  e.user.code = token;
  if (SDL_PushEvent(&e) <= 0)
    cth3ds::music_event_owner.delivery_failed(token);
#else
  SDL_PushEvent(&e);
#endif
}'''

PLAY_FENCE = '''#ifdef CORSIXTH_3DS
  // SDL's finish callback has no decoder argument. Join the old playback before
  // publishing the next identity, including failed play and same-object replay.
  Mix_HookMusicFinished(nullptr);
  Mix_HaltMusic();
  cth3ds::music_event_owner.invalidate_all();
  SDL_FlushEvent(SDL_USEREVENT_MUSIC_OVER);
  pLMusic->playback_token = cth3ds::music_event_owner.begin();
  Mix_HookMusicFinished(audio_music_over_callback);
  if (!pLMusic->playback_token) {
    lua_pushnil(L); lua_pushliteral(L, "Music event identity exhausted"); return 2;
  }
#endif
  int err = Mix_PlayMusic(pLMusic->pMusic,'''

AUDIO_SITES = (
    ('#include "config.h"', HEADER),
    ('  Mix_Music* pMusic{nullptr};', '''  Mix_Music* pMusic{nullptr};
#ifdef CORSIXTH_3DS
  cth3ds::MusicEventOwner::Token playback_token{0};
#endif'''),
    ('''    if (pMusic) {
      Mix_FreeMusic(pMusic);''', '''    if (pMusic) {
#ifdef CORSIXTH_3DS
      cth3ds::music_event_owner.invalidate(playback_token);
#endif
      Mix_FreeMusic(pMusic);'''),
    ('''void audio_music_over_callback() {
  SDL_Event e;
  e.type = SDL_USEREVENT_MUSIC_OVER;
  SDL_PushEvent(&e);
}''', CALLBACK),
    ('''int l_destroy(lua_State* L) {
  Mix_CloseAudio();''', '''int l_destroy(lua_State* L) {
#ifdef CORSIXTH_3DS
  cth3ds::music_event_owner.invalidate_all();
#endif
  Mix_CloseAudio();'''),
    ('''  if (owner->pMusic) { Mix_FreeMusic(owner->pMusic); owner->pMusic = nullptr; }''',
     '''  if (owner->pMusic) {
    cth3ds::music_event_owner.invalidate(owner->playback_token);
    Mix_FreeMusic(owner->pMusic); owner->pMusic = nullptr;
  }'''),
    ('  int err = Mix_PlayMusic(pLMusic->pMusic,', PLAY_FENCE),
    ('''                          static_cast<int>(luaL_optinteger(L, 2, 1)));
  if (err != 0) {
    lua_pushnil(L);''', '''                          static_cast<int>(luaL_optinteger(L, 2, 1)));
  if (err != 0) {
#ifdef CORSIXTH_3DS
    cth3ds::music_event_owner.invalidate(pLMusic->playback_token);
#endif
    lua_pushnil(L);'''),
    ('''int l_stop_music(lua_State* L) {
#ifdef CORSIXTH_3DS
  Mix_HookMusicFinished(nullptr);''', '''int l_stop_music(lua_State* L) {
#ifdef CORSIXTH_3DS
  cth3ds::music_event_owner.invalidate_all();
  Mix_HookMusicFinished(nullptr);'''),
)
CORE_SITES = (
    ('#include "sdl_core.h"', '''#include "sdl_core.h"
// CORSIXTH_3DS_MUSIC_EVENTS_R75
#ifdef CORSIXTH_3DS
#include "cth3ds/music_event_owner.hpp"
#endif'''),
    ('''        case SDL_USEREVENT_MUSIC_OVER:
          last_dispatch = dispatch_music_over;''',
     '''        case SDL_USEREVENT_MUSIC_OVER:
#ifdef CORSIXTH_3DS
          // The event may have left SDL's queue before a Lua operation stopped
          // or replaced that decoder. Queue flushing alone cannot revoke it.
          if (!cth3ds::music_event_owner.consume(e.user.code)) {
            nargs = 0;
            break;
          }
#endif
          last_dispatch = dispatch_music_over;'''),
)


def patch(text, sites):
    if MARKER in text:
        if text.count(MARKER) != 1 or any(text.count(new) != 1 for _, new in sites):
            raise SoundPatchError('music event ownership generated source drift')
        return text
    for old, new in sites:
        if text.count(new) == 1:
            continue
        text = replace_exact(text, old, new, 'music event ownership')
    return text


def patch_audio(text):
    """Called after R58's file stream/free/explicit-stop overlay."""
    return patch(text, AUDIO_SITES)


def transforms(root):
    present = [(root / name).is_file() for name in (AUDIO, CORE)]
    if not any(present):
        return
    if not all(present):
        raise SoundPatchError('music event audio/core source pair is incomplete')
    yield AUDIO, patch_audio((root / AUDIO).read_text())
    yield CORE, patch((root / CORE).read_text(), CORE_SITES)
    # WAV is the supported 3DS music source. An untagged desktop MIDI event must
    # have a deterministic zero code, never uninitialized bytes that could match
    # a live WAV token. Desktop dispatch ignores code and retains its behavior.
    midi = 'CorsixTH/Src/midi_player.cpp'
    if (root / midi).is_file():
        old = 'void midi_music_over_callback() {\n  SDL_Event e;'
        new = 'void midi_music_over_callback() {\n  SDL_Event e{};'
        yield midi, patch((root / midi).read_text(), ((old, new),))
