// Focused native/Lua integration tests. Real Lua and SDL2; deterministic mixer seam.
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <vector>
#include <limits>
#include "SDL_mixer.h"
#include "lua.hpp"
#include "3ds/runtime_3ds.hpp"
#if defined(__has_feature)
# if __has_feature(address_sanitizer)
#  define CTH_TEST_ASAN 1
# endif
#endif
#if defined(__SANITIZE_ADDRESS__)
# define CTH_TEST_ASAN 1
#endif
#ifdef CTH_TEST_ASAN
# include <sanitizer/asan_interface.h>
#endif
#include "th_sound.h"
// Include the complete generated binding source; its anonymous functions are
// called through real lua_pcall below, not reimplemented as a test mock.
#include "th_lua_sound.cpp"

static int cpp_fail_after=-1, cpp_attempts=0;
void* operator new(std::size_t n) {
  if(cpp_fail_after>=0) {++cpp_attempts;if(cpp_fail_after--==0) throw std::bad_alloc();}
  void* p=std::malloc(n?n:1);if(!p)throw std::bad_alloc();return p;
}
void* operator new[](std::size_t n) {return ::operator new(n);}
void* operator new(std::size_t n,const std::nothrow_t&) noexcept {try{return ::operator new(n);}catch(...){return nullptr;}}
void* operator new[](std::size_t n,const std::nothrow_t&) noexcept {try{return ::operator new(n);}catch(...){return nullptr;}}
void operator delete(void* p,const std::nothrow_t&) noexcept {std::free(p);}
void operator delete[](void* p,const std::nothrow_t&) noexcept {std::free(p);}

void operator delete(void* p) noexcept {std::free(p);}
void operator delete[](void* p) noexcept {std::free(p);}
void operator delete(void* p,std::size_t) noexcept {std::free(p);}
void operator delete[](void* p,std::size_t) noexcept {std::free(p);}

#define CHECK(x) do {if(!(x)) {std::fprintf(stderr,"CHECK FAILED %s:%d: %s\n",__FILE__,__LINE__,#x);std::exit(41);}} while(0)
struct LuaFault {
  int growth_budget=-1;
  bool deny_growth=false;
  bool deny_on_commit=false;
  bool commit_seen=false;
  size_t refused=0,live_bytes=0;
};
static LuaFault* observed_fault=nullptr;
static bool allow_reserve=true,mixer_allocate_fail=false;
static size_t reserve_requests=0, largest_request=0, fatal_count=0;
static std::recursive_mutex mixer_mutex;
static std::array<Mix_Chunk*,32> active_chunks{};
static std::array<bool,32> paused{};
static void(*finished_callback)(int)=nullptr;
static size_t live_chunks=0, halt_all_calls=0, decodes=0;

