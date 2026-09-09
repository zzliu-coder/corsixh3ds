#include "runtime/observation.hpp"
#include "cth3ds/bounded_log.hpp"
#include "runtime_3ds.hpp"
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
using namespace cth3ds;
namespace cth3ds {
RuntimeObservations g_observations;
SimulationClock g_simulation_clock;
static std::uint64_t clock_us{},sink_cost{},frame_count{};
static std::string captured_output;
static bool drop_lines=false;
static bool reentrant_slow_sink=false;
std::uint64_t now_us(){return clock_us;}
unsigned long long runner_frames() noexcept {return frame_count;}
void boot_log(const char* format,...){
  if(reentrant_slow_sink){
    clock_us+=500000;
    const auto phase=g_observations.frame_tail.enter(FramePhase::Runtime,clock_us);
    g_observations.frame_tail.leave(phase,clock_us);
  }
  char buffer[4096];va_list args;va_start(args,format);
  std::vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);
  if(!drop_lines){captured_output+=buffer;captured_output+='\n';}
}
void boot_log_flush() noexcept {clock_us+=sink_cost;}
struct MemoryObservationGate {static constexpr std::uint64_t interval_us=250000;};
struct Sampling {std::uint64_t sampled{},skipped{},forced{};}g_memory_sampling;
lua_State* g_observation_state=nullptr;
void update_lua_memory(lua_State*){}
struct Heap {std::uint64_t heap_available_estimate=32000000,heap_available_low_water=30000000,lua_bytes=6000000,linear_free=6000000;};
Heap heap_snapshot(){return {};}
std::uint64_t g_log_time_us{},g_workload_time_us{};
struct Log {std::uint64_t flushes(){return 0;}std::uint64_t bytes(){return 0;}
  BoundedLog::Costs costs(){return {};}
  bool failed(){return false;}bool truncated(){return false;}}g_log;
