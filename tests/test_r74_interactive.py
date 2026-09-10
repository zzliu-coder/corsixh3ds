"""Private ordinary-play contracts. Hardware HOME/lid/audio remain unproven."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import prepare_runner_benchmark as prepare
import read_interactive_result as reader
import test_lua_runtime
from test_r65_reception_recovery import method
from support.pinned_upstream import generated_sources

ROOT=Path(__file__).resolve().parents[1]

class InteractiveTests(unittest.TestCase):
    def test_native_private_start_identity_exit_and_no_false_pass(self):
        native=ROOT/'src/3ds/runner'
        harness=r'''
#include "adapter.cpp"
#include <cassert>
#include <filesystem>
namespace runner { void nextLoad(const std::string& p,const std::vector<std::string>& a){assert(p==SELF&&a.empty());} }
int main(int argc,char** argv){
  using namespace cth3ds;
  const std::string test=argv[1],base="sdmc:/3ds/corsixth/";
  std::filesystem::create_directories(base+"Lua");
  runner::atomicWrite(base+"Lua/a.lua","return {}\n");
  runner::atomicWrite(base+"config.txt","player config");
  runner::atomicWrite(base+"receipt.json","{}\n");
  runner::Job j;j.id="interactive-01";
  const auto dir=j.dir(runner::SDROOT);
  std::filesystem::create_directories(dir);
  runner::Fields cfg={{"adapter","corsixth-r63-v1"},{"profile","zh-on"},
    {"interactive","r74-v1"},{"stress_ms","0"},{"warmup_ms","1000"},{"sample_ms","1000"},
    {"assets_receipt_sha256",std::string(64,'a')},
    {"lua_tree_sha256",runner::sha256("a.lua|"+runner::hashFile(base+"Lua/a.lua")+"\n")},
    {"player_config_sha256",runner::hashFile(base+"config.txt")},
    {"verify_0",runner::hashFile(base+"receipt.json")+"|"+base+"receipt.json"}};
  if(test=="unknown")cfg["interactive"]="r75";
  if(test=="capacity")cfg["capacity"]="r74-v1";
  if(test=="recovery")cfg["recovery_sha256"]=std::string(64,'a');
  if(test=="stress")cfg["stress_ms"]="1";
  if(test=="profile")cfg["profile"]="matrix";
  if(test=="legacy")cfg.erase("interactive");
  runner::atomicWrite(j.target(runner::SDROOT),"binary");j.sha=runner::hashFile(j.target(runner::SDROOT));
  runner::atomicWrite(dir+"/input.bin","healthy input");j.inputSha=runner::hashFile(dir+"/input.bin");
  runner::atomicWrite(dir+"/config.bin",runner::encode(cfg));j.configSha=runner::hashFile(dir+"/config.bin");
  const auto manifest=runner::encode({{"version","1"},{"run_id",j.id},{"artifact_sha256",j.sha},
    {"config_sha256",j.configSha},{"input_sha256",j.inputSha}});
  runner::atomicWrite(dir+"/manifest.kv",manifest);j.manifestSha=runner::sha256(manifest);
  if(test=="input_hash")runner::atomicWrite(dir+"/input.bin","changed");
  if(test=="binary_hash")runner::atomicWrite(j.target(runner::SDROOT),"changed");
  if(test=="lua_hash")runner::atomicWrite(base+"Lua/a.lua","changed");
  if(test=="config_hash")runner::atomicWrite(base+"config.txt","changed");
  if(test=="asset_hash")runner::atomicWrite(base+"receipt.json","changed");
  auto target=j.target(runner::SDROOT);char* entry[]={target.data(),j.id.data(),j.manifestSha.data()};
  const auto before=runner::hashFile(base+"config.txt");
  const int result=runner_start(3,entry);
  if(test!="good"&&test!="fail"&&test!="legacy"){
    assert(result==-1&&!runner::exists(dir+"/started.kv"));
    assert(!runner::exists(dir+"/save/Acceptance.sav"));
    assert(runner::hashFile(base+"config.txt")==before);return 0;
  }
  assert(result==1&&runner_active());
  if(test=="legacy"){
    assert(!runner_interactive()&&!runner::exists(dir+"/save/Acceptance.sav"));
    runner_process_exit();assert(!runner::exists(dir+"/result.kv"));return 0;
  }
  assert(runner_interactive()&&runner::hashFile(dir+"/save/Acceptance.sav")==j.inputSha);
  assert(runner::read(dir+"/save/config.txt")=="player config");
  bool rejected=false;try{runner_finish("PASS","fake");}catch(...){rejected=true;}
  assert(rejected&&!runner::exists(dir+"/result.kv"));
  runner_present(true);runner_present(false);
  if(test=="fail")runner_finish("FAIL","native_fatal");
  runner_process_exit();const auto bytes=runner::read(dir+"/result.kv");
  auto fields=runner::validateResult(j,bytes);
  assert(fields.at("outcome")== (test=="fail"?"FAIL":"NOT_PROVEN"));
  assert(fields.at("workload")=="corsixth-r74-interactive-v1");
  if(test=="good")assert(fields.at("reason")=="needs_human_confirmation"&&fields.at("frames")=="1");
  runner_process_exit();runner_finish("NOT_PROVEN","override");assert(runner::read(dir+"/result.kv")==bytes);
  runner::atomicWrite(dir+"/launch.kv",runner::encode({{"version","1"},{"run_id",j.id},
    {"artifact_sha256",j.sha},{"config_sha256",j.configSha},{"input_sha256",j.inputSha},
    {"manifest_sha256",j.manifestSha},{"launch_boot","first"}}));
  runner::atomicWrite(std::string(runner::SDROOT)+"/active",runner::encode({{"run_id",j.id},{"manifest_sha256",j.manifestSha}}));
  runner::recover(runner::SDROOT,"second");
  auto receipt=runner::parse(runner::read(dir+"/receipt.kv"));
  assert(receipt.at("status")=="COMPLETED"&&receipt.at("outcome")==fields.at("outcome"));
  assert(runner::hashFile(base+"config.txt")==before);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);source=work/'probe.cpp';source.write_text(harness)
            subprocess.run(['c++','-std=c++17','-fsanitize=address,undefined','-I'+str(native),str(source),
                str(native/'core.cpp'),'-o',str(work/'probe')],check=True,capture_output=True)
            for case in ('good','fail','legacy','unknown','capacity','recovery','stress','profile','input_hash',
                         'binary_hash','lua_hash','config_hash','asset_hash'):
                with self.subTest(case=case):
                    cwd=work/case;cwd.mkdir()
                    subprocess.run([str(work/'probe'),case],cwd=cwd,check=True,capture_output=True)
                    if case in ('good','fail'):
                        run=cwd/'sdmc:/3ds/ftpd-runner/runs/interactive-01'
                        (run/'artifacts/boot.log').write_text('retained raw log')
                        output=reader.inspect(run)
                        self.assertEqual(output['product_acceptance'],'NOT_PROVEN')
                        self.assertEqual(output['outcome'],'FAIL' if case=='fail' else 'NOT_PROVEN')
                        original_launch=(run/'launch.kv').read_text();original_receipt=(run/'receipt.kv').read_text()
                        for bad in ('missing','empty','same'):
                            launch=original_launch;receipt=original_receipt
                            if bad=='same':receipt=receipt.replace('return_boot=second','return_boot=first')
                            else:
                                replacement='' if bad=='missing' else 'launch_boot=\n'
                                launch=launch.replace('launch_boot=first\n',replacement)
                                receipt=receipt.replace('launch_boot=first\n',replacement)
                            (run/'launch.kv').write_text(launch);(run/'receipt.kv').write_text(receipt)
                            with self.assertRaisesRegex(ValueError,'launcher reentry'):reader.inspect(run)
                        (run/'launch.kv').write_text(original_launch);(run/'receipt.kv').write_text(original_receipt)
                        for filename in ('result.kv','launch.kv','receipt.kv'):
                            original_version=(run/filename).read_text()
                            (run/filename).write_text(original_version.replace('version=1','version=2'))
                            with self.assertRaisesRegex(ValueError,'record version'):reader.inspect(run)
                            (run/filename).write_text(original_version)
                        original=(run/'result.kv').read_text()
                        (run/'result.kv').write_text(original.replace('outcome=NOT_PROVEN','outcome=PASS'))
                        if case=='good':
                            with self.assertRaisesRegex(ValueError,'PASS forbidden'):reader.inspect(run)
                        (run/'result.kv').write_text(original)
                        (run/'save/Acceptance.sav').write_text('overwritten')
                        self.assertTrue(reader.inspect(run)['acceptance_save']['modified_from_input'])
                        (run/'save/Acceptance.sav').unlink()
                        self.assertFalse(reader.inspect(run)['acceptance_save']['present'])
                        (run/'input.bin').write_text('tampered original')
                        with self.assertRaisesRegex(ValueError,'input.bin identity mismatch'):reader.inspect(run)

    def test_preparation_legacy_bytes_private_input_and_no_submit(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);base=work/'installed';(base/'Lua').mkdir(parents=True);(base/'Benchmark').mkdir()
            (base/'Lua/a.lua').write_text('return {}');(base/'config.txt').write_text('config')
            (base/'receipt.json').write_text('{}');(base/'Benchmark/input.sav').write_text('input')
            healthy=work/'healthy.sav';healthy.write_text('healthy')
            args=argparse.Namespace(installed_tree=base,integration_receipt='receipt.json',assets_receipt_sha256='a'*64,
                profile='zh-on',warmup_ms=1000,sample_ms=1000,stress_ms=0,recovery=False,out=work/'old')
            prepare.prepare(args);old=(args.out/'config.bin').read_text()
            args.interactive=False;args.interactive_input=None;args.out=work/'unchanged';prepare.prepare(args)
            self.assertEqual(old,(args.out/'config.bin').read_text())
            args.interactive=True;args.interactive_input=healthy;args.out=work/'interactive';prepare.prepare(args)
            cfg=(args.out/'config.bin').read_text();self.assertEqual(cfg.replace('interactive=r74-v1\n',''),old)
            receipt=json.loads((args.out/'preparation.json').read_text())
            self.assertEqual(receipt['command'][-1],'1800');self.assertEqual(receipt['input_sha256'],prepare.sha(healthy))
            self.assertEqual(sorted(p.name for p in args.out.iterdir()),['config.bin','preparation.json'])
            for key,value in [('capacity',True),('busy_capacity',True),('recovery',True),('stress_ms',1),('profile','matrix')]:
                original=getattr(args,key,None);setattr(args,key,value);args.out=work/('bad-'+key)
                with self.assertRaises(ValueError):prepare.prepare(args)
                self.assertFalse(args.out.exists());setattr(args,key,original)

    def test_actual_generated_main_exit_outside_restart_and_private_app_routes(self):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        with tempfile.TemporaryDirectory() as temp:
            generated=generated_sources(Path(temp))
            main=(generated/'CorsixTH/SrcUnshared/main.cpp').read_text()
            hook=main.index('cth3ds::runner_process_exit();')
            loop=main.index('while (bRun) {');start=main.index('{',loop)
            # The actual generated C++ control structure, including restart and
            # runtime shutdown, must close before the one final-process hook.
            depth=1;end=start+1
            while depth:
                if main[end]=='{':depth+=1
                elif main[end]=='}':depth-=1
                end+=1
            self.assertLess(end,hook);self.assertEqual(main.count('runner_process_exit();'),1)
            self.assertIn('runtime_shutdown(L.get())',main[start:end])
            self.assertIn('bRun = lua_toboolean',main[start:end])
            self.assertNotIn('runner_process_exit',(ROOT/'src/3ds/runtime_3ds.cpp').read_text())
            from integration.runner_adapter import patch_runner_adapter
            self.assertEqual(patch_runner_adapter(generated),[])
            source=(generated/'CorsixTH/Lua/app.lua').read_text()
            script="App={};IS_3DS=true;local root="+repr(str(Path(temp)/'private')+'/')+r'''
TH3DS={runner_context=function()return{root=root,interactive='r74-v1'}end}
local writes={};local open=io.open
io.open=function(path,mode)writes[#writes+1]=path;return{write=function()return true end,close=function()return true end}end
local configs={};package.loaded.config_finder={save_config=function(path)configs[#configs+1]=path end}
'''
            for signature in ('function App:getConfigPath()', 'function App:initUserDirectories()',
                              'function App:initScreenshotsDir()', 'function App:writeToFileOrTmp(',
                              'function App:initSavegameDir()', 'function App:saveConfig()'):
                script+=method(source,signature)+'\n'
            script+=r'''
local a=setmetatable({config={}},{__index=App})
a:initUserDirectories();a:initSavegameDir();a:initScreenshotsDir();a:saveConfig()
assert(a.savegame_dir==root..'save/' and a:getConfigPath()==root..'save/config.txt')
assert(a.user_log_dir==root..'artifacts/' and a.screenshot_dir==root..'artifacts/')
assert(configs[1]==root..'save/config.txt')
assert(a:writeToFileOrTmp(root..'save/new.sav','w'))
assert(not pcall(a.writeToFileOrTmp,a,'sdmc:/3ds/corsixth/Saves/player.sav','w'))
assert(#writes==1);io.open=open
'''
            test_lua_runtime.LuaRuntimeTests().run_lua(script)
            config_source=(generated/'CorsixTH/Lua/config_finder.lua').read_text()
            config_script=r'''
local root='sdmc:/3ds/ftpd-runner/runs/private-01/'
package.loaded.th3ds={runner_context=function()return{root=root,interactive='r74-v1'}end}
local paths={};local oldopen=io.open
io.open=function(path)paths[#paths+1]=path;return{write=function()return true end,close=function()return true end}end
local config_contents=function()return 'config'end
local hotkeys_contents=function()return 'hotkeys'end
local apply_config_defaults=function()end;local apply_hotkeys_defaults=function()end
local new_config_defaults=function()return{}end;local new_hotkeys_defaults=function()return{}end
lfs={attributes=function(path)paths[#paths+1]=path;return true end};package.loaded.lfs=lfs
function loadfile_envcall(path)paths[#paths+1]=path;return function()end end
'''
            for signature in ('local function save_config(', 'local function save_hotkeys(',
                              'local function load_config(', 'local function load_hotkeys('):
                config_script+=method(config_source,signature)+'\n'
            config_script+=r'''
save_config('player/config.txt',{});save_hotkeys('player/hotkeys.txt',{})
load_config('player/config.txt');load_hotkeys('player/hotkeys.txt')
assert(#paths==6)
for _,path in ipairs(paths)do assert(path==root..'save/config.txt' or path==root..'save/hotkeys.txt')end
io.open=oldopen
'''
            test_lua_runtime.LuaRuntimeTests().run_lua(config_script)

    def test_actual_benchmark_gate_returns_before_marker_peek_or_claim(self):
        source=(ROOT/'src/3ds/runtime_3ds.cpp').read_text();start=source.index('int l_benchmark_enabled(')
        gate=source[start:source.index('\n  constexpr const char* marker',start)]
        # Compile the exact early native branch: remaining marker path is an
        # observable seam, reached only for ordinary non-runner launches.
        harness='''#include <cassert>
struct lua_State{};bool active,interactive,pushed;int markers=0;
bool runner_active(){return active;}bool runner_interactive(){return interactive;}
void lua_pushboolean(lua_State*,bool b){pushed=b;}
'''+gate+'''\n++markers;return 0;}
int main(){active=true;interactive=true;for(int i=0;i<2;i++){assert(l_benchmark_enabled(nullptr)==1&&!pushed);}
assert(markers==0);interactive=false;assert(l_benchmark_enabled(nullptr)==1&&pushed&&markers==0);
active=false;assert(l_benchmark_enabled(nullptr)==0&&markers==1);}
'''
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp);(work/'gate.cpp').write_text(harness)
            subprocess.run(['c++','-std=c++17',str(work/'gate.cpp'),'-o',str(work/'gate')],check=True,capture_output=True)
            subprocess.run([str(work/'gate')],check=True,capture_output=True)