int Mix_AllocateChannels(int n) {return mixer_allocate_fail ? -1 : n;}
void Mix_ChannelFinished(void(*cb)(int)) {std::lock_guard<std::recursive_mutex> lock(mixer_mutex);finished_callback=cb;}
int Mix_HaltChannel(int c) {
  std::lock_guard<std::recursive_mutex> lock(mixer_mutex);
  if(c==-1) {++halt_all_calls;for(int i=0;i<32;++i)Mix_HaltChannel(i);return 0;}
  if(c<0||c>=32)return -1;
  if(active_chunks[c]) {active_chunks[c]=nullptr;paused[c]=false;if(finished_callback)finished_callback(c);}return 0;
}
int Mix_PlayChannel(int c,Mix_Chunk* chunk,int) {
  std::lock_guard<std::recursive_mutex> lock(mixer_mutex);
  if(c<0||c>=32||!chunk)return -1;
  Mix_HaltChannel(c);active_chunks[c]=chunk;paused[c]=false;return c;
}
int Mix_Playing(int c) {std::lock_guard<std::recursive_mutex> lock(mixer_mutex);return c>=0&&c<32&&active_chunks[c]!=nullptr;}
int Mix_Paused(int c) {return c>=0&&c<32&&paused[c];}
void Mix_Pause(int c) {if(c>=0&&c<32)paused[c]=true;}
void Mix_Resume(int c) {if(c>=0&&c<32)paused[c]=false;}
int Mix_Volume(int,int v) {return v;}
int Mix_VolumeChunk(Mix_Chunk* p,int v) {p->volume=static_cast<Uint8>(v);return v;}
int Mix_QuerySpec(int* r,Uint16* f,int* c) {*r=22050;*f=AUDIO_S16LSB;*c=2;return 1;}
Mix_Chunk* Mix_LoadWAV_RW(SDL_RWops* rw,int freesrc) {
  SDL_AudioSpec spec{};Uint8* data=nullptr;Uint32 length=0;
  if(!SDL_LoadWAV_RW(rw,freesrc,&spec,&data,&length))return nullptr;
  SDL_AudioCVT cvt{};
  int result=SDL_BuildAudioCVT(&cvt,spec.format,spec.channels,spec.freq,AUDIO_S16LSB,2,22050);
  if(result<0) {SDL_FreeWAV(data);return nullptr;}
  auto* chunk=static_cast<Mix_Chunk*>(SDL_malloc(sizeof(Mix_Chunk)));
  if(!chunk) {SDL_FreeWAV(data);return nullptr;}
  if(result>0) {
    cvt.len=static_cast<int>(length);
    cvt.buf=static_cast<Uint8*>(SDL_malloc(static_cast<size_t>(length)*cvt.len_mult));
    if(!cvt.buf){SDL_FreeWAV(data);SDL_free(chunk);return nullptr;}
    std::memcpy(cvt.buf,data,length);SDL_FreeWAV(data);
    if(SDL_ConvertAudio(&cvt)<0){SDL_free(cvt.buf);SDL_free(chunk);return nullptr;}
    data=cvt.buf;length=static_cast<Uint32>(cvt.len_cvt);
  }
  *chunk={1,data,length,128};++live_chunks;++decodes;return chunk;
}
void Mix_FreeChunk(Mix_Chunk* chunk) {
  if(!chunk)return;
  std::lock_guard<std::recursive_mutex> lock(mixer_mutex);
  for(int c=0;c<32;++c)if(active_chunks[c]==chunk)Mix_HaltChannel(c);
  SDL_free(chunk->abuf);SDL_free(chunk);--live_chunks;
}
namespace cth3ds {
void runtime_observe_memory(const char* site,const char* phase,const char*,MemoryGate,uint64_t,bool,uint64_t,bool,bool,bool) noexcept {
  if(observed_fault&&observed_fault->deny_on_commit&&!std::strcmp(site,"sound_release")&&!std::strcmp(phase,"bank-after")) {
    observed_fault->commit_seen=true;observed_fault->deny_growth=true;
  }
}
bool runtime_audio_reserve(size_t n,const char*) noexcept {++reserve_requests;largest_request=std::max(largest_request,n);return allow_reserve;}
void report_allocation_failure(const char*,const char*,uint64_t,const char*,const char*) noexcept {}
void report_fatal(const char*) noexcept {++fatal_count;}
}
static void* lua_allocator(void* ud,void* ptr,size_t old,size_t n) {
  auto* fault=static_cast<LuaFault*>(ud);
  if(n==0) {if(ptr){fault->live_bytes-=old;std::free(ptr);}return nullptr;}
  const bool growth=!ptr||n>old;
  if(growth && (fault->deny_growth||fault->growth_budget==0)) {++fault->refused;return nullptr;}
  if(growth&&fault->growth_budget>0)--fault->growth_budget;
  void* p=std::realloc(ptr,n);
  if(p)fault->live_bytes+=n-(ptr?old:0);
  return p;
}
static std::array<char,1024> finalizers{};
static size_t finalizer_count=0;
static bool poison_archive=false;
static int gc_archive(lua_State* L) {
  auto* p=static_cast<sound_archive*>(lua_touserdata(L,1));p->~sound_archive();
  CHECK(finalizer_count<finalizers.size());finalizers[finalizer_count++]='A';
#ifdef CTH_TEST_ASAN
  if(poison_archive) {__asan_poison_memory_region(p,sizeof(*p));}
#endif
  return 0;
}
static int gc_player(lua_State* L) {
  auto* p=static_cast<sound_player*>(lua_touserdata(L,1));p->~sound_player();
  CHECK(finalizer_count<finalizers.size());finalizers[finalizer_count++]='P';return 0;
}
static void setup(lua_State* L) {
  for(auto pair : {std::pair<const char*,lua_CFunction>{"archive",gc_archive},{"player",gc_player}}) {
    luaL_newmetatable(L,pair.first);lua_pushcfunction(L,pair.second);lua_setfield(L,-2,"__gc");lua_pop(L,1);
  }
}
static void push_constructor(lua_State* L,bool player) {
  lua_getfield(L,LUA_REGISTRYINDEX,player?"player":"archive");
  lua_pushcclosure(L,player?l_soundfx_new:l_soundarc_new,1);
}
static void create_player(lua_State* L,const char* name) {
  push_constructor(L,true);CHECK(lua_pcall(L,0,1,0)==LUA_OK);lua_setglobal(L,name);
}
static sound_player* get_player(lua_State* L,const char* name="player") {
  lua_getglobal(L,name);auto* p=static_cast<sound_player*>(lua_touserdata(L,-1));lua_pop(L,1);CHECK(p);return p;
}
static sound_archive* get_archive(lua_State* L,const char* name) {
  lua_getglobal(L,name);auto* p=static_cast<sound_archive*>(lua_touserdata(L,-1));lua_pop(L,1);CHECK(p);return p;
}
static void create_archive(lua_State* L,const char* name,const std::string& file,bool load=true) {
  push_constructor(L,false);CHECK(lua_pcall(L,0,1,0)==LUA_OK);
  if(load)CHECK(static_cast<sound_archive*>(lua_touserdata(L,-1))->load_from_file(file.c_str()));
  lua_setglobal(L,name);
}
static int set_archive(lua_State* L,const char* a,const char* p="player") {
  lua_pushcfunction(L,l_soundfx_set_archive);lua_getglobal(L,p);lua_getglobal(L,a);
  try {return lua_pcall(L,2,1,0);} catch(const std::bad_alloc&) {
    cpp_fail_after=-1;std::fprintf(stderr,"NATIVE_EXCEPTION_ESCAPED_LUA_PCALL\n");std::_Exit(42);
  }
}
static bool retained(lua_State* L,const char* a,const char* p="player") {
  lua_getglobal(L,p);lua_getfenv(L,-1);lua_getfield(L,-1,"archive");lua_getglobal(L,a);
  bool equal=lua_rawequal(L,-1,-2);lua_pop(L,4);return equal;
}
static void close_state(lua_State* L,LuaFault& f) {
  observed_fault=nullptr;f.deny_growth=false;f.growth_budget=-1;cpp_fail_after=-1;
  // Lua frees userdata storage during lua_close; ASan's malloc/free interceptors
  // unpoison allocator chunks. Do not touch the saved pointers after closure.
  lua_close(L);CHECK(f.live_bytes==0);CHECK(live_chunks==0);
  CHECK(sound_player::get_singleton()==nullptr);
}
static int test_success(const std::string& dir) {
  sound_archive a;CHECK(a.load_from_file((dir+"/747.dat").c_str()));CHECK(a.get_number_of_sounds()==747);
  sound_player p;p.populate_from(&a);CHECK(p.cached_bytes()==0&&p.decoded_clip_count()==0);
  for(size_t i=1;i<747;++i) {auto h=p.play(i,1.0,0);CHECK(h!=0);CHECK(p.is_playing(h));p.stop(h);CHECK(!p.is_playing(h));CHECK(p.owner_bytes()<=3*1024*1024);}
  auto h=p.play(1,1,-1);CHECK(h);CHECK(p.toggle_pause(h)==sound_player::toggle_pause_result::paused);
  CHECK(p.toggle_pause(h)==sound_player::toggle_pause_result::resumed);p.populate_from(&a);CHECK(p.cached_bytes()==0);
  p.populate_from(nullptr);CHECK(p.cached_bytes()==0);CHECK(live_chunks==0);return 0;
}
static int test_native_failures(const std::string& dir) {
  sound_archive a,b;CHECK(a.load_from_file((dir+"/a.dat").c_str()));CHECK(b.load_from_file((dir+"/b.dat").c_str()));
  for(bool initial : {true,false})for(int at=-1;at<3;++at) {
    sound_player p;uint32_t handle=0;if(!initial){p.populate_from(&a);handle=p.play(1,1,-1);CHECK(handle);}
    auto before=p.owner_bytes(),cache=p.cached_bytes(),chunks=live_chunks;auto halts=halt_all_calls;
    cpp_attempts=0;cpp_fail_after=at;allow_reserve=at!=-1;bool caught=false;
    try {p.populate_from(&b);}catch(const std::bad_alloc&){caught=true;}
    cpp_fail_after=-1;allow_reserve=true;CHECK(caught);CHECK(p.owner_bytes()==before&&p.cached_bytes()==cache);
    CHECK(live_chunks==chunks&&halt_all_calls==halts);if(handle)CHECK(p.is_playing(handle));
    p.populate_from(&b);CHECK(p.play(1,1,0));p.populate_from(nullptr);
  }
  return 0;
}
static int test_lua_cpp_failures(const std::string& dir) {
  for(bool initial : {true,false})for(int at=-1;at<3;++at) {
    LuaFault fault;auto* L=lua_newstate(lua_allocator,&fault);CHECK(L);setup(L);
    create_archive(L,"a",dir+"/a.dat");create_player(L,"player");create_archive(L,"b",dir+"/b.dat");
    auto* p=get_player(L);uint32_t h=0;
    if(!initial){CHECK(set_archive(L,"a")==LUA_OK);lua_pop(L,1);h=p->play(1,1,-1);CHECK(h);}
    auto before=p->owner_bytes();cpp_fail_after=at;allow_reserve=at!=-1;
    int result=set_archive(L,"b");cpp_fail_after=-1;allow_reserve=true;
    CHECK(result==LUA_ERRRUN);lua_pop(L,1);CHECK(p->owner_bytes()==before);
    if(!initial) {CHECK(retained(L,"a"));CHECK(p->is_playing(h));}
    lua_gc(L,LUA_GCCOLLECT);CHECK(set_archive(L,"b")==LUA_OK);lua_pop(L,1);CHECK(retained(L,"b"));
    CHECK(p->play(1,1,0));close_state(L,fault);
  }
  return 0;
}
static int test_after_commit_oom(const std::string& dir) {
  LuaFault f;auto* L=lua_newstate(lua_allocator,&f);CHECK(L);setup(L);
  create_archive(L,"a",dir+"/a.dat");create_player(L,"player");
  f.deny_on_commit=true;observed_fault=&f;
  int result=set_archive(L,"a");f.deny_growth=false;f.deny_on_commit=false;observed_fault=nullptr;
  std::printf("after-commit: status=%d commit=%d refused=%zu retained=%d\n",result,f.commit_seen,f.refused,retained(L,"a"));
  CHECK(f.commit_seen);CHECK(result==LUA_OK);lua_pop(L,1);CHECK(retained(L,"a"));
  CHECK(get_player(L)->play(1,1,0));close_state(L,f);return 0;
}
static int test_lua_prepare_failures(const std::string& dir) {
  int rejected=0,accepted=0;
  for(int budget=0;budget<16;++budget) {
    LuaFault f;auto* L=lua_newstate(lua_allocator,&f);CHECK(L);setup(L);
    create_archive(L,"a",dir+"/a.dat");create_player(L,"player");create_archive(L,"b",dir+"/b.dat");
    CHECK(set_archive(L,"a")==LUA_OK);lua_pop(L,1);auto* p=get_player(L);auto h=p->play(1,1,-1);CHECK(h);
    // A future environment field must survive the replacement, too.
    lua_getglobal(L,"player");lua_getfenv(L,-1);lua_pushinteger(L,53);lua_setfield(L,-2,"other");
    const void* oldenv=lua_topointer(L,-1);lua_pop(L,2);auto before=p->owner_bytes();
    f.growth_budget=budget;int result=set_archive(L,"b");f.growth_budget=-1;
    if(result!=LUA_OK) {
      ++rejected;CHECK(result==LUA_ERRMEM);CHECK(p->owner_bytes()==before);CHECK(p->is_playing(h));CHECK(retained(L,"a"));
      lua_pop(L,1);lua_getglobal(L,"player");lua_getfenv(L,-1);CHECK(lua_topointer(L,-1)==oldenv);lua_pop(L,2);
      CHECK(set_archive(L,"b")==LUA_OK);
    } else ++accepted;
    lua_pop(L,1);CHECK(retained(L,"b"));lua_getglobal(L,"player");lua_getfenv(L,-1);lua_getfield(L,-1,"other");
    CHECK(lua_tointeger(L,-1)==53);lua_pop(L,3);CHECK(p->play(1,1,0));close_state(L,f);
  }
  CHECK(rejected>0&&accepted>0);std::printf("lua-preparation: rejected=%d accepted=%d retries=%d\n",rejected,accepted,rejected);return 0;
}
static int test_retired_player(const std::string& dir) {
  sound_archive a;CHECK(a.load_from_file((dir+"/a.dat").c_str()));
  auto* old=new sound_player;old->populate_from(&a);CHECK(old->play(1,1,-1));
  auto* current=new sound_player;current->populate_from(&a);auto h=current->play(1,1,-1);CHECK(h);
  CHECK(Mix_Playing(0));auto* callback=finished_callback;auto halts=halt_all_calls;
  delete old;
  std::printf("retired-finalizer: current-playing=%d callback-retained=%d\n",Mix_Playing(0),finished_callback==callback);
  CHECK(Mix_Playing(0));CHECK(finished_callback==callback);CHECK(halt_all_calls==halts);
  Mix_HaltChannel(0);CHECK(!current->is_playing(h));delete current;CHECK(live_chunks==0);return 0;
}
static int test_finalizer_order(const std::string& dir) {
  LuaFault f;auto* L=lua_newstate(lua_allocator,&f);CHECK(L);setup(L);finalizer_count=0;
  create_player(L,"player");create_archive(L,"a",dir+"/a.dat");CHECK(set_archive(L,"a")==LUA_OK);lua_pop(L,1);
  CHECK(get_player(L)->play(1,1,-1));poison_archive=true;close_state(L,f);poison_archive=false;
  CHECK(finalizer_count==2&&finalizers[0]=='A'&&finalizers[1]=='P');
  std::printf("lua-close-order: %c%c (archive lifetime ends before player)\n",finalizers[0],finalizers[1]);return 0;
}
static int test_new_player_failure(const std::string& dir) {
  LuaFault f;auto* L=lua_newstate(lua_allocator,&f);CHECK(L);setup(L);
  create_archive(L,"a",dir+"/a.dat");create_player(L,"player");CHECK(set_archive(L,"a")==LUA_OK);lua_pop(L,1);
  auto* old=get_player(L);auto h=old->play(1,1,-1);CHECK(h);auto before=old->owner_bytes();
  mixer_allocate_fail=true;push_constructor(L,true);int result;
  try {result=lua_pcall(L,0,1,0);}catch(...){std::fprintf(stderr,"PLAYER_CONSTRUCTOR_EXCEPTION_ESCAPED\n");std::_Exit(42);}
  mixer_allocate_fail=false;CHECK(result==LUA_ERRRUN);lua_pop(L,1);
  CHECK(sound_player::get_singleton()==old);CHECK(old->owner_bytes()==before&&old->is_playing(h));
  create_player(L,"replacement");CHECK(set_archive(L,"a","replacement")==LUA_OK);lua_pop(L,1);
  CHECK(get_player(L,"replacement")->play(1,1,-1));lua_pushnil(L);lua_setglobal(L,"player");
  lua_gc(L,LUA_GCCOLLECT);CHECK(Mix_Playing(0));close_state(L,f);return 0;
}
static int test_archive_cpp_errors(const std::string& dir) {
  for(int at=0;at<2;++at) {
    LuaFault f;auto* L=lua_newstate(lua_allocator,&f);CHECK(L);setup(L);create_archive(L,"a","",false);
    lua_pushcfunction(L,l_soundarc_load_file);lua_getglobal(L,"a");lua_pushstring(L,(dir+"/a.dat").c_str());cpp_fail_after=at;int result;
    try {result=lua_pcall(L,2,1,0);}catch(...){std::fprintf(stderr,"ARCHIVE_EXCEPTION_ESCAPED\n");std::_Exit(42);}
    cpp_fail_after=-1;CHECK(result==LUA_ERRRUN);lua_pop(L,1);CHECK(get_archive(L,"a")->get_number_of_sounds()==0);
    CHECK(get_archive(L,"a")->load_from_file((dir+"/a.dat").c_str()));close_state(L,f);
  }
  return 0;
}
static int test_release_no_allocation(const std::string& dir) {
  sound_archive a;CHECK(a.load_from_file((dir+"/a.dat").c_str()));
  for(int i=0;i<100;++i) {
    sound_player p;p.populate_from(&a);CHECK(p.play(1,1,-1));cpp_attempts=0;cpp_fail_after=0;allow_reserve=false;
    p.populate_from(nullptr);CHECK(cpp_attempts==0&&live_chunks==0);cpp_fail_after=-1;allow_reserve=true;
  }
  return 0;
}
static int test_cache(const std::string& dir) {
  sound_archive a;CHECK(a.load_from_file((dir+"/large.dat").c_str()));sound_player p;p.populate_from(&a);
  auto pinned=p.play(1,1,-1);CHECK(pinned);
  for(size_t i=2;i<a.get_number_of_sounds();++i) {
    auto h=p.play(i,1,0);CHECK(h);p.stop(h);CHECK(p.is_playing(pinned));CHECK(p.owner_bytes()<=3*1024*1024);
  }
  CHECK(p.decoded_clip_count()<a.get_number_of_sounds()-1);CHECK(pinned&&p.pinned_bytes()>0);
  p.populate_from(nullptr);CHECK(live_chunks==0);return 0;
}
static int test_bad_archives(const std::string& dir) {
  for(const char* name: {"truncated.dat","overlap.dat","conflicting.dat"}) {sound_archive a;CHECK(!a.load_from_file((dir+"/"+name).c_str()));CHECK(a.get_number_of_sounds()==0);}
  sound_archive a;CHECK(a.load_from_file((dir+"/alias.dat").c_str()));CHECK(a.get_number_of_sounds()==3);
  sound_player p;p.populate_from(&a);CHECK(p.play(1,1,0));CHECK(p.play(2,1,0));p.populate_from(nullptr);
  sound_archive bad;CHECK(bad.load_from_file((dir+"/invalid-wave.dat").c_str()));p.populate_from(&bad);auto previous=fatal_count;
  CHECK(p.play(1,1,0)==0);CHECK(fatal_count==previous+1&&p.cached_bytes()==0);return 0;
}
static SDL_Event read_completion(int caller) {
  SDL_Event event{};
  if (SDL_PeepEvents(&event,1,SDL_GETEVENT,SDL_USEREVENT_SOUND_OVER,SDL_USEREVENT_SOUND_OVER)==1) return event;
  std::fprintf(stderr,"missing sound event at caller line %d: %s\n",caller,SDL_GetError());
  CHECK(false); return event;
}
#define next_completion() read_completion(__LINE__)
static void no_completion() {
  SDL_Event event{};
  CHECK(SDL_PeepEvents(&event,1,SDL_GETEVENT,SDL_USEREVENT_SOUND_OVER,SDL_USEREVENT_SOUND_OVER)==0);
}
static int reject_completion(void*, SDL_Event* event) {
  return event->type != SDL_USEREVENT_SOUND_OVER;
}
static int test_main_thread_callbacks(const std::string& dir) {
  CHECK(SDL_InitSubSystem(SDL_INIT_EVENTS | SDL_INIT_TIMER)==0);
  cth3ds_clear_sound_callbacks();
  CHECK(schedule_sound_deadline(101, 0, 10));
  cth3ds_poll_sound_callbacks(10);
  auto first = next_completion();
  CHECK(first.user.code==101 && first.user.data1==nullptr);
  CHECK(cth3ds_consume_sound_callback(first));
  CHECK(!cth3ds_consume_sound_callback(first)); // exactly once

  CHECK(schedule_sound_deadline(102, 100, 0xfffffff0U));
  cth3ds_poll_sound_callbacks(0x53U); no_completion();
  cth3ds_poll_sound_callbacks(0x54U);
  CHECK(cth3ds_consume_sound_callback(next_completion())); // clock wrap

  CHECK(schedule_sound_deadline(103, 100, 100));
  pause_sound_deadline(103, true, 140);
  cth3ds_poll_sound_callbacks(1000); no_completion();
  pause_sound_deadline(103, false, 1000);
  cth3ds_poll_sound_callbacks(1059); no_completion();
  cth3ds_poll_sound_callbacks(1060);
  auto paused_event = next_completion();
  pause_sound_deadline(103, true, 1061);
  CHECK(!cth3ds_consume_sound_callback(paused_event));
  pause_sound_deadline(103, false, 2000);
  cth3ds_poll_sound_callbacks(2000);
  CHECK(cth3ds_consume_sound_callback(next_completion())); // saturated remainder

  CHECK(schedule_sound_deadline(104, 0, 0));
  cth3ds_poll_sound_callbacks(1); auto stopped = next_completion();
  stop_sound_deadline(104);
  CHECK(schedule_sound_deadline(104, 0, 2));
  CHECK(!cth3ds_consume_sound_callback(stopped));
  cth3ds_poll_sound_callbacks(2);
  CHECK(cth3ds_consume_sound_callback(next_completion())); // reused ID, new token

  CHECK(schedule_sound_deadline(105, 0, 0));
  SDL_SetEventFilter(reject_completion, nullptr);
  cth3ds_poll_sound_callbacks(0); no_completion();
  SDL_SetEventFilter(nullptr, nullptr);
  cth3ds_poll_sound_callbacks(1);
  CHECK(cth3ds_consume_sound_callback(next_completion())); // queue rejection retained

  CHECK(schedule_sound_deadline(201,100,100));
  CHECK(schedule_sound_deadline(202,100,100));
  pause_sound_deadline(202,true,120); // user-paused clip stays paused after HOME
  cth3ds_suspend_sound_callbacks(true,140);
  cth3ds_suspend_sound_callbacks(true,500); // repeated system hook is idempotent
  cth3ds_poll_sound_callbacks(1000); no_completion();
  cth3ds_suspend_sound_callbacks(false,1000);
  cth3ds_suspend_sound_callbacks(false,1050);
  cth3ds_poll_sound_callbacks(1059); no_completion();
  cth3ds_poll_sound_callbacks(1060);
  auto system_event=next_completion(); CHECK(system_event.user.code==201);
  CHECK(cth3ds_consume_sound_callback(system_event)); no_completion();
  pause_sound_deadline(202,false,2000);
  cth3ds_poll_sound_callbacks(2079); no_completion();
  cth3ds_poll_sound_callbacks(2080);
  CHECK(cth3ds_consume_sound_callback(next_completion()));

  CHECK(schedule_sound_deadline(203,0,0));
  cth3ds_poll_sound_callbacks(1); auto before_sleep=next_completion();
  cth3ds_suspend_sound_callbacks(true,1);
  CHECK(!cth3ds_consume_sound_callback(before_sleep));
  cth3ds_suspend_sound_callbacks(false,1000);
  cth3ds_poll_sound_callbacks(1000);
  CHECK(cth3ds_consume_sound_callback(next_completion()));

  CHECK(schedule_sound_deadline(204,100,0xffffffe0U));
  cth3ds_suspend_sound_callbacks(true,0xfffffff0U);
  cth3ds_suspend_sound_callbacks(false,0x100U);
  cth3ds_poll_sound_callbacks(0x153U); no_completion();
  cth3ds_poll_sound_callbacks(0x154U);
  CHECK(cth3ds_consume_sound_callback(next_completion()));

  for(int i=0;i<1000;++i) CHECK(schedule_sound_deadline(i, 0, 0));
  CHECK(!schedule_sound_deadline(1001, 0, 0));
  cth3ds_poll_sound_callbacks(1);
  auto stale = next_completion();
  cth3ds_clear_sound_callbacks();
  CHECK(!cth3ds_consume_sound_callback(stale));
  SDL_FlushEvent(SDL_USEREVENT_SOUND_OVER);
  for(int i=0;i<5000;++i) {
    CHECK(schedule_sound_deadline(i, 0, 0));
    cth3ds_poll_sound_callbacks(1);
    CHECK(cth3ds_consume_sound_callback(next_completion()));
  }

  LuaFault f; auto* L=lua_newstate(lua_allocator,&f); CHECK(L); setup(L);
  create_archive(L,"a",dir+"/a.dat"); create_player(L,"player");
  CHECK(schedule_sound_deadline(9999, 0, 0));
  lua_pushcfunction(L,l_soundfx_set_archive_owned);
  lua_getglobal(L,"player"); lua_getglobal(L,"a");
  CHECK(lua_pcall(L,2,1,0)==LUA_OK); lua_pop(L,1);
  cth3ds_poll_sound_callbacks(1); no_completion(); // committed bank cancels old callbacks
  CHECK(schedule_sound_deadline(9998, 0, 0));
  allow_reserve=false;
  lua_pushcfunction(L,l_soundfx_set_archive_owned);
  lua_getglobal(L,"player"); lua_getglobal(L,"a");
  CHECK(lua_pcall(L,2,1,0)==LUA_ERRRUN); lua_pop(L,1); allow_reserve=true;
  cth3ds_poll_sound_callbacks(1);
  CHECK(cth3ds_consume_sound_callback(next_completion())); // failed bank keeps prior callback
  close_state(L,f); cth3ds_clear_sound_callbacks();
  return 0;
}

