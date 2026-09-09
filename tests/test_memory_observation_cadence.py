"""Actual runtime observation routing: bounded ordinary cost, immediate gates."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_save_memory import native_inputs

ROOT = Path(__file__).resolve().parents[1]


class MemoryObservationCadenceTests(unittest.TestCase):
    def test_actual_routing_and_gate_boundaries(self):
        source = (ROOT / 'src/3ds/runtime_3ds.cpp').read_text()
        begin = source.index('void runtime_observe_memory(const char* checkpoint,')
        end = source.index('void runtime_note_timer_event()', begin)
        method = source[begin:end]
        code = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "cth3ds/allocation_watch.hpp"
using namespace cth3ds;
std::uint64_t time_us{},snapshots{},lua_queries{},recorded{},fail_logs{};
std::uint64_t now_us() noexcept {return time_us;}
enum class CpuWork {MemoryObserve};
struct CpuWorkScope {explicit CpuWorkScope(CpuWork) {}};
enum class MemoryGate {Operation};
struct Heap {std::uint64_t heap_total{},arena{},uordblks{},fordblks{},linear_total{},linear_free{},lua_bytes{};};
Heap heap_snapshot() {++snapshots;return {};}
void* g_observation_state=reinterpret_cast<void*>(1);
void update_lua_memory(void*) {++lua_queries;}
struct MemorySample {std::uint64_t now{},heap_total{},arena{},uordblks{},fordblks{},linear_total{},linear_free{},lua_bytes{};bool known{};};
struct Observation {std::array<char,16> phase{},resource{};};
Observation memory_observation(MemorySample,MemoryGate,const char*,const char*,const char*,
 std::uint64_t,bool,std::uint64_t,bool,bool,bool) {return {};}
struct Observations {void observe(const char*,const Observation&) {++recorded;}} g_observations;
const char* g_current_stage="test";
MemoryObservationGate g_memory_sampling;
AllocationWatch g_lua_allocations;
void boot_log(const char*,...) {}
void boot_log_memory(const char*) {++fail_logs;}
// ACTUAL_RUNTIME_METHOD
void reset() {time_us=snapshots=lua_queries=recorded=fail_logs=0;g_memory_sampling={};}
void observe(const char* site,bool failed=false,std::uint64_t requested=0,bool known=false,const char* phase="after") {
 runtime_observe_memory(site,phase,"fixture",MemoryGate::Operation,requested,known,0,false,failed,false);
 assert(snapshots==lua_queries && snapshots==recorded);
}
int main() {
 static_assert(MemoryObservationGate::interval_us==250000);
 // Real event routing at 1,000 events/sec. A detailed sample is taken 240
 // times in 60sec rather than the old 1,200. This measures calls, not device ms.
 for(const auto* site:{"vspr_decode","textures","release","gc","sound_play","sound_release"}) {
  reset();for(time_us=0;time_us<60000000;time_us+=1000)observe(site);
  assert(snapshots==240 && g_memory_sampling.skipped==59760 && g_memory_sampling.forced==0);
 }
 // Operations use actual source classification and cannot be throttled by
 // an immediately preceding high-frequency sample.
 for(const auto* site:std::array<const char*,8>{{"save","reload","language","sound","world","restore","menu",nullptr}}) {
  reset();observe("textures");time_us=1;observe(site);
  assert(snapshots==2 && g_memory_sampling.forced==1);
 }
 reset();observe("textures");time_us=1;observe("textures",false,262143,true);
 assert(snapshots==1);observe("textures",false,262144,false);assert(snapshots==1);
 observe("textures",false,262144,true);assert(snapshots==2 && g_memory_sampling.forced==1);
 observe("sound_play",true);assert(snapshots==3 && fail_logs==1 && g_memory_sampling.forced==2);
 time_us=250000;observe("textures");assert(snapshots==3);
 time_us=250001;observe("textures");assert(snapshots==4);
 // Each millisecond contains a before/after pair, sharing the existing gate.
 reset();for(time_us=0;time_us<60000000;time_us+=1000) {
  observe("sound_read",false,4,true,"before");observe("sound_read",false,4,true,"after");
 }
 assert(snapshots==240 && g_memory_sampling.skipped==119760 && !g_memory_sampling.forced);
 for(const auto* phase:{"before","after"})for(const auto request:{0ULL,4ULL,262143ULL,262144ULL}) {
  reset();observe("textures");observe("sound_read",false,request,true,phase);
  assert(snapshots==(request>=262144?2:1));
  observe("sound_read",false,request,false,phase);assert(snapshots==(request>=262144?3:2));
 }
 for(const auto* phase:std::array<const char*,6>{{"music-playing","decode-before","chunk-after","owner-after","",nullptr}}) {
  reset();observe("sound_read",false,4,true,"before");observe("sound_read",false,4,true,phase);
  assert(snapshots==2 && g_memory_sampling.forced==1);
 }
 for(const auto request:{0ULL,4ULL,262143ULL,262144ULL}) {
  reset();observe("sound_read",false,4,true,"before");
  observe("sound_read",true,request,true,"after");
  assert(snapshots==2 && fail_logs==1 && g_memory_sampling.forced==1);
 }
 for(const auto* site:{"sound_decode","sound_index","sound_evict"}) {
  reset();observe("sound_read",false,4,true,"before");observe(site,false,4,true);
  assert(snapshots==2 && g_memory_sampling.forced==1);
 }
 // Zero origin, exact boundary, backward clock and reset preserve determinism.
 MemoryObservationGate gate;
 assert(gate.take(0,false));assert(!gate.take(0,false));assert(!gate.take(249999,false));
 assert(gate.take(250000,false));assert(gate.take(249999,false));
 assert(gate.take(249999,true) && gate.forced==1);
 gate={};assert(gate.sampled==0 && gate.skipped==0 && gate.forced==0 && gate.take(0,false));
 std::puts("PASS actual routing: 240 ordinary snapshots/60sec, immediate operations/failures/large requests");
}
'''.replace('// ACTUAL_RUNTIME_METHOD', method)
        compiler, _, _ = native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-memory-cadence-') as temp:
            directory = Path(temp)
            path = directory / 'probe.cpp'
            path.write_text(code)
            binary = directory / 'probe'
            build = subprocess.run([*compiler, '-std=c++17', '-O2', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                '-I' + str(ROOT / 'include'), str(path), '-o', str(binary)],
                capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                         UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS actual routing', result.stdout)
            print(result.stdout, end='')


if __name__ == '__main__':
    unittest.main()
