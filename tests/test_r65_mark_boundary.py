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
struct Observation{
 bool open=false;uint64_t start=0;
 bool sample_open(){return open;}
 bool sample_can_close(uint64_t t){return open&&t>start;}
 void sample_mark(const char* event,uint64_t t,Output){
   marked_us=t;
   if(!std::strcmp(event,"SAMPLE-BEGIN")){open=true;start=t;}
   else if(!std::strcmp(event,"SAMPLE-END"))open=false;
 }
}g_observations;
'''+method+r'''
int main(){
 lua_State begin{"SAMPLE-BEGIN"};assert(l_benchmark_mark(&begin)==2);
 assert(logged_us==1000000&&marked_us==1500000&&begin.boundary==1500000&&begin.frames==42);
 bool rejected=false;try{l_benchmark_mark(&begin);}catch(const std::exception&){rejected=true;}assert(rejected);
 clock_us=61500000;lua_State end{"SAMPLE-END"};assert(l_benchmark_mark(&end)==2);
 assert(marked_us==61500000&&end.boundary==61500000&&logged_us==61500000&&clock_us==62000000);
 assert(end.boundary-begin.boundary==60000000);
 rejected=false;try{l_benchmark_mark(&end);}catch(const std::exception&){rejected=true;}assert(rejected);
 clock_us=70000000;l_benchmark_mark(&begin);clock_us=begin.boundary-1;
 rejected=false;try{l_benchmark_mark(&end);}catch(const std::exception&){rejected=true;}assert(rejected);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'mark.cpp';source.write_text(harness)
            binary=Path(tmp)/'mark'
            subprocess.run(['c++','-std=c++17',str(source),'-o',str(binary)],check=True,capture_output=True)
            subprocess.run([str(binary)],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
