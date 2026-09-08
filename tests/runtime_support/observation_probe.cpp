#include "runtime/observation.hpp"
#include "cth3ds/cpu_work.hpp"
#include "cth3ds/input_queue.hpp"
#include <cstdarg>
#include <cstdio>
#include <string>
#include <cstring>
#include <type_traits>
using namespace cth3ds;
static std::uint64_t clock_us=0;
static std::string output;
static unsigned flush_count=0;
RuntimeObservations observations;
static_assert(!std::is_copy_constructible_v<RuntimeObservations>);
static_assert(!std::is_copy_assignable_v<RuntimeObservations>);
static_assert(!std::is_move_assignable_v<RuntimeObservations>);
SimulationClock g_simulation_clock;
void log_line(const char* format,...) {
  char b[4096];va_list args;va_start(args,format);
  vsnprintf(b,sizeof(b),format,args);va_end(args);output+=b;output+='\n';
}
void log_flush() noexcept {++flush_count;}
void display() {log_line("display-stats: seam=1");}
void runtime_flush_observations(bool force) {
  ObservationInputs inputs{};
  inputs.now=clock_us; inputs.heap_available_estimate=32000000;
  inputs.heap_available_low_water=30000000;inputs.lua_bytes=6000000;inputs.linear_free=6000000;
  inputs.clock=g_simulation_clock.statistics();
  observations.flush(inputs,{log_line,log_flush,display},force);
}

