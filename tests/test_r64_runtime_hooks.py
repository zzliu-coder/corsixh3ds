"""Exercise real adapter save hooks and the protected native pressure callback."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import test_lua_runtime
from test_save_memory import native_inputs

ROOT = Path(__file__).resolve().parents[1]


class R64RuntimeHooks(unittest.TestCase):
    setUpClass = classmethod(lambda cls: test_lua_runtime.LuaRuntimeTests.setUpClass())

    def lua(self, body):
        test_lua_runtime.LuaRuntimeTests().run_lua(
            "package.path=" + repr(str(ROOT / 'lua/?.lua') + ';') + "..package.path\n" + r'''
local P=require('3ds.platform')
local events={}
local function event(name)events[#events+1]=name end
local native={operation_block=function()end,span_abandon=function()end,span_begin=function()return 1 end,span_end=function()end,
 observe_memory=function()end,operation_boundary=function()end,
 flush_observations=function()end,checkpoint=function()end,
 request_redraw=function()end,set_notice=function()end,
 begin_critical_io=function()event('begin')end,
 end_critical_io=function()event('end')end,
 prepare_save=function()event('prepare')end,
 atomic_commit=function(tmp,final,backup)
  assert(tmp==final..'.tmp' and backup);event('commit');return true
 end}
local app={savegame_dir='PRIVATE/',config={},ui={windows={}},
 save=function(_,path)assert(path=='PRIVATE/slot.sav.tmp');event('write');return true end,
 load=function()return true end}
''' + body)

    def test_save_releases_optional_sources_before_prepare_and_preserves_failure(self):
        self.lua(r'''
local live={};local weak=setmetatable({image=live},{__mode='v'})
app.gfx={cache={raw=weak},raw_recent={{bitmap=live}},raw_warm_bytes=308224,
 trimRawWarm=function(self)
  event('trim');self.raw_recent[1]=nil;self.raw_warm_bytes=0
 end}
local platform=P.attach(app,native,{epoch=1,resource_events=false})
assert(app:save('PRIVATE/slot.sav'))
assert(table.concat(events,',')=='begin,trim,prepare,write,commit,end')
assert(weak.image==live and app.gfx.raw_warm_bytes==0)
events={};native.prepare_save=function()event('prepare');error('admission refused')end
local ok,err=pcall(app.save,app,'PRIVATE/slot.sav')
assert(not ok and err:find('admission refused',1,true))
assert(table.concat(events,',')=='begin,trim,prepare,end')
events={};app.gfx.trimRawWarm=function()event('trim');error('trim refused')end
ok,err=pcall(app.save,app,'PRIVATE/slot.sav')
assert(not ok and err:find('trim refused',1,true))
assert(table.concat(events,',')=='begin,trim,end')
assert(weak.image==live,'live ownership must remain unchanged')
''')

    def test_old_or_missing_graphics_still_save_and_failed_recovery_keeps_reason(self):
        self.lua(r'''
local platform=P.attach(app,native,{epoch=1,resource_events=false})
assert(app:save('PRIVATE/slot.sav'))
assert(table.concat(events,',')=='begin,prepare,write,commit,end')
events={};app.gfx={};assert(app:save('PRIVATE/slot.sav'))
assert(table.concat(events,',')=='begin,prepare,write,commit,end')
local observed,paused=0,0
package.loaded['3ds.recovery_activity']={capture=function()return {}end}
package.loaded['3ds.state_health']={
 repairR62=function()error('staff has no resumable timer: 15')end,
 auditR62=function(w,emit)
  assert(w==app.world);observed=observed+1;emit('audit row')
 end}
-- Reattach to capture the load function that now creates a world.
app._3ds=nil;app.world=nil
app.load=function(self)
 self.world={setSpeed=function(_,v)assert(v=='Pause');paused=paused+1 end}
 return true
end
platform=P.attach(app,native,{epoch=1,resource_events=false})
platform.syncScene=function()end
native.diagnostic_line=function(line)
 if line=='audit row' then error('diagnostic output failed')end
end
local ok,reason=app:load('sdmc:/3ds/corsixth/Benchmark/r62-recovery.sav')
assert(ok==false and reason:find('no resumable timer: 15',1,true))
assert(observed==1 and paused==1 and platform.save_prefix=='R63-Recovered-')
''')

    def test_native_pressure_callback_protected_and_stack_balanced(self):
        source = (ROOT / 'src/3ds/runtime_3ds.cpp').read_text()
        start = source.index('      // At this safe point Lua owns')
        end = source.index('    });', start)
        callback = source[start:end]
        compiler, flags, links = native_inputs()
        code = r'''
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}
#include <cassert>
#include <cstdio>
static int pressure(lua_State* L) {
// CALLBACK
}
int main() {
 auto* L=luaL_newstate();assert(L);luaL_openlibs(L);
 auto script=[&](const char* text){
   if(luaL_dostring(L,text)!=LUA_OK){std::fprintf(stderr,"%s\n",lua_tostring(L,-1));assert(false);}
 };
 auto run=[&](bool success){
   const int base=lua_gettop(L);lua_pushcfunction(L,pressure);
   const int status=lua_pcall(L,0,0,0);assert((status==LUA_OK)==success);
   if(status!=LUA_OK)lua_pop(L,1);assert(lua_gettop(L)==base);
 };
 script("TheApp=nil");run(true);
 script("TheApp={gfx={}}");run(true);
 script("trimmed=0; live={}; weak=setmetatable({live=live},{__mode='v'}); "
        "TheApp={gfx={raw_recent={live},trimRawWarm=function(self) "
        "trimmed=trimmed+1; self.raw_recent[1]=nil end}}");
 run(true);script("assert(trimmed==1 and weak.live==live); live=nil");
 run(true);script("assert(trimmed==2 and weak.live==nil)");
 script("TheApp.gfx.trimRawWarm=function()error('injected trim failure')end");run(false);
 script("TheApp=nil;setmetatable(_G,{__index=function()error('strict global')end})");run(false);
 lua_close(L);std::puts("PASS protected pressure callback, live owners, collection and stack");
}
'''.replace('// CALLBACK', callback)
        with tempfile.TemporaryDirectory(prefix='cth-r64-pressure-') as temp:
            path = Path(temp)
            src = path / 'probe.cpp'
            src.write_text(code)
            binary = path / 'probe'
            build = subprocess.run([*compiler, '-std=c++17', '-O2', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', *flags,
                str(src), *links, '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                         UBSAN_OPTIONS='halt_on_error=1'))
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('PASS protected pressure callback', run.stdout)


if __name__ == '__main__':
    unittest.main()
