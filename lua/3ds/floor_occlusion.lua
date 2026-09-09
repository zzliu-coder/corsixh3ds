-- R73: proof for four fixed fullscreen draw prefixes. This module owns class
-- function identities only; no App/world/window or background is retained.
local M = {}
local fixed = {}
local names = {
  Window = {"draw"}, Map = {"draw"},
  UIPolicy = {"draw"}, UIProgressReport = {"draw"},
  UIResearch = {"draw"}, UIStaffManagement = {"draw"},
  UIBottomPanel = {"draw", "drawDynamicInfo", "drawReputationMeter"},
  UIAdviser = {"draw"}, UIMenuBar = {"draw", "drawMenu"},
  Subtitles = {"draw"},
}
local opaque, bitmap_draw
do
  local ok, th = pcall(require, "TH")
  if ok and th.bitmap then
    local bm = th.bitmap()
    opaque, bitmap_draw = bm.opaqueCanvas, bm.draw
  end
end

function M.remember(name, class)
  local methods = names[name]
  if not methods or fixed[name] then return end
  local record = {class = class}
  for _, key in ipairs(methods) do record[key] = class[key] end
  fixed[name] = record
end

local function exact(object, name)
  local record = fixed[name]
  local mt = getmetatable(object)
  if not record or type(mt) ~= "table" or rawget(mt, "__index") ~= record.class then return false end
  if _G[name] ~= record.class then return false end
  for _, key in ipairs(names[name]) do
    if object[key] ~= record[key] or record.class[key] ~= record[key] then return false end
  end
  return true
end

local function plain(t)
  return type(t) == "table" and getmetatable(t) == nil
end

local function panels_safe(window)
  if not plain(window.panels) then return false end
  for _, panel in ipairs(window.panels) do
    -- The normal machine-menu callback requires width/ui_scale > 676. This
    -- contract only accepts 640/1; any remaining custom draw is unsupported.
    if panel.visible and panel.custom_draw then return false end
  end
  -- These normal foreground widgets have no textboxes/hotkeyboxes. Their
  -- cursors may be arbitrary methods and cannot precede the opaque prefix.
  if not plain(window.textboxes) or next(window.textboxes) then return false end
  if not plain(window.hotkeyboxes) or next(window.hotkeyboxes) then return false end
  return true
end

local function leaf(window, name)
  return exact(window, name) and panels_safe(window) and
    (not window.windows or plain(window.windows) and not next(window.windows))
end

local function predecessor(ui, window)
  if window == ui.bottom_panel and exact(window, "UIBottomPanel") and panels_safe(window) then
    if not plain(window.windows) then return false end
    for _, child in ipairs(window.windows) do
      if child.visible and (child ~= ui.adviser or not leaf(child, "UIAdviser")) then return false end
    end
    return true
  end
  if window == ui.menu_bar then return leaf(window, "UIMenuBar") end
  if window == ui.subtitles then return leaf(window, "Subtitles") end
  return false
end

function M.covered(ui, canvas)
  local candidate = ui.modal_windows and ui.modal_windows.fullscreen
  if not candidate then return false end
  if not opaque or not bitmap_draw or TheApp ~= ui.app then return false end
  local config = ui.app.config
  if not plain(config) or config.width ~= 640 or config.height ~= 480 or config.ui_scale ~= 1 or
      ui.zoom_factor ~= 1 or ui.map_editor or ui.x ~= 0 or ui.y ~= 0 then return false end
  local window_draw = fixed.Window
  if not window_draw or Window ~= window_draw.class or Window.draw ~= window_draw.draw or
      not exact(ui.app.map, "Map") or not plain(ui.windows) or not plain(ui.panels) or next(ui.panels) then return false end
  if candidate.closed or not candidate.visible or candidate.ui ~= ui or
      candidate.x ~= 0 or candidate.y ~= 0 or candidate.width ~= 640 or candidate.height ~= 480 or
      candidate.dragging or candidate.border_sprites then return false end
  if not (exact(candidate, "UIPolicy") or exact(candidate, "UIProgressReport") or
      exact(candidate, "UIResearch") or exact(candidate, "UIStaffManagement")) then return false end
  local background = candidate.background
  if type(background) ~= "userdata" or background.draw ~= bitmap_draw then return false end
  -- Walk only the real prefix before this bitmap; all later Window.draw work
  -- stays in its original order. Unknown visible predecessors disable A2.
  local found = false
  for i = #ui.windows, 1, -1 do
    local window = ui.windows[i]
    if window == candidate then found = true; break end
    if window.visible and not predecessor(ui, window) then return false end
  end
  return found and opaque(background, canvas) == true
end

return M
