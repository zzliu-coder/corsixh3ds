-- Actual fixed class/UI/Window/four draw functions. Service objects below are
-- deterministic fixtures; native bitmap ownership and GPU pixels are separate.
package.path=product..'/lua/?.lua;'..package.path
strict_declare_global=function()end;destrict=function(f)return f end
permanent=function(_,v)if v~=nil then return v end;return function(x)return x end end
corsixth={require=function()end}
local trace={};local function event(s)trace[#trace+1]=s end
local resources=setmetatable({},{__mode='k'})
local draw_errors=setmetatable({},{__mode='k'})
local original_file_mt=getmetatable(io.tmpfile())
local methods={}
function methods.draw(self,canvas,x,y)event('bitmap:'..x..':'..y);assert(resources[self]~=nil);if draw_errors[self]then error(draw_errors[self],0)end end
function methods.opaqueCanvas(self,canvas)return resources[self] and canvas.valid end
local bm_mt={__index=methods,__gc=original_file_mt.__gc}
local function bitmap()
 local b=assert(io.tmpfile());debug.setmetatable(b,bm_mt);resources[b]=true;return b
end
package.preload.TH=function()return {bitmap=bitmap,cursor={setPosition=function()end}}end
package.preload.sdl=function()return {wm={}}end
package.preload.lfs=function()return {}end
shallow_clone=function(t)local r={};for k,v in pairs(t)do r[k]=v end;return r end
list_to_set=function(t)local r={};for _,v in ipairs(t)do r[v]=true end;return r end
local files={'class.lua','window.lua','ui.lua','dialogs/fullscreen.lua','map.lua',
 'game_ui.lua','dialogs/bottom_panel.lua','dialogs/adviser.lua','dialogs/menu.lua',
 'dialogs/subtitles.lua','dialogs/fullscreen/hospital_policy.lua',
 'dialogs/fullscreen/progress_report.lua','dialogs/fullscreen/research_policy.lua',
 'dialogs/fullscreen/staff_management.lua'}
for _,f in ipairs(files)do dofile(generated..'/CorsixTH/Lua/'..f)end
local gate=require('3ds.floor_occlusion')
local font={draw=function()event('font')end,drawWrapped=function()event('wrapped')end}
local sprites={draw=function()event('sprite')end,sizeOf=function()return 16,16 end}
_S={policy={sliders={send_home='send',guess='guess',stop='stop',staff_room='staff'}},
 research={categories={}},misc={done='done'},staff_list={},progress_report={header='Report',win_criteria='Win',percentage_pop='Pop'},tooltip={toolbar={}},date_format={daymonth='%d/%d'}}
UIPatient={normaliseWarmth=function(x)return x end}
DrawFlags={Nearest=1}
local canvas={valid=true,scale=function(_,n,kind)event('scale:'..n..':'..tostring(kind));return true end,
 fillBlack=function()event('black')end,mapRGB=function()return 1 end,drawRect=function()event('rect')end,nonOverlapping=function(_,v)event('overlap:'..tostring(v))end}
local function base(c,ui)
 local w=setmetatable({},c._metatable);w:Window();w.ui=ui;return w
end
local function setup(c)
 local h={name='Hospital',population=.5,show_progress_screen_warnings=1,getAveragePatientAttribute=function(_,k)return k=='warmth' and .2 or .5 end}
 local app={config={width=640,height=480,ui_scale=1},runtime_config={},hotkeys=setmetatable({},{__index=function()return 'a'end}),gfx={loadSpriteTable=function()return sprites end,loadFontAndSpriteTable=function()return font end}}
 local ui=base(GameUI);ui.app=app;ui.hospital=h;app.ui=ui;ui.width=640;ui.height=480
 ui.zoom_factor=1;ui.in_visible_diamond=true;ui.shake_screen_intensity=0
 ui.screen_offset_x=0;ui.screen_offset_y=0;ui.drawTooltip=function()event('tooltip')end
 app.world={hospitals={h},date=function()return {year=function()return 1 end} end,endconditions={getAttribute=function()return 4 end},map={level_config={payroll={MaxSalary=500}}}}
 h.world=app.world;TheApp=app
 local native={draw=function(_,_,sx,sy,sw,sh,dx,dy,skip)
   event('map:'..sw..':'..sh..':'..tostring(skip));if not skip then event('floor')end
   event('entity');event('audio');event('overlay')
 end}
 app.map=setmetatable({th=native,WorldToScreen=function()return 4,5 end},Map._metatable)
 local w=base(c,ui);w:UIFullscreen(ui);w.background=bitmap();w.panel_sprites=sprites
 w.text_font=font;w.label_font=font;w.normal_font=font;w.red_font=font;w.number_font=font;w.title_font=font;w.blue_font=font;w.small_font=font
 w.sliders={};for _,k in ipairs{'send_home','guess_cure','stop_procedure','goto_staffroom'}do w.sliders[k]={x=1,y=2}end
 w.selected=1;w.crit_data={{visible=true,name='cures',win_value=10}};w.warning={}
 w.research={research_policy=setmetatable({total=100},{__index=function()return {current=false}end})}
 w.staff_members={Doctor={},Nurse={},Handyman={},Receptionist={}};w.category='Nurse';w.page=1;w.hospital=h
 w.row_blankers={};for i=1,10 do w.row_blankers[i]={}end
 for _,k in ipairs{'progress_surgeon','qualified_surgeon','progress_psychiatrist','qualified_psychiatrist','progress_researcher','qualified_researcher','arrow','portrait_back'}do w[k]={setTooltip=function()event('tip')end}end
 ui.windows={w};ui.modal_windows={fullscreen=w};return ui,w
end
local count=0
for _,c in ipairs{UIPolicy,UIProgressReport,UIResearch,UIStaffManagement}do
 local ui,w=setup(c);assert(gate.covered(ui,canvas),'must hit '..tostring(c))
 trace={};math.randomseed(100);ui:draw(canvas);local optimized=table.concat(trace,'|');local rng=math.random()
 resources[w.background]=false;trace={};math.randomseed(100);ui:draw(canvas);local full=table.concat(trace,'|')
 assert(rng==math.random());assert(full:find('map:640:480:false|floor|entity|audio|overlay',1,true))
 assert(optimized:find('map:640:480:true|entity|audio|overlay',1,true))
 assert(full:gsub('map:640:480:false|floor','map:640:480:true',1)==optimized)
 resources[w.background]=true;w.visible=false;assert(not gate.covered(ui,canvas));trace={};ui:draw(canvas);assert(table.concat(trace,'|'):find('|floor|',1,true))
 w.visible=true;assert(gate.covered(ui,canvas));ui.windows={};ui.modal_windows={};assert(not gate.covered(ui,canvas));count=count+1
end
-- The real staff draw keeps the 83x82 Map draw's default false even inside an
-- optimized top-level frame, including its entity/sound/overlay call order.
do
 local ui,w=setup(UIStaffManagement);local profile={skill=.5,wage=100,attention_to_detail=.4,getFullName=function()return 'Test' end,drawFace=function()event('face')end}
 w.staff_members.Nurse={{profile=profile,getAttribute=function()return .5 end,th={getSecondaryMarker=function()return 1,2,3,4 end}}};w.selected_staff=1
 trace={};ui:draw(canvas);local t=table.concat(trace,'|');assert(t:find('map:640:480:true|entity|audio|overlay',1,true));assert(t:find('map:83:82:false|floor|entity|audio|overlay',1,true));count=count+1
end
local rejects={
 function(ui,w)ui.app.config.width=800 end,function(ui,w)ui.app.config.ui_scale=2 end,
 function(ui,w)ui.zoom_factor=1.2 end,function(ui,w)ui.map_editor={}end,
 function(ui,w)ui.x=1 end,function(ui,w)w.x=1 end,function(ui,w)w.y=1 end,
 function(ui,w)w.width=639 end,function(ui,w)w.height=479 end,
 function(ui,w)w.dragging=true end,function(ui,w)w.border_sprites={}end,
 function(ui,w)w.background={}end,function(ui,w)resources[w.background]=false end,
 function(ui,w)w.draw=function()end end,function(ui,w)ui.app.map.draw=function()end end,
 function(ui,w)ui.panels={{visible=true,custom_draw=function()end}}end,
 function(ui,w)ui.windows[#ui.windows+1]=Window()end,
 function(ui,w)setmetatable(ui.windows,{})end,function(ui,w)w.closed=true end,
 function(ui,w)TheApp={}end,
}
for i,f in ipairs(rejects)do local ui,w=setup(UIPolicy);f(ui,w);assert(not gate.covered(ui,canvas),'reject '..i);count=count+1 end
-- Real normal predecessor objects and actual width-dependent drawPanels.
do
 local ui,w=setup(UIPolicy);ui.registerKeyHandler=function()end
 ui.bottom_panel=base(UIBottomPanel,ui);ui.bottom_panel.panel_sprites=sprites
 ui.adviser=base(UIAdviser,ui);ui.bottom_panel.windows={ui.adviser}
 ui.menu_bar=base(UIMenuBar,ui);ui.subtitles=base(Subtitles,ui)
 ui.windows={w,ui.subtitles,ui.menu_bar,ui.bottom_panel}
 assert(gate.covered(ui,canvas))
 -- This helper uses original config predicates, no replacement of draw methods.
 ui.app.config.machine_menu_button=true
 ui.bottom_panel:drawPanels()
 assert(gate.covered(ui,canvas),'drawPanels success should hit')
 local seen=0;for _,p in ipairs(ui.bottom_panel.panels)do if p.custom_draw then seen=seen+1 end end
 assert(seen==0,'640px never admits machine callback')
 -- Original width predicate + real resize rebuild: exactly 676 excludes,
 -- 677 includes; returning to 640 rebuilds away its unsupported closure.
 for _,width in ipairs{676,677,640}do
  ui.app.config.width=width;ui.bottom_panel:onChangeResolution()
  local custom=0;for _,p in ipairs(ui.bottom_panel.panels)do if p.custom_draw then custom=custom+1 end end
  assert(custom==(width==677 and 1 or 0));assert(gate.covered(ui,canvas)==(width==640))
 end
 ui.bottom_panel:afterLoad(999,999);assert(gate.covered(ui,canvas),'actual afterLoad rebuilt panels')
 local h=ui.hospital;h.balance=1234;h.reputation=500;h.reputation_min=0;h.reputation_max=1000
 ui.app.gfx.drawNumbersFromUnicode=function()return false end
 ui.app.world.isCurrentSpeed=function()return false end
 ui.app.world.date=function()return {monthOfYear=function()return 1 end,dayOfMonth=function()return 2 end}end
 local b=ui.bottom_panel;b.world=ui.app.world;b.money_font=font;b.date_font=font;b.message_door={closed_amount=0}
 ui.adviser.phase=0;ui.adviser.th={setScaleFactor=function()event('adviser-scale')end,draw=function()event('adviser-draw')end}
 ui.menu_bar.panel_sprites=sprites;ui.menu_bar.width=640;ui.menu_bar.menus={};ui.menu_bar.open_menus={};ui.menu_bar.white_font=font
 ui.subtitles.queue={isEmpty=function()return true end}
 trace={};math.randomseed(47);ui:draw(canvas);local optimized=table.concat(trace,'|');local rng=math.random()
 resources[w.background]=false;trace={};math.randomseed(47);ui:draw(canvas);local full=table.concat(trace,'|')
 assert(rng==math.random());assert(full:gsub('map:640:480:false|floor','map:640:480:true',1)==optimized)
 resources[w.background]=true
 local t=os.clock();for _=1,100000 do assert(gate.covered(ui,canvas))end
 print(('normal 3 widgets + %d panels: %.3fus/predicate host only'):format(#b.panels,(os.clock()-t)*10))
 ui.bottom_panel.panels[#ui.bottom_panel.panels+1]={visible=true,custom_draw=function()end}
 assert(not gate.covered(ui,canvas),'unknown supported custom callback')
 ui.bottom_panel:removeAllPanels();ui.bottom_panel:drawPanels();assert(gate.covered(ui,canvas))
 -- Same exact rebuild sequence present in afterLoad; full migration services
 -- are outside this draw predicate fixture.
 local weak=setmetatable({ui,w,ui.bottom_panel},{__mode='v'});ui=nil;w=nil;b=nil;h=nil;TheApp=nil
 collectgarbage('collect');collectgarbage('collect');assert(next(weak)==nil,'registry retained world')
 count=count+1
end
-- Lightweight successful predicate cost, independent of device/net FPS.
do
 local ui=setup(UIPolicy);local n=100000;collectgarbage('collect');local kb=collectgarbage('count');local t=os.clock()
 for _=1,n do assert(gate.covered(ui,canvas))end
 local elapsed=os.clock()-t;collectgarbage('collect');assert(collectgarbage('count')<=kb+1)
 print(('predicate %d calls %.6fs %.3fus/call; host only'):format(n,elapsed,elapsed*1e6/n))
 ui.windows={};ui.modal_windows={};t=os.clock();for _=1,n do assert(not gate.covered(ui,canvas))end
 print(('ordinary game no target: %.3fus/predicate host only'):format((os.clock()-t)*1e6/n))
end
print('PASS Lua floor contract cases='..count)
-- A real native bitmap draw error enters the original draw caller exactly
-- once; optimization never catches/retries/reorders the remaining UI work.
do
 local ui,w=setup(UIPolicy);local raw={};draw_errors[w.background]=raw
 trace={};math.randomseed(55);local ok,err=pcall(ui.draw,ui,canvas);assert(not ok and err==raw)
 local optimized=table.concat(trace,'|');local next_random=math.random()
 resources[w.background]=false;trace={};math.randomseed(55);ok,err=pcall(ui.draw,ui,canvas);assert(not ok and err==raw)
 assert(next_random==math.random());assert(table.concat(trace,'|'):gsub('map:640:480:false|floor','map:640:480:true',1)==optimized)
end
-- Execute the actual optional-module preamble + complete GameUI draw with a
-- missing module. This is the supported SD/old-deployment fallback; there is
-- no newly required embedded adapter dependency.
do
 local f=assert(io.open(generated..'/CorsixTH/Lua/game_ui.lua'));local text=f:read('*a');f:close()
 local draw=assert(text:match('(%-%- Optional optimization;.-function GameUI:draw%(canvas%).-\nend)'))
 local env=setmetatable({GameUI={},require=function()error('module missing',0)end,shake_screen_max_movement=50},{__index=_G})
 assert(load(draw,'@actual-optional-GameUI','t',env))()
 local ui=setup(UIPolicy);trace={};env.GameUI.draw(ui,canvas)
 assert(table.concat(trace,'|'):find('map:640:480:false|floor|entity|audio|overlay',1,true))
end
print('PASS actual optional module fallback and raw draw error order')
