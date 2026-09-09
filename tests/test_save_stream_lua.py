"""Generated production Lua transactions with real files and injected native seam.

The serializer seam here verifies ownership/cleanup, not native format or memory.
Native dump_file bytes, short writes and allocation failures need the C++ probe.
"""
from pathlib import Path
import tempfile
import unittest
from support.pinned_upstream import generated_sources
import test_lua_runtime

ROOT = Path(__file__).resolve().parents[1]


class SaveStreamLuaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.generated = generated_sources(Path(cls.temp.name))
        test_lua_runtime.LuaRuntimeTests.setUpClass()

    def test_generated_stream_transaction_failure_matrix_and_retry(self):
        source = (self.generated / 'CorsixTH/Lua/persistance.lua').read_text()
        source = source[source.index('strict_declare_global "SaveGame"'):]
        prefix = r'''
local IS_3DS=true
local persist={}
local failure,prepared,cleaned,closed,dumped,commits='',0,0,0,0,0
local real_open,real_print=io.open,print
local messages={}
print=function(message)messages[#messages+1]=tostring(message)end
local final=TEST_DIRECTORY..'/private.sav'
local payload='SERIALIZED\0GRAPH'
local function write(path,data)
 local f=assert(real_open(path,'wb'));assert(f:write(data));assert(f:close())
end
local function read(path)
 local f=assert(real_open(path,'rb'));local s=f:read('*a');assert(f:close());return s
end
strict_declare_global=function()end
math.randomdump=function()return 'RANDOM' end
local NameOf=function()return 'fixture' end
local live='LIVE'
local map={prepareForSave=function()
 if failure=='prepare' then error('injected prepare') end
 assert(live=='LIVE');live='PREPARED';prepared=prepared+1
end,afterSave=function()
 assert(live=='PREPARED');live='LIVE';cleaned=cleaned+1
 if failure=='afterSave' then error('injected afterSave') end
end}
local MakePermanentObjectsTable=function()
 if failure=='permanent' then error('injected permanent') end
 return {sentinel=true}
end
TheApp={map=map,world={},ui={},savegame_dir=TEST_DIRECTORY..'/'}
local native={span_begin=function()return 1 end,span_end=function()end,
 operation_boundary=function()end,flush_observations=function()end,
 checkpoint=function()end,set_notice=function()end,request_redraw=function()end,
 begin_critical_io=function()end,end_critical_io=function()end,
 clock_ms=function()return 123 end,
 observe_memory=function(_,phase)
  if failure==phase then error('injected '..phase) end
 end,
 atomic_commit=function(tmp,path)
  assert(closed==1 and live=='LIVE' and tmp==final..'.tmp' and path==final)
  commits=commits+1
  assert(os.remove(path..'.bak'));assert(os.rename(path,path..'.bak'))
  assert(os.rename(tmp,path));return true
 end}
TH3DS=native
persist.dump=function(state,permanent)
 assert(state.map==map and state.output_file==nil and permanent.sentinel)
 return payload
end
persist.dump_file=function(state,permanent,f)
 dumped=dumped+1
 assert(state.map==map and state.output_file==nil and permanent.sentinel)
 assert(live=='PREPARED' and f.unbuffered)
 if failure=='serialize' then error('injected serialize') end
 if failure=='serialize_result' then return nil,'injected serialize_result',state.world end
 if failure=='invalid_result' then return 'payload',#payload end
 if failure=='invalid_bytes' then return true,-1 end
 if failure=='invalid_flushes' then return true,#payload,-1 end
 local ok,err=f:write(payload);assert(ok,err)
 return true,#payload,1
end
io.open=function(path,mode)
 assert(path==final..'.tmp' and mode=='wb')
 if failure=='open' then return nil,'injected open' end
 local file=assert(real_open(path,mode))
 local proxy={}
 function proxy:setvbuf(mode)
  assert(mode=='no' and prepared==0)
  if failure=='setvbuf' then return nil,'injected setvbuf' end
  if failure=='setvbuf_throw' then error('injected setvbuf_throw') end
  self.unbuffered=true;return file:setvbuf(mode)
 end
 function proxy:write(data)
  if failure=='write' then return nil,'injected write' end
  return file:write(data)
 end
 function proxy:close()
  closed=closed+1;assert(closed==1);local result=assert(file:close())
  if failure=='close' then return nil,'injected close' end
  if failure=='close_throw' then error('injected close_throw') end
  return result
 end
 return proxy
end
'''
        suffix = r'''
TheApp.save=function(_,path)return SaveGameFile(path)end
TheApp.load=function()return true end
local platform=dofile(PLATFORM_PATH)
platform.attach(TheApp,native,{epoch=1,asset_mode='loose',resource_events=false})
for _,stage in ipairs{'open','setvbuf','setvbuf_throw','prepare-before','prepare','prepare-after',
 'permanent','writer-before','serialize','serialize_result','write','writer-after',
 'dump-after','afterSave-before','afterSave','afterSave-after','close-before',
 'close','close_throw','close-after','invalid_result','invalid_bytes','invalid_flushes'} do
 failure=stage;prepared=0;cleaned=0;closed=0;dumped=0;commits=0;live='LIVE'
 write(final,'OLD');write(final..'.bak','OLDER')
 local ok,err=pcall(TheApp.save,TheApp,final)
 assert(not ok,stage..' unexpectedly passed')
 assert(commits==0 and read(final)=='OLD' and read(final..'.bak')=='OLDER',stage)
 assert(closed==(stage=='open' and 0 or 1),stage..' close count')
 assert(cleaned==prepared and live=='LIVE',stage..' cleanup pairing')
 if stage=='open' or stage:find('setvbuf') then assert(prepared==0 and dumped==0) end
 -- A new successful transaction proves reuse after every controlled failure.
 failure='';prepared=0;cleaned=0;closed=0;dumped=0
 assert(TheApp:save(final)==true and commits==1)
 assert(read(final)==payload and read(final..'.bak')=='OLD')
 assert(prepared==1 and cleaned==1 and closed==1 and live=='LIVE')
end
-- The original string API still performs exactly one paired transaction.
prepared=0;cleaned=0
assert(SaveGame()==payload and prepared==1 and cleaned==1)
local stream_reports=0
for _,message in ipairs(messages)do
 if message:find('save-stream:',1,true) then
  stream_reports=stream_reports+1
  assert(message:find('mode=stream16k bytes=16 flush_count=1',1,true))
  assert(message:find('writer_includes_io=1',1,true) and message:find('commit_included=0',1,true))
 end
end
assert(stream_reports==23,'one successful report per retry; failed saves never report success')
io.open=real_open;print=real_print
'''
        script = ('local TEST_DIRECTORY=' + repr(self.temp.name) + '\n' +
                  'local PLATFORM_PATH=' + repr(str(ROOT / 'lua/3ds/platform.lua')) + '\n' +
                  prefix + source + suffix)
        test_lua_runtime.LuaRuntimeTests().run_lua(script)


if __name__ == '__main__':
    unittest.main()
