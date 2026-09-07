"""Move 3DS sound-over deadlines onto the existing game event thread.

SDL2 timer callbacks run on a separate thread. The upstream map and recycled
int pointers therefore cannot safely be used by both those callbacks and Lua.
The bounded records below carry event IDs by value, retain queue-full work, and
invalidate already queued events when stopped, paused, or replaced.
"""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

STATE_OLD = '''struct map_timer_info {
  SDL_TimerID timer_id;
  Uint32 interval;
  Uint32 start_time;
  int* callback_id_ptr;
};

std::array<int, 1000> played_sound_callback_ids;
int played_sound_callback_index = 0;
std::map<int, map_timer_info> map_sound_timers;'''
STATE_NEW = '''#ifdef CORSIXTH_3DS
// CORSIXTH_3DS_MAIN_THREAD_SOUND_CALLBACKS_V1
struct sound_deadline {
  int id{};
  Uint32 remaining{}, start{}, token{};
  bool active{}, paused{}, queued{};
};
std::array<sound_deadline, 1000> sound_deadlines{};
Uint32 sound_deadline_token = 0;
bool sound_deadlines_suspended = false;
Uint32 sound_suspend_started = 0;

Uint32 next_sound_token() {
  if (++sound_deadline_token == 0) ++sound_deadline_token;
  return sound_deadline_token;
}
void clear_sound_deadlines() {
  for (auto& item : sound_deadlines) item.active = false;
}
bool schedule_sound_deadline(int id, Uint32 duration, Uint32 now) {
  if (sound_deadlines_suspended) now = sound_suspend_started;
  sound_deadline* slot = nullptr;
  for (auto& item : sound_deadlines) {
    if (item.active && item.id == id) { slot = &item; break; }
    if (!item.active && !slot) slot = &item;
  }
  if (!slot) return false;
  *slot = {id, duration, now, next_sound_token(), true, false, false};
  return true;
}
void stop_sound_deadline(int id) {
  for (auto& item : sound_deadlines)
    if (item.active && item.id == id) item.active = false;
}
void pause_sound_deadline(int id, bool pause, Uint32 now) {
  if (sound_deadlines_suspended) now = sound_suspend_started;
  for (auto& item : sound_deadlines) {
    if (!item.active || item.id != id || item.paused == pause) continue;
    if (pause) {
      const Uint32 elapsed = now - item.start; // defined modulo tick wrap
      item.remaining = elapsed < item.remaining ? item.remaining - elapsed : 0;
    }
    item.start = now;
    item.paused = pause;
    item.queued = false;
    item.token = next_sound_token(); // reject any already queued old event
  }
}
#else
''' + STATE_OLD + '''
#endif'''

CALLBACK_OLD = '''Uint32 played_sound_callback(Uint32 interval, void* param) {
  SDL_Event e;
  e.type = SDL_USEREVENT_SOUND_OVER;
  e.user.data1 = param;
  int iSoundID = *(static_cast<int*>(param));
  SDL_RemoveTimer(map_sound_timers[iSoundID].timer_id);
  map_sound_timers.erase(iSoundID);
  SDL_PushEvent(&e);

  return interval;
}'''

SCHEDULE_OLD = '''    if (played_sound_callback_index == played_sound_callback_ids.size())
      played_sound_callback_index = 0;

    played_sound_callback_ids[played_sound_callback_index] =
        static_cast<int>(luaL_checkinteger(L, 6));
    int& callback_id = played_sound_callback_ids[played_sound_callback_index];

    Uint32 interval =
        static_cast<Uint32>(pArchive->get_sound_duration(iIndex) * (loops + 1) +
                            iPlayedCallbackDelay);
    SDL_TimerID timersID =
        SDL_AddTimer(interval, played_sound_callback, &callback_id);
    map_sound_timers.emplace(std::pair<int, map_timer_info>(
        callback_id, {timersID, interval, SDL_GetTicks(), &callback_id}));
    played_sound_callback_index++;'''
SCHEDULE_NEW = '''#ifdef CORSIXTH_3DS
    const int callback_id = static_cast<int>(luaL_checkinteger(L, 6));
    const uint64_t duration = uint64_t(pArchive->get_sound_duration(iIndex)) *
        (uint64_t(loops) + 1U) + uint64_t(iPlayedCallbackDelay > 0 ? iPlayedCallbackDelay : 0);
    const Uint32 interval = static_cast<Uint32>(std::min<uint64_t>(duration, 0x7fffffffU));
    if (!schedule_sound_deadline(callback_id, interval, SDL_GetTicks())) {
      pEffects->stop(handle);
      return luaL_error(L, "sound completion queue capacity exceeded");
    }
#else
''' + SCHEDULE_OLD + '''
#endif'''

