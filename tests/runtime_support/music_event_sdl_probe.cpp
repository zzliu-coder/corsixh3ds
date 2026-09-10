#include "cth3ds/music_event_owner.hpp"
#include <SDL.h>
#include <SDL_mixer.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

// Real generated callback/play/stop/free/destroy/class and SDL core dispatch are
// inserted by the host builder. Only the Lua stack/userdata accessors are seams.
using Owner = cth3ds::MusicEventOwner;
constexpr Uint32 SDL_USEREVENT_MUSIC_OVER = SDL_USEREVENT + 1;
constexpr Uint32 music_over = SDL_USEREVENT_MUSIC_OVER;
auto& owner = cth3ds::music_event_owner;
// INSERT_MUSIC_CLASS
struct lua_State { music* userdata{}; bool success{}; };
template<class T> T* luaT_testuserdata(lua_State* L, int) { return L->userdata; }
long long luaL_optinteger(lua_State*, int, long long) { return 0; }
void lua_pushnil(lua_State* L) { L->success = false; }
void lua_pushstring(lua_State*, const char*) {}
void lua_pushliteral(lua_State*, const char*) {}
void lua_pushboolean(lua_State* L, int value) { L->success = value != 0; }
void push_app_dispatch(lua_State*, const char*) {}
// INSERT_NATIVE_FUNCTIONS
bool dispatch(SDL_Event e) {
  int nargs = -1;
  const char* last_dispatch = nullptr;
  const char* dispatch_music_over = "music_over";
  lua_State* L = nullptr;
  switch (e.type) {
// INSERT_NATIVE_DISPATCH
    default: break;
  }
  return nargs == 1;
}
void stop() { lua_State L; l_stop_music(&L); }
Owner::Token play(music* value) {
  lua_State L; L.userdata = value;
  l_play_music(&L);
  return L.success ? value->playback_token : 0;
}
std::vector<Uint8> wav(unsigned samples) {
  const auto payload = samples * 2U;
  std::vector<Uint8> value(44U + payload, 0);
  const auto u16 = [&](unsigned p, unsigned n) {
    value[p] = static_cast<Uint8>(n); value[p+1] = static_cast<Uint8>(n >> 8);
  };
  const auto u32 = [&](unsigned p, unsigned n) {
    for (unsigned i = 0; i < 4; ++i) value[p+i] = static_cast<Uint8>(n >> (8U*i));
  };
  std::memcpy(value.data(), "RIFF", 4); u32(4, payload+36U);
  std::memcpy(value.data()+8, "WAVEfmt ", 8); u32(16,16); u16(20,1); u16(22,1);
  u32(24,22050); u32(28,44100); u16(32,2); u16(34,16);
  std::memcpy(value.data()+36, "data", 4); u32(40,payload);
  return value;
}
music* load(const std::vector<Uint8>& value) {
  auto* stream = SDL_RWFromConstMem(value.data(), static_cast<int>(value.size()));
  assert(stream);
  auto* result = Mix_LoadMUSType_RW(stream, MUS_WAV, 1);
  assert(result);
  auto* userdata = new music(); userdata->pMusic = result; return userdata;
}
SDL_Event wait_completion() {
  SDL_Event event{};
  const Uint32 deadline = SDL_GetTicks() + 4000U;
  while (SDL_GetTicks() < deadline) {
    if (SDL_WaitEventTimeout(&event, 30) && event.type == music_over) return event;
  }
  assert(false && "real mixer did not deliver short WAV completion");
  return event;
}
void wait_phase(Owner::Phase phase) {
  const Uint32 deadline = SDL_GetTicks() + 4000U;
  while (SDL_GetTicks() < deadline && owner.snapshot().phase != phase) SDL_Delay(5);
  assert(owner.snapshot().phase == phase);
}
int reject_music(void*, SDL_Event* event) { return event->type != music_over; }

int main() {
  assert(SDL_setenv("SDL_AUDIODRIVER", "dummy", 1) == 0);
  assert(SDL_Init(SDL_INIT_AUDIO | SDL_INIT_EVENTS) == 0);
  assert(Mix_OpenAudio(22050, AUDIO_S16SYS, 2, 256) == 0);
  const auto short_wav = wav(2205);
  const auto long_wav = wav(44100);
  auto* first = load(short_wav);
  auto* second = load(long_wav);
  const auto old_token = play(first);
  const auto waited_event = wait_completion();
  assert(waited_event.user.code == old_token);
  assert(!Mix_PlayingMusic() && owner.snapshot().phase == Owner::Phase::completed);
  const auto new_token = play(second);
  assert(new_token != old_token && Mix_PlayingMusic());
  assert(!dispatch(waited_event)); // Event was already dequeued.
  delete first; // Actual old userdata destructor preserves new music.
  assert(owner.snapshot().token == new_token && Mix_PlayingMusic());
  std::puts("PASS real WAV EOF dequeued then stop replay stale rejection old free");

  Mix_PauseMusic(); SDL_Delay(80);
  assert(Mix_PausedMusic() && owner.snapshot().phase == Owner::Phase::playing);
  Mix_ResumeMusic();
  assert(!Mix_PausedMusic());
  stop();
  auto* natural = load(short_wav);
  const auto natural_token = play(natural);
  const auto natural_event = wait_completion();
  assert(natural_event.user.code == natural_token);
  assert(dispatch(natural_event));
  assert(!dispatch(natural_event));
  const auto following_token = play(second);
  assert(following_token != natural_token && Mix_PlayingMusic());
  std::puts("PASS real natural completion consumed once following WAV plays");

  stop();
  SDL_SetEventFilter(reject_music, nullptr);
  const auto rejected_token = play(natural);
  wait_phase(Owner::Phase::delivery_failed);
  assert(!Mix_PlayingMusic() && !owner.consume(rejected_token));
  SDL_SetEventFilter(nullptr, nullptr);
  stop();
  const auto lost_token = play(natural);
  wait_phase(Owner::Phase::completed);
  SDL_FlushEvent(music_over);
  assert(owner.snapshot().token == lost_token);
  assert(owner.snapshot().phase == Owner::Phase::completed);
  stop();
  assert(!owner.consume(lost_token));
  Mix_CloseAudio();
  assert(play(second) == 0 && owner.snapshot().phase == Owner::Phase::inactive);
  assert(Mix_OpenAudio(22050, AUDIO_S16SYS, 2, 256) == 0);
  assert(play(second) > 0 && Mix_PlayingMusic());
  std::puts("PASS real event filter queue loss failed play and replay");
  lua_State free_state; free_state.userdata = second;
  l_free_music(&free_state);
  assert(!second->pMusic && owner.snapshot().phase == Owner::Phase::inactive);
  delete second; delete natural;
  l_destroy(&free_state); SDL_Quit();
}
