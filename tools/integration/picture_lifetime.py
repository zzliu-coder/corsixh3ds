"""Keep visible pictures alive, retain a small warm set, prepare before UI changes."""
from sound_lifetime import replace_exact

WARM = '''
-- CORSIXTH_3DS_RAW_WARM_R62: windows own their live pictures. Three recently
-- loaded backgrounds stay warm; closed older windows can release their source
-- blocks. The weak lookup preserves identity for any still-visible picture.
function Graphics:_retainRaw(name, bitmap)
  local recent = self.raw_recent
  if not recent then recent = {}; self.raw_recent = recent end
  for i = #recent, 1, -1 do
    if recent[i].name == name then table.remove(recent, i) end
  end
  recent[#recent + 1] = {name = name, bitmap = bitmap}
  if #recent > 3 then table.remove(recent, 1) end
  return bitmap
end
'''

PREFLIGHT = '''  -- CORSIXTH_3DS_WINDOW_PREPARE_R62: load the known large picture before
  -- setEditRoom, modal replacement or pause changes. A failed resource request
  -- leaves the current hospital/window usable and records its exact error.
  local raw_name = ({UIResearch="Res01V", UIPolicy="Pol01V", UIProgressReport="Rep01V"})[dialog_class]
  local native = self.ui.app._3ds and self.ui.app._3ds.native
  if native and raw_name then
    local gfx = self.ui.app.gfx
    local ok, result = pcall(gfx.loadRaw, gfx, raw_name, 640, 480, "QData", "QData", raw_name..".pal", true)
    if not ok then
      print("window-prepare: class="..dialog_class.." status=FAIL error="..tostring(result))
      native.set_notice("WINDOW LOAD FAILED - CLOSE OTHER WINDOWS", true)
      self:updateButtonStates()
      return false
    end
    print("window-prepare: class="..dialog_class.." status=PASS")
  end
'''

def transforms(root):
    name='CorsixTH/Lua/graphics.lua'
    text=(root/name).read_text()
    if 'CORSIXTH_3DS_RAW_WARM_R62' not in text:
        text=replace_exact(text,'    raw = {},','    raw = setmetatable({}, {__mode = "v"}),','raw weak lookup')
        begin=text.index('function Graphics:loadRaw(')
        text=text[:begin]+WARM+'\n'+text[begin:]
        text=text.replace('    return self.cache.raw[name]','    return self:_retainRaw(name, self.cache.raw[name])')
        text=replace_exact(text,'  self.cache.raw[name] = bitmap',
            '  self.cache.raw[name] = bitmap\n  self:_retainRaw(name, bitmap)','raw bounded warm ownership')
        # Observational fast wrapper has to touch the warm set too.
        text=text.replace('if TH3DS and self.cache.raw[name] then return self.cache.raw[name] end',
            'if TH3DS and self.cache.raw[name] then return self:_retainRaw(name, self.cache.raw[name]) end')
    yield name,text
    name='CorsixTH/Lua/dialogs/bottom_panel.lua'
    text=(root/name).read_text()
    if 'CORSIXTH_3DS_WINDOW_PREPARE_R62' not in text:
        anchor='function UIBottomPanel:addDialog(dialog_class, extra_function)\n'
        text=replace_exact(text,anchor,anchor+PREFLIGHT,'prepare large window resources before publication')
    text=text.replace('  if TH3DS and raw_name then',
        '  local native = self.ui.app._3ds and self.ui.app._3ds.native\n  if native and raw_name then')
    text=text.replace('      TH3DS.set_notice("WINDOW LOAD FAILED - CLOSE OTHER WINDOWS", true)',
        '      native.set_notice("WINDOW LOAD FAILED - CLOSE OTHER WINDOWS", true)')
    yield name,text
