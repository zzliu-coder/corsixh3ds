"""Small additions to the real upstream save dialog, retaining its commit path."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

def transform(text):
    text = replace_exact(text,
        '  self:UIFileBrowser(ui, "game", _S.save_game_window.caption:format(".sav"), 265,',
        '  self:UIFileBrowser(ui, "game", _S.save_game_window.caption:format(".sav"), ui.app._3ds and 235 or 265,',
        'slot row room')
    anchor = '    --[[persistable:save_game_new_savegame_textbox_abort_callback]] function() self:abortName() end)'
    if '-- CORSIXTH_3DS_SAVE_SLOTS_R48' not in text:
      text = replace_exact(text, anchor, anchor + '''
  -- CORSIXTH_3DS_SAVE_SLOTS_R48: use the existing overwrite and atomic-save path.
  if ui.app._3ds then
    self:setInputValue("Slot1")
    for slot = 1, 3 do
      self:addBevelPanel(5 + (slot - 1) * 147, 276, 142, 26, self.col_bg)
        :setLabel("Save slot " .. slot)
        :makeButton(0, 0, 142, 26, nil, --[[persistable:3ds_save_slot]] function()
          self:trySave(self.ui.app.savegame_dir .. "Slot" .. slot .. ".sav")
        end)
    end
  end''', 'slot buttons')
    text = replace_exact(text, '  local app = self.ui.app\n  if filename == "" then', '''  local app = self.ui.app
  if app._3ds and (type(filename) ~= "string" or #filename > 40 or
      filename:find("[^A-Za-z0-9 _%-]") or not filename:find("%S")) then
    app._3ds:showError("Use 1-40 English letters, numbers, spaces, - or _.")
    return
  end
  if filename == "" then''', 'portable save names')
    if '-- CORSIXTH_3DS_RECOVERY_SAVE_TARGET_R63' not in text:
        text=replace_exact(text,'    self:setInputValue("Slot1")',
            '''    -- CORSIXTH_3DS_RECOVERY_SAVE_TARGET_R63
    self:setInputValue((ui.app._3ds.save_prefix or "") .. "Slot1")''',
            'isolated recovery default name')
        text=replace_exact(text,
            'self:trySave(self.ui.app.savegame_dir .. "Slot" .. slot .. ".sav")',
            'self:trySave(self.ui.app.savegame_dir .. (self.ui.app._3ds.save_prefix or "") .. "Slot" .. slot .. ".sav")',
            'isolated recovery quick slots')
    return text

def patch_handheld_ui(root: Path, dry_run=False):
    path = root / 'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua'
    old = path.read_text(encoding='utf-8'); new = transform(old)
    if new == old: return []
    if not dry_run: path.write_text(new, encoding='utf-8')
    return [path.relative_to(root).as_posix()]

def check_handheld_ui(root):
    try: return ['handheld UI missing: ' + path for path in patch_handheld_ui(root, True)]
    except (OSError, SoundPatchError) as exc: return [str(exc)]
