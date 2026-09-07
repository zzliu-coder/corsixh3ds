-- Read-only defect reproduction; no game assets, saves, device or render calls.
-- Runs the real upstream UIWatch constructor / UIFax:choice and this repository's
-- platform adapter. Minimal graphics/window/native seams are stated below.
-- Usage: lua reproduce_watch_context.lua REPO PINNED_UPSTREAM
local repo, upstream = assert(arg[1]), assert(arg[2])
local function noop() end
corsixth = {require = noop}
Date = {hoursPerDay = function() return 48 end}
_S = {tooltip = {watch = {hospital_opening = "open", emergency = "emergency",
                         epidemic = "epidemic"}}}
local panel = {}
function panel:makeButton() return self end
function panel:setTooltip() return self end
Window = {}
function Window:Window() self.visible = true; self.textboxes = {}; self.panels = {} end
function Window:setDefaultPosition() end
function Window:addPanel() local p = setmetatable({}, {__index=panel}); table.insert(self.panels,p); return p end
UIFullscreen = {close = function(self) self.ui:removeWindow(self); self.closed = true end}
-- Only class registration/inheritance are emulated; loaded method bodies are untouched.
class = function(name)
  return function(base)
    local cls = {}; cls.__index = cls
    setmetatable(cls, {__index=base, __call=function(_, ...)
      local instance = setmetatable({}, cls); cls[name](instance, ...); return instance
    end})
    _G[name] = cls
  end
end
dofile(upstream .. "/CorsixTH/Lua/dialogs/watch.lua")
dofile(upstream .. "/CorsixTH/Lua/dialogs/fullscreen/fax.lua")
local scrolls, spawned = 0, 0
local ui = {windows={}, textboxes={}, cursor_x=320, cursor_y=240, down_count=0,
            hospital={vip_declined=0}}
function ui:addWindow(w) table.insert(self.windows,1,w) end
function ui:removeWindow(w) for i,v in ipairs(self.windows) do if v==w then table.remove(self.windows,i); return end end end
function ui:scrollMap() scrolls=scrolls+1 end
local app = {ui=ui,config={language="English"},save=noop,load=noop,
             gfx={loadSpriteTable=function() return {} end},
             world={newObject=function(_, name) assert(name=="helicopter"); spawned=spawned+1 end}}
ui.app=app
local native={}
for _,name in ipairs({"span_begin","span_end","observe_memory","flush_observations",
  "atomic_commit","begin_critical_io","end_critical_io","set_notice","checkpoint","request_redraw"}) do native[name]=noop end
local p=dofile(repo .. "/lua/3ds/platform.lua").attach(app,native,{resource_events=false,epoch=1})
assert(p:inputContext()=="world")
p:handleAction{type="pan_camera",dx=20,dy=0}
assert(scrolls==1)
print("before_accept: context=world scroll_calls=1")
-- Fax construction (graphics/layout) is a seam; its real acceptance/close methods execute.
local icon={removeMessage=noop,adjustToggle=noop}
local fax=setmetatable({ui=ui,visible=true,textboxes={},icon=icon,
  message={choices={{choice="accept_emergency"}}}},UIFax)
ui:addWindow(fax)
fax:choice(1)
assert(fax.closed and spawned==1 and #ui.windows==1)
local watch=ui.windows[1]
assert(watch.count_type=="emergency" and watch.modal_class=="open_countdown")
assert(watch.visible and watch.esc_closes==false and ui.down_count==0)
assert(p:inputContext()=="dialog")
p:handleAction{type="pan_camera",dx=20,dy=0}
assert(scrolls==1, "R53 watch blocking no longer reproduced: re-audit this candidate")
print("after_accept: real_UIWatch=emergency modal_class=open_countdown context=dialog scroll_calls=1")
ui:removeWindow(watch)
assert(p:inputContext()=="world")
p:handleAction{type="pan_camera",dx=20,dy=0}
assert(scrolls==2)
print("after_watch_removed: context=world scroll_calls=2")
print("REPRODUCED: R53 timer HUD blocks camera pan; product verdict=FAIL; device event correlation=NOT_PROVEN")
