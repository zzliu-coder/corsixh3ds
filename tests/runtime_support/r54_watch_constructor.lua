-- Original UIWatch constructor, CorsixTH v0.70.1, fixed source commit
-- 56bd5d00f76331c7f76d7b696726a7926303ca0c, dialogs/watch.lua:33-114.
-- Copyright (c) 2009 Peter "Corsix" Cawley; MIT, see THIRD_PARTY.md in delivery.
-- Only the constructor is retained; graphics/window base methods are test seams.
class "UIWatch" (Window)
local UIWatch = _G["UIWatch"]
local TICK_DAYS = 100
local TICK_DAYS_EMERGENCY = 52
local TIMER_SEGMENTS = 13
function UIWatch:UIWatch(ui, count_type)
  self:Window()

  local app = ui.app

  self.esc_closes = false
  self.modal_class = "open_countdown"
  if count_type == "emergency" then
    self.tick_rate = math.floor((TICK_DAYS_EMERGENCY * Date.hoursPerDay()) / TIMER_SEGMENTS)
    self.tick_timer = self.tick_rate
  else
    self.tick_rate = math.floor((TICK_DAYS * Date.hoursPerDay()) / TIMER_SEGMENTS)
    self.tick_timer = self.tick_rate  -- Initialize tick timer
  end
  self.open_timer = 12
  self.ui = ui
  self.hospital = ui.hospital
  self.width = 39
  self.height = 79
  self:setDefaultPosition(20, -100)
  self.panel_sprites = app.gfx:loadSpriteTable("Data", "Watch01V", true)
  self.epidemic = false
  self.count_type = count_type
  self.active_hover = false
  -- For cycling the list of epidemic/emergency patients which index to use
  self.current_index = nil
  -- The last patient whose dialog was opened by clicking the timer
  self.lastCycledPatient = nil

  local end_sprite = (count_type == "epidemic") and 14 or 16
  self.end_sprite = end_sprite

  local tooltips = {
    ["initial_opening"] = _S.tooltip.watch.hospital_opening,
    ["emergency"]       = _S.tooltip.watch.emergency,
    ["epidemic"]        = _S.tooltip.watch.epidemic,
  }

  if count_type == "epidemic" then
    self.end_button = self:addPanel(end_sprite, 4, 0)
    :makeButton(4, 0, 27, 28, end_sprite + 1, self.toggleVaccinationMode)
    :setTooltip(tooltips[count_type])

    self:addPanel(end_sprite, 4, 0)
    .custom_draw = --[[persistable:epidemic_timer_button]] function(panel, canvas, x, y)
      local s = TheApp.config.ui_scale
      x = x + panel.x * s
      y = y + panel.y * s
      panel.window.panel_sprites:draw(canvas, panel.sprite_index, x, y, { scaleFactor = s })
      if self.active_hover then
        self.panel_sprites:draw(canvas, 15, x, y, { scaleFactor = s })
      end
    end

  elseif count_type ~= "emergency" then
    self.end_button = self:addPanel(end_sprite, 4, 0)
      :makeButton(4, 0, 27, 28, end_sprite + 1, self.onCountdownEnd)
      :setTooltip(tooltips[count_type])
  end

  local timer_sprite = 13
  if count_type == "epidemic" or count_type == "emergency" then
    self:addPanel(timer_sprite, 0, 28)
      :setTooltip(tooltips[count_type])
      :makeButton(timer_sprite, 0, 25, 50, timer_sprite,
        self.scrollToTimerEventPatient, nil, self.cycleTimerEventPatient)
  else
    self:addPanel(timer_sprite, 0, 28):setTooltip(tooltips[count_type])
    .custom_draw = --[[persistable:open_hospital_timer_button]] function(panel, canvas, x, y)
      local s = TheApp.config.ui_scale
      x = x + panel.x * s
      y = y + panel.y * s
      panel.window.panel_sprites:draw(canvas, panel.sprite_index, x, y, { scaleFactor = s })
      if self.active_hover then
        self.panel_sprites:draw(canvas, 17, x + 4 * s, y - 28 * s, { scaleFactor = s })
      end
    end
  end
  self:addPanel(1, 2, 47)
end
