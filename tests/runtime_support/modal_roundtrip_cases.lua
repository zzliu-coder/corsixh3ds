-- Loaded after the test supplies source paths. P is the actual native module.
package.path=product..'/lua/?.lua;'..package.path
package.loaded.persist=P
package.preload.TH=function()return {cursor=setmetatable({setPosition=function()end}, {__call=function()return assert(true)end})}end
package.preload.sdl=function()return {wm={}}end
package.preload.lfs=function()return {}end
P.dofile(strict)
for _,name in ipairs{'corsixth','TheApp','shallow_clone','list_to_set','Date','_S',
  'pause_gc_and_use_weak_keys'}do strict_declare_global(name)end
corsixth={require=function()end}
local S=require('3ds.benchmark_stress')
local early=S.new({savegame_dir='private/',config={autosave_frequency=0}},
  {clock_ms=function()return 0 end},1,'private/')
assert(early.annual_class==nil and early.button_class==nil and early.watch_class==nil)
assert(not pcall(function()return undeclared_modal_probe end))
P.dofile(source['class.lua'])
local make_permanent=P.dofile(registry)
for _,name in ipairs{'window.lua','ui.lua','dialogs/fullscreen.lua',
  'dialogs/fullscreen/annual_report.lua','dialogs/confirm_dialog.lua','dialogs/watch.lua',
  'dialogs/machine_dialog.lua'}do P.dofile(source[name])end
assert(not pcall(function()return undeclared_modal_probe end))
print('PASS strict initialization before and after optional classes')
shallow_clone=function(t)local c={};for k,v in pairs(t)do c[k]=v end;return c end
list_to_set=function(t)local s={};for _,v in ipairs(t)do s[v]=true end;return s end
-- The graphics fixture has no collectable native handles.
pause_gc_and_use_weak_keys=function(callback,t)callback(t)end
Date={hoursPerDay=function()return 24 end}
_S={transactions={eoy_trophy_bonus='trophy',eoy_bonus_penalty='award'},
 tooltip={window_general={cancel='cancel',confirm='confirm'},
 watch={hospital_opening='open',emergency='emergency',epidemic='epidemic'},
 machine_window={repair='repair',replace='replace',close='close',name='name',times_used='used',status='status'}}}
class 'ModalFixtureHospital'
function ModalFixtureHospital:receiveMoney(n)self.balance=self.balance+n;self.calls=self.calls+1 end
function ModalFixtureHospital:changeReputation(kind,_,n)assert(kind=='year_end');self.rep=self.rep+n end
class 'ModalFixtureWorld'
function ModalFixtureWorld:getLocalPlayerHospital()return self.hospitals[1]end
function ModalFixtureWorld:mustPauseWindowAdd()self.pause_count=self.pause_count+1 end
function ModalFixtureWorld:mustPauseWindowRemoved()self.pause_count=self.pause_count-1 end
function ModalFixtureWorld:checkIfGameWon()self.won_checks=self.won_checks+1 end
-- Subclasses intentionally satisfy class.is; the exact guard must reject them.
class 'DerivedModalWatch' (UIWatch)
class 'DerivedModalAnnual' (UIAnnualReport)
class 'DerivedModalButton' (Button)
class 'DerivedModalMachine' (UIMachine)
local resource=permanent('modal.fixture.resource',{sizeOf=function()return 10,11 end})
local gfx=setmetatable({load_info={}}, {__index=function()return function()return resource end end})
local function setup()
 local h=setmetatable({balance=100,loan=0,num_visitors=0,num_deaths=0,num_cured=0,value=100,
  player_salary=0,num_cured_ty=0,rep=10,calls=0},ModalFixtureHospital._metatable)
 local app={savegame_dir='private/',config={autosave_frequency=0,width=640,height=480,ui_scale=1,
  play_sounds=true},runtime_config={},hotkeys={},gfx=gfx,modes={},strings={},fs={},moviePlayer={},
  walls={},objects={},rooms={},humanoid_actions={},diseases={},audio={calls=0},video={setBlueFilterActive=function()end}}
 function app.audio:playSound()self.calls=self.calls+1 end
 function app:loadLuaFolder()end -- Source files were loaded above, graphics/services are fixtures.
 local keys={'cancel','cancel_alt','stop_movie','stop_movie_alt','pause_movie','screenshot',
  'fullscreen_toggle','exitApp','resetApp','releaseMouse','confirm','confirm_alt','showLuaConsole','runDebugScript'}
 for i,key in ipairs(keys)do app.hotkeys['global_'..key]='key'..i end
 local w=setmetatable({hospitals={h},map={},pause_count=0,won_checks=0},ModalFixtureWorld._metatable)
 app.world=w;TheApp=app
 local ui=UI(app,true);app.ui=ui;w.ui=ui;ui.hospital=h
 -- Retain the same menu-bar permanent on load, as normal persistence does.
 ui.menu_bar={};ui:addWindow(Window())
 return app,S.new(app,{clock_ms=function()return 0 end},100000,'private/')
