"""Real pinned annual/window/button/UI closure; graphics and world services are fixtures."""
import base64
import hashlib
import json
import tempfile
import zlib
from pathlib import Path
import unittest
import test_lua_runtime

ROOT=Path(__file__).resolve().parents[1]

class AnnualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_lua_runtime.LuaRuntimeTests.setUpClass()
        cls.temp=tempfile.TemporaryDirectory(prefix='cth-annual-')
        cls.upstream=Path(cls.temp.name)
        fixture=json.loads((ROOT/'tests/fixtures/annual_upstream.json').read_text())
        assert fixture['commit']=='56bd5d00f76331c7f76d7b696726a7926303ca0c'
        sources=json.loads(zlib.decompress(base64.b64decode(fixture['sources_zlib_base64'])))
        for name,text in sources.items():
            assert hashlib.sha256(text.encode()).hexdigest()==fixture['sha256'][name]
            path=cls.upstream/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_real_annual_confirmation_and_refusal_closure(self):
        prefix='local source='+repr(str(self.upstream))+'\nlocal product='+repr(str(ROOT))+'\n'
        script=r'''
package.path=product..'/lua/?.lua;'..package.path
package.loaded['3ds.state_health']={}
-- Load before optional classes exist: no strict-global read is permitted.
local S=dofile(product..'/lua/3ds/benchmark_stress.lua')
do
 local e={};for k,v in pairs(_G)do e[k]=v end;e._G=e
 assert(loadfile(product..'/tests/fixtures/strict.lua.pinned','t',e))()
 local early=assert(loadfile(product..'/lua/3ds/benchmark_stress.lua','t',e))()
 local a={savegame_dir='private/',config={autosave_frequency=0}}
 local s=early.new(a,{clock_ms=function()return 0 end},1000,'private/')
 assert(s.annual_class==nil and s.button_class==nil)
end
strict_declare_global=function()end;destrict=function(f)return f end
permanent=function(_,v)if v~=nil then return v end;return function(x)return x end end
corsixth={require=function()end}
package.preload.TH=function()return {cursor={setPosition=function()end}}end
package.preload.sdl=function()return {wm={}}end
package.preload.lfs=function()return {}end
dofile(source..'/class.lua');dofile(source..'/window.lua')
dofile(source..'/ui.lua');dofile(source..'/dialogs/fullscreen.lua')
dofile(source..'/dialogs/fullscreen/annual_report.lua')
dofile(source..'/dialogs/confirm_dialog.lua');dofile(source..'/dialogs/watch.lua')
shallow_clone=function(t)local c={};for k,v in pairs(t)do c[k]=v end;return c end
list_to_set=function(t)local s={};for _,v in ipairs(t)do s[v]=true end;return s end
Date={hoursPerDay=function()return 24 end}
local now=0
local native={clock_ms=function()return now end,set_notice=function()end}
_S={transactions={eoy_trophy_bonus='trophy',eoy_bonus_penalty='award'},
 tooltip={window_general={cancel='cancel',confirm='confirm'},
 watch={hospital_opening='open',emergency='emergency',epidemic='epidemic'}}}
local function setup()
 local h={balance=100,loan=0,num_visitors=0,num_deaths=0,num_cured=0,value=100,
   player_salary=0,num_cured_ty=0,rep=10,calls=0}
 function h:receiveMoney(n)self.balance=self.balance+n;self.calls=self.calls+1 end
 function h:changeReputation(kind,_,n)assert(kind=='year_end');self.rep=self.rep+n end
 local gfx=setmetatable({},{__index=function()return function()return {sizeOf=function()return 10,11 end}end end})
 local app={savegame_dir='private/',config={autosave_frequency=0,width=640,height=480,ui_scale=1},
   runtime_config={},hotkeys={global_confirm='enter',global_confirm_alt='space'},
   gfx=gfx,video={setBlueFilterActive=function()end}}
 local ui=setmetatable({},UI._metatable);ui:Window();ui.app=app;ui.hospital=h
 ui.modal_windows={};ui.windows={Window()};ui.sound_count=0
 function ui:playSound()self.sound_count=self.sound_count+1 end
 local w={hospitals={h},map={},pause_count=0,won_checks=0}
 function w:getLocalPlayerHospital()return h end
 function w:mustPauseWindowAdd()self.pause_count=self.pause_count+1 end
 function w:mustPauseWindowRemoved()self.pause_count=self.pause_count-1 end
 function w:checkIfGameWon()self.won_checks=self.won_checks+1 end
 app.ui=ui;app.world=w;w.ui=ui;TheApp=app
 return app,S.new(app,native,100000,'private/'),h,ui,w
end
local function annual(app,a,b,r,page)
 local win=UIAnnualReport(app.ui,app.world)
 win.won_amount=a or 0;win.award_won_amount=b or 0;win.rep_amount=r or 0
 if page then win:changePage(page)end
 app.ui:addWindow(win);return win
end
local function refused(s)
 local ok,err=pcall(s.checkMandatory,s);assert(not ok,tostring(err))
end
for _,amount in ipairs{20,-30,0}do
 for _,page in ipairs{2,3}do
  local app,s,h,ui,w=setup();local win=annual(app,amount,amount,2.8,page)
  s:checkMandatory()
  assert(win.closed and h.balance==100+amount*2 and h.rep==12)
  assert(h.calls==(amount==0 and 0 or 2) and w.won_checks==1 and w.pause_count==0)
  assert(ui.sound_count==1 and s.annual_count==1)
  s:checkMandatory();assert(h.balance==100+amount*2)
  local second=annual(app,1,0,0);s:checkMandatory();assert(second.closed and s.annual_count==2)
 end
end
-- Execute the exact year-end call block and complete World:onEndYear body.
-- World services remain fixtures; a full simulated calendar is device evidence.
do
 local f=assert(io.open(source..'/world.lua'));local text=f:read('*a');f:close()
 local body=assert(text:match('(function World:onEndYear%(%)\n.-\nend)'))
 World={};assert(load(body))()
 local block=assert(text:match('(self.ui:addWindow%(UIAnnualReport%(self.ui, self%)%)%s+self:onEndYear%(%))'))
 local app,s,h,ui,w=setup();w.onEndYear=World.onEndYear
 w.endconditions={checkEndGame=function()return nil,nil end}
 local reset=0
 function h:onEndYear()
  local report=ui:getWindow(UIAnnualReport);assert(report and report.cures_sort[1].value==17)
  reset=reset+1;self.num_cured_ty=0
 end
 h.num_cured=17;h.num_cured_ty=17
 assert(load('return function(self) '..block..' end'))()(w)
 assert(reset==1 and h.num_cured_ty==0);s:checkMandatory();assert(s.annual_count==1)
end
-- Successful annual confirmation precedes both round-8 and final save branches.
for _,final in ipairs{false,true}do
 local app,s,h=setup();local win=annual(app,7,0,0)
 s.phase='close';s.cycle=8;s.finish_at=final and -1 or 100000
 local closes,saves=0,0
 s.window={close=function(self)assert(win.closed);self.closed=true;closes=closes+1 end}
 s.saveReload=function()assert(win.closed and h.balance==107);saves=saves+1 end
 assert(s:tick()==final and closes==1 and saves==(final and 2 or 1))
end
local cases={
 function(a,s,w)w.second_close=nil end,
 function(a,s,w)w.second_close.enabled=false end,
 function(a,s,w)w.second_close.visible=false end,
 function(a,s,w)w.second_close.on_click=function()error('must not call')end end,
 function(a,s,w)w.second_close.on_click_self={}end,
 function(a,s,w)w.second_close.is_toggle=true end,
 function(a,s,w)w.second_close.is_repeat=true end,
 function(a,s,w)w.second_close.panel_for_sprite.window={}end,
 function(a,s,w)w.buttons[#w.buttons+1]=w.second_close end,
 function(a,s,w)w.parent={}end,
 function(a,s,w)w.closed=true end,
 function(a,s,w)w.close=function()error('must not call')end end,
 function(a,s,w)setmetatable(w,{__index=UIAnnualReport})end,
 function(a,s,w)a.ui.windows[#a.ui.windows+1]=w end,
 function(a,s,w)TheApp={}end,
 function(a,s,w)a.savegame_dir='USER/'end,
 function(a,s,w)s.annual_attempts[w]=true end,
 function(a,s,w)s.annual_count=32 end,
}
for _,mutate in ipairs(cases)do
 local app,s,h=setup();local win=annual(app,12,0,0);mutate(app,s,win)
 refused(s);assert(h.balance==100 and s.annual_count~=1)
end
-- Unknown or combined mandatory windows block before close/save/final work.
for _,phase in ipairs{'open','close'}do
 for _,cycle in ipairs{7,8}do
  local app,s,h,ui=setup();annual(app,4,0,0)
  ui.windows[#ui.windows+1]={mustPause=function()return true end}
  s.phase=phase;s.cycle=cycle;s.finish_at=-1
  s.close=function()error('should not close')end
  s.saveReload=function()error('should not save')end
  local ok,err=pcall(s.tick,s);assert(not ok and tostring(err):find('TH3DS_NEEDS_INPUT',1,true))
  assert(h.balance==100)
 end
end
-- Real non-pausing confirmation is still a player choice; unknown modals stop.
for _,with_annual in ipairs{false,true}do
 for _,kind in ipairs{'confirm','unknown'}do
  local app,s,h,ui=setup();local win
  if with_annual then win=annual(app,7,0,0)end
  local callbacks=0
  local dialog=kind=='confirm' and UIConfirmDialog(ui,false,'choice',
    function()callbacks=callbacks+1 end,function()callbacks=callbacks+1 end) or Window()
  if kind=='unknown' then dialog.ui=ui;dialog.modal_class='unknown_decision' end
  ui:addWindow(dialog);assert(not dialog:mustPause())
  refused(s);assert(callbacks==0 and not dialog.closed and h.balance==100 and s.annual_count==0)
  if win then assert(not win.closed)end
 end
end
-- Passive original countdown and nonmodal message overlays do not stop stress.
for _,kind in ipairs{'initial_opening','emergency','epidemic'}do
 local app,s,h,ui=setup();local watch=UIWatch(ui,kind);ui:addWindow(watch)
 local message=Window();message.ui=ui;message.on_top=true;ui:addWindow(message)
 s:checkMandatory();assert(not watch.closed and not message.closed)
 annual(app,1,0,0);s:checkMandatory();assert(s.annual_count==1 and not watch.closed)
end
-- Only our registered readonly fullscreen is exempt; an unowned one stops.
do
 local app,s,h,ui=setup();local window=UIFullscreen(ui);ui:addWindow(window)
 refused(s);s.window=window;s.window_class=UIFullscreen;s:checkMandatory()
 ui.modal_windows.fullscreen=nil;refused(s)
end
-- Any error after marking an attempt is sticky; no later settlement/save/cleanup.
for _,where in ipairs{'before','money','remove','win','replace'}do
 local app,s,h,ui,w=setup();local win=annual(app,9,1,0)
 if where=='before' then ui.playSound=function()error('before')end
 elseif where=='money' then h.receiveMoney=function(self,n)self.balance=self.balance+n;error('money')end
 elseif where=='remove' then ui._onRemoveWindow=function()error('remove')end
 elseif where=='win' then w.checkIfGameWon=function()error('win')end
 else w.checkIfGameWon=function()app.world={}end end
 refused(s);local balance=h.balance;refused(s)
 assert(not pcall(s.saveReload,s) and not pcall(s.close,s) and h.balance==balance)
end
-- A victory fax created by the real annual close remains unanswered.
local app,s,h,ui,w=setup();annual(app,9,0,0)
w.checkIfGameWon=function()ui.windows={{mustPause=function()return true end}}end
refused(s);assert(h.balance==109 and s.annual_count==1 and not s.annual_failed)
app,s,h,ui,w=setup();annual(app,9,0,0)
local followup,chosen
w.checkIfGameWon=function()
 followup=UIConfirmDialog(ui,false,'new choice',function()chosen=true end,function()chosen=true end)
 ui:addWindow(followup)
end
refused(s);assert(h.balance==109 and s.annual_count==1 and not chosen and not followup.closed)
-- Fresh world/UI after normal reload is checked at the current identity.
local app,s=setup();local nextapp=setup();app.ui=nextapp.ui;app.world=nextapp.world
app.ui.app=app;TheApp=app;annual(app,1,0,0);s:checkMandatory();assert(s.annual_count==1)
print('PASS actual annual constructor/award/close/Button/Window/UI; bounded refusal and sticky failure')
'''
        test_lua_runtime.LuaRuntimeTests().run_lua(prefix+script)

if __name__=='__main__':unittest.main()
