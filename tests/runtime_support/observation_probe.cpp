#include "runtime/observation.hpp"
#include "cth3ds/cpu_work.hpp"
#include <cstdarg>
#include <cstdio>
#include <string>
#include <cstring>
using namespace cth3ds;
static std::uint64_t clock_us=0;
static std::string output;
static unsigned flush_count=0;
RuntimeObservations observations;
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
  std::puts("PASS compact throttle terminal partial spans retained no false completion");
}
