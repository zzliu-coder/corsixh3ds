"""R68-C actual module installation and extracted native activation/claim API.

Native callbacks/UI objects are fault-injection seams in the Lua matrix. The
native test executes the exact C++ functions against real FILEs and strict Lua.
The fixed A defect-reproduction files are deliberately separate and unchanged.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import test_lua_runtime
from test_playable_path import function_body
from test_save_memory import native_inputs

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=r'''
local P=require('3ds.platform')
local B=require('3ds.benchmark')
local fields={'save','load','quickSave','quickLoad','errorHandler','_3ds','ui'}
local function fixture(inherited)
 local count={active=false,activate=0,claims=0,errors=0,original=0,block=0,shutdown=0,events=0}
 local methods={save=function()return true end,load=function()return true end,
  quickSave=function()return 'old-save' end,quickLoad=function()return 'old-load' end,
  errorHandler=function(...)count.original=count.original+1;return 'handled',nil,false,... end}
 local bottom=setmetatable({},{__index={visible=false}})
 local ui=setmetatable({},{__index={bottom_panel=bottom}})
 local app={ui=ui,config={},savegame_dir='private/'}
 if inherited then setmetatable(app,{__index=methods})else for k,v in pairs(methods)do app[k]=v end end
 local native={}
 for _,name in ipairs({'span_begin','span_end','span_abandon','observe_memory','operation_boundary',
  'flush_observations','atomic_commit','begin_critical_io','end_critical_io','request_redraw','set_notice'})do
  native[name]=function()return true end
 end
 native.operation_block=function()count.block=count.block+1 end
 native.shutdown=function()count.shutdown=count.shutdown+1 end
 native.checkpoint=function(kind)if kind=='simulation' then count.errors=count.errors+1 end end
 native.resource_event=function()count.events=count.events+1;return true end
 native.benchmark_active=function()return count.active end
 native.benchmark_state=function(value)count.active=value;count.activate=count.activate+1 end
 native.benchmark_enabled=function(claim)
  if claim then count.claims=count.claims+1 end
  return count.enabled==true
 end
 local before={}
 for _,name in ipairs(fields)do before[name]={raw=rawget(app,name),value=app[name]}end
 local function restored()
  for _,name in ipairs(fields)do assert(rawget(app,name)==before[name].raw and app[name]==before[name].value,name)end
  assert(app.ui==ui and ui.bottom_panel==bottom and rawget(ui,'bottom_panel')==nil)
  assert(rawget(bottom,'visible')==nil and bottom.visible==false)
 end
 return app,native,count,{epoch=68,resource_events=false},restored,bottom
end
local calls=0
local token=setmetatable({},{__tostring=function()calls=calls+1;error('forbidden tostring')end})
local function same(actual,wanted)
 if type(wanted)=='string' then
  assert(type(actual)=='string' and actual:find(wanted,1,true) and actual:find('stack traceback:',1,true))
 else assert(type(actual)==type(wanted) and rawequal(actual,wanted))end
end
'''

class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):test_lua_runtime.LuaRuntimeTests.setUpClass()

    def lua(self,script):test_lua_runtime.LuaRuntimeTests().run_lua(FIXTURE+script)

    def test_private_construction_retry_identity_and_activation_ownership(self):
        self.lua(r'''
for _,inherited in ipairs({false,true})do
 for _,site in ipairs({'capability','reader','peek','construct','activate','readback','claim','bottom'})do
  local app,n,c,caps,restored,bottom=fixture(inherited)
  c.enabled=true
  local original_load=app.load
  for attempt=1,2 do
   local undo
   if site=='capability' then local old=n.span_abandon;n.span_abandon=nil;undo=function()n.span_abandon=old end
   elseif site=='reader' then local own=rawget(app,'load');rawset(app,'load',false);undo=function()rawset(app,'load',own)end
   elseif site=='peek' then local old=n.benchmark_enabled;n.benchmark_enabled=function()error(token,0)end;undo=function()n.benchmark_enabled=old end
   elseif site=='construct' then n.runner_context=function()error(token,0)end;undo=function()n.runner_context=nil end
   elseif site=='activate' then local old=n.benchmark_state;n.benchmark_state=function(v)old(v);if v then error(token,0)end end;undo=function()n.benchmark_state=old end
   elseif site=='readback' then local old=n.benchmark_active;n.benchmark_active=function()if c.active then error(token,0)end;return old()end;undo=function()n.benchmark_active=old end
   elseif site=='claim' then local old=n.benchmark_enabled;n.benchmark_enabled=function(claim)if claim then return false end;return true end;undo=function()n.benchmark_enabled=old end
   else getmetatable(bottom).__newindex=function()error(token,0)end;undo=function()getmetatable(bottom).__newindex=nil end end
   local ok,e=pcall(P.attach,app,n,caps);assert(not ok,site)
   undo();restored();assert(not c.active and c.claims==0 and c.block==0 and c.shutdown==0)
   if site~='capability' and site~='reader' and site~='claim' then assert(e==token,site)end
  end
  assert(app.load==original_load)
  local p=P.attach(app,n,caps);assert(p.completed and p.app==app and p.native==n)
  assert(p.operations.platform==p and p.benchmark.app==app and p.benchmark.native==n)
  assert(c.active and c.claims==1 and bottom.visible)
  local saved,handler,activated=app.save,app.errorHandler,c.activate
  assert(P.attach(app,n,caps)==p and app.save==saved and app.errorHandler==handler)
  assert(c.claims==1 and c.activate==activated)
  assert(not pcall(P.attach,app,{},caps))
  assert(not pcall(P.attach,app,n,{epoch=69,resource_events=false}))
  assert(not pcall(P.attach,setmetatable({},{__index=app}),n,caps))
  caps.epoch=900;assert(p.capabilities.epoch==68)
  local a,b,d,owner,event,detail,extra=app:errorHandler('event',false,47)
  assert(a=='handled' and b==nil and d==false and owner==app and event=='event' and detail==false and extra==47)
  assert(c.original==1 and c.errors==1 and p.simulation_errors==1)
  p.benchmark:releaseActivation();assert(not c.active)
 end
end
-- Pure Benchmark construction does not acquire an already active native flag.
local a,n,c=fixture(false);c.active=true
local b=B.new(a,n);assert(c.active and c.activate==0)
assert(not pcall(b.activate,b));b:releaseActivation();assert(c.active and c.activate==0)
-- Notice is an observer: successful binding and one-shot claim remain true.
a,n,c=fixture(false);c.enabled=true;n.set_notice=function()error(token,0)end
local p=P.attach(a,n,{epoch=68,resource_events=false})
assert(p.completed and c.active and c.claims==1 and p.benchmark.results.activation_diagnostics==1)
p.benchmark:releaseActivation()
assert(calls==0)
print('PASS C construction/activation retry matrix: 2 layouts x 8 fault stages, identities and original active refusal')
''')

    def test_raw_primary_diagnostic_isolation_and_irreversible_failure_stop(self):
        self.lua(r'''
for _,spec in ipairs({{value='original string'},{value=false},{},{value=47},{value=token}})do
 local primary=spec.value
 local app,n,c,caps,restored=fixture(false);c.enabled=true
 n.runner_context=function()error(primary,0)end
 local ok,e=pcall(P.attach,app,n,caps);assert(not ok);same(e,primary);restored()
 n.runner_context=nil
 local seen
 app.errorHandler=function(owner,...)
  c.original=c.original+1;seen=table.pack(owner,...);error(primary,0)
 end
 local p=P.attach(app,n,caps)
 local old_print=print;print=function()error('diagnostic print failure')end
 n.checkpoint=function()error('diagnostic checkpoint failure')end
 local accepted,value=pcall(app.errorHandler,app,token,primary,nil,47)
 print=old_print
 assert(not accepted and rawequal(value,primary) and type(value)==type(primary))
 assert(seen.n==5 and seen[1]==app and seen[2]==token and rawequal(seen[3],primary) and seen[5]==47)
 assert(c.original==1 and p.simulation_errors==1 and p.error_diagnostics==2)
 p.benchmark:releaseActivation()
end
for _,inherited in ipairs({false,true})do
 local app,n,c,caps,restored=fixture(inherited);caps.resource_events=true
 n.resource_event=function()c.events=c.events+1;error(token,0)end
 local ok,e=pcall(P.attach,app,n,caps);assert(not ok and e==token);restored()
 assert(c.block==1 and c.shutdown==1 and app._3ds_binding_failed)
 assert(not pcall(P.attach,app,n,caps) and c.events==1)
 -- A failed native inverse is equally unsafe even if the setter changes state.
 app,n,c,caps,restored=fixture(inherited);c.enabled=true
 n.benchmark_state=function(v)c.active=v;error(token,0)end
 ok,e=pcall(P.attach,app,n,caps);assert(not ok and e==token);restored()
 assert(c.block==1 and c.shutdown==1 and app._3ds_binding_failed)
 assert(not pcall(P.attach,app,n,caps))
end
assert(calls==0)
print('PASS C raw five-type errors, original handler once, diagnostics isolated, resource/rollback safe stop')
''')

    def test_binding_ui_owner_claim_uncertainty_and_benchmark_cleanup_safety(self):
        self.lua(r'''
local app,n,c,caps,restored=fixture(false);c.enabled=true
n.benchmark_enabled=function(claim)if claim then c.claims=c.claims+1;error(token,0)end;return true end
local ok,value=pcall(P.attach,app,n,caps)
assert(not ok and value==token and c.claims==1 and c.block==1 and c.shutdown==1);restored()
assert(not pcall(P.attach,app,n,caps))
app,n,c,caps,restored=fixture(false);c.enabled=true
n.benchmark_state=function(value)c.active=value;if value then app.ui={bottom_panel={visible=true}}end end
ok,value=pcall(P.attach,app,n,caps);assert(not ok and value:find('UI owner changed',1,true));restored()
assert(not c.active and c.claims==0)
-- Real Benchmark.restore failure preserves normal ordering and closes native
-- and direct-call gates before releasing the owned active flag.
for _,site in ipairs({'activity','stress','speed','media'})do
 app,n,c,caps=fixture(false);c.enabled=true
 local p=P.attach(app,n,caps);local b=p.benchmark;local order={}
 local A=require('3ds.recovery_activity');local stop=A.stop
 A.stop=function()order[#order+1]='activity';if site=='activity' then error(token,0)end end
 b.stress={close=function()order[#order+1]='stress';if site=='stress' then error(token,0)end end}
 app.world={setSpeed=function()order[#order+1]='speed';if site=='speed' then error(token,0)end end}
 n.benchmark_state=function(value)order[#order+1]=value and 'activate' or 'release';c.active=value end
 if site=='media' then b.media_captured=true;b.applyMedia=function()error(token,0)end end
 n.operation_block=function()order[#order+1]='block';c.block=c.block+1 end
 n.shutdown=function()order[#order+1]='shutdown';c.shutdown=c.shutdown+1 end
 assert(b:cleanup()==false and not c.active and c.block==1 and c.shutdown==1)
 A.stop=stop
 assert(order[1]=='activity' and p.operations.blocked)
 if site=='activity' or site=='speed' then
  assert(table.concat(order,','):find('block,shutdown,release',1,true))
 end
 assert(not pcall(app.save,app,'private.sav') and not pcall(app.load,app,'private.sav'))
 assert(not pcall(p.benchmarkTick,p) and not pcall(p.handleAction,p,{type='none'}))
end
assert(calls==0)
print('PASS C owner identity restore, uncertain claim stops, real benchmark cleanup four fault stages closes no-HID/direct gates')
''')

    def test_raw_visibility_capabilities_failed_candidates_and_closed_owner_gc(self):
        self.lua(r'''
for _,spec in ipairs({{value=false},{value=true},{},{value=0}})do
 for _,inherited in ipairs({false,true})do
  local app,n,c,caps=fixture(inherited);c.enabled=true
  local bottom={visible=spec.value};app.ui.bottom_panel=bottom
  n.benchmark_state=function(v)c.active=v;if v then error(token,0)end end
  local ok,value=pcall(P.attach,app,n,caps)
  assert(not ok and value==token and rawget(bottom,'visible')==spec.value)
  assert(app._3ds==nil and not c.active)
 end
end
for _,name in ipairs({'operation_block','span_abandon'})do
 local app,n,c,caps,restored=fixture(false);n[name]=nil
 assert(not pcall(P.attach,app,n,caps));restored();assert(c.activate==0 and c.events==0)
end
for _,epoch in ipairs({'68',0,-1,68.5})do
 local app,n,c,caps,restored=fixture(false);caps.epoch=epoch
 assert(not pcall(P.attach,app,n,caps));restored()
end
local weak=setmetatable({},{__mode='v'})
do
 local app,n,c,caps=fixture(false);c.enabled=true
 local p=P.attach(app,n,caps)
 weak.app,weak.platform,weak.operations,weak.benchmark=app,p,p.operations,p.benchmark
 p.benchmark:releaseActivation()
end
collectgarbage('collect');collectgarbage('collect');assert(next(weak)==nil)
local weak_failed=setmetatable({},{__mode='v'})
local old_new=B.new
B.new=function(app,native)local b=old_new(app,native);weak_failed[1]=b;return b end
do
 local app,n,c,caps=fixture(false);c.enabled=true
 n.benchmark_state=function(v)c.active=v;if v then error(token,0)end end
 assert(not pcall(P.attach,app,n,caps))
end
B.new=old_new
collectgarbage('collect');collectgarbage('collect');assert(next(weak_failed)==nil)
assert(calls==0)
print('PASS C raw bottom visibility, mandatory APIs, integer epochs, closed and failed owner graphs collect')
''')

    def test_terminal_cleanup_once_real_stress_and_native_no_hid_gate(self):
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        self.assertEqual(runtime.count('bool g_operation_blocked = false;'),1)
        self.assertLess(runtime.index('bool g_operation_blocked = false;'),runtime.index('int l_mark_ready('))
        actual='\n'.join(function_body(runtime,name) for name in (
            'int l_operation_block(', 'bool runtime_simulation_step('))
        code=r'''
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include <cstdio>
#include "cth3ds/simulation_clock.hpp"
cth3ds::SimulationClock g_simulation_clock;
bool g_operation_blocked=false;
std::uint64_t now_us(){return 36001;}
'''+actual+r'''
int reset(lua_State*){g_operation_blocked=false;return 0;}
int probe(lua_State* L){
 g_simulation_clock.reset();g_simulation_clock.begin(1);g_simulation_clock.begin(36001);
 lua_pushboolean(L,runtime_simulation_step());return 1;
}
int main(int argc,char** argv){
 if(argc!=2)return 2;
 auto* L=luaL_newstate();luaL_openlibs(L);
 lua_pushcfunction(L,l_operation_block);lua_setglobal(L,"native_block");
 lua_pushcfunction(L,reset);lua_setglobal(L,"native_reset");
 lua_pushcfunction(L,probe);lua_setglobal(L,"native_step");
 int result=luaL_dofile(L,argv[1]);if(result)std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
 lua_close(L);return result?1:0;
}
'''
        script='package.path='+repr(str(ROOT/'lua/?.lua')+';')+'..package.path\n'+FIXTURE+r'''
local Health=require('3ds.state_health');Health.assertActive=function()return {}end
local Activity=require('3ds.recovery_activity')
local Stress=require('3ds.benchmark_stress') -- complete actual module; close clears window before callback
local cases=0
for _,route in ipairs({'finish','runner','cancel','runner_cancel','error','runner_error','terminal'})do
 for _,fault in ipairs({{},{bad=true,value='first window failure'},{bad=true,value=token},
   {bad=true,value=false},{bad=true},{bad=true,value=47},{bad=true,annual=true}})do
  native_reset();assert(native_step())
  local app,n,c,caps=fixture(false);c.enabled=true
  local writes,reads,exits,terminals=0,0,0,{}
  app.save=function()writes=writes+1;return true end
  app.load=function()reads=reads+1;return true end
  app.exit=function()exits=exits+1 end
  n.operation_block=function()c.block=c.block+1;native_block()end
  n.runner_finish=function(outcome,reason,fields)terminals[#terminals+1]={outcome,reason,fields}end
  local p=P.attach(app,n,caps);local b=p.benchmark
  local order,attempts,restores={},0,0
  Activity.stop=function()order[#order+1]='activity'end
  app.world={setSpeed=function(_,v)order[#order+1]='speed:'..v end}
  n.benchmark_state=function(v)c.active=v;order[#order+1]='activation'end
  b.stress=setmetatable({annual_failed=fault.annual,window={close=function()
   attempts=attempts+1;order[#order+1]='window'
   -- A callback may reenter terminal routes while its owner is cleaning up.
   b:finish();b:cancel('nested');b:tick();b:terminal('PASS','COMPLETE')
   assert(#terminals==0 and exits==0 and not b.cleanup_finished)
   if fault.bad and not fault.annual then error(fault.value,0)end
  end}},Stress)
  b.stress_progress={world=0,hours=0,entities=0,frames=0,at=0}
  b.progress=function()return {world=1,hours=1,entities=1,frames=1,at=1}end
  b.mark=function()end
  local restore=b.restore;b.restore=function(self)restores=restores+1;return restore(self)end
  if route=='runner' or route:find('runner_',1,true) or route=='terminal' then b.run={}end
  if route:find('cancel',1,true)then b:cancel('user')
  elseif route=='terminal'then b:terminal('PASS','COMPLETE')
  else
   if route:find('error',1,true)then b.advance=function()error('primary advance failure',0)end
   else b.advance=b.finish end
   b:tick()
  end
  assert(attempts==1 and restores==1 and not c.active,route)
  assert(table.concat(order,',')=='activity,window,speed:'..
    (route:find('error',1,true) and 'Pause' or 'Normal')..',activation')
  assert(b.cleanup_started and b.cleanup_finished and b.cleanup_ok==not fault.bad)
  if fault.bad then
   assert(c.block==1 and c.shutdown==1 and p.operations.blocked and not native_step())
   assert(not pcall(app.save,app,'blocked.sav') and not pcall(app.load,app,'blocked.sav'))
   assert(not pcall(p.benchmarkTick,p))
   assert(type(b.results.cleanup_error)=='string' and #b.results.cleanup_error<=1024)
   if fault.annual then assert(b.results.cleanup_error:find('annual confirmation incomplete; cleanup blocked',1,true))
   elseif type(fault.value)=='string' then assert(b.results.cleanup_error==fault.value)
   else assert(b.results.cleanup_error=='non-string Lua error ('..type(fault.value)..')')end
   if b.run then assert(#terminals==1 and terminals[1][1]=='FAIL' and terminals[1][2]=='CLEANUP_FAILED')end
  else
   assert(c.block==0 and c.shutdown==0 and not p.operations.blocked and native_step())
   assert(app:save('allowed.sav')==true and app:load('allowed.sav')==true)
   if b.run then assert(#terminals==1 and terminals[1][2]~='CLEANUP_FAILED')end
  end
  if route:find('error',1,true)then assert(b.results.failure_detail=='primary advance failure')end
  local saves_before,loads_before,exit_before,result_before=writes,reads,exits,#terminals
  local first_error=b.results.cleanup_error
  assert(b:cleanup()==not fault.bad);b:finish();b:cancel('again');b:tick();b:terminal('PASS','COMPLETE')
  assert(attempts==1 and restores==1 and b.results.cleanup_error==first_error)
  assert(writes==saves_before and reads==loads_before and exits==exit_before and #terminals==result_before)
  if fault.bad then assert(not native_step() and not pcall(app.save,app,'again.sav'))end
  cases=cases+1
 end
end
assert(calls==0 and cases==49)
print('PASS 49 cleanup success/failure/reentry routes: actual Stress, annual incomplete, raw error kinds, direct save/load and native no-HID gate')
'''
        compiler,flags,links=native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-r68-cleanup-') as name:
            directory=Path(name);source=directory/'probe.cpp';source.write_text(code)
            lua=directory/'probe.lua';lua.write_text(script);binary=directory/'probe'
            result=subprocess.run([*compiler,'-std=c++17','-g','-Wall','-Wextra','-Werror',
                '-fsanitize=address,undefined','-I'+str(ROOT/'include'),*flags,
                str(source),*links,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary),str(lua)],cwd=directory,capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'),timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_native_peek_claim_active_and_readiness_real_files(self):
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        actual='\n'.join(function_body(runtime,name) for name in (
            'void reset_benchmark_activation(', 'int l_benchmark_state(', 'int l_benchmark_active(',
            'int l_benchmark_enabled(', 'int l_mark_ready(', 'int load_embedded_operations(', 'int load_embedded_media(', 'int ensure_adapter('))
        header=(ROOT/'src/3ds/embedded_platform_lua.hpp').read_text()
        for symbol,delimiter,filename in (('Platform','cth3ds_lua','platform.lua'),('Operations','cth3ds_ops','operations.lua'),('Media','cth3ds_media','media.lua')):
            self.assertEqual(re.search(r'R"'+delimiter+r'\((.*)\)'+delimiter+r'"',header,re.S).group(1),
                             (ROOT/'lua/3ds'/filename).read_text())
        self.assertIn('++epoch_;\n    reset_benchmark_activation();',runtime)
        shutdown=function_body(runtime,'  void shutdown() noexcept {')
        self.assertLess(shutdown.index('seal_observation_tail("SHUTDOWN");'),
                        shutdown.index('reset_benchmark_activation();'))
        self.assertIn('int l_shutdown(lua_State*) {runtime().shutdown();return 0;}',runtime)
        wrapper=function_body(runtime,'void runtime_shutdown(')
        self.assertLess(wrapper.index('seal_observation_tail'),wrapper.index('runtime_flush_observations(true)'))
        self.assertIn('runtime().shutdown();',wrapper)
        self.assertIn('reset_runtime_observations();',function_body(runtime,'void register_lua_module('))
        self.assertIn('g_operation_blocked=false;\n  reset_benchmark_activation();',runtime)
        compiler,flags,links=native_inputs()
        code=r'''
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include <cstdio>
#include <cstring>
#include "embedded_platform_lua.hpp"
using namespace cth3ds;
const char* kAdapterModule="3ds.platform";
void boot_log_checkpoint(const char*,const char*){}
bool g_benchmark_active=false,g_operation_blocked=false,g_runner=false,g_runner_interactive=false;
bool runner_active(){return g_runner;}
bool runner_interactive(){return g_runner_interactive;}
void boot_log(const char*,...){}
struct Runtime {int calls=0;int epoch(){return 68;}bool mark_ready(lua_State*){++calls;return true;}} instance;
Runtime& runtime(){return instance;}
'''+actual+r'''
int flags(lua_State* L){g_runner=lua_toboolean(L,1);g_operation_blocked=lua_toboolean(L,2);g_runner_interactive=lua_toboolean(L,3);return 0;}
int reset(lua_State*){reset_benchmark_activation();return 0;}
int main(int argc,char**argv){
 auto* L=luaL_newstate();luaL_openlibs(L);
 lua_pushcfunction(L,l_benchmark_state);lua_setglobal(L,"state");
 lua_pushcfunction(L,l_benchmark_active);lua_setglobal(L,"active");
 lua_pushcfunction(L,l_benchmark_enabled);lua_setglobal(L,"enabled");
 lua_pushcfunction(L,l_mark_ready);lua_setglobal(L,"ready");
 lua_pushcfunction(L,flags);lua_setglobal(L,"flags");
 lua_pushcfunction(L,reset);lua_setglobal(L,"reset");
 lua_pushcfunction(L,ensure_adapter);lua_setglobal(L,"get_adapter");
 int result=luaL_dofile(L,argv[1]);if(result)std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
 lua_close(L);return result?1:0;
}
'''
        script="package.path="+repr(str(ROOT/'lua/?.lua')+';')+"..package.path\n"+FIXTURE+r'''
local marker='sdmc:/3ds/corsixth/benchmark-run.txt'
local used='sdmc:/3ds/corsixth/benchmark-used-r63.txt'
local input='sdmc:/3ds/corsixth/Benchmark/input.sav'
local function write(path,text)local f=assert(io.open(path,'wb'));assert(f:write(text));assert(f:close())end
local function read(path)local f=io.open(path,'rb');if not f then return nil end;local s=f:read('a');f:close();return s end
assert(not active());state(true);assert(active());state(false);assert(not active())
state(true);reset();assert(not active())
assert(not enabled(false));write(marker,'bad');assert(not enabled(true) and read(marker)=='bad')
write(marker,'R63\n');assert(not enabled(false) and read(marker)=='R63\n')
write(input,'private input');write(used,'old claim')
assert(enabled(false) and enabled(false) and read(marker)=='R63\n' and read(used)=='old claim')
-- Rename fails against an existing nonempty directory; neither file changes.
assert(os.rename(used,used..'.old'));assert(os.execute('mkdir '..used));write(used..'/sentinel','keep')
assert(not enabled(true) and read(marker)=='R63\n' and read(used..'/sentinel')=='keep')
assert(os.remove(used..'/sentinel'));assert(os.remove(used));assert(os.rename(used..'.old',used))
assert(enabled(true) and read(marker)==nil and read(used)=='R63\n' and read(input)=='private input')
assert(not enabled(false) and not enabled(true))
-- Actual native claim is composed with the real Platform/Benchmark modules.
write(marker,'R63\n')
local app,n,c,caps,restored=fixture(false)
n.benchmark_enabled=enabled;n.benchmark_active=active;n.benchmark_state=state
for attempt=1,2 do
 n.runner_context=function()error(token,0)end
 local ok,e=pcall(P.attach,app,n,caps);assert(not ok and e==token);restored()
 assert(read(marker)=='R63\n' and not active())
end
n.runner_context=nil
local p=P.attach(app,n,caps);assert(p.completed and active() and read(marker)==nil)
assert(P.attach(app,n,caps)==p);p.benchmark:releaseActivation();assert(not active())
reset();local next_app=fixture(false)
local next_platform=P.attach(next_app,n,{epoch=69,resource_events=false})
assert(next_platform.completed and next_platform.benchmark==nil and not active())
-- SD and compiled fallback both construct the real Benchmark and Operations.
for _,origin in ipairs({'sd','embedded'})do
 if origin=='embedded' then
  package.loaded['3ds.platform']=nil
  package.preload['3ds.platform']=function()error('SD adapter unavailable')end
 end
 local module=get_adapter()
 if origin=='embedded' then
  assert(debug.getinfo(module.attach).source=='@builtin/3ds/platform.lua')
  assert(debug.getinfo(require('3ds.operations').new).source=='@builtin/3ds/operations.lua')
  assert(debug.getinfo(require('3ds.media').isChinese).source=='@builtin/3ds/media.lua')
 end
 local owner,native=fixture(false)
 native.benchmark_enabled=enabled;native.benchmark_active=active;native.benchmark_state=state
 write(marker,'R63\n')
 local adapter=module.attach(owner,native,{epoch=68,resource_events=false})
 assert(adapter.completed and active() and adapter.benchmark and read(marker)==nil)
 assert(adapter.operations.platform==adapter)
 assert(module.attach(owner,native,{epoch=68,resource_events=false})==adapter)
 adapter.benchmark:releaseActivation();assert(not active())
end
-- Explicit runner-interactive native service: the actual early branch must
-- leave every real one-shot file unchanged for both peek and claim. Ordinary
-- binding remains active without constructing or activating a Benchmark.
write(marker,'R63\n');local prior_used,prior_input=read(used),read(input)
flags(true,false,true)
assert(not enabled(false) and not enabled(true) and not enabled(false))
assert(read(marker)=='R63\n' and read(used)==prior_used and read(input)==prior_input)
local interactive_app,interactive_native=fixture(false)
interactive_native.benchmark_enabled=enabled
interactive_native.benchmark_active=active;interactive_native.benchmark_state=state
interactive_native.runner_context=function()error('interactive must not construct Benchmark')end
local interactive_platform=P.attach(interactive_app,interactive_native,{epoch=68,resource_events=false})
assert(interactive_platform.completed and interactive_platform.benchmark==nil and not active())
assert(read(marker)=='R63\n' and read(used)==prior_used and read(input)==prior_input)
flags(false,false,true);assert(enabled(false) and read(marker)=='R63\n')
assert(os.remove(marker))
flags(true,false);assert(enabled(false) and enabled(true));flags(false,false);assert(not enabled(false))
TheApp={};TheApp._3ds={app=TheApp,completed=true,capabilities={epoch=68}}
assert(ready());TheApp._3ds.app={};assert(not pcall(ready));TheApp._3ds.app=TheApp
TheApp._3ds.capabilities.epoch=69;assert(not pcall(ready));TheApp._3ds.capabilities.epoch=68
flags(false,true);assert(not pcall(ready));flags(false,false)
local adapter=TheApp._3ds;TheApp._3ds=nil;setmetatable(TheApp,{__index={_3ds=adapter}})
assert(not pcall(ready))
print('PASS native active getter/setter, read-only peek, single claim, bad/missing input/rename failure/runner, interactive bypass preserves files and ordinary binding, owner+epoch+raw readiness')
'''
        with tempfile.TemporaryDirectory(prefix='cth-r68-binding-') as name:
            directory=Path(name)
            (directory/'sdmc:/3ds/corsixth/Benchmark').mkdir(parents=True)
            source=directory/'binding.cpp';source.write_text(code)
            lua=directory/'binding.lua';lua.write_text(script)
            binary=directory/'binding'
            result=subprocess.run([*compiler,'-std=c++17','-g','-fsanitize=address,undefined',
                '-I'+str(ROOT/'src/3ds'),*flags,
                str(source),*links,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(binary),str(lua)],cwd=directory,capture_output=True,text=True,
                env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:halt_on_error=1'),timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())