PAUSE_OLD = '''  if (auto itr = map_sound_timers.find(callbackId);
      itr != map_sound_timers.end()) {
    switch (pauseResult) {
      case sound_player::toggle_pause_result::paused: {
        Uint32 elapsed = SDL_GetTicks() - itr->second.start_time;
        itr->second.interval -= elapsed;
        SDL_RemoveTimer(itr->second.timer_id);
        break;
      }
      case sound_player::toggle_pause_result::resumed:
        itr->second.start_time = SDL_GetTicks();
        itr->second.timer_id =
            SDL_AddTimer(itr->second.interval, played_sound_callback,
                         itr->second.callback_id_ptr);
        break;
      case sound_player::toggle_pause_result::error:
        // Do nothing with callback on error
        break;
    };
  }'''
PAUSE_NEW = '''#ifdef CORSIXTH_3DS
  if (pauseResult != sound_player::toggle_pause_result::error)
    pause_sound_deadline(callbackId,
        pauseResult == sound_player::toggle_pause_result::paused, SDL_GetTicks());
#else
''' + PAUSE_OLD + '''
#endif'''
STOP_OLD = '''  if (auto itr = map_sound_timers.find(callbackId);
      itr != map_sound_timers.end()) {
    SDL_RemoveTimer(itr->second.timer_id);
    map_sound_timers.erase(itr);
  }'''

EXPORTS = '''
#ifdef CORSIXTH_3DS
// Called only by the SDL/Lua game thread, including pause/stop/owner changes.
void cth3ds_poll_sound_callbacks(Uint32 now) {
  if (sound_deadlines_suspended) return;
  for (auto& item : sound_deadlines) {
    if (!item.active || item.paused || item.queued || now - item.start < item.remaining) continue;
    SDL_Event event{};
    event.type = SDL_USEREVENT_SOUND_OVER;
    event.user.code = item.id;
    event.user.windowID = item.token;
    if (SDL_PushEvent(&event) == 1) item.queued = true;
  }
}
bool cth3ds_consume_sound_callback(const SDL_Event& event) {
  for (auto& item : sound_deadlines) {
    if (item.active && item.queued && !item.paused && item.id == event.user.code &&
        item.token == event.user.windowID) {
      item.active = false;
      return true;
    }
  }
  return false;
}
void cth3ds_clear_sound_callbacks() { clear_sound_deadlines(); }
void cth3ds_suspend_sound_callbacks(bool suspend, Uint32 now) {
  if (sound_deadlines_suspended == suspend) return;
  if (suspend) {
    sound_suspend_started = now;
    for (auto& item : sound_deadlines) {
      if (!item.active) continue;
      item.queued = false;
      item.token = next_sound_token();
    }
  } else {
    const Uint32 paused_time = now - sound_suspend_started;
    for (auto& item : sound_deadlines)
      if (item.active && !item.paused) item.start += paused_time;
  }
  sound_deadlines_suspended = suspend;
}
#endif
'''