int main(int argc,char** argv) {
  if(argc!=3){std::fprintf(stderr,"usage: test CASE FIXTURE_DIR\n");return 2;}
  // This suite uses SDL RWops/decoders only; no host device or DBus startup.
  const std::string name=argv[1],dir=argv[2];int result=0;
  if(name=="success-747")result=test_success(dir);
  else if(name=="native-failures")result=test_native_failures(dir);
  else if(name=="lua-cpp-failures")result=test_lua_cpp_failures(dir);
  else if(name=="post-commit-lua-oom")result=test_after_commit_oom(dir);
  else if(name=="lua-preparation")result=test_lua_prepare_failures(dir);
  else if(name=="retired-player")result=test_retired_player(dir);
  else if(name=="lua-finalizers")result=test_finalizer_order(dir);
  else if(name=="new-player-failure")result=test_new_player_failure(dir);
  else if(name=="archive-cpp-failures")result=test_archive_cpp_errors(dir);
  else if(name=="release-no-allocation")result=test_release_no_allocation(dir);
  else if(name=="cache-eviction")result=test_cache(dir);
  else if(name=="bad-archives")result=test_bad_archives(dir);
  else if(name=="main-thread-callbacks")result=test_main_thread_callbacks(dir);
  else {std::fprintf(stderr,"unknown case\n");return 2;}
  CHECK(live_chunks==0);CHECK(sound_player::get_singleton()==nullptr);SDL_Quit();
  std::printf("PASS %s decodes=%zu reserve_requests=%zu largest_request=%zu\n",name.c_str(),decodes,reserve_requests,largest_request);
  return result;
}