void seal_observation_tail(const char*) noexcept;
struct Runtime {
  unsigned shutdowns{};
  void log_display_stats(){}
  void shutdown() noexcept {
// INSERT_SHUTDOWN_PREFIX
    ++shutdowns; // External hardware/resource teardown is outside this probe.
  }
};
Runtime& runtime(){static Runtime value;return value;}
// INSERT_NATIVE
std::uint64_t runtime_span_begin(TimingStage stage) noexcept {return g_observations.timing.begin_span(stage,clock_us);}
bool runtime_span_end(std::uint64_t token,bool success) noexcept {return g_observations.timing.end_span(token,clock_us,success);}
void runtime_observe_memory(const char*,const char*,const char*,MemoryGate,std::uint64_t,bool,std::uint64_t,bool,bool,bool) noexcept {clock_us+=50000;}
}
static int test_gc(lua_State* state,int what,int amount){clock_us+=500000;return lua_gc(state,what,amount);}
struct Event{int type{};};
static constexpr int SDL_FIRSTEVENT=0;
static int SDL_WaitEventTimeout(Event*,int timeout){assert(timeout==8);clock_us+=500000;return 0;}
static void generated_sweep(lua_State* L,bool do_frame){
  struct {bool limit_fps=true;}fps;
#define lua_gc test_gc
// INSERT_GC
#undef lua_gc
}
static void generated_wait(){
  Event e;
// INSERT_WAIT
  assert(u3_wait()==1&&e.type==SDL_FIRSTEVENT);
}
static std::uint64_t sum(const std::array<std::uint64_t,7>& values){std::uint64_t result=0;for(auto value:values)result+=value;return result;}
static void ledger(){
  FrameTail t;
  auto outer=t.enter(FramePhase::Runtime,0);
  auto inner=t.enter(FramePhase::Benchmark,0);
  t.begin(100);t.leave(inner,110);t.present(120,PresentResult::Success);
  t.leave(outer,130);
  auto wait=t.enter(FramePhase::Wait,140);t.present(180,PresentResult::Success);t.leave(wait,190);
  t.close(200);
  const auto r=t.record();
  assert(!r.invalid&&r.begin_phase==FramePhase::Benchmark&&r.end_phase==FramePhase::Other);
  assert(sum(r.whole)==100&&sum(r.first_prefix)==20&&sum(r.last_prefix)==80);
  assert(r.whole[6]==10&&r.whole[5]==20&&r.whole[4]==50&&r.whole[0]==20);
  // END inside an already open scope; exiting it still restores the context
  // before the next window without importing the previous sample's totals.
  auto a=t.enter(FramePhase::Runtime,210);t.begin(220);t.close(230);t.leave(a,240);
  t.begin(250);t.present(251,PresentResult::Skipped);t.present(252,PresentResult::Failed);t.close(260);
  assert(t.record().begin_phase==FramePhase::Other&&t.record().sequence==3);
  assert(!t.record().first&&!t.record().last&&sum(t.record().whole)==10&&sum(t.record().first_prefix)==0);
  assert(t.record().failed==1&&t.record().skipped==1);
  t.begin(300);t.present(310,PresentResult::Success);t.close(320);
  assert(t.record().first==t.record().last&&t.record().first_prefix==t.record().last_prefix);
  t.begin(400);t.present(399,PresentResult::Success);t.close(410);assert(t.record().invalid&FrameTail::Clock);
  t.begin(500);auto x=t.enter(FramePhase::Wait,501);auto y=t.enter(FramePhase::GCStep,502);
  t.leave(x,503);assert(t.record().invalid&FrameTail::Scope);t.leave(y,504);t.leave(x,505);t.close(510);
  t.reset();t.begin(600);t.leave(x,601);assert(t.record().invalid&FrameTail::Scope);t.close(610);
  t.begin(700);t.begin(701);t.close(710);assert(t.record().invalid&FrameTail::Order);
  t.close(711);assert(t.record().invalid&FrameTail::Order);
  t.reset();t.begin(0);t.close(UINT64_MAX);assert(!t.record().invalid&&sum(t.record().whole)==UINT64_MAX);
  t.reset();t.begin(10);const auto bad=t.enter(FramePhase::Count,11);t.leave(bad,12);t.close(13);
  assert(t.record().invalid&FrameTail::Scope);
  std::printf("PASS ledger: scopes, zero/one/multi present, failed/skipped, order, clock, epoch, uint64 limit; bytes=%zu\n",sizeof(t));
}
static void lua(lua_State* L,const std::string& code){
  if(luaL_dostring(L,code.c_str())!=LUA_OK){std::fprintf(stderr,"%s\n",lua_tostring(L,-1));std::abort();}
}
static void seam(const char* module_root){
  lua_State* L=luaL_newstate();assert(L);luaL_openlibs(L);
  g_observations.reset(1000000);clock_us=1000000;
  lua_pushcfunction(L,l_request_observation_flush);lua_setglobal(L,"request_flush");
  lua_pushcfunction(L,l_benchmark_mark);lua_setglobal(L,"mark_native");
  lua(L,"package.path='"+std::string(module_root)+"/?.lua;'..package.path\n"
    "local B=require('3ds.benchmark');b=setmetatable({app={world={getCurrentSpeed=function()return 'Normal' end}},"
    "native={benchmark_mark=mark_native,flush_observations=request_flush}},B)");
  {
    RuntimePhaseScope runtime_phase(FramePhase::Runtime);
    RuntimePhaseScope benchmark_phase(FramePhase::Benchmark);
    lua(L,"progress={};b:mark('SAMPLE-BEGIN',progress);assert(progress.at_us==1000000)");
    assert(g_observations.flush_requested&&clock_us==1000000);
    clock_us+=500000; // Health/callback work inside the existing callback.
  }
  clock_us+=100;g_observations.sample_present(clock_us,PresentResult::Success);++frame_count;
  sink_cost=500000;generated_sweep(L,true); // Real request consumed only here.
  assert(!g_observations.flush_requested&&g_observations.full_us==2100100);
  assert(g_observations.frame_tail.record().flush_end==2600100);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::Full);
  generated_wait();
  const auto full=g_observations.full_us;
  generated_sweep(L,false); // no-frame loop still records GC and skipped.
  assert(g_observations.full_us==full);
  clock_us=61000000;g_observations.sample_present(clock_us,PresentResult::Success);++frame_count;
  {
    RuntimePhaseScope runtime_phase(FramePhase::Runtime);
    RuntimePhaseScope benchmark_phase(FramePhase::Benchmark);
    clock_us+=500000;
    lua(L,"b:mark('SAMPLE-END',progress);assert(progress.at_us==61500000 and progress.frames==2)");
  }
  const auto record=g_observations.frame_tail.record();
  assert(!record.invalid&&record.whole[1]==200000&&record.whole[2]==1000000);
  assert(record.whole[3]==500000&&record.whole[4]==500000&&record.whole[6]==1000000);
  assert(record.skipped==1&&record.success==2&&sum(record.whole)==60500000);
  // Preserve actual producer rows for the canonical offline reader; only the
  // advertisement below is a fixture, since boot initialization is not run.
  std::puts("D2_CAPTURE_BEGIN");
  std::puts("diagnostics: revision=R69 boundary_schema=1");
  std::fputs(captured_output.c_str(),stdout);
  std::puts("D2_CAPTURE_END");
  runtime_flush_observations(true);assert(g_observations.frame_tail.record().end==61500000);
  // True Lua longjmp from the actual native mark stays inside lua_pcall. No
  // phase RAII lives in that naked Lua C frame; C++ caller scope unwinds once.
  {
    RuntimePhaseScope phase(FramePhase::Benchmark);
    lua(L,"assert(not pcall(mark_native,'SAMPLE-END','Normal','day'))");
  }
  g_observations.sample_mark("SAMPLE-BEGIN",clock_us,{boot_log,boot_log_flush,nullptr});
  const auto token=g_observations.timing.begin_span(TimingStage::Runtime,clock_us);
  const auto old_full=g_observations.full_us;
  g_observations.flush_requested=true;runtime_flush_observations(true);
  assert(g_observations.full_us==old_full&&g_observations.flush_requested);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::CompactDeferred);
  assert(g_observations.timing.end_span(token,clock_us,true));
  runtime_flush_observations(true);assert(!g_observations.flush_requested);
  const auto before=captured_output.size();
  g_observations.seal_tail(clock_us,{boot_log,boot_log_flush,nullptr});
  const auto after=captured_output.size();assert(after>before);
  g_observations.seal_tail(clock_us+1,{boot_log,boot_log_flush,nullptr});assert(captured_output.size()==after);
  g_observations.terminal=true;runtime_flush_observations(true);
  assert(captured_output.find("event=SHUTDOWN")!=std::string::npos);
  assert(!g_observations.frame_tail.active());
  // A failed/truncated external sink cannot erase elapsed time. The consumer
  // separately refuses a declared schema whose rows were not delivered.
  g_observations.reset(clock_us);drop_lines=true;
  g_observations.sample_mark("SAMPLE-BEGIN",clock_us,{boot_log,boot_log_flush,nullptr});
  clock_us+=100;g_observations.sample_present(clock_us,PresentResult::Success);
  clock_us+=100;g_observations.sample_mark("ABORT-user",clock_us,{boot_log,boot_log_flush,nullptr});
  assert(!g_observations.frame_tail.active()&&sum(g_observations.frame_tail.record().whole)==200);
  drop_lines=false;
  // Fatal flush freezes at its original entry clock, before the first slow,
  // reentrant output callback. Existing frame owner still uses inputs.now.
  reset_runtime_observations();
  g_observations.sample_mark("SAMPLE-BEGIN",clock_us,{boot_log,boot_log_flush,nullptr});
  clock_us+=100;const auto fatal_boundary=clock_us;
  g_observations.terminal=true;reentrant_slow_sink=true;runtime_flush_observations(true);reentrant_slow_sink=false;
  assert(!g_observations.frame_tail.active()&&!g_observations.frame_tail.record().invalid);
  assert(g_observations.frame_tail.record().end==fatal_boundary);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::Terminal);
  assert(sum(g_observations.frame_tail.record().whole)==100);
  // Actual reset helper used by register, then old token rejection.
  reset_runtime_observations();
  g_observations.sample_mark("SAMPLE-BEGIN",clock_us,{boot_log,boot_log_flush,nullptr});
  const auto old_epoch=g_observations.frame_tail.record().epoch;
  const auto stale=runtime_phase_begin(FramePhase::Runtime);
  clock_us+=123;reset_runtime_observations();
  assert(captured_output.find("event=RESET")!=std::string::npos);
  g_observations.sample_mark("SAMPLE-BEGIN",clock_us,{boot_log,boot_log_flush,nullptr});
  assert(g_observations.frame_tail.record().epoch!=old_epoch);
  runtime_phase_end(stale);assert(g_observations.frame_tail.record().invalid&FrameTail::Scope);
  reset_runtime_observations();
  g_observations.sample_mark("SAMPLE-BEGIN",clock_us,{boot_log,boot_log_flush,nullptr});
  const auto count_before=captured_output.size();
  lua_pushcfunction(L,l_shutdown);assert(lua_pcall(L,0,0,0)==LUA_OK);
  const auto count_after=captured_output.size();assert(count_after>count_before);
  lua_pushcfunction(L,l_shutdown);assert(lua_pcall(L,0,0,0)==LUA_OK);assert(captured_output.size()==count_after);
  runtime_shutdown(L);assert(!g_observations.frame_tail.active());
  assert(runtime().shutdowns==3);
  // All flush actions describe work actually taken, independently of the
  // requested reason. A zero timestamp remains a valid completed instant.
  clock_us=0;sink_cost=0;reset_runtime_observations();
  g_observations.sample_mark("SAMPLE-BEGIN",0,{boot_log,boot_log_flush,nullptr});
  g_observations.flush_requested=true;runtime_flush_observations(false);
  assert(g_observations.frame_tail.record().flush_completed&&g_observations.frame_tail.record().flush_end==0);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::Full);
  clock_us=10000000;runtime_flush_observations(false);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::Compact);
  const auto open=g_observations.timing.begin_span(TimingStage::Runtime,clock_us);
  g_observations.flush_requested=true;runtime_flush_observations(false);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::Deferred);
  assert(g_observations.timing.end_span(open,clock_us,true));
  runtime_flush_observations(false);
  assert(g_observations.frame_tail.record().flush_action==FrameTail::FlushAction::Full);
  seal_observation_tail("ABORT-fixture");
  lua_close(L);
  std::puts("PASS actual Lua/native deferred request, generated GC/wait, 500ms residency, no-frame, real Lua error, full-reset/open-span, terminal single seal");
}
int main(int argc,char** argv){assert(argc==3);if(!std::strcmp(argv[1],"ledger"))ledger();else seam(argv[2]);}