def binding(text):
    # Upgrade an already assembled first R42 candidate as well as a clean pin.
    previous_state = STATE_NEW.replace('bool sound_deadlines_suspended = false;\nUint32 sound_suspend_started = 0;\n', '').replace('  if (sound_deadlines_suspended) now = sound_suspend_started;\n', '')
    if previous_state in text and STATE_NEW not in text:
        text = replace_exact(text, previous_state, STATE_NEW, 'lifecycle deadline upgrade')
    previous_exports = EXPORTS.split('void cth3ds_suspend_sound_callbacks(', 1)[0].replace('  if (sound_deadlines_suspended) return;\n', '') + '#endif\n'
    if previous_exports in text and EXPORTS not in text:
        text = replace_exact(text, previous_exports, EXPORTS, 'lifecycle export upgrade')
    edits = [
        (STATE_OLD, STATE_NEW, 'main-thread records'),
        (CALLBACK_OLD, '#ifndef CORSIXTH_3DS\n' + CALLBACK_OLD + '\n#endif', 'desktop-only timer'),
        (SCHEDULE_OLD, SCHEDULE_NEW, 'schedule'),
        (PAUSE_OLD, PAUSE_NEW, 'pause'),
        (STOP_OLD, '#ifdef CORSIXTH_3DS\n  stop_sound_deadline(callbackId);\n#else\n' + STOP_OLD + '\n#endif', 'stop'),
        ('int l_soundfx_set_sound_volume(lua_State* L) {', '''int l_soundfx_new_owned(lua_State* L) {
  const int result = l_soundfx_new(L);
#ifdef CORSIXTH_3DS
  clear_sound_deadlines();
#endif
  return result;
}
int l_soundfx_set_archive_owned(lua_State* L) {
  const int result = l_soundfx_set_archive(L);
#ifdef CORSIXTH_3DS
  clear_sound_deadlines();
#endif
  return result;
}

int l_soundfx_set_sound_volume(lua_State* L) {''', 'owner publication'),
        ('lcb(pState, "soundEffects", l_soundfx_new,', 'lcb(pState, "soundEffects", l_soundfx_new_owned,', 'new registration'),
        ('lcb.add_function(l_soundfx_set_archive, "setSoundArchive",', 'lcb.add_function(l_soundfx_set_archive_owned, "setSoundArchive",', 'bank registration'),
        ('int l_soundfx_play(lua_State* L) {\n  sound_player* pEffects = luaT_testuserdata<sound_player>(L);',
         'int l_soundfx_play(lua_State* L) {\n  sound_player* pEffects = luaT_testuserdata<sound_player>(L);\n#ifdef CORSIXTH_3DS\n  if (pEffects != sound_player::get_singleton()) return luaL_error(L, "sound player is no longer active");\n#endif', 'retired caller'),
    ]
    for old, new, label in edits:
        text = replace_exact(text, old, new, 'sound callbacks: ' + label)
    if EXPORTS not in text:
        text += EXPORTS
    return text


def core(text):
    edits = [
        ('#include "lua_sdl.h"', '#include "lua_sdl.h"\n#ifdef CORSIXTH_3DS\nvoid cth3ds_poll_sound_callbacks(Uint32 now);\nbool cth3ds_consume_sound_callback(const SDL_Event& event);\nvoid cth3ds_clear_sound_callbacks();\n#endif', 'declarations'),
        ('    cth3ds::runtime_tick(L);', '    cth3ds::runtime_tick(L);\n    cth3ds_poll_sound_callbacks(SDL_GetTicks());', 'main-thread poll'),
        ('        case SDL_USEREVENT_SOUND_OVER:\n', '        case SDL_USEREVENT_SOUND_OVER:\n#ifdef CORSIXTH_3DS\n          if (!cth3ds_consume_sound_callback(e)) { nargs = 0; break; }\n#endif\n', 'stale event rejection'),
        ('          lua_pushinteger(L, *(static_cast<int*>(e.user.data1)));', '#ifdef CORSIXTH_3DS\n          lua_pushinteger(L, e.user.code);\n#else\n          lua_pushinteger(L, *(static_cast<int*>(e.user.data1)));\n#endif', 'event value'),
        ('  cth3ds::runtime_shutdown(L);\n#endif\n  // CORSIXTH_3DS_END: runtime-shutdown', '  cth3ds_clear_sound_callbacks();\n  cth3ds::runtime_shutdown(L);\n#endif\n  // CORSIXTH_3DS_END: runtime-shutdown', 'shutdown'),
    ]
    for old, new, label in edits:
        text = replace_exact(text, old, new, 'sound callbacks: ' + label)
    return text


def patch_sound_callbacks(root: Path, dry_run=False):
    plan = {}
    for name, transform in [('th_lua_sound.cpp', binding), ('sdl_core.cpp', core)]:
        path = root / 'CorsixTH/Src' / name
        old = path.read_text(encoding='utf-8')
        new = transform(old)
        if new != old:
            plan[path] = new
    if not dry_run:
        for path, new in plan.items():
            path.write_text(new, encoding='utf-8')
    return [path.relative_to(root).as_posix() for path in plan]


def check_sound_callbacks(root):
    try:
        return ['sound callback patch missing: ' + name for name in patch_sound_callbacks(root, True)]
    except (OSError, SoundPatchError) as exc:
        return [str(exc)]
