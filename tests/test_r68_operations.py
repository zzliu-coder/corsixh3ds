"""R68-B actual serializer/atomic file, UI and bounded native cleanup checks."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_save_stream_native import build_stream_probe
from test_save_memory import native_inputs
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]


class OperationsTests(unittest.TestCase):
    def test_real_cli_old_marker_preflight_preserves_both_trees(self):
        import hashlib
        import sys
        from support.pinned_upstream import generated_sources
        markers={
            'CorsixTH/Lua/app.lua':'CORSIXTH_3DS_LOAD_CALLER_R68',
            'CorsixTH/Lua/persistance.lua':'CORSIXTH_3DS_LOAD_OWNER_R68',
            'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua':'CORSIXTH_3DS_SAVE_UI_R68',
            'CorsixTH/Lua/dialogs/resizables/file_browsers/load_game.lua':'CORSIXTH_3DS_LOAD_UI_R68',
        }
        def snapshot(tree):
            return {str(path.relative_to(tree)):
                    ('link:'+os.readlink(path) if path.is_symlink() else
                     hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'directory')
                    for path in tree.rglob('*')}
        with tempfile.TemporaryDirectory(prefix='cth-r68-cli-preflight-') as name:
            directory=Path(name)
            tree=generated_sources(directory) # Real CLI fresh and repeat succeed, exact hashes checked.
            overlay=directory/'overlay'
            adapter=overlay/'lua/3ds/platform.lua';original_adapter=adapter.read_bytes()
            adapter.write_bytes(original_adapter+b'\n-- private preflight drift sentinel\n')
            command=[sys.executable,'-B',str(overlay/'tools/integrate_corsixth.py'),
                     str(tree),'--overlay-root',str(overlay),'--json']
            for relative,marker in markers.items():
                path=tree/relative;original=path.read_bytes()
                self.assertIn(marker.encode(),original)
                path.write_bytes(original.replace(marker.encode(),b'MISSING_R68_MARKER',1))
                for mode in (('--output',str(directory/'new-view')),('--dry-run',),('--check',)):
                    with self.subTest(relative=relative,mode=mode):
                        before_tree,before_overlay=snapshot(tree),snapshot(overlay)
                        result=subprocess.run(command+list(mode),capture_output=True,text=True,timeout=60)
                        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                        self.assertIn('R68 requires fresh pinned assembly',result.stdout)
                        self.assertIn(marker,result.stdout)
                        self.assertEqual(snapshot(tree),before_tree,'CLI changed upstream contents or paths')
                        self.assertEqual(snapshot(overlay),before_overlay,'CLI changed overlay contents or paths')
                path.write_bytes(original)
            adapter.write_bytes(original_adapter)
            before_tree,before_overlay=snapshot(tree),snapshot(overlay)
            result=subprocess.run(command+['--output',str(directory/'final-view')],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(snapshot(tree),before_tree)
            self.assertEqual(snapshot(overlay),before_overlay)

    def test_r62_repair_traceback_and_raw_values_with_secondary_failures(self):
        from test_r68_action_contract import ActionContractTests
        ActionContractTests.setUpClass()
        ActionContractTests().lua(r'''
local previous_health=package.loaded['3ds.state_health']
local previous_activity=package.loaded['3ds.recovery_activity']
local previous_print=print
local tostring_calls=0
local token=setmetatable({},{__tostring=function()tostring_calls=tostring_calls+1;error('forbidden tostring')end})
for _,spec in ipairs({{value='R62 repair origin failure'},{value=false},{},{value=token},{value=47}})do
  local p,app=fresh();local primary=spec.value
  local blocked,audited,printed=0,0,0
  local function r62RepairOrigin()error(primary,0)end
  package.loaded['3ds.recovery_activity']={capture=function()return {}end}
  package.loaded['3ds.state_health']={repairR62=r62RepairOrigin,
    auditR62=function(_,emit)audited=audited+1;emit('secondary audit output')end}
  p.native.operation_block=function()blocked=blocked+1 end
  app.world.setSpeed=function()error('secondary pause failure')end
  print=function()printed=printed+1;error('secondary print failure')end
  local loaded,value=app:load('sdmc:/3ds/corsixth/Saves/R62-Recovered.sav')
  print=previous_print
  assert(not loaded)
  if type(primary)=='string' then
    assert(value:find(primary,1,true) and value:find('stack traceback:',1,true))
    assert(value:find("in function 'error'",1,true) or value:find('[C]: in function',1,true))
  else assert(rawequal(value,primary) and type(value)==type(primary))end
  assert(blocked==1 and audited==1 and printed>0 and tostring_calls==0)
  assert(not p.operations.last.ready and p.operations.last.cleanup_count>=2)
  assert(p.operations.last.diagnostic_count>=1 and p.operations.last.error_type==type(primary))
  assert(p.operations.current==nil and not pcall(p.benchmarkTick,p))
end
package.loaded['3ds.state_health']=previous_health
package.loaded['3ds.recovery_activity']=previous_activity
''')

    def test_old_assembly_refused_before_any_product_file_mutation(self):
        import hashlib
        from support.pinned_upstream import original_sources
        from integration.product_patches import patch_product_sources
        from integration.common import IntegrationError
        for relative in ('CorsixTH/Lua/app.lua','CorsixTH/Lua/persistance.lua',
            'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua',
            'CorsixTH/Lua/dialogs/resizables/file_browsers/load_game.lua'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as name:
                tree=original_sources(Path(name))
                path=tree/relative
                path.write_text('-- CORSIXTH_3DS_PRODUCT_U1\n'+path.read_text())
                def snapshot():
                    return {str(p.relative_to(tree)):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in tree.rglob('*') if p.is_file()}
                before=snapshot()
                with self.assertRaisesRegex(IntegrationError,'R68 requires fresh pinned assembly'):
                    patch_product_sources(tree,False)
                self.assertEqual(snapshot(),before)

    def test_real_benchmark_load_rejection_and_failure_cleanup(self):
        from test_r68_action_contract import ActionContractTests
        ActionContractTests.setUpClass()
        ActionContractTests().lua(r'''
local B=require('3ds.benchmark')
local token=setmetatable({},{__tostring=function()error('do not stringify')end})
local p,app=fresh();app.config={};app.savegame_dir='private/'
p.operations.reader=function()return false,token end
local b=setmetatable({app=app,native=p.native,root='private/',phase='pending',index=1,
 profiles={{}},results={}},B)
local ok,raw=pcall(b.load,b)
assert(not ok and raw==token and p.operations.last.ready)
local restores,terminals=0,0
b.mark=function()error('mark unavailable')end
b.restore=function()restores=restores+1;error(token,0)end
b.terminal=function()terminals=terminals+1;error('terminal unavailable')end
b.native.set_notice=function()error('notice unavailable')end
b.native.runner_error=function()error('runner unavailable')end
local previous_print=print;print=function()error('print unavailable')end
assert(pcall(b.tick,b))
print=previous_print
assert(restores==1 and terminals==1 and b.phase=='done' and b.failed)
assert(b.results.failure_detail=='non-string Lua error (table)')
assert(b.results.cleanup_error=='non-string Lua error (table)' and b.results.failure_diagnostics>=4)
-- Unsafe publication prevents fallback to the next profile before any sampling.
p,app=fresh();app.config={};app.savegame_dir='private/'
p.operations.reader=function()return true end
p.afterLoadOperation=function()return false,token end
b=setmetatable({app=app,native=p.native,root='private/',phase='pending',index=1,
 profiles={{}},results={},recovery_copy=true},B)
ok,raw=pcall(b.load,b)
assert(not ok and type(raw)=='string' and raw:find('UNSAFE TO CONTINUE',1,true))
assert(not b.healthy_started and not b.recovery_refused and p.operations.blocked)
''')

    def test_quick_refusals_primary_exceptions_and_recovery_audit(self):
        from test_r68_action_contract import ActionContractTests
        ActionContractTests.setUpClass()
        ActionContractTests().lua(r'''
local p,app,ui,c=fresh()
app.quickSave=function(self)return self:save('quick.sav')end
local token=setmetatable({},{__tostring=function()error('must not stringify primary')end})
p.operations.writer=function()error(token)end
local ok,value=pcall(p.handleAction,p,{type='quick_save'})
assert(not ok and value==token and not p.operations.blocked)
p.operations.writer=function()return true end
p.native.atomic_commit=function()return false,'no destination space' end
action(p,'quick_save','noop:save-refused')
assert(p.operations.last.rejected and p.operations.last.reported)
p.native.atomic_commit=function()return true end
app.quickLoad=function(self)return self:load('quick.sav')end
p.operations.reader=function()return false,'incompatible file' end
action(p,'quick_load','noop:load-refused')
p.operations.reader=function()error(false,0)end
ok,value=pcall(p.handleAction,p,{type='quick_load'})
assert(not ok and value==false)
app.quickLoad=function()return false,'ordinary caller refusal' end
action(p,'quick_load','noop:load-refused') -- stale raised result belongs to the previous request
-- Only the exact R62 copy path uses recovery. Audit/display failures cannot
-- override the repair error; a failed pause still closes the simulation gate.
p,app,ui,c=fresh()
local blocked,audits,prints=0,0,0
p.native.operation_block=function()blocked=blocked+1 end
app.world.setSpeed=function()error('pause failed')end
local previous_health=package.loaded['3ds.state_health']
local previous_activity=package.loaded['3ds.recovery_activity']
package.loaded['3ds.recovery_activity']={capture=function()return {}end}
package.loaded['3ds.state_health']={repairR62=function()error(token,0)end,
 auditR62=function(_,emit)audits=audits+1;emit('audit')end}
local previous_print=print
print=function()prints=prints+1;error('print unavailable')end
local loaded,primary=app:load('sdmc:/3ds/corsixth/Saves/R62-Recovered.sav')
print=previous_print
package.loaded['3ds.state_health']=previous_health
package.loaded['3ds.recovery_activity']=previous_activity
assert(not loaded and primary==token and audits==1 and prints>0)
assert(blocked==1 and not p.operations.last.ready and p.operations.last.cleanup_count>=2)
assert(p.operations.last.diagnostic_count>=1 and p.operations.last.error_type=='table')
assert(not pcall(p.benchmarkTick,p))
''')

    def test_actual_stream_owner_failure_matrix_and_generated_ui(self):
        with tempfile.TemporaryDirectory(prefix='cth-r68-operations-') as name:
            directory=Path(name)
            binary,closure,generated=build_stream_probe(directory)
            source=(ROOT/'tests/sound_lifetime_support/native_persistence_cases.lua').read_text()
            utility=(generated/'CorsixTH/Lua/utility.lua').read_text()
            helper=re.search(r'(?ms)^function pause_gc_and_use_weak_keys\(.*?^end',utility).group()
            original_helper=re.search(r'(?ms)^function pause_gc_and_use_weak_keys\(.*?^end',
                (ROOT/'tests/fixtures/utility.lua.pinned').read_text()).group()
            self.assertEqual(helper,original_helper)
            source=source.replace('function pause_gc_and_use_weak_keys(fn, value) fn(value) end',helper)
            source=source.replace('"flush_observations",','"operation_boundary", "flush_observations",',1)
            start=source.index('function native.atomic_commit(')
            end=source.index('\nend',start)+4
            source=source[:start]+'function native.atomic_commit(a,b)return host_atomic_commit(a,b)end'+source[end:]
            ui=(generated/'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua').read_text()
            ui='UISaveGame={}\n'+re.search(r'(?ms)^function UISaveGame:doSave\(.*?^end',ui).group()
            load_ui=(generated/'CorsixTH/Lua/dialogs/resizables/file_browsers/load_game.lua').read_text()
            ui+='\nUILoadGame={}\n'+re.search(r'(?ms)^function UILoadGame:choiceMade\(.*?^end',load_ui).group()
            app_source=(generated/'CorsixTH/Lua/app.lua').read_text()
            commandline=re.search(r'(?ms)^      local previous=self\._3ds.*?^    end',app_source).group().rsplit('\n',1)[0]
            ui+='\nfunction R68CommandlineLoad(self)\n'+commandline+'\nend\n'
            # Existing real reader/short-write/close/30-cycle cases remain.
            extra=(ROOT/'tests/runtime_support/save_stream_glue_cases.lua').read_text()
            extra+='\nIS_3DS=true\n'+ui+'\n'+(ROOT/'tests/runtime_support/r68_operation_cases.lua').read_text()
            script=directory/'operations.lua'
            script.write_text(source.replace('assert(prepared == cleaned)',extra+'\nassert(prepared == cleaned)'))
            result=subprocess.run([str(binary),str(closure),str(directory),str(script)],
                capture_output=True,text=True,timeout=90,env=dict(os.environ,
                CTH3DS_PERSIST_TESTDIR=str(directory),
                CTH3DS_PERSIST_SOURCE=str(generated/'CorsixTH/Lua/persistance.lua'),
                CTH3DS_PLATFORM_SOURCE=str(generated/'CorsixTH/Lua/3ds/platform.lua')))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('native_persistence_cases=27 ',result.stdout)
            self.assertEqual((generated/'CorsixTH/Lua/3ds/operations.lua').read_bytes(),
                             (ROOT/'lua/3ds/operations.lua').read_bytes())
            for line in result.stdout.splitlines():
                if line.startswith(('PASS ','native_persistence_cases=','model_lua_')):print(line)

    def test_native_owned_abandon_and_no_input_simulation_block(self):
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        functions='\n'.join(re.search(pattern,runtime).group() for pattern in (
            r'(?m)^int l_operation_block\(.*$',r'(?ms)^int l_span_abandon\(.*?^\}',
            r'(?m)^bool runtime_simulation_step\(.*$'))
        code=r'''
extern "C" {
#include <lua.h>
#include <lauxlib.h>
}
#include "runtime/observation.hpp"
#include "cth3ds/simulation_clock.hpp"
#include <cassert>
using namespace cth3ds;
RuntimeObservations g_observations;
SimulationClock g_simulation_clock;
bool g_operation_blocked=false;
std::uint64_t now_us(){return 36001;}
'''+functions+r'''
int main(){
 auto& t=g_observations.timing;
 auto parent=t.begin_span(TimingStage::Runtime,10);
 auto op=t.begin_span(TimingStage::Save,20);
 auto gc=t.begin_span(TimingStage::GC,30);
 assert(!t.end_span(op,40));assert(!t.end_span(gc,29));
 lua_State* L=luaL_newstate();assert(L);
 lua_pushinteger(L,op);assert(l_span_abandon(L)==1 && lua_toboolean(L,-1));lua_settop(L,0);
 auto s=t.snapshot(40);
 assert(s.stages[(unsigned)TimingStage::Runtime].open==1);
 assert(s.stages[(unsigned)TimingStage::Save].open==0 && s.stages[(unsigned)TimingStage::GC].open==0);
 assert(s.stages[(unsigned)TimingStage::Save].completed==0 && s.invalid_events>=3);
 assert(!t.abandon_span(op) && !t.abandon_span(0));
 assert(t.end_span(parent,50));assert(t.reset_window(60));
 auto next=t.begin_span(TimingStage::Load,70);assert(t.end_span(next,80));
 auto old=t.begin_span(TimingStage::Save,90);t.clear();
 parent=t.begin_span(TimingStage::Logic,100);assert(!t.abandon_span(old));
 std::uint64_t full[15];for(auto& v:full)v=t.begin_span(TimingStage::GC,101);
 assert(t.begin_span(TimingStage::Save,102)==0);
 assert(!t.abandon_span(0));assert(t.abandon_span(full[0]));
 assert(t.snapshot().stages[(unsigned)TimingStage::Logic].open==1);
 assert(t.end_span(parent,110));
 g_simulation_clock.begin(1);g_simulation_clock.begin(36001);
 assert(runtime_simulation_step());assert(l_operation_block(L)==0);
 auto steps=g_simulation_clock.statistics().steps;
 for(int i=0;i<100;i++){g_simulation_clock.begin(36001+i*18000);assert(!runtime_simulation_step());}
 assert(g_simulation_clock.statistics().steps==steps);
 lua_close(L);
}
'''
        compiler,flags,links=native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-r68-abandon-') as name:
            directory=Path(name);source=directory/'probe.cpp';binary=directory/'probe'
            source.write_text(code)
            built=subprocess.run([*compiler,'-std=c++17','-O1','-g','-fsanitize=address,undefined',
                '-I'+str(ROOT/'include'),'-I'+str(ROOT/'src/3ds'),*flags,str(source),
                str(ROOT/'src/common/telemetry.cpp'),*links,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_embedded_operations_without_sd_and_no_module_world_roots(self):
        header=(ROOT/'src/3ds/embedded_platform_lua.hpp').read_text()
        operations=re.search(r'R"cth3ds_ops\((.*)\)cth3ds_ops"',header,re.S).group(1)
        self.assertEqual(operations,(ROOT/'lua/3ds/operations.lua').read_text())
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        import json
        from test_r68_action_contract import FIXTURE
        platform=re.search(r'R"cth3ds_lua\((.*)\)cth3ds_lua"',header,re.S).group(1)
        script='package.path="";package.cpath=""\n'
        script+=FIXTURE.replace('local P=assert(loadfile(adapter_path))()',
            'local P=get_adapter()')
        script+='''
local p,app=fresh();assert(app:save('embedded.sav'))
local exported=require('3ds.operations');local count=0
for key,value in pairs(exported)do assert(key=='new' and type(value)=='function');count=count+1 end
assert(count==1 and p.operations.last.committed)
assert(debug.getinfo(exported.new).source=='@builtin/3ds/operations.lua')
'''
        runtime=(ROOT/'src/3ds/runtime_3ds.cpp').read_text()
        actual='\n'.join(re.search(pattern,runtime).group() for pattern in (
            r'(?ms)^int load_embedded_operations\(.*?^\}',r'(?ms)^int ensure_adapter\(.*?^\}'))
        code=r'''
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include "embedded_platform_lua.hpp"
#include <cstring>
#include <cstdio>
using namespace cth3ds;
const char* kAdapterModule="3ds.platform";
void boot_log_checkpoint(const char*,const char*){}
'''+actual+r'''
int main(int argc,char** argv){
 if(argc!=2)return 2;auto* L=luaL_newstate();luaL_openlibs(L);
 lua_pushcfunction(L,ensure_adapter);lua_setglobal(L,"get_adapter");
 int result=luaL_dofile(L,argv[1]);if(result)std::fprintf(stderr,"%s\n",lua_tostring(L,-1));
 lua_close(L);return result?1:0;
}
'''
        compiler,flags,links=native_inputs()
        with tempfile.TemporaryDirectory(prefix='cth-r68-embedded-') as name:
            directory=Path(name);cpp=directory/'main.cpp';binary=directory/'probe';lua=directory/'probe.lua'
            cpp.write_text(code);lua.write_text(script)
            build=subprocess.run([*compiler,'-std=c++17','-O1','-g','-fsanitize=address,undefined',
                '-I'+str(ROOT/'src/3ds'),*flags,str(cpp),*links,'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(binary),str(lua)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)


if __name__=='__main__':unittest.main()
