"""Keep visible pictures alive, retain a small warm set, prepare before UI changes."""
from sound_lifetime import replace_exact

LEGACY_WARM = '''
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

WARM = '''
-- CORSIXTH_3DS_RAW_WARM_R64: source working set, separate from GPU atlas VRAM.
-- Four 640x480 indexed backgrounds + 65x1350 faces + five 1024-byte palettes
-- cost 1321670 bytes. Bound warm ownership to 1.5 MiB and eight identities.
-- Actual retained GPU metadata/atlas tiles are governed by the renderer.
function Graphics:trimRawWarm()
  local bytes = self.raw_warm_bytes or 0
  -- Clear in place: pressure relief must not require a replacement table.
  local recent = self.raw_recent
  if recent then for i = #recent, 1, -1 do recent[i] = nil end end
  self.raw_warm_bytes = 0
  return bytes
end

function Graphics:_retainRaw(name, bitmap, source_bytes)
  local recent = self.raw_recent
  if not recent then recent = {}; self.raw_recent = recent end
  local costs = self.raw_source_bytes
  if not costs then
    costs = setmetatable({}, {__mode = "k"})
    self.raw_source_bytes = costs
  end
  local budget = math.max(0, math.min(self.raw_warm_budget or 1572864, 1572864))
  local limit = math.max(0, math.min(self.raw_warm_max_entries or 8, 8))
  if type(source_bytes) == "number" and source_bytes > 0 and
      source_bytes < math.huge and source_bytes == math.floor(source_bytes) then
    costs[bitmap] = source_bytes
  end
  source_bytes = costs[bitmap]
  local total = self.raw_warm_bytes or 0
  for i = #recent, 1, -1 do
    if recent[i].name == name then
      total = total - recent[i].bytes
      table.remove(recent, i)
    end
  end
  -- Unknown/oversized pictures retain their normal live-window ownership only.
  if source_bytes and source_bytes <= budget and limit >= 1 then
    recent[#recent + 1] = {name = name, bitmap = bitmap, bytes = source_bytes}
    total = total + source_bytes
  end
  while #recent > 0 and (total > budget or #recent > limit) do
    total = total - recent[1].bytes
    table.remove(recent, 1)
  end
  self.raw_warm_bytes = total
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
    if 'CORSIXTH_3DS_RAW_WARM_R64' not in text:
        text=text.replace(LEGACY_WARM+'\n', '')
        if 'CORSIXTH_3DS_RAW_WARM_R62' in text:
            raise ValueError('unknown legacy raw warm implementation')
        if '    raw = {},' in text:
            text=replace_exact(text,'    raw = {},','    raw = setmetatable({}, {__mode = "v"}),','raw weak lookup')
        begin=text.index('function Graphics:loadRaw(')
        text=text[:begin]+WARM+'\n'+text[begin:]
        text=text.replace('    return self.cache.raw[name]','    return self:_retainRaw(name, self.cache.raw[name])')
        text=text.replace('  self.cache.raw[name] = bitmap\n  self:_retainRaw(name, bitmap)',
                          '  self.cache.raw[name] = bitmap')
        text=replace_exact(text,'  self.cache.raw[name] = bitmap',
            '  self.cache.raw[name] = bitmap\n'
            '  -- bitmap:load consumes one index per data byte, plus its 256 RGBA palette.\n'
            '  self:_retainRaw(name, bitmap, #data + 1024)','raw bounded warm ownership')
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
