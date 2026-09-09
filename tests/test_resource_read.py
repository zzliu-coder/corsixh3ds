"""Real generated FS/App/Graphics entry points and bounded read fault cases."""
from pathlib import Path
import tempfile
import unittest

from support.pinned_upstream import generated_sources
from test_r62_contracts import method
import test_lua_runtime


class ResourceReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp = tempfile.TemporaryDirectory(prefix='cth-r70-resource-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.generated = generated_sources(cls.directory / 'assembly')
        cls.data = cls.directory / 'game'
        (cls.data / 'QData').mkdir(parents=True)
        (cls.data / 'Data').mkdir()
        cls.sizes = (0, 1, 8191, 8192, 8193, 65536, 2228540, 4194305)
        for size in cls.sizes:
            (cls.data / 'QData' / ('Size-%d.dat' % size)).write_bytes(b'x' * size)
        for name, content in {'Raw.dat': b'RNC' + b'p' * 64,
                              'Plain.dat': b'q' * 64, 'Bad.dat': b'RNCbad',
                              'Sheet.tab': b'tab', 'Sheet.dat': b'RNCsprites'}.items():
            (cls.data / 'QData' / name).write_bytes(content)
        cls.names = [p.name for p in (cls.data / 'QData').iterdir()]
        app = (cls.generated / 'CorsixTH/Lua/app.lua').read_text()
        graphics = (cls.generated / 'CorsixTH/Lua/graphics.lua').read_text()
        cls.app = method(app, 'function App:readDataFile(')
        cls.graphics = '\n'.join(method(graphics, signature) for signature in (
            'function Graphics:trimRawWarm(', 'function Graphics:_retainRaw(',
            'function Graphics:loadRaw(', 'function Graphics:loadSpriteTable(',
            'function Graphics:updateTarget('))
        persistence = (cls.generated / 'CorsixTH/Lua/persistance.lua').read_text()
        cls.load_outer = persistence[persistence.index('local function loadDescription('):
                                    persistence.index('\n-- CORSIXTH_3DS_U3_OBSERVATIONS_V1',
                                                      persistence.index('function LoadGameFile('))]

    def setup_lua(self):
        return 'local root=' + repr(str(self.data)) + '\n' + \
            'local generated=' + repr(str(self.generated / 'CorsixTH/Lua')) + '\n' + \
            'local names={' + ','.join(repr(n) for n in self.names) + '}\n' + r'''
package.path=generated..'/?.lua;'..package.path
local reader=require('3ds.resource_read')
local pathsep='/'
local IS_3DS=true
TH={iso_fs=function()error('unexpected ISO constructor')end}
package.loaded.TH=TH
class=function(name)_G[name]={}end
lfs={attributes=function(path,attribute)
 if path==root or path==root..'/QData' or path==root..'/Data' then return 'directory' end
 return 'file'
end,dir=function(path)
 local list=path==root and {'QData','Data'} or path==root..'/QData' and names or {}
 local index=0
 return function()index=index+1;return list[index]end
end}
assert(loadfile(generated..'/filesystem.lua'))()
local fs=setmetatable({},{__index=FileSystem});fs:FileSystem();assert(fs:setRoot(root))
local original_open=io.open
local opens,closes,formats,seeks=0,0,{},0
io.open=function(path,mode)
 assert(mode=='rb');opens=opens+1
 local f,e=original_open(path,mode);if not f then return nil,e end
 return {read=function(_,format)formats[#formats+1]=format;return f:read(format)end,
 seek=function(_,...)seeks=seeks+1;return f:seek(...)end,
 close=function()closes=closes+1;return f:close()end}
end
local function reset()opens=0;closes=0;formats={};seeks=0 end
App={};Graphics={}
local rnc={decompress=function(data)
 if data=='RNCbad' then return nil,'bad RNC' end
 return data:sub(4)
end}
''' + self.app + '\n' + self.graphics + r'''
local app=setmetatable({fs=fs},{__index=App})
local native_loads=0
local function native()
 return {setPalette=function()end,load=function(_,a,b)
   native_loads=native_loads+1;assert(type(a)=='string');return true
 end}
end
TH.bitmap=native;TH.sheet=native
local gfx=setmetatable({app=app,cache={raw={},tabled={},palette={['MPalette.dat']={}}},
 reload_functions=setmetatable({},{__mode='k'}),reload_functions_last=setmetatable({},{__mode='k'}),
 load_info=setmetatable({},{__mode='k'}),
 getPalette=function()return {}end},{__index=Graphics})
pause_gc_and_use_weak_keys=function(callback,value)return callback(value)end
'''

    def run_lua(self, suffix):
        test_lua_runtime.LuaRuntimeTests().run_lua(self.setup_lua() + suffix)

    def test_real_files_sizes_normalization_provider_and_platform_routes(self):
        self.run_lua('local sizes={' + ','.join(map(str, self.sizes)) + '}\n' + r'''
for _,size in ipairs(sizes)do
 local path='qdata/size_'..size..'.DAT'
 local expected=assert(fs:readContents(path));reset()
 local actual=assert(reader.read(fs,path))
 assert(actual==expected and #actual==size)
 assert(opens==1 and closes==1 and seeks==2)
 if size==0 or size>4*1024*1024 then assert(#formats==1 and formats[1]=='*a')
 else assert(#formats==2 and formats[1]==size and formats[2]=='*a')end
end
reset();assert(fs:readContents('QData','Size-1.dat')=='x' and seeks==0)
local provider_calls=0
fs.provider={readContents=function(_,path)provider_calls=provider_calls+1;return 'provider',nil,17 end}
reset();local value,err,code=reader.read(fs,'ignored')
assert(value=='provider' and err==nil and code==17 and opens==0)
assert(app:readDataFile('QData','anything')=='provider' and opens==0 and provider_calls==2)
fs.provider=nil
IS_3DS=false;reset();assert(app:readDataFile('QData','Plain.dat')==string.rep('q',64))
assert(seeks==0 and #formats==1 and formats[1]=='*a')
IS_3DS=true
app.readBitmapDataFile=function(_,name)assert(name=='file');return 'bitmap-meta'end
app.readMapDataFile=function(_,name)assert(name=='file');return 'level-meta'end
reset();assert(app:readDataFile('Bitmap','file')=='bitmap-meta')
assert(app:readDataFile('Levels','file')=='level-meta' and opens==0)
local value,err=reader.read(fs,'QData/missing');assert(value==nil and err:find('Unable to find'))
local unready=setmetatable({},{__index=FileSystem});unready:FileSystem()
value,err=reader.read(unready,'QData/Plain.dat');assert(value==nil and err:find('not initialised'))
''')

    def test_read_seek_growth_truncation_errors_and_close_ownership(self):
        self.run_lua(r'''
local primary,secondary={},{}
local cases={
 {name='stable',size=3,parts={'abc',''},expected='abc'},
 {name='empty',size=0,parts={''},expected=''},
 {name='growth',size=3,parts={'abc','def'},expected='abcdef'},
 {name='short',size=5,parts={'ab',''},expected='ab'},
 {name='truncated-empty',size=3,parts={false,''},expected=''},
 {name='large-fallback',size=4194305,parts={'large'},expected='large'},
 {name='unknown-size',size=false,parts={'fallback'},expected='fallback'},
 {name='rewind-reopen',size=3,rewind=false,parts={'start'},expected='start',handles=2},
 {name='read-error',size=3,parts={false},read_error='read IO',expected_error='read IO'},
 {name='tail-error',size=3,parts={'abc',false},read_error='tail IO',expected_error='tail IO'},
 {name='read-throw',size=3,throw_read=true,throw_close=true,thrown=primary},
 {name='seek-throw',size=3,throw_seek=true,throw_close=true,thrown=primary},
 {name='close-throw',size=3,parts={'abc',''},throw_close=true,thrown=secondary},
 {name='close-return',size=3,parts={'abc',''},close_false=true,expected='abc'},
 {name='read-error-close-throw',size=3,parts={false},read_error='first IO',throw_close=true,expected_error='first IO'},
 {name='reopen-failure',size=3,rewind=false,fail_reopen=true,expected_error='reopen IO'},
 {name='open-failure',fail_open=true,expected_error='open IO'},
}
for _,case in ipairs(cases)do
 local opened,closed,reads=0,{},0
 io.open=function(path,mode)
  assert(path==root..'/QData/Plain.dat' and mode=='rb');opened=opened+1
  if case.fail_open then return nil,'open IO' end
  if opened==2 and case.fail_reopen then return nil,'reopen IO' end
  local ordinal=opened
  return {seek=function(_,kind,offset)
    if case.throw_seek then error(primary)end
    if kind=='end' then return case.size or nil,'seek IO' end
    assert(kind=='set' and offset==0)
    if case.rewind==false then return nil,'rewind IO' end
    return 0
   end,read=function(_,format)
    if case.throw_read then error(primary)end
    reads=reads+1
    if case.size==0 or case.size==false or case.size==4194305 or ordinal==2 then assert(format=='*a')
    elseif reads==1 then assert(format==case.size)else assert(format=='*a')end
    local data=case.parts[reads];if data==false then return nil,case.read_error,case.read_error and 5 end
    return data
   end,close=function()
    closed[ordinal]=(closed[ordinal] or 0)+1
    if case.throw_close then error(secondary)end
    if case.close_false then return nil,'close IO' end
    return true
   end}
 end
 local ok,value,err=pcall(reader.read,fs,'QData/Plain.dat')
 if case.thrown then assert(not ok and value==case.thrown,case.name)
 else assert(ok and value==case.expected and err==case.expected_error,case.name)end
 local handles=case.fail_open and 0 or case.fail_reopen and 1 or case.handles or 1
 for i=1,handles do assert(closed[i]==1,case.name..' close '..i)end
 assert(not closed[handles+1],case.name)
end
io.open=original_open
''')

    def test_actual_app_graphics_rnc_cache_failure_retry_and_reload(self):
        self.run_lua(r'''
reset();local raw=gfx:loadRaw('Raw',8,8)
assert(opens==1 and closes==1 and formats[1]==67 and native_loads==1)
assert(gfx:loadRaw('Raw',8,8)==raw and opens==1)
local plain=gfx:loadRaw('Plain',8,8);assert(opens==2)
local sheet=gfx:loadSpriteTable('QData','Sheet');assert(opens==4)
assert(gfx:loadSpriteTable('QData','Sheet')==sheet and opens==4)
gfx:updateTarget({});assert(opens==8 and closes==8)
local ok,err=pcall(gfx.loadRaw,gfx,'Bad',8,8)
assert(not ok and err:find('bad RNC') and gfx.cache.raw.Bad==nil)
assert(gfx.raw_source_bytes.Bad==nil)
local expected=opens
rnc.decompress=function()return string.rep('b',64)end
local retry=gfx:loadRaw('Bad',8,8);assert(retry and opens==expected+1)
assert(gfx:loadRaw('Bad',8,8)==retry and opens==expected+1)
''')

    def test_actual_load_file_resource_rebuild_failure_preserves_original_error(self):
        self.run_lua(r'''
local TH3DS=nil
local observePersistence=function()end
local MakePermanentObjectsTable=function()return {}end
local failure={}
local persist={load=function(data)
 assert(data=='saved-state')
 -- Native persistence decodes graphics load_info by calling these same methods.
 gfx:loadSpriteTable('QData','Sheet')
 error('publication must not receive failed resource')
end}
TheApp=app;TheApp.world={original=true};TheApp.map={original=true};TheApp.ui={original=true}
local previous_world,previous_map=TheApp.world,TheApp.map
local close_counts={}
io.open=function(path,mode)
 assert(mode=='rb')
 if path=='slot' or path=='slot.bak' then
  return {read=function(_,format)assert(format=='*a');return 'saved-state'end,
   close=function()close_counts[path]=(close_counts[path] or 0)+1;return true end}
 end
 return {seek=function(_,kind)if kind=='end'then return 3 end;return 0 end,
  read=function()error(failure)end,close=function()close_counts.resource=(close_counts.resource or 0)+1;return true end}
end
''' + self.load_outer + r'''
local ok,err=LoadGameFile('slot')
assert(ok==false and err==failure)
assert(TheApp.world==previous_world and TheApp.map==previous_map)
assert(close_counts.slot==1 and close_counts['slot.bak']==1 and close_counts.resource==2)
assert(gfx.cache.tabled.Sheet==nil)
-- The same resource failure after publication must return to a safe menu.
local nop=function()end
local map={registerTemperatureDisplayMethod=nop}
local state={random=1,map=map,world={gfx_set='full',savegame_version=254,map=map,
 resetAnimations=nop,updateUserActionsAllowed=nop,updateScreenBlueFilter=nop},
 ui={resync=nop,setCursor=nop,menu_bar={onChangeLanguage=nop},onChangeResolution=nop}}
persist.load=function()return state end
app.checkCompatibility=function()return true end
app.worldExited=nop;app.config={};app.audio={playSoundEffects=nop}
app.afterLoad=function()gfx:loadSpriteTable('QData','Sheet')end
local menus=0
app.loadMainMenu=function(self)menus=menus+1;self.world=nil;self.map=nil;self.ui={}end
ok,err=LoadGameFile('slot')
assert(ok==false and err==failure and menus==1)
assert(TheApp.world==nil and TheApp.map==nil and type(TheApp.ui)=='table')
assert(close_counts.slot==2 and close_counts['slot.bak']==1 and close_counts.resource==3)
''')
