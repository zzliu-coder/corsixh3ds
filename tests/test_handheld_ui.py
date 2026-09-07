"""Real save-dialog methods and adapter with controlled UI/applet services."""
from pathlib import Path
import sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from handheld_ui import transform
import test_lua_runtime

class HandheldUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
    def run_lua(self, body):
        # Obtain the actual class closed over by attach, without adding a
        # production-only testing API or replacing its methods.
        setup = """
local Platform
for i=1,30 do
 local name,value=debug.getupvalue(module.attach,i)
 if name=='Platform' then Platform=value;break end
end
assert(Platform)
"""
        if body.startswith("local Platform=dofile("):
            first,rest=body.split('\n',1)
            body=first.replace('local Platform=', 'local module=')+'\n'+setup+rest
        test_lua_runtime.LuaRuntimeTests().run_lua(body)

    def test_keyboard_cancel_validation_and_replaced_owner(self):
        self.run_lua("local Platform=dofile("+repr(str(ROOT/'lua/3ds/platform.lua'))+")\n"+r'''
local confirmations, notices=0,0
local box={text='Previous',active=true,visible=true,enabled=true,char_limit=12,
 setText=function(self,t)self.text=t end,setActive=function(self,a)self.active=a end,
 confirm=function(self)self.active=false;confirmations=confirmations+1 end}
local ui={textboxes={box}}
local p=setmetatable({app={ui=ui},native={set_notice=function()notices=notices+1 end}},Platform)
p.native.text_keyboard=function(initial,limit) assert(initial=='Previous' and limit==12);return false end
assert(p:editText());assert(box.text=='Previous' and box.active and confirmations==0)
p.native.text_keyboard=function()return true,'New Slot' end
assert(p:editText());assert(box.text=='New Slot' and confirmations==1 and not box.active)
box.active=true
for _,invalid in ipairs({'../other','bad/name',string.rep('a',13),'','  ','中文'})do
 p.native.text_keyboard=function()return true,invalid end
 assert(p:editText());assert(box.text=='New Slot' and confirmations==1)
end
p.native.text_keyboard=function()p.app.ui={textboxes={}};return true,'wrong owner' end
assert(p:editText());assert(box.text=='New Slot' and confirmations==1)
assert(notices==6)
''')

    def test_actual_upstream_slots_overwrite_and_save_path(self):
        original=(ROOT/'tests/fixtures/save_game.lua.pinned').read_text()
        transformed=transform(original);self.assertEqual(transform(transformed),transformed)
        with tempfile.TemporaryDirectory() as temp:
            script=Path(temp)/'save.lua';script.write_text(transformed)
            self.run_lua(r'''
function class(name) _G[name]={};return function()end end
_S={save_game_window={caption='%s',save_button='Save',new_save_game='Name',missing_filename='Missing'},
 tooltip={save_game_window={new_save_game='Name'}},confirmation={overwrite_save='Overwrite?'},errors={save_prefix='Save: '}}
function FilteredFileTreeNode(path)return {path=path}end
local saved,existing,confirm,error_count,panels={},false,nil,0,{}
lfs={attributes=function()if existing then return 10 end end}
function UIConfirmDialog(ui,modal,title,callback) return {callback=callback}end
function UIInformation(ui,text)return {text=text}end
'''+'dofile('+repr(str(script))+')\n'+r'''
local app={savegame_dir='/Saves/',_3ds={showError=function()error_count=error_count+1 end}}
local ui={app=app,addWindow=function(self,window)confirm=window.callback end}
local w=setmetatable({ui=ui}, {__index=UISaveGame})
function w:UIFileBrowser(_,_,_,height)assert(height==235);self.width=450;self.col_bg={};self.control={sortByDate=function()end}end
function w:addBevelPanel(x,y,width,height)
 local p={x=x,y=y,width=width,height=height}
 function p:setLabel(text)self.label=text;return self end
 function p:setTooltip()return self end
 function p:makeButton(_,_,_,_,_,callback)self.callback=callback;return self end
 function p:makeTextbox()return {text='',panel=self,setText=function(self,text)self.text=text end}end
 panels[#panels+1]=p;return p
end
function w:close()self.closed=true end
function app:save(path)assert(w.closed);saved[#saved+1]=path;return true end
w:UISaveGame(ui);assert(w.new_savegame_textbox.text=='Slot1')
assert(#panels==4)
for i=2,4 do assert(panels[i].y==276 and panels[i].height==26 and panels[i].x+panels[i].width<=450)end
for i=2,4 do w.closed=false;panels[i].callback();assert(saved[#saved]=='/Saves/Slot'..(i-1)..'.sav')end
existing=true;w.closed=false;panels[2].callback();assert(#saved==3 and not w.closed and type(confirm)=='function')
confirm=nil -- cancel overwrite leaves file and window unchanged
assert(#saved==3 and not w.closed)
panels[2].callback();confirm();assert(#saved==4 and w.closed)
w.new_savegame_textbox.text='../invalid';w:confirmName();assert(error_count==1 and #saved==4)
''')

    def test_suspend_restore_uses_real_speed_names_and_world_owner(self):
        self.run_lua("local Platform=dofile("+repr(str(ROOT/'lua/3ds/platform.lua'))+")\n"+r'''
local speed='Normal';local calls=0
local world={getCurrentSpeed=function()return speed end,setSpeed=function(self,v)
 assert(v=='Pause' or v=='Normal');speed=v;calls=calls+1 end}
local p=setmetatable({app={world=world,ui={}},native={request_redraw=function()end}},Platform)
p.inputContext=function()return 'world' end
assert(p:handleAction{type='lifecycle_suspend'});assert(speed=='Pause' and calls==1)
assert(p:handleAction{type='lifecycle_suspend'});assert(calls==1)
assert(p:handleAction{type='lifecycle_resume'});assert(speed=='Normal' and calls==2)
assert(p:handleAction{type='lifecycle_suspend'});p.app.world={setSpeed=function()error('wrong world')end}
assert(p:handleAction{type='lifecycle_resume'});assert(p.saved_speed==nil)
''')
