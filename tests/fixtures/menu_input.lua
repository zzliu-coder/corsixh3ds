-- Frozen 56bd5d00f76331c7f76d7b696726a7926303ca0c menu input methods.
-- Construction, layout and hit-testing are explicit fixture seams.
--[[ Copyright (c) 2009 Peter "Corsix" Cawley

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE. --]]

function UIMenuBar:appear()
  self.disappear_counter = nil
  self.visible = true
  if not self.on_top then
    self.ui:sendToTop(self)
    self.on_top = true
  end
end

function UIMenuBar:disappear()
  if not self.disappear_counter then
    self.disappear_counter = 100
  end
end

function UIMenuBar:onMouseDown(button, x, y)
  if button ~= "left" or not self.visible then
    return
  end
  local repaint = false
  while self.active_menu do
    local menu = self.active_menu
    if menu:hitTest(x, y, 0) then
      if repaint then
        self:onMouseMove(x, y)
      end
      return true
    end
    for i = #self.open_menus, self.active_menu.level, -1 do
      self.open_menus[i] = nil
    end
    self.active_menu = menu.parent
    repaint = true
  end
  local new_active = self:hitTestBar(x, y)
  if new_active ~= self.active_menu then
    self.open_menus = {new_active}
    self.active_menu = new_active
    repaint = true
    self.ui:playSound("selectx.wav")
  end
  return repaint
end

function UIMenuBar:onMouseUp(button, x, y)
  if button ~= "left" or not self.visible then
    return
  end
  local repaint = false
  local s = TheApp.config.ui_scale
  while self.active_menu do
    local index = self.active_menu:hitTest(x, y, 0)
    if index == false then
      if not self.active_menu.parent and y < 16 * s then
        break
      else
        self.active_menu = self.active_menu.parent
      end
    elseif index == true then
      break
    else
      local item = self.active_menu.items[index]
      if item.submenu then
        break
      elseif item.is_check_item then
        if item.group then
          if not item.checked then
            item.checked = true
            for _, itm in ipairs(self.active_menu.items) do
              if itm ~= item and itm.group == item.group then
                itm.checked = false
              end
            end
            if item.handler then
              item.handler(item, self.active_menu)
            end
          end
        else
          item.checked = not item.checked
          if item.handler then
            item.handler(item, self.active_menu)
          end
        end
      else
        if item.handler then
          item.handler(item, self.active_menu)
        end
        if y > 22 * s then
          self:disappear()
        end
        self.active_menu = false
      end
      self.ui:playSound("selectx.wav")
      repaint = true
      break
    end
  end
  for i = #self.open_menus, (self.active_menu and self.active_menu.level or 0) + 1, -1 do
    self.open_menus[i] = nil
  end
  return repaint
end



