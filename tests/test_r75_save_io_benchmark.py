"""R75 explicit private IO experiment. Native serializer tests remain separate.

These cases execute the actual Operations and save-IO controller with named
world/serializer seams; they do not claim hardware speed or clinical service.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import prepare_runner_benchmark as prepare
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

class SaveIoBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def lua(self,script):
        test_lua_runtime.LuaRuntimeTests().run_lua(
            'package.path='+repr(str(ROOT/'lua/?.lua')+';')+'..package.path\n'+script)

    def test_private_operations_options_and_atomic_failures(self):
        with tempfile.TemporaryDirectory() as name:
            # Actual operations owner; the file writer and commit are explicit
            # host filesystem seams, not substitutes for native format tests.
            self.lua('local directory='+repr(name) + r'''
local root='sdmc:/3ds/ftpd-runner/runs/r75-test-01/'
local app={savegame_dir=root..'save/'}
local mode,writes,commits,events=nil,0,0,0
local active=true;local context={root=root,capacity='r75-v1'}
local function localpath(path)return directory..'/'..assert(path:match('([^/]+)$'))end
local function put(path,data)local f=assert(io.open(localpath(path),'wb'));assert(f:write(data));assert(f:close())end
local function get(path)local f=assert(io.open(localpath(path),'rb'));local s=f:read('*a');assert(f:close());return s end
local noop=function()end
local native={benchmark_active=function()return active end,runner_context=function()return context end,
 operation_boundary=noop,flush_observations=noop,begin_critical_io=noop,end_critical_io=noop,
 atomic_commit=function(tmp,final)
  commits=commits+1
  if mode=='commit' then return false,'injected atomic failure' end
  os.remove(localpath(final..'.bak'));assert(os.rename(localpath(final),localpath(final..'.bak')))
  assert(os.rename(localpath(tmp),localpath(final)));return true
 end}
local p={app=app,native=native,resourceEvent=function()events=events+1 end,showError=noop}
local writer=function(instance,path,capacity)
 assert(instance==app);writes=writes+1
 assert(capacity==nil or capacity==16384 or capacity==65536)
 if mode=='write' then error('injected writer failure')end
 put(path,'PAYLOAD');return true
end
local o=require('3ds.operations').new(p,writer,noop)
local final=root..'save/r75-io-1.sav'
local function denied(path,preload,bytes)
 local w,c,e=writes,commits,events
 assert(not pcall(o.save,o,app,path,preload,bytes))
 assert(writes==w and commits==c and events==e and o.current==nil)
end
for _,bytes in ipairs{0,-1,'65536',true,{},65537}do denied(final,false,bytes)end
denied(final,true,65536);denied(root..'save/ordinary.sav',false,65536)
denied(root..'save/../r75-io-1.sav',false,65536)
active=false;denied(final,false,65536);active=true
context.capacity='r74-v1';denied(final,false,65536);context.capacity='r75-v1'
app.savegame_dir='PLAYER/';denied(final,false,65536);app.savegame_dir=root..'save/'
for _,bytes in ipairs{16384,65536}do
 for _,fault in ipairs{'write','commit','ok'}do
  mode=fault;put(final,'OLD');put(final..'.bak','OLDER')
  local ok=pcall(o.save,o,app,final,false,bytes)
  if fault=='ok' then assert(ok and get(final)=='PAYLOAD' and get(final..'.bak')=='OLD')
  else assert(not ok and get(final)=='OLD' and get(final..'.bak')=='OLDER')end
  assert(o.current==nil and o.last.ready)
 end
end
-- Ordinary call carries nil, even after both explicit experiments.
mode='ok';put(final,'OLD');assert(o:save(app,final,false)==true)
''')

    def controller(self,tail):
        self.lua(r'''
local active=false
local report={outcome='NOT_PROVEN',count=1,updated=1,action_covered=0}
local A={start=function()active=true end,report=function()return report end,
 stop=function()active=false end}
setmetatable(A,{__index=function(_,key)if key=='active'then return active end end})
package.loaded['3ds.recovery_activity']=A
package.loaded['3ds.state_health']={assertActive=function(app)assert(not app.broken);return{staff=1}end}
package.loaded['3ds.benchmark_stress']={fingerprint=function(app)return app.state end,
 assertFingerprint=function(app,before,message)assert(app.state==before,message)end}
class={is=function(e,kind)return e.staff==true end};Staff={}
local now,writes,fail_at,advanced,closed=0,{},nil,0,false
local root='sdmc:/3ds/ftpd-runner/runs/r75-test-01/'
local world={entities={{staff=true,humanoid_class='Doctor'}},setSpeed=function(self,s)self.speed=s end,
 getCurrentSpeed=function(self)return self.speed end}
local app={world=world,savegame_dir=root..'save/',state='FIXED',_3ds={}}
app._3ds.operations={save=function(self,a,path,preload,bytes)
 writes[#writes+1]={path=path,capacity=bytes}
 if fail_at==#writes then error('injected save failure')end
 self.last={method='save',committed=true,completed=true,ready=true};now=now+10;return true
end}
local b={app=app,root=root,run={capacity='r75-v1',save_io_input_sha256=string.rep('a',64)},results={},
 native={clock_ms=function()return now end,memory=function()return{heap_available_estimate=17000000,
 heap_available_low_water=16000000,linear_free=2199552}end},
 progress=function()return{world=7,hours=7,frames=7}end,
 recoveryLine=function(_,line)assert(#line<=230)end}
local snapshots={}
local c={b=b,check=function()assert(not closed)end,
 load=function(self,path)assert(path:sub(1,#root)==root);app.state='FIXED' end,
 snapshot=function(self,stage)snapshots[#snapshots+1]=stage end,
 normal=function(self,phase,duration)world:setSpeed('Normal');b.deadline=now+duration;self.phase=phase end,
 advanced=function()advanced=advanced+1 end}
local IO=require('3ds.benchmark_save_io');local io_run=IO.new(c)
assert(not io_run:tick() and active and b.deadline==30000)
''' + tail)

    def test_same_frame_ab_order_roundtrip_and_bounded_results(self):
        self.controller(r'''
now=29999;assert(not io_run:tick() and #writes==0)
now=30000;assert(io_run:tick() and advanced==1 and not active)
for i,bytes in ipairs{16384,65536,65536,16384}do
 assert(writes[i].capacity==bytes and writes[i].path==root..'save/r75-io-'..i..'.sav')
 assert(b.results['save_io_sample_'..i]:find('elapsed_ms=10',1,true))
end
assert(#writes==4 and b.results.save_io_roundtrip=='PASS')
assert(b.results.save_io_outcome=='HOST_READBACK_REQUIRED' and b.results.save_io_bytes_outcome=='NOT_PROVEN')
assert(c.phase=='begin' and world:getCurrentSpeed()=='Pause')
local count,size=0,0
for k,v in pairs(b.results)do count=count+1;size=size+#k+#v+2;assert(#v<=1024)end
assert(count<=12 and size<2200)
assert(not pcall(io_run.tick,io_run),'completed IO batch must not replay')
io_run:close();assert(#writes==4)
''')

    def test_cancel_and_failure_do_not_claim_pass_or_replay(self):
        self.controller(r'''
io_run:close();closed=true
assert(not active and #writes==0 and b.results.save_io_outcome=='NOT_PROVEN')
''')
        self.controller(r'''
fail_at=2;now=30000;assert(not pcall(io_run.tick,io_run))
assert(#writes==2 and b.results.save_io_sample_1 and not b.results.save_io_sample_2)
assert(not pcall(io_run.tick,io_run) and #writes==2)
io_run:close();assert(not active and b.results.save_io_outcome=='NOT_PROVEN')
''')

    def test_real_benchmark_cancel_and_failure_dispatch_capacity_cleanup(self):
        # Reuse the existing real Benchmark/Capacity/Activity constructor chain.
        # Only App load-level method definitions come from pinned originals;
        # these cases terminate before calling loadLevel, so no generated whole
        # checkout or fake completion of that downstream path is involved.
        import test_r73_capacity as previous
        from support.pinned_upstream import original_sources
        with tempfile.TemporaryDirectory() as name:
            old=previous.GENERATED
            try:
                previous.GENERATED=original_sources(Path(name)/'original')
                script=previous.benchmark_script().split("step(1);assert(b.capacity.phase=='reception_1')")[0]
            finally:previous.GENERATED=old
        script=script.replace("capacity='r73-v1'","capacity='r75-v1',save_io_input_sha256=string.rep('a',64)")
        script=script.replace("local continuity=file:find('continuity',1,true)~=nil",
            "local continuity=file:find('continuity',1,true)~=nil or file:find('input.sav',1,true)~=nil")
        script=script.replace('runner_context=function()',
            'simulation_clock=function()return {at_us=now*1000,nominal_timer_us=18000,completed_steps=now,'
            'failed_steps=0,dropped_us=0,debt_us=0,rebases=0,budget_exits=0}end,runner_context=function()')
        script+="\nstep(1);assert(b.capacity.save_io and A.active)\n"
        for tail in (r'''
b:cancel('lifecycle')
assert(fields.reason=='CANCEL' and fields.outcome=='NOT_PROVEN')
assert(fields.save_io_outcome=='NOT_PROVEN' and not A.active and not active)
assert(b.capacity.save_io==nil and b.phase=='done')
''',r'''
b.capacity.advanced=function()error('injected IO activity failure')end
step(30000)
assert(fields.reason=='FAILED' and fields.outcome=='FAIL')
assert(fields.failure_detail:find('injected IO activity failure',1,true))
assert(fields.save_io_outcome=='FAIL' and not A.active and not active)
assert(b.capacity.save_io==nil and b.phase=='done')
''',r'''
local writes=0
app._3ds.operations={guard=function()end,save=function(self,a,file,preload,bytes)
 writes=writes+1;if writes==2 then error('injected IO writer failure')end
 self.last={method='save',committed=true,completed=true,ready=true};return true
end}
step(30000)
assert(fields.reason=='FAILED' and fields.outcome=='FAIL' and writes==2)
assert(fields.save_io_sample_1 and not fields.save_io_sample_2)
assert(fields.failure_detail:find('injected IO writer failure',1,true))
assert(fields.save_io_outcome=='FAIL' and not A.active and not active)
assert(b.capacity.save_io==nil and b.phase=='done')
step(1);assert(writes==2)
'''):
            self.lua(script+tail)

    def test_prepare_opt_in_input_identity_and_budget(self):
        with tempfile.TemporaryDirectory() as name:
            base=Path(name)/'installed';(base/'Lua').mkdir(parents=True)
            (base/'Benchmark').mkdir();(base/'game/LEVELS').mkdir(parents=True)
            (base/'Lua/a.lua').write_text('return {}');(base/'config.txt').write_text('config')
            (base/'receipt.json').write_text('{}')
            for item in ('input','expanded','continuity'):(base/'Benchmark'/f'{item}.sav').write_text(item)
            for item in prepare.CAPACITY_ASSETS:(base/'game/LEVELS'/item).write_text(item)
            input_file=Path(name)/'busy.sav';input_file.write_bytes(b'PRIVATE BUSY INPUT')
            args=argparse.Namespace(installed_tree=base,integration_receipt='receipt.json',
                assets_receipt_sha256='a'*64,profile='expanded-zh-on',warmup_ms=1000,sample_ms=1000,
                stress_ms=1,recovery=False,save_io_capacity=True,capacity_input=input_file,
                out=Path(name)/'out')
            original=prepare.sha
            def dependency_sha(path):
                if path.name=='continuity.sav':return prepare.CONTINUITY_SHA
                if path.name=='expanded.sav':return 'f8a8039644a81a22b44fd1dfed6201c70782ae6bf4873bdb50b3ba7b2c63a0e7'
                return prepare.CAPACITY_ASSETS.get(path.name) or original(path)
            with patch.object(prepare,'sha',dependency_sha):
                prepare.prepare(args)
                fields=dict(line.split('=',1)for line in(args.out/'config.bin').read_text().splitlines())
                receipt=json.loads((args.out/'preparation.json').read_text())
                self.assertEqual(fields['capacity'],'r75-v1')
                self.assertEqual(fields['save_io_input_sha256'],original(input_file))
                self.assertEqual(receipt['input'],str(input_file.resolve()))
                self.assertEqual(receipt['command'][-1],'1297')
                args.out=Path(name)/'bad';args.save_io_capacity=False
                with self.assertRaisesRegex(ValueError,'capacity input requires'):prepare.prepare(args)
                self.assertFalse(args.out.exists())

    def test_native_input_identity_contract_matches_opt_in(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name);source=path/'probe.cpp'
            source.write_text(r'''
#include "adapter.cpp"
#include <cassert>
int main(){
  using namespace cth3ds;
  runner::Fields f;const std::string hash(64,'a');
  validateSaveIoInput(f,hash);f["capacity"]="r74-v1";validateSaveIoInput(f,hash);
  f["save_io_input_sha256"]=hash;
  bool denied=false;try{validateSaveIoInput(f,hash);}catch(...){denied=true;}assert(denied);
  f["capacity"]="r75-v1";validateSaveIoInput(f,hash);
  for(const auto& bad:{std::string(),std::string(64,'b'),std::string(64,'X')}){
    f["save_io_input_sha256"]=bad;denied=false;
    try{validateSaveIoInput(f,hash);}catch(...){denied=true;}assert(denied);
  }
}
''')
            native=ROOT/'src/3ds/runner'
            subprocess.run(['c++','-std=c++17','-DCTH3DS_STUB_BUILD','-I'+str(native),
                str(source),str(native/'core.cpp'),str(native/'rosalina.cpp'),'-o',str(path/'probe')],
                capture_output=True,check=True)
            subprocess.run([str(path/'probe')],cwd=path,capture_output=True,check=True)

    def test_readback_requires_all_four_identical_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name)
            self.assertEqual(prepare.compare_save_io_readback(directory)['outcome'],'NOT_PROVEN')
            for i in range(1,5):(directory/f'r75-io-{i}.sav').write_bytes(b'FIXED GRAPH')
            result=prepare.compare_save_io_readback(directory)
            self.assertEqual(result['outcome'],'PASS')
            self.assertEqual([row['capacity']for row in result['rows']],[16384,65536,65536,16384])
            (directory/'r75-io-3.sav').write_bytes(b'OTHER GRAPH')
            self.assertEqual(prepare.compare_save_io_readback(directory)['outcome'],'NOT_PROVEN')

if __name__=='__main__':unittest.main()