end
local function add_annual(app,page)
 local win=UIAnnualReport(app.ui,app.world)
 win.won_amount=9;win.award_won_amount=2;win.rep_amount=2.8
 win:changePage(page or 2);app.ui:addWindow(win);return win
end
local function roundtrip(app)
 local original_ui=app.ui
 local forward=make_permanent(false)
 assert(forward[UIWatch] and forward[UIAnnualReport] and forward[Button])
 assert(forward[UIWatch._metatable]==nil and forward[UIAnnualReport._metatable]==nil)
 -- Window explicitly registers the Button mt; this exception is part of the
 -- real persistence lifecycle and must not be lost in a class-only registry.
 assert(forward[Button._metatable]=='Window.<button_mt>')
 local bytes=assert(P.dump({ui=app.ui,world=app.world},forward))
 local restored=assert(P.load(bytes,make_permanent(true)))
 app.ui=restored.ui;app.world=restored.world;TheApp=app
 assert(app.ui~=original_ui and app.ui.app==app and app.world.ui==app.ui)
 -- Current schema has no migration. Real UI recursively restores child windows,
 -- panels and hotkeys before the production guard sees the reconstructed graph.
 app.ui:afterLoad(237,237)
 return original_ui
end
local function restored(win,cls)
 assert(getmetatable(win)~=cls._metatable and rawget(getmetatable(win),'__index')==cls)
