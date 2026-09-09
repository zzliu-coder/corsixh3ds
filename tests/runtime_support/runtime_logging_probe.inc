#include "logging_io_probe.hpp"
#include "cth3ds/bounded_log.hpp"
#include "runtime/observation.hpp"
#include "runtime_3ds.hpp"
#include <cstdarg>
#include <sstream>
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
namespace cth3ds {
BoundedLog g_log;
RuntimeObservations g_observations;
SimulationClock g_simulation_clock;
std::uint64_t log_clock=1000000,g_log_time_us{},g_workload_time_us{};
std::uint64_t now_us(){return log_clock;}
unsigned long long runner_frames() noexcept {return 42;}
lua_State* g_observation_state=nullptr;
void update_lua_memory(lua_State*){}
struct Heap {
  std::uint64_t heap_available_estimate=32000000,heap_available_low_water=30000000,
    lua_bytes=6000000,linear_free=6000000;
};
Heap heap_snapshot(){return {};}
struct MemoryObservationGate {static constexpr std::uint64_t interval_us=250000;};
struct Sampling {std::uint64_t sampled{},skipped{},forced{};}g_memory_sampling;
bool nested_diagnostic=false;
struct Runtime {void log_display_stats(){
  if(nested_diagnostic) {
    runtime_diagnostic_line("nested-immediate");
    assert(logging_io::delivered.find("nested-immediate\n")!=std::string::npos);
  }
  gpu_log_statistics();
}};
Runtime& runtime(){static Runtime value;return value;}
// INSERT_NATIVE_LOGGING
}
static void exercise_report_boundaries() {
  using namespace cth3ds;
  auto open=[](){
    g_log.close();logging_io::reset();
    assert(g_log.open("/no-r70-fixture/current","/no-r70-fixture/previous","/no-r70-fixture/oldest"));
    logging_io::on_write=[](){log_clock+=10000;};
  };
  auto count=[](const std::string& text,const char* prefix) {
    std::size_t n=0,at=0;
    while((at=text.find(prefix,at))!=std::string::npos){++n;at+=std::strlen(prefix);}
    return n;
  };
  gpu_shutdown();open();
  static unsigned selected_writes;
  selected_writes=0;
  logging_io::on_deliver=[](const char* bytes,std::size_t n) {
    const std::string text(bytes,n);
    if(text.find("gpu: selected=citro2d")!=std::string::npos) {
      ++selected_writes;
      assert(text.find("gpu: existing_lcd_format_top=")!=std::string::npos);
      assert(text.find("gpu: atlas_floor_affinity=")!=std::string::npos);
    }
  };
  assert(gpu_initialize());assert(selected_writes==1);
  assert(count(logging_io::delivered,"gpu: selected=citro2d")==1);
  assert(logging_io::delivered.find("gpu: selected=citro2d")<logging_io::delivered.find("gpu: existing_lcd_format_top="));
  assert(logging_io::delivered.find("gpu: existing_lcd_format_top=")<logging_io::delivered.find("gpu: atlas_floor_affinity="));
  std::puts("QUANT gpu-success-selected-lines=3 underlying_writes=1 explicit_group_flushes=1");
  open();
  runtime_diagnostic_line("startup %s literal");
  assert(logging_io::delivered=="startup %s literal\n"&&g_log.flushes()==1);
  const auto first=g_log.flushes();gpu_log_statistics();
  assert(g_log.flushes()==first);
  runtime_diagnostic_flush();
  assert(count(logging_io::delivered,"gpu-source:")==1);
  assert(count(logging_io::delivered,"gpu-hot-paths:")==1);
  assert(count(logging_io::delivered,"gpu-work:")==1);
  open();gpu_submit_sample_begin(log_clock);gpu_submit_sample_log();
  assert(g_log.flushes()==0&&logging_io::delivered.empty());
  gpu_submit_sample_end(log_clock+1,true);gpu_submit_sample_log();
  assert(g_log.flushes()==1);
  assert(count(logging_io::delivered,"gpu-submit-")==26);
  assert(count(logging_io::delivered,"gpu-submit-count:")==20);
  assert(count(logging_io::delivered,"gpu-submit-ticks:")==4);

  lua_State* L=luaL_newstate();assert(L);
  auto mark=[&](const char* event,bool error=false) {
    lua_pushcfunction(L,l_benchmark_mark);lua_pushstring(L,event);
    lua_pushstring(L,"Normal");lua_pushstring(L,"fixture");
    const auto boundary=log_clock;
    const int result=lua_pcall(L,3,2,0);
    assert((result!=LUA_OK)==error);
    if(!error&&std::strcmp(event,"SAMPLE-BEGIN"))
      assert(lua_tonumber(L,-2)==static_cast<lua_Number>(boundary));
    lua_settop(L,0);
  };
  auto begin=[&](){
    open();g_observations.reset(log_clock);g_simulation_clock.reset();mark("SAMPLE-BEGIN");
    log_clock+=50000;g_observations.sample_present(log_clock,PresentResult::Success);
  };
  const auto report=[](const char* name) {
    std::printf("QUANT scenario=%s explicit_flushes=%lu underlying_writes=%lu bytes=%lu\n",
      name,static_cast<unsigned long>(g_log.flushes()),static_cast<unsigned long>(logging_io::writes),
      static_cast<unsigned long>(logging_io::delivered.size()));
  };
  begin();log_clock+=60000000;runtime_flush_observations();report("full");
  assert(g_log.flushes()==1);
  for(const char* event:{"SAMPLE-END","ABORT-user","SAMPLE-BEGIN","INVALID-TIME"}) {
    begin();
    const bool backwards=!std::strcmp(event,"INVALID-TIME");
    if(backwards)log_clock-=100000;else log_clock+=60000000;
    const auto boundary=log_clock;
    const auto flushes=g_log.flushes();
    mark(backwards?"SAMPLE-END":event,backwards||!std::strcmp(event,"SAMPLE-BEGIN"));
    assert(!g_observations.sample_open()&&g_log.flushes()==flushes+1);
    assert(logging_io::delivered.find("benchmark-tail: schema=1")!=std::string::npos);
    assert(logging_io::delivered.find("end_us="+std::to_string(boundary))!=std::string::npos);
    assert(count(logging_io::delivered,"gpu-submit-")==26);
    report(event);
    if(!backwards && std::strcmp(event,"SAMPLE-BEGIN"))
      assert(logging_io::delivered.find(std::string(" event=")+event+" speed=\"Normal\"")!=std::string::npos);
    assert(logging_io::delivered.find("class=checkpoint")!=std::string::npos);
  }
  begin();log_clock+=100000;g_observations.terminal=true;
  const auto terminal_boundary=log_clock;
  runtime_flush_observations(true);
  assert(g_observations.terminal_saved&&!g_observations.sample_open());
  assert(logging_io::delivered.find("end_event=TERMINAL")!=std::string::npos);
  assert(logging_io::delivered.find("end_us="+std::to_string(terminal_boundary))!=std::string::npos);
  assert(count(logging_io::delivered,"gpu-submit-")==26);
  report("terminal");
  assert(g_log.flushes()==1);
  const auto final_flushes=g_log.flushes();runtime_flush_observations(true);
  assert(g_log.flushes()==final_flushes);
  open();g_observations.reset(log_clock);g_observations.terminal=true;
  runtime_flush_observations(true);
  assert(g_log.flushes()==1 && g_observations.terminal_saved);
  begin();log_clock+=100000;g_observations.terminal=true;nested_diagnostic=true;
  runtime_flush_observations(true);nested_diagnostic=false;
  assert(g_log.flushes()==2 && logging_io::delivered.find("gpu-submit-ticks: class=checkpoint")!=std::string::npos);
  begin();logging_io::fail_after=0;log_clock+=60000000;
  mark("SAMPLE-END");assert(g_log.failed()&&!g_observations.sample_open());
  const auto aggregate_failed_writes=logging_io::writes;
  runtime_diagnostic_line("discarded after aggregate failure");
  assert(logging_io::writes==aggregate_failed_writes);
  begin();log_clock+=100000;g_observations.terminal=true;logging_io::fail_after=0;
  runtime_flush_observations(true);assert(g_log.failed()&&g_observations.terminal_saved);

  begin();log_clock+=100000;const auto partial_boundary=log_clock;
  seal_observation_tail("SHUTDOWN");
  assert(g_log.flushes()==1&&logging_io::delivered.find("event=SHUTDOWN")!=std::string::npos);
  assert(g_observations.frame_tail.record().end==partial_boundary);
  seal_observation_tail("SHUTDOWN");assert(g_log.flushes()==1);
  begin();log_clock+=100000;reset_runtime_observations();
  assert(g_log.flushes()==1&&logging_io::delivered.find("event=RESET")!=std::string::npos);
  assert(!g_observations.sample_open()&&!g_observations.frame_tail.active());
  begin();logging_io::fail_after=0;seal_observation_tail("SHUTDOWN");
  assert(g_log.failed()&&!g_log.available());
  const auto failed_writes=logging_io::writes;
  seal_observation_tail("SHUTDOWN");reset_runtime_observations();
  assert(logging_io::writes==failed_writes);

  begin();log_clock+=10000000;runtime_flush_observations();
  const auto& tail=g_observations.frame_tail.record();
  assert(g_log.flushes()==1&&tail.flush_completed&&tail.flush_end>tail.flush_begin);
  assert(logging_io::delivered.find("capacity=8192")!=std::string::npos);
  report("compact");
  open();g_log.emergency();const auto urgent=g_log.flushes();gpu_log_statistics();
  assert(g_log.flushes()==urgent+3);
  assert(logging_io::delivered.find("gpu-work:")!=std::string::npos);
  g_log.close();assert(!g_log.available());lua_close(L);
  std::puts("PASS actual GPU/native report boundaries, Lua errors, terminal, partial/reset and D2 flush I/O");
}
