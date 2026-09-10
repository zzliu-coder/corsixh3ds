-- Load full production chunks in their own real strict environment. Only
-- graphics, file existence and persistence registration are service seams.
return function(root, services)
  services=services or {}
  local env={}
  for key,value in pairs(_G) do env[key]=value end
  env._G=env
  env.IS_3DS=nil
  env.corsixth={require=function(name) assert(name=='persistance') end}
  env.permanent=function(_,value)
    if value~=nil then return value end
    return function(item) return item end
  end
  env.lfs={attributes=function(...) if services.attributes then return services.attributes(...) end end}
  env.require=function(name) if name=='lfs' then return env.lfs end;return require(name) end
  env.UIInformation=services.information or function(_,text) return {text=text} end
  env._S={save_game_window={caption='%s',save_button='Save',new_save_game='Name',missing_filename='Missing'},
    tooltip={save_game_window={new_save_game='Name'}},confirmation={overwrite_save='Overwrite?'},
    errors={save_prefix='Save: '}}
  for _,file in ipairs({'strict.lua','class.lua','window.lua','dialogs/resizable.lua',
    'dialogs/tree_ctrl.lua','dialogs/resizables/file_browser.lua','dialogs/confirm_dialog.lua',
    'dialogs/resizables/file_browsers/save_game.lua','dialogs/resizables/file_browsers/load_game.lua'}) do
    assert(loadfile(root..'/'..file,'t',env))()
  end
  assert(rawget(env,'IS_3DS')==nil)
  assert(env.class.superclass(env.UISaveGame)==env.UIFileBrowser)
  assert(env.class.superclass(env.UIFileBrowser)==env.UIResizable)
  assert(env.class.superclass(env.UIResizable)==env.Window)
  -- The confirmation display constructor is a graphics seam. Its real
  -- ok/cancel/close methods and Window.close remain unmodified.
  function env.UIConfirmDialog:UIConfirmDialog(ui, _, _, callback_ok, callback_cancel)
    self:Window();self.ui=ui;self.callback_ok=callback_ok;self.callback_cancel=callback_cancel
  end
  local function create(ui)
    local window=setmetatable({ui=ui},env.UISaveGame._metatable)
    local panels={}
    function window:UIFileBrowser(_,_,_,height)
      assert(height==(ui.app._3ds and 235 or 265));self:Window();self.ui=ui;self.width=450;self.col_bg={}
      self.control={sortByDate=function() end}
    end
    function window:addBevelPanel()
      local panel={}
      function panel:setLabel() return self end
      function panel:setTooltip() return self end
      function panel:makeButton(_,_,_,_,_,callback) self.callback=callback;return self end
      function panel:makeTextbox(confirm,abort)
        return {text='',panel=self,confirm_callback=confirm,abort_callback=abort,
          setText=function(self,text) self.text=text end}
      end
      panels[#panels+1]=panel;return panel
    end
    window:UISaveGame(ui)
    assert(#panels==(ui.app._3ds and 4 or 1))
    if ui.app._3ds then
      assert(window.new_savegame_textbox.text==(ui.app._3ds.save_prefix or '')..'Slot1')
    end
    return window,panels
  end
  return {save=env.UISaveGame,load=env.UILoadGame,create=create,environment=env,services=services}
end