end
local function refused(s,reason)
 local before=s.app.world.hospitals[1].balance
 local successes=s.annual_count
 local count=0;local original_print=print
 print=function(line)
  assert(type(line)=='string' and #line<=230 and line:find('event=NEEDS_INPUT',1,true))
  if reason then assert(line:find('reason='..reason,1,true))end
  assert(line:find('class=',1,true) and line:find('registered=',1,true))
  count=count+1
 end
 for i=1,2 do
  local ok,err=pcall(s.checkMandatory,s)
  assert(not ok and type(err)=='string' and err:match('TH3DS_NEEDS_INPUT$'),tostring(err))
 end
 print=original_print
 assert(count==1 and s.annual_count==successes and s.app.world.hospitals[1].balance==before)
end
for _,kind in ipairs{'initial_opening','emergency','epidemic'}do
 local app,s=setup();app.ui:addWindow(UIWatch(app.ui,kind));s:checkMandatory()
 roundtrip(app)
 local watch=assert(app.ui:getWindow(UIWatch));restored(watch,UIWatch)
 assert(watch.ui==app.ui and watch.parent==app.ui and app.ui.modal_windows.open_countdown==watch)
 s:checkMandatory();assert(not watch.closed)
end
print('PASS native restored countdowns: all three real constructors and UI afterLoad')
do
 local app,s=setup()
 local machine={times_used=3,strength=10,total_usage=3,object_type={name='inflator'}}
 local room={needs_repair=false}
 app.world.machine=machine;app.world.room=room
 app.ui:addWindow(UIMachine(app.ui,machine,room));s:checkMandatory()
 roundtrip(app)
 local win=assert(app.ui:getWindow(UIMachine));restored(win,UIMachine)
 local balance=app.ui.hospital.balance
 s:checkMandatory()
 assert(not win.closed and win.machine==app.world.machine and win.room==app.world.room)
 assert(win.machine.times_used==3 and app.ui.hospital.balance==balance)
 -- Keeping an information panel never acknowledges its separate purchase
 -- confirmation, and no mutation or paused/derived impostor is adopted.
 local choice=UIConfirmDialog(app.ui,true,'purchase',function()error('must not purchase')end)
 app.ui:addWindow(choice)
 local records={}
 s.native.diagnostic_line=function(line)assert(#line<=230);records[#records+1]=line end
 for i=1,2 do
  local ok,err=pcall(s.checkMandatory,s)
  assert(not ok and err:match('TH3DS_NEEDS_INPUT$'))
 end
 assert(#records==1 and records[1]:find('class=UIConfirmDialog',1,true))
 assert(not choice.closed and app.ui.hospital.balance==balance)
end
for _,mutate in ipairs{
 function(a,w)w.parent={}end,
 function(a,w)w.ui={}end,
 function(a,w)a.ui.modal_windows.humanoid_info={}end,
 function(a,w)w.mustPause=function()return true end end,
 function(a,w)setmetatable(w,DerivedModalMachine._metatable)end,
}do
 local app,s=setup();app.ui:addWindow(UIMachine(app.ui,{},{}));roundtrip(app)
 mutate(app,assert(app.ui:getWindow(UIMachine)));refused(s)
end
print('PASS restored machine information and native diagnostics')
for _,page in ipairs{2,3}do
 local app,s=setup();app.ui:addWindow(UIWatch(app.ui,'emergency'));add_annual(app,page)
 roundtrip(app)
 local win=assert(app.ui:getWindow(UIAnnualReport));local button=win.second_close
 restored(win,UIAnnualReport)
 assert(getmetatable(button)==Button._metatable and rawget(getmetatable(button),'__index')==Button)
 assert(button.on_click==UIAnnualReport.close and button.on_click_self==win)
 assert(button.panel_for_sprite.window==win and button.ui==app.ui)
 s:checkMandatory()
 local h=app.world.hospitals[1]
 assert(h.balance==111 and h.calls==2 and h.rep==12 and app.world.won_checks==1)
 assert(win.closed and app.world.pause_count==0 and app.audio.calls==1 and s.annual_count==1)
 assert(app.ui.modal_windows.fullscreen==nil and app.ui:getWindow(UIAnnualReport)==nil)
 s:checkMandatory();assert(h.balance==111 and h.calls==2)
 -- Save the successfully completed state and check again with a fresh guard.
 roundtrip(app);local fresh=S.new(app,{clock_ms=function()return 0 end},1,'private/')
 fresh:checkMandatory();assert(app.world.hospitals[1].balance==111 and fresh.annual_count==0)
end
print('PASS native annual and Button confirmation: pages 2/3, callbacks, once-only and completed-state reload')
local watch_cases={
 function(a,w,old)w.parent=old end,
 function(a,w,old)w.ui=old end,
 function(a,w)a.ui.modal_windows.open_countdown=nil end,
 function(a,w)a.ui.modal_windows.open_countdown={}end,
 function(a,w)w.closed=true end,
 function(a,w)w.modal_class='unknown' end,
 function(a,w)setmetatable(w,DerivedModalWatch._metatable);assert(class.is(w,UIWatch))end,
 function(a,w)setmetatable(w,{__index=setmetatable({},{__index=UIWatch})})end,
}
for _,mutate in ipairs(watch_cases)do
 local app,s=setup();app.ui:addWindow(UIWatch(app.ui,'emergency'));local old=roundtrip(app)
 mutate(app,assert(app.ui:getWindow(UIWatch)),old);refused(s,'modal_contract')
end
local annual_cases={
 function(a,s,w,old)w.parent=old end,
 function(a,s,w,old)w.ui=old end,
 function(a,s,w)a.ui.modal_windows.fullscreen=nil end,
 function(a,s,w)a.ui.modal_windows.fullscreen={}end,
 function(a,s,w)setmetatable(w,DerivedModalAnnual._metatable);assert(class.is(w,UIAnnualReport))end,
 function(a,s,w)setmetatable(w.second_close,DerivedModalButton._metatable);assert(class.is(w.second_close,Button))end,
 function(a,s,w)w.second_close.on_click=function()error('must not call')end end,
 function(a,s,w)w.second_close.on_click_self={}end,
 function(a,s,w)w.second_close.handleClick=function()error('must not call')end end,
 function(a,s,w)w.close=function()error('must not call')end end,
 function(a,s,w)w.updateAwards=function()error('must not call')end end,
 function(a,s,w)w.second_close.ui={}end,
 function(a,s,w)w.second_close.panel_for_sprite.window={}end,
 function(a,s,w)w.buttons[#w.buttons+1]=w.second_close end,
 function(a,s,w)w.panels={}end,
 function(a,s,w)s.annual_attempts[w]=true end,
 function(a,s,w)s.annual_count=32 end,
}
for _,mutate in ipairs(annual_cases)do
 local app,s=setup();add_annual(app);local old=roundtrip(app)
 mutate(app,s,assert(app.ui:getWindow(UIAnnualReport)),old)
 refused(s)
end
-- An actual unknown confirmation and a mustPause window still require input.
for _,mandatory in ipairs{false,true}do
 local app,s=setup();app.ui:addWindow(UIWatch(app.ui,'emergency'));roundtrip(app)
 if mandatory then
  local watch=app.ui:getWindow(UIWatch);watch.mustPause=function()return true end
 else app.ui:addWindow(UIConfirmDialog(app.ui,false,'choice',function()error('must not choose')end))end
 refused(s)
end
print('PASS native refusal boundaries: owner, registry, exact class, callbacks, attachments, once-only, unknown and mustPause')
do
 local app,s=setup();local win=UIFullscreen(app.ui);app.ui:addWindow(win)
 s.window=win;s.window_class=UIFullscreen;s:checkMandatory()
 roundtrip(app)
 -- A restored copy is not the stress instance we opened; never adopt it.
 refused(s,'modal_contract')
 local current=app.ui:getWindow(UIFullscreen)
 -- A currently held object with a reconstructed instance mt retains exact type.
 local app2,s2=setup();local held=UIFullscreen(app2.ui);app2.ui:addWindow(held)
 s2.window=held;s2.window_class=UIFullscreen;setmetatable(held,getmetatable(current))
 s2:checkMandatory();assert(s2.window==held and not held.closed)
end
print('PASS current owned window identity: held instance accepted, old reload copy refused')
print('scope=native dump/load + actual strict/class/UI constructors/afterLoad/guard/confirmation; graphics/audio/world services are fixtures; full hospital and device NOT_PROVEN')
