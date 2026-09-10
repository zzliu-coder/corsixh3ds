"""Small additions to the real upstream save dialog, retaining its commit path."""
from pathlib import Path
from sound_lifetime import replace_exact, SoundPatchError

def transform(text):
    text = text.replace('app._3ds:showError("Use 1-40 English letters, numbers, spaces, - or _.")',
                        'app._3ds:showError(require("3ds.media").uiText(app,"save_name_rule"))')
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
    app._3ds:showError(require("3ds.media").uiText(app,"save_name_rule"))
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
    if '-- CORSIXTH_3DS_TEXT_POLICY_R74' not in text:
        text = replace_exact(text, anchor, anchor + '''
  -- CORSIXTH_3DS_TEXT_POLICY_R74: the original confirm/overwrite path owns saving.
  if ui.app._3ds then self.new_savegame_textbox._3ds_keyboard_kind = "filename" end''',
            'save textbox keyboard policy')
        text = replace_exact(text, ':setLabel("Save slot " .. slot)',
            ':setLabel((require("3ds.media").isChinese(ui.app) and "存档槽 " or "Save slot ") .. slot)',
            'localized save slot labels')
    text=text.replace('((ui.app.config and ui.app.config.language == "Chinese (simplified)") and "存档槽 " or "Save slot ")',
                      '(require("3ds.media").isChinese(ui.app) and "存档槽 " or "Save slot ")')
    return text

def transform_textbox(text):
    if '-- CORSIXTH_3DS_TEXT_CLICK_R74' in text:
        return text
    return replace_exact(text, 'function Textbox:clicked()\n', '''function Textbox:clicked()
  -- CORSIXTH_3DS_TEXT_CLICK_R74: explicit pen release only, never setActive/init.
  local platform = self.panel.window.ui.app._3ds
  if platform and platform:requestTextKeyboard(self) then
    self:setActive(true)
    return
  end
''', 'textbox pen keyboard request')

def transform_player(text):
    if '-- CORSIXTH_3DS_PLAYER_TEXT_R74' in text:
        return text
    anchor = '    :allowedInput({"alpha", "numbers", "misc"}):characterLimit(15):setText(self.player_name)'
    return replace_exact(text, anchor, anchor + '''
  -- CORSIXTH_3DS_PLAYER_TEXT_R74: keep the original 15-byte/name callback rules.
  if app._3ds then self.name_textbox._3ds_keyboard_kind = "player" end''', 'player textbox policy')

def transform_staff_name(text):
    if '-- CORSIXTH_3DS_CJK_DISPLAY_NAME' in text:
        return text.replace('app and app.is_3ds and app.config.language == "Chinese (simplified)"',
                            'app and app.is_3ds and require("3ds.media").isChinese(app)')
    return replace_exact(text, 'function StaffProfile:getFullName()\n', '''function StaffProfile:getFullName()
  -- CORSIXTH_3DS_CJK_DISPLAY_NAME: Chinese initials are arbitrary syllables,
  -- not an omitted full given name. Display the stored name without inventing
  -- personal data; preserve fields, RNG, persistence and Latin initials.
  local app = self.world and self.world.app
  if app and app.is_3ds and require("3ds.media").isChinese(app) then
    local initial = tostring(self.initial)
    -- U+3400..U+9FFF: the CJK range used by the pinned name catalogue.
    local a, b, c = initial:byte(1, 3)
    if a and b and c and b >= 128 and b <= 191 and c >= 128 and c <= 191 then
      local point = (a - 224) * 4096 + (b - 128) * 64 + c - 128
      if a >= 224 and a <= 239 and point >= 0x3400 and point <= 0x9fff then
        return self.name
      end
    end
  end
''', 'stored Chinese name display')

def transform_chinese(text):
    marker = '-- CORSIXTH_3DS_CHINESE_COMPLETION'
    if marker in text:
        text = text[:text.index(marker)].rstrip() + '\n'
    addition = (Path(__file__).resolve().parents[1] /
                'resources/translations/simplified_chinese.lua').read_text(encoding='utf-8')
    return text.rstrip() + '\n\n' + marker + '\n' + addition

def patch_handheld_ui(root: Path, dry_run=False):
    path = root / 'CorsixTH/Lua/dialogs/resizables/file_browsers/save_game.lua'
    old = path.read_text(encoding='utf-8'); new = transform(old)
    changes=[]
    if new != old:
        if not dry_run: path.write_text(new, encoding='utf-8')
        changes.append(path.relative_to(root).as_posix())
    # Minimal pinned test inventories omit these modules. Complete product
    # generation always supplies both, and real-module tests cover the hooks.
    for relative, convert in (
        ('CorsixTH/Lua/window.lua', transform_textbox),
        ('CorsixTH/Lua/dialogs/resizables/new_game.lua', transform_player),
        ('CorsixTH/Lua/staff_profile.lua', transform_staff_name),
        ('CorsixTH/Lua/languages/simplified_chinese.lua', transform_chinese),
    ):
        path=root/relative
        if not path.exists(): continue
        old=path.read_text(encoding='utf-8');new=convert(old)
        if new != old:
            if not dry_run:path.write_text(new,encoding='utf-8')
            changes.append(relative)
    return changes

def check_handheld_ui(root):
    try: return ['handheld UI missing: ' + path for path in patch_handheld_ui(root, True)]
    except (OSError, SoundPatchError) as exc: return [str(exc)]
