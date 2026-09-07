-- Loads the complete candidate adapter and real pinned UIWatch constructor.
-- Graphics, native platform, base window and class registration are test seams.
local repo=assert(arg[1]);local function noop()end
Date={hoursPerDay=function()return 48 end}
_S={tooltip={watch={hospital_opening="open",emergency="emergency",epidemic="epidemic"}}}
local panel={};function panel:makeButton()return self end;function panel:setTooltip()return self end
Window={}
function Window:Window()self.visible=true;self.textboxes={};self.panels={} end
function Window:setDefaultPosition()end
function Window:addPanel()local p=setmetatable({}, {__index=panel});self.panels[#self.panels+1]=p;return p end
class=setmetatable({}, {__call=function(_,name)return function(base)
  local cls={};cls.__index=cls
  setmetatable(cls,{__index=base,__call=function(c,...)
    local instance=setmetatable({},c);c[name](instance,...);return instance end})
  _G[name]=cls
end end})
-- Same inheritance traversal as the pinned class.is method.
function class.is(instance,kind)
  local typ=type(instance);if typ~="table" and typ~="userdata" then return false end
  local methods=instance
  while methods do if methods==kind then return true end
    local mt=getmetatable(methods);methods=mt and mt.__index
  end
  return false
end
dofile(repo.."/tests/runtime_support/r54_watch_constructor.lua")
UIPlaceObjects={}
local scrolls,focuses=0,0;local events={}
local ui={windows={},textboxes={},cursor_x=320,cursor_y=240,down_count=0,
  hospital={},bottom_panel={},adviser={},subtitles={}}
ui.menu_bar={visible=true}
function ui:scrollMap()scrolls=scrolls+1 end
function ui:setMouseReleased()end
local app={ui=ui,world={},config={language="English",ui_scale=1},save=noop,load=noop,
 gfx={loadSpriteTable=function()return {} end}}
ui.app=app
function app:dispatch(event,...)
 events[#events+1]=event
 if event=="motion" then ui.cursor_x,ui.cursor_y=... end
end
local native={focus_view=function()focuses=focuses+1 end}
for _,n in ipairs({"span_begin","span_end","observe_memory","flush_observations","atomic_commit",
 "begin_critical_io","end_critical_io","set_notice","checkpoint","request_redraw"})do native[n]=noop end
local adapter=dofile(repo.."/lua/3ds/platform.lua").attach(app,native,{resource_events=false,epoch=1})
local total=0
local function context(windows,expected)
 ui.windows=windows;assert(adapter:inputContext()==expected,adapter:inputContext().." expected "..expected)
 assert(adapter:inputState().input_context==expected);total=total+1
end
local modal={visible=true,modal_class="main",x=10,y=10,width=80,height=80}
local build={visible=true,phase="walls"};local place={visible=true,phase="objects"}
for _,kind in ipairs({"initial_opening","open_countdown","emergency","epidemic"})do
 local hud=UIWatch(ui,kind)
 context({},"world");local epoch=adapter:inputState().input_epoch
 context({hud},"world");assert(adapter:inputState().input_epoch==epoch)
 local focus_before=focuses;adapter:prepareInput();assert(focuses==focus_before)
 local before=scrolls;adapter:handleAction{type="pan_camera",dx=20,dy=0};assert(scrolls==before+1)
 context({hud,modal},"dialog");before=scrolls;adapter:handleAction{type="pan_camera",dx=20};assert(scrolls==before)
 context({modal,hud},"dialog")
 context({hud,build},"build_room");context({hud,place},"place_object")
 context({hud,modal,build},"dialog");context({hud,build,modal},"build_room")
 context({hud,ui.menu_bar},"menu")
 hud.textboxes={{enabled=true,active=true,visible=true}};context({hud,build},"text_input")
 hud.textboxes[1].visible=false;context({hud,build},"build_room")
 hud.textboxes={};hud.esc_closes=true;context({hud},"dialog")
 hud.esc_closes=false;hud.modal_class="main";context({hud},"dialog")
 hud.modal_class="open_countdown";hud.visible=false;context({hud},"world")
 hud.visible=true;context({hud},"world")
 ui.down_count=1;before=scrolls;adapter:handleAction{type="pan_camera",dx=20};assert(scrolls==before);ui.down_count=0
 -- Mouse handling is dispatched unchanged, retaining HUD buttons in the list.
 events={};local windows=ui.windows
 assert(adapter:handlePointer{kind="down",x=100,y=100})
 assert(adapter:handlePointer{kind="up",x=100,y=100})
 assert(table.concat(events,",")=="motion,buttondown,motion,buttonup")
 assert(ui.windows==windows and windows[1]==hud)
end
context({{modal_class="open_countdown",esc_closes=false}},"dialog")
local hud=UIWatch(ui,"emergency");local saved=class;class=function()end
context({hud},"dialog");class=saved
context({ui.bottom_panel,ui.adviser,ui.subtitles},"world")
ui.textboxes={{enabled=true,active=true}};context({hud},"text_input");ui.textboxes={}
app.world=nil;context({},"menu");app.world={}
print("PASS full adapter + pinned UIWatch constructor: context_cases="..total.."; camera, pen, focus, ownership epochs")
