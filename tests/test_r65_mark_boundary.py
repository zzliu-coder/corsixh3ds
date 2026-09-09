"""Compile the actual native mark method; slow BEGIN logging precedes sampling."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class MarkBoundaryTests(unittest.TestCase):
    def test_actual_native_method_excludes_logging_and_rejects_order(self):
        text=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        start=text.index('int l_benchmark_mark(lua_State* state){')
        method=text[start:text.index('\nint l_runner_context(',start)]
        harness=r'''
#include <cassert>
#include <cstring>
#include <stdexcept>
#include <cstdint>
#include "cth3ds/simulation_clock.hpp"
cth3ds::SimulationClock g_simulation_clock;
using lua_Number=double;
struct lua_State{const char* event;double boundary=0;long long frames=0;};
uint64_t clock_us=1000000, logged_us=0, marked_us=0, log_cost=500000;
uint64_t now_us(){return clock_us;}
const char* luaL_checkstring(lua_State* s,int n){return n==1?s->event:"fixture";}
int luaL_error(lua_State*,const char*){throw std::runtime_error("rejected");}
void lua_pushnumber(lua_State* s,double n){s->boundary=n;}
void lua_pushinteger(lua_State* s,long long n){s->frames=n;}
long long runner_frames(){return 42;}
void boot_log(const char*,unsigned long long stamp,...){logged_us=stamp;clock_us+=log_cost;}
void boot_log_flush(){}
struct Output{decltype(&boot_log) line;decltype(&boot_log_flush) flush;void* unused;};
bool gpu_open=false,gpu_eligible=false;uint64_t gpu_begin=0,gpu_end=0;
void gpu_submit_sample_begin(uint64_t t){gpu_open=true;gpu_begin=t;}
void gpu_submit_sample_end(uint64_t t,bool eligible){gpu_open=false;gpu_end=t;gpu_eligible=eligible;}
void gpu_submit_sample_log(){assert(!gpu_open);}
struct Observation{
 bool open=false;uint64_t start=0;
 bool sample_open(){return open;}
 bool sample_can_close(uint64_t t){return open&&t>start;}
 bool sample_eligible(uint64_t t){return sample_can_close(t)&&t-start>=60000000;}
 void sample_mark(const char* event,uint64_t t,Output,const cth3ds::SimulationClock::Statistics*){
   marked_us=t;
   if(!std::strcmp(event,"SAMPLE-BEGIN")){open=true;start=t;}
   else {
#ifdef CORSIXTH_3DS_GPU
     assert(!gpu_open); // closed before a sink may block or advance the clock
#endif
     open=false;
   }
 }
}g_observations;
'''+method+r'''
int main(){
 lua_State begin{"SAMPLE-BEGIN"};assert(l_benchmark_mark(&begin)==2);
 assert(logged_us==1000000&&marked_us==1500000&&begin.boundary==1500000&&begin.frames==42);
 bool rejected=false;try{l_benchmark_mark(&begin);}catch(const std::exception&){rejected=true;}assert(rejected);
 assert(!g_observations.open); // invalid order closes the real observation window
 clock_us=1000000;l_benchmark_mark(&begin);
 clock_us=61500000;lua_State end{"SAMPLE-END"};assert(l_benchmark_mark(&end)==2);
 assert(marked_us==61500000&&end.boundary==61500000&&logged_us==61500000&&clock_us==62000000);
 assert(end.boundary-begin.boundary==60000000);
#ifdef CORSIXTH_3DS_GPU
 assert(gpu_begin==1500000&&gpu_end==61500000&&gpu_eligible);
#endif
 rejected=false;try{l_benchmark_mark(&end);}catch(const std::exception&){rejected=true;}assert(rejected);
 clock_us=80000000;l_benchmark_mark(&begin);clock_us+=1000000;
 lua_State abort{"ABORT-user"};l_benchmark_mark(&abort);
 assert(!g_observations.open&&!gpu_open&&!gpu_eligible);
 clock_us=70000000;l_benchmark_mark(&begin);clock_us=begin.boundary-1;
 rejected=false;try{l_benchmark_mark(&end);}catch(const std::exception&){rejected=true;}assert(rejected);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'mark.cpp';source.write_text(harness)
            binary=Path(tmp)/'mark'
            for defines in ([],['-DCORSIXTH_3DS_GPU']):
                subprocess.run(['c++','-std=c++17','-I',str(ROOT/'include'),*defines,str(source),'-o',str(binary)],check=True,capture_output=True)
                subprocess.run([str(binary)],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
