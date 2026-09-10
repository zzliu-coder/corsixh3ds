"""Final generated strict UI entry paths, with explicit external services only."""
from pathlib import Path
import tempfile
import unittest

from support.pinned_upstream import generated_sources
from support.save_ui import install_ui_infrastructure
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]


class R74SaveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.directory=tempfile.TemporaryDirectory(prefix='cth-r74-save-ui-')
        cls.generated=generated_sources(Path(cls.directory.name))
        cls.root=install_ui_infrastructure(cls.generated)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def lua(self,body):
        script='local loadUi=dofile('+repr(str(ROOT/'tests/runtime_support/save_ui_loader.lua'))+')\n'
        script+='local root='+repr(str(self.root))+'\n'+body
        test_lua_runtime.LuaRuntimeTests().run_lua(script)

    def test_final_strict_six_entries_cancel_and_owner_error_contract(self):
        self.lua(r'''
for _,adapter in ipairs({'3ds','desktop','adapter-without-operations'})do
 local existing,saves,pending,notices=false,0,nil,0
 local current,mode
 local spec=loadUi(root,{attributes=function()if existing then return 10 end end,
   information=function(_,text)notices=notices+1;return {text=text}end})
 local app={savegame_dir='/private/'}
 if adapter~='desktop' then app._3ds={showError=function()error('invalid name')end}end
 if adapter=='3ds' then app._3ds.operations={}end
 app.save=function(_,path)
   saves=saves+1;assert(current.closed)
   if mode then
     if app._3ds and app._3ds.operations then
       app._3ds.operations.last={reported=mode=='reported',committed=mode=='committed'}
     end
     error(mode=='raw-table' and {} or 'save failed',0)
   end
   return true
 end
 local ui={app=app,addWindow=function(_,window)pending=window end}
 current=spec.create(ui)
 local function run(name,invoke)
   local window,panels=spec.create(ui);current=window;pending=nil;local before=saves
   invoke(window,panels)
   assert(saves==before+1 and window.closed,name)
 end
 run('new-name',function(w)w.new_savegame_textbox.text='New';w:confirmName()end)
 run('selected-file',function(w)w:choiceMade('/private/a.sav')end)
 if adapter~='desktop' then
   for slot=1,3 do run('slot-'..slot,function(_,p)p[slot+1].callback()end)end
 end
 existing=true
 current=spec.create(ui);local before=saves
 current:trySave('/private/old.sav');assert(pending and not current.closed)
 pending:cancel();assert(pending.closed and not current.closed and saves==before)
 run('overwrite-ok',function(w)w:trySave('/private/old.sav');pending:ok()end)
 existing=false
 if adapter=='3ds' then
   for _,failure in ipairs({'reported','unreported','committed','raw-table'})do
     mode=failure;local before_notices=notices
     run(failure,function(w)w:confirmName()end)
     assert(notices==before_notices+(failure=='reported' and 0 or 1))
     assert(app._3ds.operations.last.reported)
   end
   -- Stale owner.last.reported must never swallow an unrelated later exception.
   mode=nil;app.save=function()saves=saves+1;error('later request')end
   local before_notices=notices;run('stale-result',function(w)w:confirmName()end)
   assert(notices==before_notices+1)
 else
   mode='desktop-error';local before_notices=notices
   run('desktop-error',function(w)w:choiceMade('/private/a.sav')end)
   assert(notices==before_notices+1)
 end
 assert(rawget(spec.environment,'IS_3DS')==nil)
 print('PASS R74 final strict save entries adapter='..adapter..' success_entries='..
   (adapter=='desktop' and 3 or 6)..' cancel errors owner-local')
end
local saved,errors={},0
local app={savegame_dir='/private/',_3ds={operations={},save_prefix='R62-',
 showError=function()errors=errors+1 end},save=function(_,path)saved[#saved+1]=path;return true end}
local spec=loadUi(root);local ui={app=app}
local window=spec.create(ui);window:confirmName();assert(saved[1]=='/private/R62-Slot1.sav')
for slot=1,3 do
 local w,panels=spec.create(ui);panels[slot+1].callback()
 assert(saved[#saved]=='/private/R62-Slot'..slot..'.sav')
end
window=spec.create(ui);window.new_savegame_textbox:setText('Chosen_Name');window:confirmName()
assert(saved[#saved]=='/private/Chosen_Name.sav','explicit valid names keep the original contract')
for _,value in ipairs({'../escape','',string.rep('a',41)})do
 window=spec.create(ui);window.new_savegame_textbox:setText(value);window:confirmName()
 assert(not window.closed and #saved==5)
end
assert(errors==3)
print('PASS R74 recovery prefix default/slots, explicit filename, invalid names reject before save')
''')

    def test_same_real_module_harness_rejects_undeclared_platform_dependency(self):
        path=self.root/'dialogs/resizables/file_browsers/save_game.lua'
        original=path.read_text()
        self.assertEqual(original.count('local operations = app._3ds and app._3ds.operations'),1)
        try:
            path.write_text(original.replace('local operations = app._3ds and app._3ds.operations',
                'local operations = IS_3DS and app._3ds and app._3ds.operations'))
            self.lua(r'''
local spec=loadUi(root)
local called=0
local app={savegame_dir='/private/',_3ds={operations={}},save=function()called=called+1 end}
local w=spec.create({app=app})
local ok,err=pcall(w.confirmName,w)
assert(not ok and err:find("undeclared variable 'IS_3DS'",1,true) and called==0)
assert(w.closed and rawget(spec.environment,'IS_3DS')==nil)
print('PASS R74 negative oracle same final-module harness detects missing platform owner')
''')
        finally:
            path.write_text(original)


if __name__=='__main__':unittest.main()