#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n%s",__LINE__,#x,output.c_str());return 1;}}while(0)
int main() {
  SlowEvents slow;
  slow.owner(1,"UIStaffRise");
  slow.record(2,3,"read","quick");
  slow.record(3,50003,"read","Data/Face01V");
  slow.record(5,6,"read","bad\npath",false);
  slow.drain(log_line);
  CHECK(output.find("rows=3 dropped=0")!=std::string::npos);
  CHECK(output.find("quick")==std::string::npos);
  CHECK(output.find("owner=\"UIStaffRise\"")!=std::string::npos);
  CHECK(output.find("identity=\"bad_path\"")!=std::string::npos);
  output.clear();
  slow.owner(7,"UIStaffRise");slow.drain(log_line);CHECK(output.empty());
  for(unsigned i=0;i<40;++i) slow.record(i,i+50000,"read","bounded");
  slow.drain(log_line);
  CHECK(output.find("rows=32 dropped=8")!=std::string::npos);
  CHECK(output.find("begin_us=8 elapsed_us=50000")!=std::string::npos);
  CHECK(output.find("begin_us=7 elapsed_us=50000")==std::string::npos);
  output.clear();slow.drain(log_line);CHECK(output.empty());
  cpu_work.rows[static_cast<size_t>(CpuWork::Temperature)]={2,3000,1800,32768};
  g_simulation_clock.begin(1);g_simulation_clock.begin(36001);
  CHECK(g_simulation_clock.take_step(36001));
  std::snprintf(observations.scene.data(),observations.scene.size(),"level:1");
  observations.timing.present_complete(1,PresentResult::Success);
  observations.timing.present_complete(10001,PresentResult::Success);
  clock_us=10000000;runtime_flush_observations(false);
  CHECK(flush_count==1);
  CHECK(output.find("log-buffer: capacity=4096")!=std::string::npos);
  CHECK(output.find("perf:")!=std::string::npos);
  CHECK(output.find("name=temperature calls=2 total_us=3000 max_us=1800 units=32768")!=std::string::npos);
  CHECK(output.find("simulation-budget: steps=1 debt_us=18000 dropped_us=0")!=std::string::npos);
  CHECK(cpu_work.rows[static_cast<size_t>(CpuWork::Temperature)].calls==0);
  CHECK(output.find("frames:")==std::string::npos);
  CHECK(observations.timing.snapshot(clock_us).intervals.count==1);
  clock_us=11000000;
  const auto save=observations.timing.begin_span(TimingStage::Save,clock_us);CHECK(save!=0);
  clock_us=60000000;runtime_flush_observations(false);
  CHECK(flush_count==2);
  CHECK(output.find("frames:")==std::string::npos);
  const auto bounded=output.size();
  clock_us=60000001;runtime_flush_observations(false);
  CHECK(flush_count==2);
  CHECK(output.size()==bounded); // no repeated log burst while a span is open
  clock_us=70000000;observations.terminal=true;runtime_flush_observations(true);
  CHECK(flush_count==3);
  CHECK(output.find("observation: terminal=1 active_spans=1 reset_allowed=0")!=std::string::npos);
  CHECK(output.find("stable_eligible=0")!=std::string::npos);
  CHECK(output.find("span: stage=save count=0")!=std::string::npos);
  CHECK(output.find("open=1")!=std::string::npos);
  CHECK(output.find("frames:")!=std::string::npos);
  CHECK(observations.timing.snapshot(clock_us).stages[static_cast<size_t>(TimingStage::Save)].open==1);
  CHECK(observations.terminal_saved);
  // Passive memory observation receives a value snapshot, never a writable clock.
  const auto clock_before=g_simulation_clock.statistics();
  MemorySample memory{};
  for(const auto* phase:{"before","after","gc-after","failed"}) {
    const auto observation=memory_observation(memory,MemoryGate::Operation,"S70",phase,"load");
    observations.observe("reload",observation);
  }
  CHECK(g_simulation_clock.statistics().rebases==clock_before.rebases);
  CHECK(g_simulation_clock.statistics().debt_us==clock_before.debt_us);
  const auto final=output.size();clock_us+=10000000;runtime_flush_observations(true);
  CHECK(output.size()==final);
  // Exercise the exact production reset after dirty terminal/operation/ring
  // state, including a still-open span. Repeat without allocating a new owner.
  for(unsigned round=0;round<3;++round) {
    observations.slow.owner(clock_us,"stale-window");
    for(unsigned i=0;i<40;++i) observations.slow.record(1,100001,"read","stale-resource");
    observations.window_has_operation=observations.window_scene_changed=true;
    observations.flush_requested=observations.terminal=observations.terminal_saved=true;
    observations.timer_events=observations.logic_callbacks=observations.logic_failures=99;
    observations.reset(clock_us);
    CHECK(observations.scene[0]==0);
    CHECK(!observations.window_has_operation && !observations.window_scene_changed);
    CHECK(!observations.terminal && !observations.terminal_saved && !observations.flush_requested);
    CHECK(observations.compact_us==clock_us && observations.full_us==clock_us);
    CHECK(observations.timer_events==0 && observations.logic_callbacks==0 && observations.logic_failures==0);
    for(const auto& checkpoint:observations.memory.checkpoints()) CHECK(checkpoint.samples==0);
    CHECK(!observations.memory.has_failure() && observations.memory.invalid_events()==0);
    CHECK(!observations.timing.end_span(save,clock_us));
    const auto token=observations.timing.begin_span(TimingStage::Logic,clock_us);
    CHECK(token!=0 && token!=save);
    CHECK(observations.timing.end_span(token,clock_us));
    output.clear();observations.slow.drain(log_line);CHECK(output.empty());
    observations.slow.record(1,100001,"read","fresh-resource");
    observations.slow.drain(log_line);
    CHECK(output.find("owner=\"\"")!=std::string::npos);
    CHECK(output.find("stale-")==std::string::npos);
    output.clear();runtime_flush_observations(true);
    CHECK(output.find("operation_rows=0 overflow=0")!=std::string::npos);
    CHECK(output.find("operation-memory:")==std::string::npos);
    CHECK(output.find("scene= stable_eligible=0")!=std::string::npos);
  }
  std::puts("PASS in-place reset stale records retired tokens invalidated");
  std::puts("PASS compact throttle terminal partial spans retained no false completion");
  const ObservationOutput sink{log_line,log_flush,display};
  observations.reset(0);output.clear();
  observations.timing.present_complete(1,PresentResult::Success);
  observations.sample_mark("SAMPLE-BEGIN",2000000,sink);
  observations.sample_present(2100000,PresentResult::Success);
  observations.sample_present(62100000,PresentResult::Success);
  observations.sample_mark("SAMPLE-END",62200000,sink);
  CHECK(output.find("eligible=1")!=std::string::npos);
  CHECK(output.find("coverage_begin=2100000 coverage_end=62100000")!=std::string::npos);
  CHECK(output.find("intervals=1 sum_us=60000000")!=std::string::npos);
  for(const char* event:{"FAILED","ABORT-user","SAMPLE-BEGIN"}){
    output.clear();observations.reset(0);
    observations.sample_mark("SAMPLE-BEGIN",1,sink);
    observations.sample_present(100,PresentResult::Success);
    observations.sample_present(60000100,PresentResult::Success);
    observations.sample_mark(event,60000200,sink);
    CHECK(output.find("eligible=0")!=std::string::npos);
  }
  output.clear();observations.reset(0);
  observations.sample_mark("SAMPLE-BEGIN",1,sink);
  observations.sample_present(100,PresentResult::Success);
  observations.sample_present(10001,PresentResult::Failed);
  observations.sample_present(60000100,PresentResult::Success);
  observations.sample_mark("SAMPLE-END",60000200,sink);
  CHECK(output.find("eligible=0")!=std::string::npos);
  // Window flush keeps the crossing interval but explicitly disqualifies it.
  observations.reset(1);output.clear();
  observations.timing.present_complete(1,PresentResult::Success);
  clock_us=100;runtime_flush_observations(true);
  observations.timing.present_complete(200,PresentResult::Success);
  clock_us=201;runtime_flush_observations(true);
  CHECK(output.find("crossing_interval=1")!=std::string::npos);
  CHECK(output.find("count=1 sum=199")!=std::string::npos);
  observations.reset(0);output.clear();
  auto phase=memory_observation(memory,MemoryGate::Operation,"S70","writer-before","persist");
  observations.observe("save",phase);clock_us=100;runtime_flush_observations(true);
  CHECK(output.find("site=save phase=writer-before")!=std::string::npos);
  RawInputSnapshot input{};
  CHECK(!benchmark_user_input(input));
  input.circle_x=23;CHECK(!benchmark_user_input(input));
  input.circle_x=24;CHECK(benchmark_user_input(input));
  input.circle_x=0;input.touching=true;CHECK(benchmark_user_input(input));
  InputQueue queue;queue.push(input);input.touching=false;queue.push(input);
  bool tapped=false;while(queue.pop(input,1))tapped=benchmark_user_input(input)||tapped;
  CHECK(tapped); // Press/release between two game ticks still cancels.
  std::puts("PASS strict benchmark anchors interrupted samples raw gaps retained");
}
