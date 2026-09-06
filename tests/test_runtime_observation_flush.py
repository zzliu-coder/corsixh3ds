"""Execute production flush with real timing state and controlled clock/heap.

SD byte limits are tested separately against real files. CPU/GPU utilization,
physical scanout and hardware allocator measurements are outside this harness.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PREFIX=r"""
#include "cth3ds/telemetry.hpp"
#include "cth3ds/memory_telemetry.hpp"
#include "cth3ds/bounded_log.hpp"
#include <cstdarg>
#include <cstdio>
#include <string>
using namespace cth3ds;
struct lua_State {};
static uint64_t clock_us=0;
static std::string output;
void boot_log(const char* format,...) {
  char b[4096];va_list args;va_start(args,format);
  vsnprintf(b,sizeof(b),format,args);va_end(args);output+=b;output+='\n';
}
void update_lua_memory(lua_State*) {}
struct Display {void log_display_stats() {boot_log("display-stats: seam=1");}};
Display& runtime() {static Display d;return d;}
"""
MAIN=r"""
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n%s",__LINE__,#x,output.c_str());return 1;}}while(0)
int main() {
  std::snprintf(g_scene_identity.data(),g_scene_identity.size(),"level:1");
  g_timing.present_complete(1,PresentResult::Success);
  g_timing.present_complete(10001,PresentResult::Success);
  clock_us=10000000;runtime_flush_observations(false);
  CHECK(output.find("perf:")!=std::string::npos);
  CHECK(output.find("frames:")==std::string::npos);
  CHECK(g_timing.snapshot(clock_us).intervals.count==1);
  clock_us=11000000;
  const auto save=g_timing.begin_span(TimingStage::Save,clock_us);CHECK(save!=0);
  clock_us=60000000;runtime_flush_observations(false);
  CHECK(output.find("frames:")==std::string::npos);
  const auto bounded=output.size();
  clock_us=60000001;runtime_flush_observations(false);
  CHECK(output.size()==bounded); // no repeated log burst while a span is open
  clock_us=70000000;g_terminal_observation=true;runtime_flush_observations(true);
  CHECK(output.find("observation: terminal=1 active_spans=1 reset_allowed=0")!=std::string::npos);
  CHECK(output.find("stable_eligible=0")!=std::string::npos);
  CHECK(output.find("span: stage=save count=0")!=std::string::npos);
  CHECK(output.find("open=1")!=std::string::npos);
  CHECK(output.find("frames:")!=std::string::npos);
  CHECK(g_timing.snapshot(clock_us).stages[static_cast<size_t>(TimingStage::Save)].open==1);
  CHECK(g_terminal_observation_saved);
  const auto final=output.size();clock_us+=10000000;runtime_flush_observations(true);
  CHECK(output.size()==final);
  std::puts("PASS compact throttle terminal partial spans retained no false completion");
}
"""
class RuntimeObservationFlushTests(unittest.TestCase):
    def test_production_short_run_and_terminal_open_span_are_retained(self):
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        globals=runtime[runtime.index('Telemetry g_timing;'):runtime.index('bool g_log_attempted')]
        heap=re.search(r'(?ms)^struct HeapSnapshot \{.*?^\};',runtime).group()
        flush=re.search(r'(?ms)^void runtime_flush_observations\(.*?^\}',runtime).group()
        seams="""
std::uint64_t now_us() noexcept {return clock_us;}
HeapSnapshot heap_snapshot() {HeapSnapshot h;h.heap_available_estimate=32000000;
h.heap_available_low_water=30000000;h.lua_bytes=6000000;h.linear_free=6000000;return h;}
"""
        with tempfile.TemporaryDirectory(prefix='cth3ds-observation-flush-') as temp:
            temp=Path(temp);cpp=temp/'flush.cpp';binary=temp/'flush'
            cpp.write_text(PREFIX+globals+heap+seams+flush+MAIN)
            command=[os.environ.get('CXX','c++'),'-std=c++17','-O1','-g','-I'+str(ROOT/'include'),
                     str(cpp),str(ROOT/'src/common/telemetry.cpp'),'-o',str(binary)]
            if os.environ.get('CTH3DS_SOUND_SANITIZERS'):
                command[1:1]=['-fsanitize='+os.environ['CTH3DS_SOUND_SANITIZERS'],'-fno-omit-frame-pointer']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS compact throttle',result.stdout)
