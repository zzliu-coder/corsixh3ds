"""Execute generated raw loader and byte-bounded ownership with real Lua GC."""
from pathlib import Path
import tempfile
import unittest
from support.pinned_upstream import generated_sources
from test_r62_contracts import method
import test_lua_runtime


class R64PictureWorkingSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp = tempfile.TemporaryDirectory(prefix='cth-r64-pictures-')
        cls.generated = generated_sources(Path(cls.temp.name))
        text = (cls.generated/'CorsixTH/Lua/graphics.lua').read_text()
        cls.methods = 'Graphics={}\n' + '\n'.join(method(text, sig) for sig in (
            'function Graphics:trimRawWarm(', 'function Graphics:_retainRaw(',
            'function Graphics:loadRaw('))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_script(self, script):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.methods + r'''
local loads, reads, freed, fail = 0, 0, 0, false
TH={bitmap=function()
  return setmetatable({setPalette=function()end, load=function(self,data,width)
    loads=loads+1
    if fail then error('injected bitmap allocation failure')end
    assert(#data%width==0)
    return true
  end}, {__gc=function()freed=freed+1 end})
end}
local dimensions={Pol01V={640,480},Rep01V={640,480},Res01V={640,480},
                  Staff01V={640,480},Face01V={65,1350}}
local gfx=setmetatable({cache={raw=setmetatable({},{__mode='v'})},
  reload_functions=setmetatable({},{__mode='k'}),
  load_info=setmetatable({},{__mode='k'}), getPalette=function()return {}end,
  app={readDataFile=function(_,dir,name)
    reads=reads+1
    local size=dimensions[name:sub(1,-5)] or {640,480}
    return string.rep('a',size[1]*size[2])
  end}}, {__index=Graphics})
local function load(name)
 local d=dimensions[name] or {640,480}
 return gfx:loadRaw(name,d[1],d[2])
end
local function gc()collectgarbage('collect');collectgarbage('collect')end
''' + script)

    def test_four_windows_five_sources_gc_cycle_and_trim_rebuild(self):
        self.run_script(r'''
local names={'Pol01V','Rep01V','Res01V','Staff01V','Face01V'}
local identities=setmetatable({},{__mode='v'})
for cycle=1,20 do
 for _,name in ipairs(names)do
  local live=load(name)
  if cycle==1 then identities[name]=live else assert(identities[name]==live)end
  live=nil;gc()
 end
 assert(#gfx.raw_recent==5 and gfx.raw_warm_bytes==1321670)
end
assert(loads==5 and reads==5 and freed==0)
local live=load('Pol01V')
gfx:trimRawWarm();gc()
assert(freed==4 and gfx.cache.raw.Pol01V==live and gfx.raw_warm_bytes==0)
assert(load('Pol01V')==live and loads==5 and gfx.raw_warm_bytes==308224)
live=nil
for _,name in ipairs(names)do load(name)end
gc();assert(loads==9 and reads==9 and #gfx.raw_recent==5)
gfx:trimRawWarm();gc()
assert(freed==9 and next(gfx.cache.raw)==nil and next(gfx.raw_source_bytes)==nil)
print('PASS four windows / five sources: 100 requests, 5 reads; trim and live-owner rebuild')
''')

    def test_lru_source_budget_entry_cap_unknown_oversized_and_live_owners(self):
        self.run_script(r'''
gfx.raw_warm_budget=700
local alive=setmetatable({},{__mode='v'})
local function retain(name,bytes)
 local image={};alive[name]=image;gfx.cache.raw[name]=image
 gfx:_retainRaw(name,image,bytes)
 return image
end
local live=retain('a',300)
retain('b',300)
gfx:_retainRaw('a',live)
retain('c',300);gc()
assert(not alive.b and alive.a==live and alive.c)
assert(gfx.raw_recent[1].name=='a' and gfx.raw_recent[2].name=='c')
retain('d',400);gc()
assert(alive.a==live and #gfx.raw_recent==2 and gfx.raw_warm_bytes==700)
retain('huge',701);retain('unknown',nil);retain('bad',0);retain('nan',0/0)
retain('infinite',math.huge);gc()
assert(not alive.huge and not alive.unknown and not alive.bad and not alive.nan and not alive.infinite)
assert(gfx.raw_warm_bytes==700)
gfx:trimRawWarm();gc();assert(alive.a==live and not alive.c and not alive.d)
gfx.raw_warm_budget=nil;gfx.raw_warm_max_entries=1000
for i=1,12 do retain('entry'..i,1)end
gc();assert(#gfx.raw_recent==8 and gfx.raw_warm_bytes==8)
assert(not alive.entry4 and alive.entry5 and alive.entry12)
gfx.raw_warm_budget=10000000
retain('over-hard-cap',1572865);gc();assert(not alive['over-hard-cap'])
gfx.raw_warm_budget=0;gfx:_retainRaw('a',live);gc()
assert(#gfx.raw_recent==0 and gfx.raw_warm_bytes==0 and alive.a==live)
live=nil;gc();assert(not alive.a)
print('PASS byte LRU, hard entry cap, unknown/oversized sources and visible ownership')
''')

    def test_failed_actual_loader_retries_without_warm_admission(self):
        self.run_script(r'''
fail=true
for i=1,4 do assert(not pcall(load,'Pol01V'))end
gc();assert(reads==4 and loads==4 and not gfx.cache.raw.Pol01V)
assert(not gfx.raw_recent and not gfx.raw_source_bytes)
fail=false
local live=load('Pol01V');gc()
assert(reads==5 and loads==5 and gfx.raw_warm_bytes==308224)
assert(load('Pol01V')==live and reads==5)
gfx:trimRawWarm();assert(load('Pol01V')==live and reads==5)
print('PASS failed loads never admitted; successful retry and trim hit reuse source cost')
''')

    def test_warm_touch_host_delta(self):
        self.run_script(r'''
local names={'Pol01V','Rep01V','Res01V','Staff01V','Face01V'}
for _,name in ipairs(names)do load(name)end
local start=os.clock()
for i=1,100000 do local bitmap=gfx.cache.raw[names[(i%5)+1]];assert(bitmap)end
local baseline=os.clock()-start
start=os.clock()
for i=1,100000 do load(names[(i%5)+1])end
local elapsed=os.clock()-start
assert(loads==5 and reads==5 and gfx.raw_warm_bytes==1321670)
print(string.format('HOST ONLY 100000 warm hits: lookup %.6fs, loader+LRU %.6fs, delta %.3fus/hit',
 baseline,elapsed,(elapsed-baseline)*10))
''')


if __name__ == '__main__':
    unittest.main()
